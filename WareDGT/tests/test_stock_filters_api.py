import os
import django
from datetime import date
from decimal import Decimal
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.models import Company, Warehouse, BinCardEntry, SeedTypeDetail


class StockFiltersEndpointTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.client.login(username="tester", password="pass")
        self.c1 = Company.objects.create(name="Acme")
        self.c2 = Company.objects.create(name="Beta")
        self.wh = Warehouse.objects.create(
            code="W1",
            name="Warehouse 1",
            description="",
            warehouse_type=Warehouse.ECX,
            owner=self.c1,
            capacity_quintals=0,
            footprint_m2=0,
            latitude=0,
            longitude=0,
        )
        self.detail1 = SeedTypeDetail.objects.create(
            category=SeedTypeDetail.SESAME,
            symbol="SES",
            name="Sesame",
            delivery_location=self.wh,
            grade="1",
            origin="ETH",
        )
        detail2 = SeedTypeDetail.objects.create(
            category=SeedTypeDetail.COFFEE,
            symbol="COF",
            name="Coffee",
            delivery_location=self.wh,
            grade="2",
            origin="ETH",
        )
        e1 = BinCardEntry.objects.create(
            owner=self.c1,
            warehouse=self.wh,
            seed_type=self.detail1,
            grade="1",
            in_out_no="1",
            weight=Decimal("10"),
            description="inbound",
        )
        e1.date = date(2025, 1, 1)
        e1.cleaned_weight = Decimal("4")
        e1.grade = "1C"
        e1.save(update_fields=["date", "cleaned_weight", "grade"])
        BinCardEntry.objects.create(
            owner=self.c2,
            warehouse=self.wh,
            seed_type=detail2,
            grade="2",
            in_out_no="2",
            weight=Decimal("5"),
            description="inbound",
        )

    def test_filter_options_constrained_by_owner(self):
        resp = self.client.get("/api/stock-filters/", {"owner": ["Acme"]})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        owners = [o["name"] for o in data["owners"]]
        self.assertEqual(owners, ["Acme"])
        seed_types = data["seed_types"]
        self.assertEqual(len(seed_types), 1)
        self.assertEqual(seed_types[0]["id"], str(self.detail1.id))
        self.assertEqual(seed_types[0]["symbol"], "SES")
        self.assertEqual(seed_types[0]["name"], "Sesame")
        warehouses = [w["code"] for w in data["warehouses"]]
        self.assertEqual(warehouses, ["W1"])

    def test_grade_options_follow_status(self):
        resp = self.client.get("/api/stock-filters/", {"status": "cleaned"})
        self.assertEqual(resp.status_code, 200)
        grades = [g["value"] for g in resp.json()["grades"]]
        self.assertEqual(grades, ["1C"])

        resp = self.client.get("/api/stock-filters/", {"status": "uncleaned"})
        self.assertEqual(resp.status_code, 200)
        grades = [g["value"] for g in resp.json()["grades"]]
        self.assertEqual(grades, ["2"])
