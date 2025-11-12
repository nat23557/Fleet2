import decimal
import uuid
import pytest
import django
django.setup()
from django.core.management import call_command
from django.contrib.auth.models import User
from django.test import Client
from WareDGT.models import Company, Warehouse, SeedType, SeedTypeDetail, BinCardEntry, DailyRecord
from decimal import Decimal

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
        grade="A",
        origin="ETH",
    )
    lot = BinCardEntry.objects.create(
        seed_type=detail,
        owner=owner,
        in_out_no="LOT1",
        weight=Decimal("150"),
        balance=Decimal("150"),
        raw_weight_remaining=Decimal("150"),
        warehouse=warehouse,
        purity=Decimal("95"),
    )
    user = User.objects.create_user(username=f"u{uuid.uuid4().hex[:6]}", password="p")
    client = Client()
    client.force_login(user)
    return {"owner": owner, "detail": detail, "warehouse": warehouse, "lot": lot, "user": user, "client": client}


def test_quality_check_flow(basic_data):
    client = basic_data["client"]
    user = basic_data["user"]
    rec = DailyRecord.objects.create(
        warehouse=basic_data["warehouse"],
        plant="Plant",
        owner=basic_data["owner"],
        seed_type=basic_data["detail"],
        lot=basic_data["lot"],
        operation_type=DailyRecord.CLEANING,
        weight_in=Decimal("150"),
        weight_out=Decimal("0"),
        rejects=Decimal("0"),
        purity_before=Decimal("90"),
        purity_after=Decimal("90"),
        laborers=1,
        recorded_by=user,
    )
    url = f"/daily-records/{rec.id}/qc/add/"
    data1 = {
        "weight_sound_g": "27",
        "weight_reject_g": "3",
        "sample_weight_g": "30",
        "piece_quintals": "50",
        "machine_rate_kgph": "50",
    }
    r1 = client.post(url, data1)
    assert r1.status_code == 200
    assert r1.json()["c_number"] == "C-1"
    data2 = {
        "weight_sound_g": "28",
        "weight_reject_g": "2",
        "sample_weight_g": "30",
        "piece_quintals": "50",
        "machine_rate_kgph": "50",
    }
    client.post(url, data2)
    data3 = {
        "weight_sound_g": "29",
        "weight_reject_g": "1",
        "sample_weight_g": "30",
        "piece_quintals": "50",
        "machine_rate_kgph": "50",
    }
    client.post(url, data3)
    rec.refresh_from_db()
    assert rec.pieces == 3
    assert float(rec.purity_after) == pytest.approx(93.33, 0.1)
    assert float(rec.weight_out) == pytest.approx(140, 0.1)
    assert float(rec.rejects) == pytest.approx(10, 0.1)
    assert not rec.is_posted
    data4 = {
        "weight_sound_g": "30",
        "weight_reject_g": "0",
        "sample_weight_g": "30",
        "piece_quintals": "50",
        "machine_rate_kgph": "50",
    }
    r4 = client.post(url, data4)
    assert r4.status_code == 409
    assert r4.json()["no_more_stock"]


def test_quality_check_next_piece(basic_data):
    client = basic_data["client"]
    user = basic_data["user"]
    lot = basic_data["lot"]
    lot.balance = Decimal("120")
    lot.raw_weight_remaining = Decimal("120")
    lot.save()
    rec = DailyRecord.objects.create(
        warehouse=basic_data["warehouse"],
        plant="Plant",
        owner=basic_data["owner"],
        seed_type=basic_data["detail"],
        lot=lot,
        operation_type=DailyRecord.CLEANING,
        weight_in=Decimal("120"),
        weight_out=Decimal("0"),
        rejects=Decimal("0"),
        purity_before=Decimal("90"),
        purity_after=Decimal("90"),
        laborers=1,
        recorded_by=user,
    )
    url = f"/daily-records/{rec.id}/qc/add/"
    data1 = {
        "weight_sound_g": "27",
        "weight_reject_g": "3",
        "sample_weight_g": "30",
        "piece_quintals": "50",
        "machine_rate_kgph": "50",
    }
    r1 = client.post(url, data1)
    assert r1.status_code == 200
    assert r1.json()["next_piece"] == 50.0
    data2 = {
        "weight_sound_g": "28",
        "weight_reject_g": "2",
        "sample_weight_g": "30",
        "piece_quintals": "50",
        "machine_rate_kgph": "50",
    }
    r2 = client.post(url, data2)
    assert r2.status_code == 200
    assert r2.json()["next_piece"] == pytest.approx(20.0, 0.1)
    data3 = {
        "weight_sound_g": "29",
        "weight_reject_g": "1",
        "sample_weight_g": "30",
        "piece_quintals": "20",
        "machine_rate_kgph": "50",
    }
    r3 = client.post(url, data3)
    assert r3.status_code == 200
    assert r3.json()["next_piece"] == 0.0
    rec.refresh_from_db()
    assert not rec.is_posted


def test_quality_check_conflict_auto_posts(basic_data):
    client = basic_data["client"]
    user = basic_data["user"]
    lot = basic_data["lot"]
    lot.balance = Decimal("0.40")
    lot.raw_weight_remaining = Decimal("0.40")
    lot.save()
    rec = DailyRecord.objects.create(
        warehouse=basic_data["warehouse"],
        plant="Plant",
        owner=basic_data["owner"],
        seed_type=basic_data["detail"],
        lot=lot,
        operation_type=DailyRecord.CLEANING,
        weight_in=Decimal("0.40"),
        weight_out=Decimal("0"),
        rejects=Decimal("0"),
        purity_before=Decimal("90"),
        purity_after=Decimal("90"),
        laborers=1,
        recorded_by=user,
    )
    url = f"/daily-records/{rec.id}/qc/add/"
    data = {
        "weight_sound_g": "27",
        "weight_reject_g": "3",
        "sample_weight_g": "30",
        "piece_quintals": "50",
        "machine_rate_kgph": "50",
    }
    resp = client.post(url, data)
    assert resp.status_code == 409
    j = resp.json()
    assert j["no_more_stock"]
    rec.refresh_from_db()
    assert not rec.is_posted
