from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from WareDGT.models import (
    BinCardEntry,
    DailyRecord,
    SeedTypeBalance,
    Warehouse,
    PURITY_TOLERANCE,
)


Q2 = Decimal("0.01")
Q3 = Decimal("0.001")


def _q2(x: Decimal) -> Decimal:
    return Decimal(x).quantize(Q2)


def _q3(x: Decimal) -> Decimal:
    return Decimal(x).quantize(Q3, rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = (
        "Repairs historical artifacts created by earlier stock-out bugs: "
        "1) sets raw balances to 0 on stock-out rows, "
        "2) recomputes per-entry running balances consistently across seed symbol/owner/warehouse, "
        "3) rebuilds per-lot raw/cleaned/reject totals from posted DailyRecords, and "
        "4) optionally rebuilds SeedTypeBalance from ground truth."
    )

    def add_arguments(self, parser):
        parser.add_argument("--owner", dest="owner", default=None)
        parser.add_argument("--warehouse", dest="warehouse", default=None)
        parser.add_argument("--seed", dest="seed", default=None, help="Seed symbol or SeedTypeDetail id")
        parser.add_argument(
            "--commit",
            action="store_true",
            dest="commit",
            help="Apply changes. Without this flag the command runs in dry-run mode.",
        )
        parser.add_argument(
            "--no-rebuild-stb",
            action="store_true",
            dest="no_rebuild_stb",
            help="Skip rebuilding SeedTypeBalance table",
        )
        parser.add_argument(
            "--delete-bad-daily",
            action="store_true",
            dest="delete_bad_daily",
            help="Delete DRAFT DailyRecords with weight_in<=0 created from stock-out lots",
        )

    def handle(self, *args, **opts):
        owner = opts.get("owner")
        warehouse = opts.get("warehouse")
        seed = opts.get("seed")
        commit = opts.get("commit")
        skip_stb = opts.get("no_rebuild_stb")
        delete_bad_daily = opts.get("delete_bad_daily")

        # Filter scope
        entries = (
            BinCardEntry.objects.select_related("seed_type", "owner", "warehouse")
            .order_by("date", "id")
        )
        if owner:
            entries = entries.filter(owner_id=owner)
        if warehouse:
            entries = entries.filter(warehouse_id=warehouse)
        if seed:
            try:
                int(seed)
            except Exception:
                entries = entries.filter(seed_type__symbol=seed)
            else:
                entries = entries.filter(seed_type_id=seed)

        # 1) Recompute running balances per (symbol, owner, warehouse)
        updates = []
        balances = defaultdict(Decimal)
        per_lot_stats = {}
        fixed_neg_raw = 0
        touched_balance = 0
        touched_lot_totals = 0

        for e in entries.iterator():
            sym = getattr(e.seed_type, "symbol", None) or e.seed_type_id
            key = (sym, e.owner_id, e.warehouse_id)
            prev = balances[key]
            try:
                w = Decimal(e.weight)
            except Exception:
                w = Decimal("0")
            new_balance = _q2(prev + w)
            balances[key] = new_balance

            # Stock-out rows must not carry raw balances
            desired_raw_remaining = e.raw_weight_remaining
            desired_raw_balance = e.raw_balance_kg
            if w < 0:
                if desired_raw_remaining != 0 or desired_raw_balance != 0:
                    desired_raw_remaining = Decimal("0")
                    desired_raw_balance = Decimal("0")
                    fixed_neg_raw += 1

            # Per-lot totals from posted daily records (only for inbound lots)
            lot_cleaned = e.cleaned_total_kg
            lot_reject = e.rejects_total_kg
            if w > 0:
                dr_qs = DailyRecord.objects.filter(
                    lot=e,
                    status=DailyRecord.STATUS_POSTED,
                ).values("lot").aggregate(
                    weight_in=Sum("weight_in"),
                    weight_out=Sum("weight_out"),
                    rejects=Sum("rejects"),
                )
                w_in = _q3(Decimal(dr_qs.get("weight_in") or 0))
                w_out = _q3(Decimal(dr_qs.get("weight_out") or 0))
                rj = _q3(Decimal(dr_qs.get("rejects") or 0))
                new_raw_remaining = _q2(max(Decimal("0"), Decimal(e.weight) - w_in))
                new_raw_balance = _q3(max(Decimal("0"), Decimal(e.weight) - w_in))
                # cleaned/rejects tracked on the lot itself (stock-outs are separate rows)
                new_cleaned = w_out
                new_reject = rj
                if (
                    desired_raw_remaining != new_raw_remaining
                    or desired_raw_balance != new_raw_balance
                    or lot_cleaned != new_cleaned
                    or lot_reject != new_reject
                ):
                    desired_raw_remaining = new_raw_remaining
                    desired_raw_balance = new_raw_balance
                    lot_cleaned = new_cleaned
                    lot_reject = new_reject
                    touched_lot_totals += 1

            # Persist if needed
            if (
                e.balance != new_balance
                or e.raw_weight_remaining != desired_raw_remaining
                or e.raw_balance_kg != desired_raw_balance
                or e.cleaned_total_kg != lot_cleaned
                or e.rejects_total_kg != lot_reject
            ):
                updates.append(
                    (
                        e.pk,
                        {
                            "balance": new_balance,
                            "raw_weight_remaining": desired_raw_remaining,
                            "raw_balance_kg": desired_raw_balance,
                            "cleaned_total_kg": lot_cleaned,
                            "rejects_total_kg": lot_reject,
                            "pdf_dirty": True,
                        },
                    )
                )
                touched_balance += int(e.balance != new_balance)

        self.stdout.write(
            f"Planned entry updates: {len(updates)} | balance changes={touched_balance} | "
            f"negative raw cleared={fixed_neg_raw} | lot total fixes={touched_lot_totals}"
        )

        # 2) Flag clearly-invalid DailyRecords (weight_in <= 0)
        bad_daily = DailyRecord.objects.filter(
            operation_type__in=[DailyRecord.CLEANING, DailyRecord.RECLEANING],
            weight_in__lte=0,
        )
        self.stdout.write(f"Found DailyRecords with non-positive weight_in: {bad_daily.count()}")

        # 3) Rebuild SeedTypeBalance from posted daily records and stock-outs
        def rebuild_seedtype_balance():
            self.stdout.write("Rebuilding SeedTypeBalance…")
            with transaction.atomic():
                SeedTypeBalance.objects.all().delete()
                # Build cleaned buckets by final purity (within tolerance)
                posted = DailyRecord.objects.filter(status=DailyRecord.STATUS_POSTED)
                # Rejects bucket (purity=None)
                rej = (
                    posted.values("warehouse", "owner", "seed_type")
                    .annotate(total=Sum("rejects"))
                    .iterator()
                )
                for row in rej:
                    if not row["total"]:
                        continue
                    SeedTypeBalance.objects.create(
                        warehouse_id=row["warehouse"],
                        owner_id=row["owner"],
                        seed_type_id=row["seed_type"],
                        purity=None,
                        rejects_kg=_q3(Decimal(row["total"]))
                    )
                # Cleaned buckets by purity after (group by tolerance at write time)
                cleaned_map = {}
                for r in posted.values(
                    "warehouse", "owner", "seed_type", "purity_after"
                ).annotate(total=Sum("weight_out")).iterator():
                    if not r["total"]:
                        continue
                    key = (r["warehouse"], r["owner"], r["seed_type"], _q2(Decimal(r["purity_after"])) )
                    cleaned_map[key] = cleaned_map.get(key, Decimal("0")) + Decimal(r["total"])
                for (wh, owner_id, st, purity), total in cleaned_map.items():
                    SeedTypeBalance.objects.create(
                        warehouse_id=wh,
                        owner_id=owner_id,
                        seed_type_id=st,
                        purity=_q2(purity),
                        cleaned_kg=_q3(total),
                    )
                # Apply stock-out rows as deductions
                for e in BinCardEntry.objects.filter(weight__lt=0).iterator():
                    if e.cleaned_total_kg and Decimal(e.cleaned_total_kg) != 0:
                        # Cleaned
                        row = (
                            SeedTypeBalance.objects.filter(
                                warehouse=e.warehouse,
                                owner=e.owner,
                                seed_type=e.seed_type,
                                # Deduct from the nearest bucket (any purity)
                                purity__isnull=False,
                            )
                            .order_by("id")
                            .first()
                        )
                        if row:
                            row.cleaned_kg = _q3(Decimal(row.cleaned_kg) + Decimal(e.cleaned_total_kg))
                            row.save(update_fields=["cleaned_kg", "updated_at"])
                    if e.rejects_total_kg and Decimal(e.rejects_total_kg) != 0:
                        row = SeedTypeBalance.objects.filter(
                            warehouse=e.warehouse,
                            owner=e.owner,
                            seed_type=e.seed_type,
                            purity=None,
                        ).first()
                        if not row:
                            row = SeedTypeBalance.objects.create(
                                warehouse=e.warehouse,
                                owner=e.owner,
                                seed_type=e.seed_type,
                                purity=None,
                                rejects_kg=Decimal("0"),
                            )
                        row.rejects_kg = _q3(Decimal(row.rejects_kg) + Decimal(e.rejects_total_kg))
                        row.save(update_fields=["rejects_kg", "updated_at"])

        if not commit:
            self.stdout.write(self.style.WARNING("Dry-run complete. Use --commit to apply changes."))
            return

        with transaction.atomic():
            for pk, fields in updates:
                BinCardEntry.objects.filter(pk=pk).update(**fields)

            # Flag or delete invalid daily records
            if delete_bad_daily:
                deleted, _ = bad_daily.delete()
                self.stdout.write(self.style.WARNING(f"Deleted {deleted} invalid DailyRecords."))
            else:
                bad_daily.update(is_fishy=True)
                self.stdout.write(self.style.WARNING("Flagged invalid DailyRecords as fishy."))

        if not skip_stb:
            rebuild_seedtype_balance()

        self.stdout.write(self.style.SUCCESS("Repair completed."))

