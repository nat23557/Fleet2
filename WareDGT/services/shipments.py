from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date

from WareDGT.models import (
    EcxLoadRequest,
    EcxShipment,
    EcxTrade,
    EcxMovement,
    EcxLoadRequestReceiptFile,
    EcxMovementReceiptFile,
    PurchasedItemType,
)


class AlreadyProcessed(Exception):
    """Raised when a load request was already approved/declined."""


def _safe_loading_dt(payload_val: str | None) -> datetime | None:
    if not payload_val:
        return None
    # Try datetime first, then date-only
    dt = parse_datetime(payload_val)
    if dt:
        return dt
    d = parse_date(payload_val)
    if d:
        return datetime.combine(d, datetime.min.time(), tzinfo=timezone.get_current_timezone())
    return None


@transaction.atomic
def approve_load_request(lr: EcxLoadRequest, actor) -> EcxShipment:
    """Approve a pending ECX load request and create shipment + movements.

    - Idempotent: raises AlreadyProcessed if not in PENDING state
    - Aggregates selected trades by (seed_code, origin, grade)
    - Creates a parent EcxShipment and one EcxMovement per group
    - Marks trades as loaded
    - Links per‑group receipt files by origin/grade when available
    """
    if lr.status != EcxLoadRequest.STATUS_PENDING:
        raise AlreadyProcessed()

    trades: list[EcxTrade] = list(
        lr.trades.all().select_related("commodity__seed_type", "warehouse")
    )
    if not trades:
        # Nothing to do; keep request pending for safety rather than silently approving
        raise ValueError("Load request has no trades attached")

    total_qty = sum(Decimal(t.quantity_quintals) for t in trades)

    # Determine common symbol if unique
    symbols = sorted({t.commodity.seed_type.code for t in trades})
    symbol = symbols[0] if len(symbols) == 1 else None

    loading_dt = _safe_loading_dt((lr.payload or {}).get("loading_date"))

    # Create parent shipment
    shipment = EcxShipment.objects.create(
        warehouse=lr.warehouse,
        symbol=symbol,
        total_quantity=total_qty,
        created_by=actor,
        loading_date=loading_dt,
        truck_plate_no=lr.truck_plate_no or "",
        trailer_plate_no=lr.trailer_plate_no or "",
        truck_image=lr.truck_image if getattr(lr, "truck_image", None) else None,
    )

    # Group trades by (seed, origin, grade)
    groups: dict[tuple[str, str, str], dict] = {}
    for t in trades:
        key = (t.commodity.seed_type.code, t.commodity.origin, t.commodity.grade)
        g = groups.setdefault(
            key,
            {
                "trades": [],
                "qty": Decimal("0"),
                "purchase_date": t.purchase_date,
                "owner": t.owner,
            },
        )
        g["trades"].append(t)
        g["qty"] += Decimal(t.quantity_quintals)
        if t.purchase_date < g["purchase_date"]:
            g["purchase_date"] = t.purchase_date
        # Prefer first owner when mixed; typical cases are uniform
        if not g["owner"]:
            g["owner"] = t.owner

    # Attachments keyed by (origin, grade)
    files_map: dict[tuple[str, str], list[EcxLoadRequestReceiptFile]] = {}
    for rf in lr.receipt_files.all():
        files_map.setdefault((rf.origin, rf.grade), []).append(rf)

    # Create movements per group
    for (seed_code, origin, grade), g in groups.items():
        itype, _ = PurchasedItemType.objects.get_or_create(
            seed_type=seed_code, origin=origin, grade=grade
        )
        net_receipts = ", ".join(t.net_obligation_receipt_no for t in g["trades"])  # NOR list
        wr_receipts = ", ".join(
            f"{t.warehouse_receipt_no}-v{t.warehouse_receipt_version}" for t in g["trades"]
        )
        mv = EcxMovement.objects.create(
            warehouse=lr.warehouse,
            item_type=itype,
            net_obligation_receipt_no=net_receipts,
            warehouse_receipt_no=wr_receipts,
            quantity_quintals=g["qty"],
            purchase_date=g["purchase_date"],
            created_by=actor,
            owner=g["owner"],
            shipment=shipment,
        )
        if loading_dt is not None:
            mv.created_at = loading_dt
            mv.save(update_fields=["created_at"])  # keep created_at aligned to loading time

        # Link per‑group files, if any
        for rf in files_map.get((origin, grade), []) or []:
            EcxMovementReceiptFile.objects.create(movement=mv, image=rf.file)

    # Mark trades as loaded
    now = timezone.now()
    EcxTrade.objects.filter(id__in=[t.id for t in trades]).update(loaded=True, loaded_at=now)

    # Finalize request
    lr.status = EcxLoadRequest.STATUS_APPROVED
    lr.approved_by = actor
    lr.approved_at = now
    lr.shipment = shipment
    lr.save(update_fields=["status", "approved_by", "approved_at", "shipment"])

    return shipment

