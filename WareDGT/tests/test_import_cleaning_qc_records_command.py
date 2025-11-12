import os
import sys
import datetime
from decimal import Decimal

import django
from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase
from zoneinfo import ZoneInfo

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.models import (
    Company,
    Warehouse,
    SeedType,
    SeedTypeDetail,
    BinCardEntry,
    DailyRecord,
)


class ImportCleaningQcRecordsCommandTests(TestCase):
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

    def _create_lot(self, qty, date=datetime.date(2024, 1, 1)):
        lot = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.company,
            in_out_no="LOT",
            weight=Decimal(qty),
            balance=Decimal(qty),
            raw_weight_remaining=Decimal(qty),
            warehouse=self.warehouse,
            purity=Decimal("90"),
        )
        BinCardEntry.objects.filter(pk=lot.pk).update(date=date)
        lot.refresh_from_db()
        return lot

    def test_creates_draft_and_qcs(self):
        lot = self._create_lot(500)
        call_command("import_cleaning_qc_records", user="tester")
        rec = DailyRecord.objects.get(lot=lot)
        self.assertFalse(rec.is_posted)
        self.assertEqual(rec.pieces, 10)
        qcs = list(rec.quality_checks.order_by("index"))
        self.assertEqual(len(qcs), 10)
        tz = ZoneInfo("Africa/Addis_Ababa")
        self.assertEqual(qcs[0].timestamp, datetime.datetime(2024, 1, 1, 8, 0, tzinfo=tz))
        self.assertEqual(qcs[-1].timestamp, datetime.datetime(2024, 1, 1, 18, 0, tzinfo=tz))
        total_qtl = sum(q.piece_quintals for q in qcs)
        wavg = sum(q.purity_percent * q.piece_quintals for q in qcs) / total_qtl
        self.assertEqual(rec.purity_after, wavg.quantize(Decimal("0.01")))
        avg = sum(q.purity_percent for q in qcs) / Decimal(len(qcs))
        self.assertEqual(rec.purity_after, avg.quantize(Decimal("0.01")))

    def test_raises_error_if_not_multiple_of_50(self):
        self._create_lot(520)
        with self.assertRaises(CommandError):
            call_command("import_cleaning_qc_records", user="tester")

    def test_rolls_over_next_day(self):
        lot = self._create_lot(600)
        call_command("import_cleaning_qc_records", user="tester")
        rec = DailyRecord.objects.get(lot=lot)
        qcs = list(rec.quality_checks.order_by("index"))
        tz = ZoneInfo("Africa/Addis_Ababa")
        self.assertEqual(qcs[10].timestamp, datetime.datetime(2024, 1, 2, 8, 0, tzinfo=tz))
        self.assertEqual(qcs[11].timestamp, datetime.datetime(2024, 1, 2, 9, 0, tzinfo=tz))

    def test_allows_remainder_with_flag(self):
        lot = self._create_lot(520)
        call_command(
            "import_cleaning_qc_records", user="tester", allow_remainder=True
        )
        rec = DailyRecord.objects.get(lot=lot)
        self.assertEqual(rec.pieces, 11)
        qcs = list(rec.quality_checks.order_by("index"))
        self.assertEqual(len(qcs), 11)
        self.assertEqual(qcs[-1].piece_quintals, Decimal("20.00"))
        total_qtl = sum(q.piece_quintals for q in qcs)
        wavg = sum(q.purity_percent * q.piece_quintals for q in qcs) / total_qtl
        self.assertEqual(rec.purity_after, wavg.quantize(Decimal("0.01")))

