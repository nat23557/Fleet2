from __future__ import annotations

import calendar
import datetime as dt
import random
import string
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List, Optional

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from cash_management.models import BankAccount, Transaction


def _daterange(start: dt.date, end: dt.date) -> Iterable[dt.date]:
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def _last_month_range(today: Optional[dt.date] = None) -> tuple[dt.date, dt.date]:
    t = today or dt.date.today()
    # Go to first day of this month, then step back one day
    first_this = t.replace(day=1)
    last_prev = first_this - dt.timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev, last_prev


def _rand_ref(prefix: str = "SIM") -> str:
    sfx = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{sfx}"


_DESCRIPTIONS: List[str] = [
    "POS purchase - {vendor}",
    "Wire transfer - {vendor}",
    "Cash deposit - {vendor}",
    "Salary payment - {vendor}",
    "Fuel purchase - {vendor}",
    "Service fee - {vendor}",
    "Interest received - {vendor}",
    "ATM withdrawal - {vendor}",
    "Invoice payment - {vendor}",
    "Transfer between accounts - {vendor}",
]

_VENDORS: List[str] = [
    "ABYSSINIA TRDG",
    "BUNNA CAFE",
    "SKY LOGISTICS",
    "DASHEN STATION",
    "CITY SUPERMARKET",
    "ETHIO TECH",
    "GLOBAL SERVICES",
    "BLUE TAXI",
    "GREEN MOTORS",
    "OMEGA SOLUTIONS",
]


def _quant2(val: float | Decimal) -> Decimal:
    return (Decimal(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _rand_amount(ccy: str) -> Decimal:
    c = (ccy or "").upper()
    # Basic tiers by currency with a log-like spread
    if c == "USD":
        base = random.uniform(5, 2000)
    else:  # ETB or others
        base = random.uniform(200, 50000)
    # Add some variability with occasional large values
    if random.random() < 0.05:  # 5% large spikes
        base *= random.uniform(2, 6)
    return _quant2(base)


@dataclass
class GenOptions:
    per_day: int
    start_date: dt.date
    end_date: dt.date
    username: Optional[str]
    use_bulk: bool
    seed: Optional[int]
    tag: Optional[str]
    bank_filter: Optional[str]
    dry_run: bool


class Command(BaseCommand):
    help = "Generate random transactions for each bank account over a date range"

    def add_arguments(self, parser):
        parser.add_argument("--per-day", type=int, default=30, help="Transactions per day per account (default: 30)")
        parser.add_argument("--days", type=int, default=30, help="Number of days back from today (ignored if --last-month)")
        parser.add_argument("--last-month", action="store_true", help="Use the full previous calendar month")
        parser.add_argument("--user", dest="username", help="Username to set as created_by (optional)")
        parser.add_argument("--no-bulk", action="store_true", help="Disable bulk_create to trigger signals (slower)")
        parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
        parser.add_argument("--tag", help="Optional tag prefix added to description, e.g. [SIM]")
        parser.add_argument("--bank", dest="bank_filter", help="Filter accounts by bank name (icontains)")
        parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
        parser.add_argument(
            "--inflow-pct",
            type=float,
            default=50.0,
            help="Percent of transactions that are inflows (credit). 0-100. Default: 50",
        )

    def handle(self, *args, **opts):
        today = dt.date.today()
        if opts.get("last_month"):
            start_date, end_date = _last_month_range(today)
        else:
            days = int(opts.get("days") or 30)
            end_date = today
            start_date = end_date - dt.timedelta(days=days - 1)

        per_day = int(opts.get("per_day") or 30)
        username = opts.get("username")
        use_bulk = not bool(opts.get("no_bulk"))
        seed = opts.get("seed")
        tag = opts.get("tag")
        bank_filter = opts.get("bank_filter")
        dry_run = bool(opts.get("dry_run"))
        inflow_pct = float(opts.get("inflow_pct", 50.0))
        if not (0.0 <= inflow_pct <= 100.0):
            raise CommandError("--inflow-pct must be between 0 and 100")
        inflow_prob = inflow_pct / 100.0

        if seed is not None:
            random.seed(int(seed))

        qs = BankAccount.objects.all()
        if bank_filter:
            qs = qs.filter(bank_name__icontains=bank_filter)

        accounts = list(qs)
        if not accounts:
            raise CommandError(
                "No bank accounts found. Seed accounts first via 'python manage.py seed_banks' or admin."
            )

        user = None
        if username:
            User = get_user_model()
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"User not found: {username}")

        opts_obj = GenOptions(
            per_day=per_day,
            start_date=start_date,
            end_date=end_date,
            username=username,
            use_bulk=use_bulk,
            seed=seed,
            tag=tag,
            bank_filter=bank_filter,
            dry_run=dry_run,
        )

        self.stdout.write(
            self.style.NOTICE(
                f"Generating {per_day}/day for {len(accounts)} accounts from {start_date} to {end_date}"
                + (f" (bank~{bank_filter})" if bank_filter else "")
                + f" • inflow≈{inflow_pct:.0f}%"
                + (" [dry-run]" if dry_run else "")
            )
        )

        total_days = (end_date - start_date).days + 1
        est = len(accounts) * total_days * per_day
        if est > 200_000 and not dry_run:
            self.stdout.write(self.style.WARNING(f"Large generation: ~{est} transactions"))

        total_created = 0
        batch: List[Transaction] = []

        def _make_desc() -> str:
            vendor = random.choice(_VENDORS)
            tmpl = random.choice(_DESCRIPTIONS)
            body = tmpl.format(vendor=vendor)
            if tag:
                return f"{tag} {body}"
            return body

        for account in accounts:
            ccy = (account.currency or "").upper()
            for day in _daterange(start_date, end_date):
                for _ in range(per_day):
                    is_credit = random.random() < inflow_prob
                    amt = _rand_amount(ccy)
                    debit = Decimal("0.00") if is_credit else amt
                    credit = amt if is_credit else Decimal("0.00")
                    obj = Transaction(
                        account=account,
                        date=day,
                        description=_make_desc(),
                        reference=_rand_ref("SIM"),
                        debit=debit,
                        credit=credit,
                        created_by=user,
                    )
                    if dry_run:
                        continue
                    if use_bulk:
                        batch.append(obj)
                        # Flush in chunks to limit memory
                        if len(batch) >= 2000:
                            Transaction.objects.bulk_create(batch, batch_size=1000)
                            total_created += len(batch)
                            batch.clear()
                    else:
                        obj.save()
                        total_created += 1

        if not dry_run and use_bulk and batch:
            Transaction.objects.bulk_create(batch, batch_size=1000)
            total_created += len(batch)
            batch.clear()

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: would create approximately {est} transactions"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Created {total_created} transactions."))
