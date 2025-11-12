import pytest
from decimal import Decimal
from django.core.management import call_command
from django.contrib.auth import get_user_model

from WareDGT.models import Company, Warehouse, SeedTypeDetail, BinCardEntry, DailyRecord


@pytest.mark.django_db
def test_import_draft_qc_records_sets_owner():
    User = get_user_model()
    user = User.objects.create(username="Admin")
    owner = Company.objects.create(name="Owner A")
    other_owner = Company.objects.create(name="Other")
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
    seed = SeedTypeDetail.objects.create(
        symbol="SES-ETH-A",
        name="Sesame",
        delivery_location=warehouse,
        grade="A",
        origin="ETH",
    )
    lot = BinCardEntry.objects.create(
        seed_type=seed,
        owner=owner,
        in_out_no="1",
        weight=Decimal("100"),
        raw_weight_remaining=Decimal("100"),
        raw_balance_kg=Decimal("100"),
        warehouse=warehouse,
        grade="A",
    )
    record = DailyRecord.objects.create(
        warehouse=warehouse,
        owner=other_owner,
        seed_type=seed,
        lot=lot,
        weight_in=Decimal("50"),
        weight_out=Decimal("0"),
        rejects=Decimal("0"),
        target_purity=Decimal("95"),
        purity_before=Decimal("90"),
        purity_after=Decimal("90"),
        recorded_by=user,
    )
    call_command("import_draft_qc_records", user="Admin", limit=1)
    record.refresh_from_db()
    assert record.owner == owner
    assert record.status == DailyRecord.STATUS_POSTED
