import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from WareDGT.models import BinCardEntry, DailyRecord, QualityCheck


class Command(BaseCommand):
    help = "Create draft DailyRecords with hourly QualityCheck entries for cleaning lots"

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username recorded as creator")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N lots")
        parser.add_argument(
            "--dry-run", action="store_true", help="Show actions without writing to DB"
        )
        parser.add_argument(
            "--allow-remainder",
            action="store_true",
            help="Permit a final QC entry using any remaining stock < 50 qtl",
        )
        

    def handle(self, *args, **options):
        username = options["user"]
        limit = options.get("limit")
        dry_run = options["dry_run"]
        allow_remainder = options["allow_remainder"]


        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"User '{username}' does not exist")

        qs = BinCardEntry.objects.filter(raw_weight_remaining__gt=0).order_by("id")
        if limit:
            qs = qs[:limit]

        drafts = 0
        qcs_created = 0

        tz = ZoneInfo("Africa/Addis_Ababa")
        slot_hours = [8, 9, 10, 11, 13, 14, 15, 16, 17, 18]

        @transaction.atomic
        def process():
            nonlocal drafts, qcs_created
            for lot in qs:
                available = lot.raw_weight_remaining
                if available <= 0:
                    continue
                pieces_exact, remainder = divmod(available, Decimal("50"))
                remainder = remainder.quantize(Decimal("0.01"))
                if remainder and not allow_remainder:
                    raise CommandError(
                        f"Lot {lot.pk} has {available} qtl remaining which is not a multiple of 50"
                    )
                pieces = int(pieces_exact)
                if remainder:
                    pieces += 1

                record, created = DailyRecord.objects.get_or_create(
                    lot=lot,
                    operation_type=DailyRecord.CLEANING,
                    is_posted=False,
                    defaults=dict(
                        warehouse=lot.warehouse,
                        plant="",
                        owner=lot.owner,
                        seed_type=lot.seed_type,
                        date=lot.date,
                        weight_in=available,
                        weight_out=Decimal("0"),
                        rejects=Decimal("0"),
                        purity_before=lot.purity,
                        purity_after=lot.purity,
                        laborers=5,
                        labor_rate_per_qtl=Decimal("8"),
                        recorded_by=user,
                    ),
                )
                if created:
                    drafts += 1
                else:
                    # Update weight and date if record reused
                    record.weight_in = available
                    record.weight_out = Decimal("0")
                    record.date = lot.date
                    record.recorded_by = user
                    record.laborers = record.laborers or 5
                    record.labor_rate_per_qtl = record.labor_rate_per_qtl or Decimal("8")
                    record.save(update_fields=["weight_in", "weight_out", "date", "recorded_by", "laborers", "labor_rate_per_qtl"])
                    drafts += 1

                purity_weighted = Decimal("0")

                for i in range(pieces):
                    day_offset = i // len(slot_hours)
                    hour = slot_hours[i % len(slot_hours)]
                    current_date = lot.date + datetime.timedelta(days=day_offset)
                    naive_dt = datetime.datetime.combine(
                        current_date, datetime.time(hour, 0)
                    )
                    timestamp = naive_dt.replace(tzinfo=tz)

                    sound = (Decimal("29.50") + Decimal("0.05") * (i % 9)).quantize(
                        Decimal("0.01")
                    )
                    reject = (Decimal("30.00") - sound).quantize(Decimal("0.01"))

                    piece_qty = (
                        remainder if (remainder and i == pieces - 1) else Decimal("50.00")
                    )

                    qc = QualityCheck.objects.create(
                        daily_record=record,
                        index=i + 1,
                        timestamp=timestamp,
                        sample_weight_g=Decimal("30.00"),
                        piece_quintals=piece_qty,
                        machine_rate_kgph=Decimal("50.00"),
                        weight_sound_g=sound,
                        weight_reject_g=reject,
                    )

                    purity_weighted += qc.purity_percent * piece_qty

                    qcs_created += 1

                if pieces:
                    record.pieces = pieces
                    total_qtl = available
                    record.purity_after = (
                        purity_weighted / total_qtl
                    ).quantize(Decimal("0.01"))
                    record.save(update_fields=["pieces", "purity_after"])
                    record.post(user)

            if dry_run:
                raise transaction.TransactionManagementError

        try:
            process()
        except transaction.TransactionManagementError:
            self.stdout.write(self.style.WARNING("Dry run complete – no data written"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Records processed: {drafts}, QC entries created: {qcs_created}"
            )
        )
