import os
import sys
import datetime
from decimal import Decimal

import django
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

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
    DailyRecordAssessment,
)


class ImportDraftQcRecordsCommandTests(TestCase):
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

    def _create_draft_record(self, qty, date=datetime.date(2024, 1, 1)):
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
        rec = DailyRecord.objects.create(
            lot=lot,
            warehouse=self.warehouse,
            plant="",
            owner=self.company,
            seed_type=lot.seed_type,
            date=date,
            weight_in=Decimal(qty),
            weight_out=Decimal("0"),
            rejects=Decimal("0"),
            purity_before=Decimal("90"),
            purity_after=Decimal("90"),
            target_purity=Decimal("99.50"),
            laborers=5,
            labor_rate_per_qtl=Decimal("8"),
            recorded_by=self.user,
            status=DailyRecord.STATUS_DRAFT,
            operation_type=DailyRecord.CLEANING,
        )
        return rec

    def test_populates_and_posts_drafts(self):
        rec = self._create_draft_record(500)
        call_command("import_draft_qc_records", user="tester")
        rec.refresh_from_db()
        self.assertTrue(rec.is_posted)
        self.assertGreater(rec.rejects, Decimal("0"))
        self.assertLess(rec.weight_out, rec.weight_in)
        self.assertIsNotNone(rec.actual_reject_weight)
        self.assertEqual(rec.rejects, rec.actual_reject_weight.quantize(Decimal("0.01")))
        self.assertEqual(rec.reject_weighed_by, self.user)
        self.assertIsNotNone(rec.reject_weighed_at)
        self.assertFalse(rec.is_fishy)

        qcs = list(rec.quality_checks.order_by("index"))
        self.assertTrue(qcs)
        for qc in qcs:
            self.assertLessEqual(qc.piece_quintals, Decimal("50"))
            diff = abs(qc.purity_percent - rec.purity_after)
            self.assertLessEqual(diff, Decimal("0.18"))
        self.assertLess(qcs[-1].piece_quintals, Decimal("50"))

        assessment = DailyRecordAssessment.objects.get(daily_record=rec)
        spread_tol = Decimal("0.04")
        self.assertFalse(assessment.flagged)
        self.assertLessEqual(assessment.spread, spread_tol)
        mid = (rec.weight_in + rec.weight_out) / Decimal("2")
        self.assertLessEqual(abs(assessment.pre_operation - mid), spread_tol / 2)
        self.assertLessEqual(abs(assessment.in_operation - mid), spread_tol / 2)
        self.assertLessEqual(abs(assessment.post_operation - mid), spread_tol / 2)
