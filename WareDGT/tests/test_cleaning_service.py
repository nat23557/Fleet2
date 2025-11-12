import pytest
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from WareDGT.models import (
    Company,
    Warehouse,
    SeedTypeDetail,
    BinCardEntry,
    DailyRecord,
    SeedTypeBalance,
    BinCardTransaction,
)
from WareDGT.services.cleaning import post_daily_record, reverse_posted_daily_record
from django.urls import reverse


def setup_lot():
    owner = Company.objects.create(name="Owner")
    warehouse = Warehouse.objects.create(
        code="W1",
        name="Main",
        warehouse_type=Warehouse.DGT,
        owner=owner,
        capacity_quintals=1000,
        footprint_m2=100,
        latitude=0,
        longitude=0,
    )
    commodity = SeedTypeDetail.objects.create(
        symbol="SES-ETH-A",
        name="Sesame",
        delivery_location=warehouse,
        grade="A",
        origin="ETH",
    )
    lot = BinCardEntry.objects.create(
        seed_type=commodity,
        owner=owner,
        in_out_no="1",
        weight=Decimal("2000"),
        raw_weight_remaining=Decimal("2000"),
        raw_balance_kg=Decimal("2000"),
        warehouse=warehouse,
        grade="A",
    )
    user = User.objects.create(username="actor")
    return owner, warehouse, commodity, lot, user


@pytest.mark.django_db
def test_post_updates_lot_and_seed_balance():
    owner, warehouse, commodity, lot, user = setup_lot()
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        lot=lot,
        weight_in=Decimal("1000"),
        weight_out=Decimal("980"),
        rejects=Decimal("20"),
        target_purity=Decimal("99"),
        purity_after=Decimal("99"),
        recorded_by=user,
    )
    post_daily_record(record.id, user)
    lot.refresh_from_db()
    stb_clean = SeedTypeBalance.objects.get(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        purity=Decimal("99"),
    )
    stb_rej = SeedTypeBalance.objects.get(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        purity__isnull=True,
    )
    assert lot.raw_balance_kg == Decimal("1000.000")
    assert lot.cleaned_total_kg == Decimal("980.000")
    assert lot.rejects_total_kg == Decimal("20.000")
    assert stb_clean.cleaned_kg == Decimal("980.000")
    assert stb_rej.rejects_kg == Decimal("20.000")


@pytest.mark.django_db
def test_post_creates_transactions():
    owner, warehouse, commodity, lot, user = setup_lot()
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        lot=lot,
        weight_in=Decimal("100"),
        weight_out=Decimal("95"),
        rejects=Decimal("5"),
        target_purity=Decimal("99"),
        purity_after=Decimal("99"),
        recorded_by=user,
    )
    post_daily_record(record.id, user)
    txs = BinCardTransaction.objects.filter(daily_record=record)
    assert txs.count() == 3
    movements = set(t.movement for t in txs)
    assert movements == {
        BinCardTransaction.RAW_OUT,
        BinCardTransaction.CLEANED_IN,
        BinCardTransaction.REJECT_OUT,
    }


@pytest.mark.django_db
def test_post_is_idempotent():
    owner, warehouse, commodity, lot, user = setup_lot()
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        lot=lot,
        weight_in=Decimal("100"),
        weight_out=Decimal("95"),
        rejects=Decimal("5"),
        target_purity=Decimal("99"),
        purity_after=Decimal("99"),
        recorded_by=user,
    )
    post_daily_record(record.id, user)
    post_daily_record(record.id, user)
    lot.refresh_from_db()
    assert lot.raw_balance_kg == Decimal("1900.000")


@pytest.mark.django_db
def test_negative_stock_blocked():
    owner, warehouse, commodity, lot, user = setup_lot()
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        lot=lot,
        weight_in=Decimal("2500"),
        weight_out=Decimal("2400"),
        rejects=Decimal("100"),
        target_purity=Decimal("99"),
        purity_after=Decimal("99"),
        recorded_by=user,
    )
    with pytest.raises(ValidationError):
        post_daily_record(record.id, user)


@pytest.mark.django_db
def test_mass_balance_validation():
    owner, warehouse, commodity, lot, user = setup_lot()
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        lot=lot,
        weight_in=Decimal("100"),
        weight_out=Decimal("80"),
        rejects=Decimal("5"),
        target_purity=Decimal("99"),
        purity_after=Decimal("99"),
        recorded_by=user,
    )
    with pytest.raises(ValidationError):
        post_daily_record(record.id, user)


@pytest.mark.django_db
def test_reversal_restores_state():
    owner, warehouse, commodity, lot, user = setup_lot()
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        lot=lot,
        weight_in=Decimal("100"),
        weight_out=Decimal("90"),
        rejects=Decimal("10"),
        target_purity=Decimal("99"),
        purity_after=Decimal("99"),
        recorded_by=user,
    )
    post_daily_record(record.id, user)
    reverse_posted_daily_record(record.id, user)
    lot.refresh_from_db()
    stb_clean = SeedTypeBalance.objects.get(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        purity=Decimal("99"),
    )
    stb_rej = SeedTypeBalance.objects.get(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        purity__isnull=True,
    )
    assert lot.raw_balance_kg == Decimal("2000.000")
    assert lot.cleaned_total_kg == Decimal("0.000")
    assert lot.rejects_total_kg == Decimal("0.000")
    assert stb_clean.cleaned_kg == Decimal("0.000")
    assert stb_rej.rejects_kg == Decimal("0.000")
    assert BinCardTransaction.objects.filter(daily_record=record).count() == 0


@pytest.mark.django_db
def test_bin_card_list_shows_cleaning_metrics(client):
    owner, warehouse, commodity, lot, user = setup_lot()
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=owner,
        seed_type=commodity,
        lot=lot,
        weight_in=Decimal("1000"),
        weight_out=Decimal("980"),
        rejects=Decimal("20"),
        target_purity=Decimal("99"),
        purity_after=Decimal("99"),
        recorded_by=user,
    )
    post_daily_record(record.id, user)
    lot.refresh_from_db()

    client.force_login(user)
    response = client.get(reverse("bin_cards"))
    content = response.content.decode()
    assert format(lot.weight, '.2f') in content
    assert format(lot.cleaned_total_kg, '.2f') in content
    assert format(lot.rejects_total_kg, '.2f') in content

