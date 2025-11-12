from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from WareDGT.models import (
    DailyRecord,
    BinCardEntry,
    SeedTypeBalance,
    BinCardTransaction,
    PURITY_TOLERANCE,
)

TOL = Decimal("0.0075")  # 0.75% tolerance

def _q(x):
    return Decimal(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

@transaction.atomic
def post_daily_record(record_id: int, actor):
    dr = DailyRecord.objects.select_for_update().select_related(
        "lot__seed_type", "lot__warehouse"
    ).get(pk=record_id)

    if dr.status == DailyRecord.STATUS_POSTED:
        return dr

    weight_in = _q(dr.weight_in)
    weight_out = _q(dr.weight_out)
    rejects = _q(dr.rejects)
    if weight_in <= 0:
        raise ValidationError("Weight in must be > 0.")

    if abs((weight_out + rejects) - weight_in) > (weight_in * TOL):
        raise ValidationError("Mass balance check failed: in ≠ out + rejects (±0.75%).")

    lot = BinCardEntry.objects.select_for_update().get(pk=dr.lot_id)

    if _q(lot.raw_balance_kg) < weight_in:
        raise ValidationError("Insufficient raw balance on lot.")

    grade_before = lot.grade
    new_grade = lot.seed_type.grade_for_purity(dr.purity_after)

    lot.raw_balance_kg = _q(lot.raw_balance_kg) - weight_in
    lot.raw_weight_remaining = _q(lot.raw_weight_remaining) - weight_in
    lot.cleaned_total_kg = _q(lot.cleaned_total_kg) + weight_out
    lot.cleaned_weight = _q(lot.cleaned_weight) + weight_out
    lot.rejects_total_kg = _q(lot.rejects_total_kg) + rejects
    lot.purity = dr.purity_after
    lot.last_cleaned_at = timezone.now()
    update_fields = [
        "raw_balance_kg",
        "raw_weight_remaining",
        "cleaned_total_kg",
        "cleaned_weight",
        "rejects_total_kg",
        "purity",
        "last_cleaned_at",
    ]
    if new_grade:
        lot.grade = new_grade
        update_fields.append("grade")
    lot.save(update_fields=update_fields)

    # update reject balance grouped by owner/warehouse
    stb_rej, _ = SeedTypeBalance.objects.select_for_update().get_or_create(
        warehouse=lot.warehouse,
        owner=lot.owner,
        seed_type=lot.seed_type,
        purity=None,
    )
    stb_rej.rejects_kg = _q(stb_rej.rejects_kg) + rejects
    stb_rej.save(update_fields=["rejects_kg", "updated_at"])

    # update cleaned balance grouped by final purity (within tolerance)
    purity_after = dr.purity_after
    stb_clean = (
        SeedTypeBalance.objects.select_for_update()
        .filter(
            warehouse=lot.warehouse,
            owner=lot.owner,
            seed_type=lot.seed_type,
            purity__isnull=False,
            purity__gte=purity_after - PURITY_TOLERANCE,
            purity__lte=purity_after + PURITY_TOLERANCE,
        )
        .first()
    )
    if stb_clean:
        stb_clean.cleaned_kg = _q(stb_clean.cleaned_kg) + weight_out
        stb_clean.save(update_fields=["cleaned_kg", "updated_at"])
    else:
        SeedTypeBalance.objects.create(
            warehouse=lot.warehouse,
            owner=lot.owner,
            seed_type=lot.seed_type,
            purity=purity_after,
            cleaned_kg=weight_out,
            rejects_kg=Decimal("0.000"),
        )

    # ledger transactions
    tx_common = dict(
        commodity=lot.seed_type,
        warehouse=lot.warehouse,
        lot=lot,
        daily_record=dr,
        grade_before=grade_before,
    )
    BinCardTransaction.objects.bulk_create([
        BinCardTransaction(
            movement=BinCardTransaction.RAW_OUT,
            qty_kg=weight_in,
            grade_after=grade_before,
            **tx_common,
        ),
        BinCardTransaction(
            movement=BinCardTransaction.CLEANED_IN,
            qty_kg=weight_out,
            grade_after=new_grade or grade_before,
            **tx_common,
        ),
        BinCardTransaction(
            movement=BinCardTransaction.REJECT_OUT,
            qty_kg=rejects,
            grade_after="REJECT",
            **tx_common,
        ),
    ])

    dr.status = DailyRecord.STATUS_POSTED
    dr.is_posted = True
    dr.posted_at = timezone.now()
    dr.posted_by = actor
    dr.save(update_fields=["status", "is_posted", "posted_at", "posted_by"])

    return dr

@transaction.atomic
def reverse_posted_daily_record(record_id: int, actor):
    dr = DailyRecord.objects.select_for_update().select_related(
        "lot__seed_type", "lot__warehouse"
    ).get(pk=record_id)
    if dr.status != DailyRecord.STATUS_POSTED:
        raise ValidationError("Only posted records can be reversed.")

    lot = BinCardEntry.objects.select_for_update().get(pk=dr.lot_id)
    txs = list(BinCardTransaction.objects.filter(daily_record=dr))
    grade_before = txs[0].grade_before if txs else lot.grade

    lot.raw_balance_kg += dr.weight_in
    lot.raw_weight_remaining += dr.weight_in
    lot.cleaned_total_kg -= dr.weight_out
    lot.cleaned_weight -= dr.weight_out
    lot.rejects_total_kg -= dr.rejects
    lot.purity = dr.purity_before
    update_fields = [
        "raw_balance_kg",
        "raw_weight_remaining",
        "cleaned_total_kg",
        "cleaned_weight",
        "rejects_total_kg",
        "purity",
    ]
    if lot.grade != grade_before:
        lot.grade = grade_before
        update_fields.append("grade")
    lot.save(update_fields=update_fields)

    if txs:
        BinCardTransaction.objects.filter(daily_record=dr).delete()

    # reverse rejects balance
    stb_rej = SeedTypeBalance.objects.select_for_update().get(
        warehouse=lot.warehouse,
        owner=lot.owner,
        seed_type=lot.seed_type,
        purity=None,
    )
    stb_rej.rejects_kg -= dr.rejects
    stb_rej.save(update_fields=["rejects_kg", "updated_at"])

    # reverse cleaned balance
    purity_after = dr.purity_after
    stb_clean = (
        SeedTypeBalance.objects.select_for_update()
        .filter(
            warehouse=lot.warehouse,
            owner=lot.owner,
            seed_type=lot.seed_type,
            purity__isnull=False,
            purity__gte=purity_after - PURITY_TOLERANCE,
            purity__lte=purity_after + PURITY_TOLERANCE,
        )
        .first()
    )
    if stb_clean:
        stb_clean.cleaned_kg -= dr.weight_out
        stb_clean.save(update_fields=["cleaned_kg", "updated_at"])

    dr.status = DailyRecord.STATUS_DRAFT
    dr.is_posted = False
    dr.posted_at = None
    dr.posted_by = None
    dr.save(update_fields=["status", "is_posted", "posted_at", "posted_by"])

    return dr
