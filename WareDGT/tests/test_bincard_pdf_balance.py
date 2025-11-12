import os
from decimal import Decimal

import django
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from PyPDF2 import PdfReader

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import (
    Company,
    BinCardEntry,
    Warehouse,
    SeedTypeDetail,
    SeedGradeParameter,
    DailyRecord,
)
from WareDGT.pdf_utils import generate_bincard_pdf
from WareDGT.services.cleaning import post_daily_record


class BinCardBalanceSummaryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.owner = Company.objects.get(name="DGT")
        self.wh = Warehouse.objects.create(
            code="W0",
            name="Warehouse 0",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("100"),
            footprint_m2=Decimal("100"),
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
        # grading parameters to allow grade change
        SeedGradeParameter.objects.create(
            seed_type=self.detail,
            grade="1",
            min_purity=Decimal("0"),
            max_purity=Decimal("95"),
        )
        SeedGradeParameter.objects.create(
            seed_type=self.detail,
            grade="2",
            min_purity=Decimal("95"),
            max_purity=Decimal("100"),
        )

    def _pdf_text(self, entry):
        reader = PdfReader(entry.pdf_file.path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def test_balance_summary_includes_initial_stock(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="1",
            description="Test entry",
            weight=Decimal("10"),
            purity=Decimal("90"),
            grade="1",
        )
        generate_bincard_pdf(entry, self.user)
        text = self._pdf_text(entry)
        self.assertIn("Stock Balance\n10.00\n10.00", text)

    def test_balance_summary_reflects_cleaning_and_rejects(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="1",
            description="Test entry",
            weight=Decimal("10"),
            purity=Decimal("90"),
            grade="1",
        )
        dr = DailyRecord.objects.create(
            date=timezone.now().date(),
            warehouse=self.wh,
            owner=self.owner,
            seed_type=self.detail,
            lot=entry,
            operation_type=DailyRecord.CLEANING,
            status=DailyRecord.STATUS_POSTED,
            weight_in=Decimal("10"),
            weight_out=Decimal("9"),
            rejects=Decimal("1"),
            purity_before=Decimal("90"),
            purity_after=Decimal("96"),
            recorded_by=self.user,
        )
        post_daily_record(dr.id, self.user)
        generate_bincard_pdf(entry, self.user)
        text = self._pdf_text(entry)
        # Cleaned and reject balances should match the lot's results
        self.assertIn("Cleaned Balance", text)
        self.assertIn("Reject Balance", text)
        self.assertIn("9.00", text)
        self.assertIn("1.00", text)
