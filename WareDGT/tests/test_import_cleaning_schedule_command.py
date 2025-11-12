import os
import sys
import datetime
from decimal import Decimal

import django
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()

pytestmark = pytest.mark.django_db(transaction=True)

from WareDGT.models import (
    Company,
    Warehouse,
    SeedType,
    SeedTypeDetail,
    BinCardEntry,
    DailyRecord,
)


class ImportCleaningScheduleCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.company = Company.objects.create(name="Comp")
        self.warehouse = Warehouse.objects.create(
            code="W1",
            name="Warehouse",
            description="",
            warehouse_type=Warehouse.DGT,
            owner=self.company,
            capacity_quintals=Decimal("1000"),
            latitude=Decimal("0"),
            longitude=Decimal("0"),
        )
        self.seed = SeedType.objects.create(code="SES", name="Sesame")
        self.detail = SeedTypeDetail.objects.create(
            category=SeedTypeDetail.SESAME,
            symbol="SES",
            name="Sesame",
            delivery_location=self.warehouse,
            grade="1",
            origin="ETH",
        )
        self._lot_counter = 0

    def _create_lot(self, qty):
        self._lot_counter += 1
        lot = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.company,
            in_out_no=f"LOT{self._lot_counter}",
            weight=Decimal(qty),
            balance=Decimal(qty),
            raw_weight_remaining=Decimal(qty),
            warehouse=self.warehouse,
            purity=Decimal("90"),
        )
        return lot

    def test_schedule_skips_weekends_and_processes_lots_sequentially(self):
        l1 = self._create_lot(500)
        l2 = self._create_lot(500)
        l3 = self._create_lot(700)

        call_command(
            "import_cleaning_schedule",
            user="tester",
            start_date="2025-01-01",
        )

        records = DailyRecord.objects.order_by("date", "pk")
        self.assertEqual(records.count(), 4)
        dates = [r.date for r in records]
        self.assertEqual(
            dates,
            [
                datetime.date(2025, 1, 1),
                datetime.date(2025, 1, 2),
                datetime.date(2025, 1, 3),
                datetime.date(2025, 1, 6),
            ],
        )
        amounts = [r.weight_in for r in records]
        self.assertEqual(
            amounts,
            [Decimal("500"), Decimal("500"), Decimal("500"), Decimal("200")],
        )
        lots = [r.lot for r in records]
        self.assertEqual(lots[0], l1)
        self.assertEqual(lots[1], l2)
        self.assertEqual(lots[2], l3)
        self.assertEqual(lots[3], l3)
        for r in records:
            self.assertTrue(r.balance_estimates().get("flagged"))
            self.assertEqual(r.target_purity, Decimal("99"))
            self.assertEqual(r.weight_out, Decimal("0"))
            self.assertEqual(r.laborers, 5)
            self.assertEqual(r.labor_rate_per_qtl, Decimal("8"))
            self.assertEqual(r.labor_cost, Decimal("0.00"))

