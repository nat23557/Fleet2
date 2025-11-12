import datetime
from decimal import Decimal, ROUND_UP
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from WareDGT.models import BinCardEntry, DailyRecord


class Command(BaseCommand):
    """Schedule cleaning DailyRecord entries for all bin card lots.

    Each lot is cleaned sequentially starting from a given date. The command
    assumes a fixed cleaning rate (quintals per hour) and a fixed number of
    working hours per day. የሳምንቱ ቅዳሜና እሑድ ቀናት ይወሰዳሉ.
    """

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username recorded as creator")
        parser.add_argument(
            "--start-date",
            type=lambda s: datetime.date.fromisoformat(s),
            default=datetime.date(2025, 1, 1),
            help="First cleaning date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--rate",
            type=Decimal,
            default=Decimal("50"),
            help="Cleaning rate per hour in quintals",
        )
        parser.add_argument(
            "--hours",
            type=int,
            default=10,
            help="Working hours per day",
        )
        parser.add_argument(
            "--target-purity",
            type=Decimal,
            default=Decimal("99"),
            help="Target purity percent for generated records",
        )
        parser.add_argument(
            "--laborers",
            type=int,
            default=5,
            help="Number of laborers assigned per record",
        )
        parser.add_argument(
            "--labor-rate",
            dest="labor_rate",
            type=Decimal,
            default=Decimal("8"),
            help="Labor rate per quintal in ETB",
        )
        parser.add_argument(

            "--dry-run",
            action="store_true",
            help="Show actions without writing to DB",
        )

    def handle(self, *args, **options):
        username = options["user"]
        start_date = options["start_date"]
        if isinstance(start_date, str):
            start_date = datetime.date.fromisoformat(start_date)
        rate: Decimal = options["rate"]
        hours: int = options["hours"]
        target_purity: Decimal = options["target_purity"]
        laborers: int = options["laborers"]
        labor_rate: Decimal = options["labor_rate"]

        dry_run = options["dry_run"]

        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"User '{username}' does not exist")

        daily_capacity = rate * hours
        current_date = start_date
        created = 0

        lots = (
            BinCardEntry.objects.filter(raw_weight_remaining__gt=0)
            .select_related("owner")
            .order_by("id")
        )

        for lot in lots:
            remaining: Decimal = lot.raw_weight_remaining
            while remaining > 0:
                # ቅዳሜና እሑድን ይዝለው
                while current_date.weekday() >= 5:
                    current_date += datetime.timedelta(days=1)

                qty = remaining if remaining < daily_capacity else daily_capacity
                pieces = int((qty / rate).to_integral_value(rounding=ROUND_UP))

                record = DailyRecord(
                    date=current_date,
                    warehouse=lot.warehouse,
                    plant="",
                    owner=lot.owner,
                    seed_type=lot.seed_type,
                    lot=lot,
                    operation_type=DailyRecord.CLEANING,
                    target_purity=target_purity,
                    weight_in=qty,
                    weight_out=Decimal("0"),
                    rejects=Decimal("0"),
                    purity_before=lot.purity,
                    purity_after=lot.purity,
                    laborers=laborers,
                    labor_rate_per_qtl=labor_rate,
                    recorded_by=user,
                    pieces=pieces,
                )
                if not dry_run:
                    record.save()
                created += 1

                remaining -= qty
                current_date += datetime.timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(f"Created {created} daily records"))
