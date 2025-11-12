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


class StockSeriesEndpointsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.client.login(username="tester", password="pass")
        self.company = Company.objects.create(name="Acme")
        self.wh = Warehouse.objects.create(
            code="W1",
            name="Warehouse 1",
            description="",
            warehouse_type=Warehouse.ECX,
            owner=self.company,
            capacity_quintals=0,
            footprint_m2=0,
            latitude=0,
            longitude=0,
        )
        self.detail = SeedTypeDetail.objects.create(
            category=SeedTypeDetail.SESAME,
            symbol="SES",
            name="Sesame",
            delivery_location=self.wh,
            grade="1",
            origin="ETH",
        )
        e1 = BinCardEntry.objects.create(
            owner=self.company,
            warehouse=self.wh,
            seed_type=self.detail,
            grade="1",
            in_out_no="1",
            weight=Decimal("10"),
            num_bags=5,
            description="inbound",
        )
        e1.date = date(2025, 1, 1)
        e1.save(update_fields=["date"])

        e2 = BinCardEntry.objects.create(
            owner=self.company,
            warehouse=self.wh,
            seed_type=self.detail,
            grade="1",
            in_out_no="2",
            weight=Decimal("-4"),
            num_bags=2,
            description="outbound",
            source_type=BinCardEntry.ECX,
        )
        e2.date = date(2025, 1, 2)
        e2.cleaned_weight = Decimal("4")
        e2.save(update_fields=["date", "cleaned_weight"])

    def test_stock_series_returns_balance(self):
        resp = self.client.get(
            "/api/stock-series/",
            {
                "owner_id": self.company.id,
                "warehouse_id": self.wh.id,
                "seed_type": self.detail.id,
                "grade": "1",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[-1]["balance_kg"], 6.0)

    def test_stock_events_returns_rows(self):
        resp = self.client.get(
            "/api/stock-events/",
            {
                "owner_id": self.company.id,
                "warehouse_id": self.wh.id,
                "seed_type": self.detail.id,
                "grade": "1",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[1]["type"], "ecx")
        self.assertEqual(data[1]["num_bags"], 2)

    def test_status_filters(self):
        base = {
            "owner_id": self.company.id,
            "warehouse_id": self.wh.id,
            "seed_type": self.detail.id,
            "grade": "1",
        }
        resp = self.client.get("/api/stock-events/", {**base, "status": "cleaned"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["message"], "outbound")

        resp = self.client.get("/api/stock-events/", {**base, "status": "uncleaned"})
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["message"], "inbound")

        resp = self.client.get("/api/stock-series/", {**base, "status": "cleaned"})
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["outflow_kg"], 4.0)

        resp = self.client.get("/api/stock-series/", {**base, "status": "uncleaned"})
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["inflow_kg"], 10.0)

    def test_stock_series_without_view(self):
        from django.db import connection
        from importlib import import_module

        try:
            VIEW_SQL = import_module(
                "WareDGT.migrations.0002_create_v_bincard_stock_series"
            ).VIEW_SQL
        except ModuleNotFoundError:
            self.skipTest("view migration not available")

        with connection.cursor() as cursor:
            cursor.execute("DROP VIEW IF EXISTS v_bincard_stock_series")

        resp = self.client.get(
            "/api/stock-series/",
            {
                "owner_id": self.company.id,
                "warehouse_id": self.wh.id,
                "seed_type": self.detail.id,
                "grade": "1",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[-1]["balance_kg"], 6.0)

        with connection.cursor() as cursor:
            cursor.execute(VIEW_SQL)
