import os
import decimal
import pytest
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()

pytestmark = pytest.mark.django_db
from django.contrib.auth.models import User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from WareDGT.models import (
    Company,
    Warehouse,
    SeedType,
    SeedTypeDetail,
    BinCardEntry,
    DailyRecord,
)


@pytest.fixture
def setup_db():
    call_command("migrate", verbosity=0)


@pytest.fixture
def basic_data(setup_db):
    call_command("flush", verbosity=0, interactive=False)
    owner = Company.objects.create(name="Owner")
    seed = SeedType.objects.create(code="SE", name="Sesame")
    warehouse = Warehouse.objects.create(
        code="WH1",
        name="Warehouse1",
        description="",
        warehouse_type=Warehouse.DGT,
        owner=owner,
        capacity_quintals=decimal.Decimal("10000"),
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
        weight=decimal.Decimal("1000"),
        balance=decimal.Decimal("1000"),
        raw_weight_remaining=decimal.Decimal("1000"),
        warehouse=warehouse,
        purity=decimal.Decimal("95"),
    )
    user = User.objects.create_user(username="tester", password="pass")
    return {
        "owner": owner,
        "seed": seed,
        "detail": detail,
        "warehouse": warehouse,
        "lot": lot,
        "user": user,
    }


def make_record(data, **kwargs):
    defaults = dict(
        date=timezone.now().date(),
        warehouse=data["warehouse"],
        plant="Plant",
        owner=data["owner"],
        seed_type=data["detail"],
        lot=data["lot"],
        operation_type=DailyRecord.CLEANING,
        weight_in=decimal.Decimal("1000"),
        weight_out=decimal.Decimal("0"),
        rejects=decimal.Decimal("0"),
        purity_before=decimal.Decimal("95"),
        purity_after=decimal.Decimal("95"),
        laborers=1,
        recorded_by=data["user"],
        target_purity=decimal.Decimal("98"),
    )
    defaults.update(kwargs)
    return DailyRecord(**defaults)


def test_target_purity_validation(basic_data):
    data = basic_data
    rec = make_record(data, target_purity=decimal.Decimal("94"))
    with pytest.raises(Exception):
        rec.full_clean()

    rec = make_record(data, target_purity=decimal.Decimal("98"))
    rec.full_clean()
    rec.save()
    assert rec.expected_reject_weight == decimal.Decimal("35.612")
    assert rec.combined_expected_reject_weight == decimal.Decimal("35.612")


def test_estimation_math(basic_data):
    data = basic_data
    rec = make_record(data, weight_out=decimal.Decimal("990"))
    rec.compute_estimations()
    assert rec.expected_reject_weight == decimal.Decimal("35.612")
    assert rec.combined_expected_reject_weight == decimal.Decimal("33.051")


def test_reject_weighing_posting(basic_data):
    from django.test import Client

    data = basic_data
    rec = make_record(data)
    rec.full_clean()
    rec.save()
    client = Client()
    client.login(username="tester", password="pass")
    url = reverse("dailyrecord_reject_weighing", args=[rec.pk])
    resp = client.post(
        url,
        {
            "actual_reject_weight": "36",
            "laborers": "5",
            "reject_labor_payment_per_qtl": "40",
        },
    )
    assert resp.status_code == 302
    rec.refresh_from_db()
    assert rec.status == DailyRecord.STATUS_POSTED
    assert rec.is_posted
    assert rec.weight_out == decimal.Decimal("964.00")
    assert rec.rejects == decimal.Decimal("36.00")
    assert rec.actual_reject_weight == decimal.Decimal("36.000")
    assert rec.reject_weighed_by == data["user"]
    assert rec.reject_weighed_at is not None
    assert rec.labor_cost == decimal.Decimal("1440.00")

    rec.lot.refresh_from_db()
    assert rec.lot.raw_weight_remaining == decimal.Decimal("0")


def test_fishy_flag(basic_data):
    from django.test import Client

    data = basic_data
    rec = make_record(data)
    rec.full_clean()
    rec.save()
    client = Client()
    client.login(username="tester", password="pass")
    url = reverse("dailyrecord_reject_weighing", args=[rec.pk])
    client.post(
        url,
        {
            "actual_reject_weight": "45",
            "laborers": "5",
            "reject_labor_payment_per_qtl": "40",
        },
    )
    rec.refresh_from_db()
    assert rec.is_fishy
    assert rec.deviation_pct == decimal.Decimal("0.0094")


def test_balance_consistency(basic_data):
    from django.test import Client

    data = basic_data
    rec = make_record(data)
    rec.full_clean()
    rec.save()
    client = Client()
    client.login(username="tester", password="pass")
    url = reverse("dailyrecord_reject_weighing", args=[rec.pk])
    client.post(
        url,
        {
            "actual_reject_weight": "36",
            "laborers": "5",
            "reject_labor_payment_per_qtl": "40",
        },
    )
    rec.refresh_from_db()
    total = rec.weight_out + rec.actual_reject_weight.quantize(decimal.Decimal("0.01"))
    assert abs(total - rec.weight_in) < decimal.Decimal("0.01")
    assert rec.weight_out >= decimal.Decimal("0")


def test_permissions(basic_data):
    from django.test import Client

    data = basic_data
    rec = make_record(data)
    rec.full_clean()
    rec.save()
    client = Client()
    url = reverse("dailyrecord_reject_weighing", args=[rec.pk])
    resp = client.post(
        url,
        {
            "actual_reject_weight": "36",
            "laborers": "5",
            "reject_labor_payment_per_qtl": "40",
        },
    )
    assert resp.status_code in (302, 403)

    client.login(username="tester", password="pass")
    rec.status = DailyRecord.STATUS_POSTED
    rec.save(update_fields=["status"])
    resp = client.post(
        url,
        {
            "actual_reject_weight": "36",
            "laborers": "5",
            "reject_labor_payment_per_qtl": "40",
        },
    )
    assert resp.status_code == 400

