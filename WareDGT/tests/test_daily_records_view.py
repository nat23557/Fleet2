import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.core.management import call_command
from django.test import Client
from django.utils import timezone
import decimal
import uuid
from datetime import timedelta

pytestmark = pytest.mark.django_db
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
def client_logged(setup_db):
    user = User.objects.create_user(username=f"u{uuid.uuid4().hex[:6]}", password="p")
    client = Client()
    client.force_login(user)
    return client


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
    return {
        "owner": owner,
        "seed": seed,
        "detail": detail,
        "warehouse": warehouse,
        "lot": lot,
    }



def test_daily_records_page_accessible(client_logged):
    url = reverse("daily_records")
    resp = client_logged.get(url)
    assert resp.status_code == 200
    assert b"Daily Records" in resp.content
    assert b"weight_in" in resp.content


def test_save_creates_draft_record(client_logged, basic_data):
    url = reverse("daily_records")
    data = {
        "owner": basic_data["owner"].pk,
        "seed_type": basic_data["detail"].pk,
        "lot": basic_data["lot"].pk,
        "operation_type": DailyRecord.CLEANING,
        "laborers": 1,
        "labor_rate_per_qtl": "1.00",
        "remarks": "",
        "submit_record": "save_draft",
    }
    resp = client_logged.post(url, data, follow=True)
    assert resp.status_code == 200
    rec = DailyRecord.objects.filter(lot=basic_data["lot"]).latest("id")
    assert not rec.is_posted
    assert rec.warehouse == basic_data["warehouse"]
    assert rec.weight_in == decimal.Decimal("10")
    assert rec.purity_before == decimal.Decimal("95")
    assert rec.labor_cost == decimal.Decimal("0.00")


def test_save_draft_visible(client_logged, basic_data):
    url = reverse("daily_records")
    data = {
        "owner": basic_data["owner"].pk,
        "seed_type": basic_data["detail"].pk,
        "lot": basic_data["lot"].pk,
        "operation_type": DailyRecord.CLEANING,
        "laborers": 1,
        "labor_rate_per_qtl": "1.00",
        "remarks": "",
        "submit_record": "save_draft",
    }
    resp = client_logged.post(url, data, follow=True)
    assert resp.status_code == 200
    rec = DailyRecord.objects.filter(lot=basic_data["lot"]).latest("id")
    assert not rec.is_posted
    assert b"LOT1" in resp.content
    assert b"Draft" in resp.content


def test_filters_by_period(client_logged, basic_data):
    today = timezone.now().date()
    # create records on different dates
    dates = [
        today,
        today - timedelta(days=2),
        today - timedelta(days=5),
        today - timedelta(days=40),
        today - timedelta(days=400),
    ]
    for d in dates:
        DailyRecord.objects.create(
            date=d,
            warehouse=basic_data["warehouse"],
            owner=basic_data["owner"],
            seed_type=basic_data["detail"],
            lot=basic_data["lot"],
            operation_type=DailyRecord.CLEANING,
            weight_in=decimal.Decimal("10"),
            weight_out=decimal.Decimal("9"),
            recorded_by=User.objects.create_user(username=f"u{uuid.uuid4().hex[:6]}")
        )

    url = reverse("daily_records")

    resp = client_logged.get(url, {"period": "day", "start": today.isoformat()})
    assert len(resp.context["records"]) == 1

    resp = client_logged.get(url, {"period": "week", "start": today.isoformat()})
    assert len(resp.context["records"]) == 2

    resp = client_logged.get(url, {"period": "month", "start": today.isoformat()})
    assert len(resp.context["records"]) == 3

    resp = client_logged.get(url, {"period": "year", "start": today.isoformat()})
    assert len(resp.context["records"]) == 4

    resp = client_logged.get(url, {"period": "all"})
    assert len(resp.context["records"]) == 5

