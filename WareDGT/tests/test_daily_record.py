import decimal
import pytest
import django
django.setup()
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.utils import timezone
import uuid
from WareDGT.models import Company, Warehouse, SeedType, SeedTypeDetail, BinCardEntry, DailyRecord

@pytest.fixture
def setup_db():
    call_command("migrate", verbosity=0)

@pytest.fixture
def basic_data(setup_db):
    owner = Company.objects.create(name=f"Owner_{uuid.uuid4()}")
    seed = SeedType.objects.create(code=f"S{uuid.uuid4().hex[:2]}", name="Sesame")
    warehouse = Warehouse.objects.create(
        code=f"WH{uuid.uuid4().hex[:4]}",
        name="Warehouse1",
        description="",
        warehouse_type=Warehouse.DGT,
        owner=owner,
        capacity_quintals=decimal.Decimal("1000"),
        footprint_m2=decimal.Decimal("100"),
        latitude=decimal.Decimal("0"),
        longitude=decimal.Decimal("0"),
    )
    detail = SeedTypeDetail.objects.create(
        category=SeedTypeDetail.SESAME,
        symbol="SES",
        name="Sesame",
        delivery_location=warehouse,
        grade="A",
        origin="ETH",
    )
    lot = BinCardEntry.objects.create(
        seed_type=detail,
        owner=owner,
        in_out_no="LOT1",
        weight=decimal.Decimal("10"),
        warehouse=warehouse,
        purity=decimal.Decimal("95"),
    )
    user = User.objects.create_user(username=f"u{uuid.uuid4().hex[:6]}", password="pass")
    return {
        "owner": owner,
        "seed": seed,
        "detail": detail,
        "warehouse": warehouse,
        "lot": lot,
        "user": user,
    }


def test_balance_validation(basic_data):
    data = basic_data
    rec = DailyRecord(
        date=timezone.now().date(),
        warehouse=data["warehouse"],
        plant="Plant1",
        owner=data["owner"],
        seed_type=data["detail"],
        lot=data["lot"],
        operation_type=DailyRecord.CLEANING,
        weight_in=decimal.Decimal("10"),
        weight_out=decimal.Decimal("9"),
        rejects=decimal.Decimal("0.5"),
        purity_before=decimal.Decimal("95"),
        purity_after=decimal.Decimal("98"),
        laborers=1,
        recorded_by=data["user"],
    )
    with pytest.raises(ValidationError):
        rec.full_clean()


def test_post_updates_lot(basic_data):
    data = basic_data
    rec = DailyRecord.objects.create(
        warehouse=data["warehouse"],
        plant="Plant1",
        owner=data["owner"],
        seed_type=data["detail"],
        lot=data["lot"],
        operation_type=DailyRecord.CLEANING,
        weight_in=decimal.Decimal("10"),
        weight_out=decimal.Decimal("9.9"),
        rejects=decimal.Decimal("0.1"),
        purity_before=decimal.Decimal("95"),
        purity_after=decimal.Decimal("98"),
        laborers=1,
        recorded_by=data["user"],
    )
    rec.post(data["user"])
    rec.refresh_from_db()
    lot = data["lot"]
    lot.refresh_from_db()
    assert rec.is_posted
    assert lot.raw_weight_remaining == decimal.Decimal("0")
    assert lot.cleaned_weight == decimal.Decimal("9.9")
