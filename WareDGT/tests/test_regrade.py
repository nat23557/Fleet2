import os
import decimal
import pytest
import django
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()

pytestmark = pytest.mark.django_db

from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

from WareDGT.models import (
    Company,
    Warehouse,
    SeedType,
    SeedTypeDetail,
    BinCardEntry,
    DailyRecord,
    SeedGradeParameter,
)


@pytest.fixture
def setup_db():
    call_command("migrate", verbosity=0)


def test_regrade_after_cleaning(setup_db):
    call_command("flush", verbosity=0, interactive=False)
    owner = Company.objects.create(name="Owner")
    seed = SeedType.objects.create(code="SE", name="Sesame")
    warehouse = Warehouse.objects.create(
        code="WH1",
        name="Warehouse1",
        description="",
        warehouse_type=Warehouse.DGT,
        owner=owner,
        capacity_quintals=Decimal("1000"),
        footprint_m2=Decimal("100"),
        latitude=Decimal("0"),
        longitude=Decimal("0"),
    )
    detail = SeedTypeDetail.objects.create(
        category=SeedTypeDetail.SESAME,
        symbol="SES",
        name="Sesame",
        delivery_location=warehouse,
        grade="UG",
        origin="ETH",
    )
    SeedGradeParameter.objects.create(seed_type=detail, grade="1", min_purity=Decimal("98"))
    SeedGradeParameter.objects.create(seed_type=detail, grade="2", min_purity=Decimal("95"))
    lot = BinCardEntry.objects.create(
        seed_type=detail,
        owner=owner,
        in_out_no="LOT1",
        weight=Decimal("100"),
        balance=Decimal("100"),
        raw_weight_remaining=Decimal("100"),
        warehouse=warehouse,
        purity=Decimal("95"),
        grade="UG",
    )
    user = User.objects.create_user(username="tester", password="pass")

    rec = DailyRecord.objects.create(
        date=timezone.now().date(),
        warehouse=warehouse,
        plant="Plant",
        owner=owner,
        seed_type=detail,
        lot=lot,
        operation_type=DailyRecord.CLEANING,
        weight_in=Decimal("50"),
        weight_out=Decimal("50"),
        rejects=Decimal("0"),
        purity_before=Decimal("95"),
        purity_after=Decimal("98"),
        laborers=1,
        recorded_by=user,
        target_purity=Decimal("98"),
    )
    rec.full_clean()
    rec.save()
    rec.post(user)

    lot.refresh_from_db()
    assert lot.grade == "1"
