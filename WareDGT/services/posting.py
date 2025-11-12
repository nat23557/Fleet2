from __future__ import annotations

from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from WareDGT.models import BinCardEntry, DailyRecord, BinCardTransaction


def post_daily_record(record_id: int, actor):
    """Post a DailyRecord and create ledger transactions.

    The operation is idempotent: calling it multiple times will only post once.
    """
    record = DailyRecord.objects.select_related("lot").get(pk=record_id)
    if record.is_posted:
        return record
    record.full_clean()

    with transaction.atomic():
        lot = BinCardEntry.objects.select_for_update().get(pk=record.lot_id)
        # 1. mass balance validation with ±0.75% tolerance
        expected = record.weight_out + record.rejects
        tolerance = record.weight_in * Decimal("0.0075")
        if abs(record.weight_in - expected) > tolerance:
            raise ValidationError("Weight in does not balance with out + rejects")

        # 2. validate remaining raw weight
        if lot.raw_weight_remaining < record.weight_in:
            raise ValidationError("Insufficient raw weight on lot")

        # 3. update lot counters
        lot.raw_weight_remaining -= record.weight_in
        lot.cleaned_weight += record.weight_out
        new_grade = lot.seed_type.grade_for_purity(record.purity_after)
        grade_before = lot.grade
        if new_grade:
            lot.grade = new_grade
        lot.save(update_fields=["raw_weight_remaining", "cleaned_weight", "grade"])

        # 4. create transactions
        tx_common = dict(
            commodity=lot.seed_type,
            warehouse=record.warehouse,
            lot=lot,
            daily_record=record,
        )
        BinCardTransaction.objects.create(
            movement=BinCardTransaction.RAW_OUT,
            qty_kg=record.weight_in,
            grade_before=grade_before,
            grade_after=grade_before,
            **tx_common,
        )
        BinCardTransaction.objects.create(
            movement=BinCardTransaction.CLEANED_IN,
            qty_kg=record.weight_out,
            grade_before=grade_before,
            grade_after=new_grade or grade_before,
            **tx_common,
        )
        BinCardTransaction.objects.create(
            movement=BinCardTransaction.REJECT_OUT,
            qty_kg=record.rejects,
            grade_before=grade_before,
            grade_after="REJECT",
            **tx_common,
        )

        # 5. mark record as posted
        record.is_posted = True
        record.posted_by = actor
        record.posted_at = timezone.now()
        record.status = DailyRecord.STATUS_POSTED
        record.save(update_fields=["is_posted", "posted_by", "posted_at", "status"])

    return record


def reclassify_rejects(daily_record_id: int, new_disposition: str):
    record = DailyRecord.objects.get(pk=daily_record_id)
    record.reject_disposition = new_disposition
    record.save(update_fields=["reject_disposition"])
    return record
