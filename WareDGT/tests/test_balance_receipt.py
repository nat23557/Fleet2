import decimal
import uuid
import pytest
import django
django.setup()
from django.core.management import call_command
from django.contrib.auth.models import User
from WareDGT.models import Company, Warehouse, SeedType, SeedTypeDetail, BinCardEntry, DailyRecord
from WareDGT.pdf_utils import generate_dailyrecord_receipt_pdf
from decimal import Decimal

@pytest.fixture
def setup_db():
    call_command("migrate", verbosity=0)

@pytest.fixture
def base(setup_db):
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
        weight=Decimal("100"),
        balance=Decimal("100"),
        raw_weight_remaining=Decimal("100"),
        warehouse=warehouse,
        purity=Decimal("95"),
    )
    user = User.objects.create_user(username=f"u{uuid.uuid4().hex[:6]}", password="pass")
    return {"owner": owner, "warehouse": warehouse, "detail": detail, "lot": lot, "user": user}


def make_record(data, rejects):
    return DailyRecord(
        warehouse=data["warehouse"],
        plant="Plant1",
        owner=data["owner"],
        seed_type=data["detail"],
        lot=data["lot"],
        operation_type=DailyRecord.CLEANING,
        weight_in=Decimal("100"),
        weight_out=Decimal("96"),
        actual_reject_weight=Decimal(str(rejects)),
        purity_before=Decimal("95"),
        target_purity=Decimal("98"),
        laborers=1,
        recorded_by=data["user"],
    )


@pytest.mark.django_db
def test_balance_estimates_flag(base):
    rec_ok = make_record(base, 4)
    est_ok = rec_ok.balance_estimates()
    assert est_ok["flagged"] is False
    assert est_ok["tolerance"] == Decimal("0.75")

    rec_bad = make_record(base, 3)
    est_bad = rec_bad.balance_estimates()
    assert est_bad["flagged"] is True

    pdf = generate_dailyrecord_receipt_pdf(rec_bad)
    content = pdf.read()
    assert content[:4] == b"%PDF"
