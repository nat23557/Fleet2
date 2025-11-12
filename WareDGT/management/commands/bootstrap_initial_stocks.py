from decimal import Decimal
from datetime import datetime, date, timedelta
import random
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from WareDGT.models import (
    Company,
    Warehouse,
    SeedTypeDetail,
    BinCardEntry,
    next_in_out_no,
)


SEED_PRESETS = {
    # symbol: (category, default name)
    "WHGSS": (SeedTypeDetail.SESAME, "Whitish Humera/Gonder Sesame Seed"),
    "WWSS":  (SeedTypeDetail.SESAME, "Whitish Wollega Sesame Seed"),
    "NS":    (getattr(SeedTypeDetail, "OTHER", "OTHER"), "Niger Seed"),
    "GRMB":  (SeedTypeDetail.BEANS, "Green Mung Bean"),
}


DATASETS = [
    # (owner_name, symbol, quantity_qtl)
    ("DGT",      "WHGSS", Decimal("2070.58")),
    ("DGT",      "WWSS",  Decimal("1714.60")),
    ("DGT",      "NS",    Decimal("562.89")),
    ("BestWay",  "WHGSS", Decimal("62.14")),
    ("BestWay",  "WWSS",  Decimal("803.93")),
    ("BestWay",  "GRMB",  Decimal("98.07")),
]


class Command(BaseCommand):
    help = "Bootstrap initial stock balances into BinCardEntry for DGT/BestWay"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="date_str",
            help="Entry date in YYYY-MM-DD (defaults to today)",
        )
        parser.add_argument(
            "--warehouse",
            dest="warehouse_id",
            help="UUID of DGT warehouse to register stock in (defaults to first DGT)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing",
        )
        parser.add_argument(
            "--class",
            dest="stock_class",
            choices=["cleaned", "raw"],
            default="cleaned",
            help="Register as cleaned (default) or raw stock",
        )

    def handle(self, *args, **opts):
        # Resolve date
        if opts.get("date_str"):
            try:
                entry_date = datetime.strptime(opts["date_str"], "%Y-%m-%d").date()
            except Exception:
                raise CommandError("Invalid --date (use YYYY-MM-DD)")
            window_start = entry_date
            window_end = entry_date
        else:
            # Random date across the last Ethiopian year (approx Meskerem 1 to next Sep 10)
            today = date.today()
            start = date(today.year - 1, 9, 11)
            end = date(today.year, 9, 10)
            if today <= end:
                start = date(today.year - 2, 9, 11)
                end = date(today.year - 1, 9, 10)
            span = (end - start).days
            entry_date = start + timedelta(days=random.randint(0, max(span, 0)))
            window_start, window_end = start, end

        # Resolve warehouse: if one DGT warehouse exists, auto-pick it. If multiple, require --warehouse.
        wh = None
        if opts.get("warehouse_id"):
            wh = Warehouse.objects.filter(id=opts["warehouse_id"], warehouse_type=Warehouse.DGT).first()
            if not wh:
                raise CommandError("Warehouse not found or not DGT")
        else:
            dgt_qs = Warehouse.objects.filter(warehouse_type=Warehouse.DGT).order_by("name")
            count = dgt_qs.count()
            if count == 0:
                raise CommandError("No DGT warehouse found")
            if count > 1:
                raise CommandError("Multiple DGT warehouses found; pass --warehouse <uuid>")
            wh = dgt_qs.first()

        dry = bool(opts.get("dry_run"))

        # Ensure owners
        owners = {}
        for name in {o for (o, _, _) in DATASETS}:
            owners[name] = Company.objects.filter(name__iexact=name).first() or Company.objects.create(name=name)

        # Ensure seed types exist per symbol
        ensured = {}
        # Pick a delivery location for seed types: first ECX or the chosen DGT warehouse
        delivery = Warehouse.objects.filter(warehouse_type=Warehouse.ECX).order_by("name").first() or wh

        for sym, (cat, default_name) in SEED_PRESETS.items():
            st = SeedTypeDetail.objects.filter(symbol=sym).first()
            if not st:
                st = SeedTypeDetail.objects.create(
                    category=cat,
                    coffee_type=None if cat != SeedTypeDetail.COFFEE else None,
                    symbol=sym,
                    name=default_name,
                    delivery_location=delivery,
                    grade="",
                    origin="",
                )
            ensured[sym] = st

        created = []
        
        # helpers
        def _rand_date():
            if window_start == window_end:
                return window_start
            days = (window_end - window_start).days
            return window_start + timedelta(days=random.randint(0, max(days, 0)))

        def _split_qty(qty: Decimal):
            # Split qty into 2–6 chunks, sum equals qty, 2dp each
            q = Decimal(qty)
            if q <= 0:
                return [Decimal("0.00")]
            if q < Decimal("200"):
                k = random.randint(2, 3)
            elif q < Decimal("800"):
                k = random.randint(3, 5)
            else:
                k = random.randint(4, 6)
            rnd = [random.random() for _ in range(k)]
            s = sum(rnd) or 1.0
            parts = []
            remaining = q
            for i in range(k - 1):
                raw = q * Decimal(rnd[i] / s)
                part = raw.quantize(Decimal("0.01"))
                if part <= 0:
                    part = Decimal("0.01")
                parts.append(part)
                remaining -= part
            last = remaining.quantize(Decimal("0.01"))
            parts.append(last)
            # Adjust rounding drift to ensure exact sum
            diff = q - sum(parts)
            if diff != 0:
                parts[-1] = (parts[-1] + diff).quantize(Decimal("0.01"))
            # Guard against any negative last piece after adjustment
            if parts[-1] <= 0:
                # borrow 0.01 from the largest piece that can spare it
                idx = max(range(len(parts)-1), key=lambda i: parts[i])
                if parts[idx] > Decimal("0.02"):
                    parts[idx] -= Decimal("0.01")
                    parts[-1] += Decimal("0.01")
            return parts

        @transaction.atomic
        def _apply():
            for owner_name, sym, qty in DATASETS:
                st = ensured[sym]
                owner = owners[owner_name]
                io = next_in_out_no(st, owner=owner, warehouse=wh)
                w = qty.quantize(Decimal("0.01"))
                kwargs = dict(
                    seed_type=st,
                    owner=owner,
                    grade="",
                    warehouse=wh,
                    in_out_no=io,
                    description="Initial stock balance import",
                    weight=w,
                    cleaned_total_kg=w if opts.get("stock_class") == "cleaned" else Decimal("0"),
                    rejects_total_kg=Decimal("0"),
                )
                if opts.get("stock_class") == "raw":
                    kwargs["raw_balance_kg"] = w
                if not dry:
                    entry = BinCardEntry.objects.create(**kwargs)
                    d = _rand_date()
                    type(entry).objects.filter(pk=entry.pk).update(date=d)
                    entry.date = d
                    created.append(entry)
                else:
                    self.stdout.write(f"[DRY] {owner_name} {sym} {w} qtl @ {wh.name}")

        _apply()

        if not dry:
            self.stdout.write(self.style.SUCCESS(f"Created {len(created)} initial entries in {wh.name}"))
        else:
            self.stdout.write(self.style.WARNING("Dry run complete"))
