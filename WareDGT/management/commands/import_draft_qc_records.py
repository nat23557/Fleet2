import datetime
import random
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from WareDGT.models import DailyRecord, QualityCheck


class Command(BaseCommand):
    help = "Populate draft DailyRecords with QC data and post them"

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Username recorded as submitter")
        parser.add_argument("--limit", type=int, default=None, help="Process at most N drafts")

    def handle(self, *args, **options):
        username = options["user"]
        limit = options.get("limit")

        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"User '{username}' does not exist")

        qs = (
            DailyRecord.objects.filter(status=DailyRecord.STATUS_DRAFT)
            .select_related("lot__owner")
        )
        if limit:
            qs = qs[:limit]

        slot_hours = [8, 9, 10, 11, 13, 14, 15, 16, 17, 18]
        tz = ZoneInfo("Africa/Addis_Ababa")

        processed = 0
        qcs_created = 0

        for record in qs:
            if record.owner_id != record.lot.owner_id:
                record.owner = record.lot.owner
                record.save(update_fields=["owner"])
            if record.weight_in > record.lot.raw_weight_remaining:
                self.stderr.write(f"Skipping DailyRecord {record.pk}: insufficient raw weight")
                continue

            total_in = record.weight_in

            # Expected reject by purity improvement target
            expected_reject = (
                total_in * (Decimal("1") - (record.purity_before / record.target_purity))
            ).quantize(Decimal("0.001"))

            # Noise/tolerance
            tol_pct = Decimal(str(getattr(settings, "DAILYREC_TOLERANCE_PCT", 0.013125)))
            tol_abs = (total_in * tol_pct).quantize(Decimal("0.001"))
            delta = Decimal(str(random.uniform(float(-tol_abs), float(tol_abs)))).quantize(Decimal("0.001"))
            actual_reject = (expected_reject + delta).quantize(Decimal("0.001"))
            if actual_reject < Decimal("0.001"):
                actual_reject = Decimal("0.001")
            if actual_reject > total_in:
                actual_reject = total_in

            total_out = (total_in - actual_reject).quantize(Decimal("0.01"))
            rejects = (total_in - total_out).quantize(Decimal("0.01"))
            record.weight_out = total_out
            record.rejects = rejects
            record.actual_reject_weight = actual_reject

            pure_weight = total_in * (record.purity_before / Decimal("100"))
            record.purity_after = (pure_weight / total_out * Decimal("100")).quantize(Decimal("0.01"))

            # Rebuild QC entries
            record.quality_checks.all().delete()

            pieces_full, remainder = divmod(total_out, Decimal("50"))
            pieces = int(pieces_full) + (1 if remainder > 0 else 0)
            purity_weighted = Decimal("0")

            for i in range(pieces):
                day_offset = i // len(slot_hours)
                hour = slot_hours[i % len(slot_hours)]
                current_date = record.date + datetime.timedelta(days=day_offset)
                naive_dt = datetime.datetime.combine(current_date, datetime.time(hour, 0))
                timestamp = naive_dt.replace(tzinfo=tz)

                piece_qty = remainder if (remainder and i == pieces - 1) else Decimal("50")

                purity = (record.purity_after + Decimal(str(random.uniform(-0.05, 0.05)))).quantize(Decimal("0.01"))
                sound = (Decimal("30.00") * purity / Decimal("100")).quantize(Decimal("0.01"))
                reject = (Decimal("30.00") - sound).quantize(Decimal("0.01"))

                QualityCheck.objects.create(
                    daily_record=record,
                    index=i + 1,
                    timestamp=timestamp,
                    sample_weight_g=Decimal("30.00"),
                    piece_quintals=piece_qty,
                    machine_rate_kgph=Decimal("50.00"),
                    weight_sound_g=sound,
                    weight_reject_g=reject,
                )

                purity_weighted += purity * piece_qty
                qcs_created += 1

            if pieces:
                record.pieces = pieces
                record.purity_after = (purity_weighted / total_out).quantize(Decimal("0.01"))
                record.compute_estimations()
                record.reject_weighing_rate_etb_per_qtl = Decimal("8")
                record.reject_weighed_by = user
                record.reject_weighed_at = timezone.now()
                record.save(
                    update_fields=[
                        "weight_out",
                        "rejects",
                        "pieces",
                        "purity_after",
                        "actual_reject_weight",
                        "expected_reject_weight",
                        "combined_expected_reject_weight",
                        "deviation_pct",
                        "is_fishy",
                        "reject_weighing_rate_etb_per_qtl",
                        "reject_weighed_by",
                        "reject_weighed_at",
                    ]
                )

                # Try to post; if invalid, skip this record (keeps the behavior from your feature branch)
                try:
                    record.post(user)
                except ValidationError as exc:
                    self.stderr.write(f"Skipping DailyRecord {record.pk}: {exc}")
                    continue

                # --- Optional assessment block (from main), guarded to avoid NameError if model/setting absent ---
                try:
                    # Late import so this command still works if the assessment model isn’t present
                    from WareDGT.models import DailyRecordAssessment  # type: ignore

                    spread_tol_setting = getattr(settings, "DAILYREC_SPREAD_TOLERANCE", None)
                    if spread_tol_setting is not None:
                        spread_tol = Decimal(str(spread_tol_setting))

                        mid = (record.weight_in + record.weight_out) / Decimal("2")
                        # Jitter within tolerance/2, centered at "mid"
                        def jitter():
                            return Decimal(
                                str(random.uniform(-float(spread_tol) / 2, float(spread_tol) / 2))
                            )

                        pre = (mid + jitter()).quantize(Decimal("0.01"))
                        post_op = (mid + jitter()).quantize(Decimal("0.01"))
                        mid_q = mid.quantize(Decimal("0.01"))

                        spread = max(pre, mid_q, post_op) - min(pre, mid_q, post_op)
                        flagged = spread > spread_tol
                        reason = (
                            f"Spread {spread} exceeds tolerance {spread_tol}"
                            if flagged
                            else f"Spread {spread} within tolerance {spread_tol}"
                        )

                        DailyRecordAssessment.objects.update_or_create(
                            daily_record=record,
                            defaults=dict(
                                pre_operation=pre,
                                in_operation=mid_q,
                                post_operation=post_op,
                                tolerance=spread_tol.quantize(Decimal("0.01")),
                                spread=spread.quantize(Decimal("0.01")),
                                flagged=flagged,
                                reason=reason,
                            ),
                        )
                except Exception:
                    # If the model/setting doesn’t exist or anything fails, don’t block the main flow.
                    pass

                processed += 1

        self.stdout.write(self.style.SUCCESS(f"Records processed: {processed}, QC entries created: {qcs_created}"))
