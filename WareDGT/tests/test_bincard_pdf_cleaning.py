import os
from decimal import Decimal
from datetime import timedelta

import django
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PyPDF2 import PdfReader

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import Company, BinCardEntry, Warehouse, SeedTypeDetail, DailyRecord  # noqa:E402
from WareDGT.pdf_utils import get_or_build_bincard_pdf  # noqa:E402


class BinCardCleaningPDFTests(TestCase):
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

    def _pdf_text(self, entry):
        reader = PdfReader(entry.pdf_file.path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def test_pdf_includes_cleaning_details(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="1",
            description="Test entry",
            weight=Decimal("10"),
            purity=Decimal("90"),
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
            purity_after=Decimal("95"),
            shrink_margin=Decimal("1"),
            passes=2,
            remarks="Routine run",
            laborers=5,
            labor_rate_per_qtl=Decimal("10"),
            cleaning_equipment="Turbo cleaner with extended description to test wrapping",
            chemicals_used="water, soap",
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=1),
            recorded_by=self.user,
        )
        dr.workers.add(self.user)
        get_or_build_bincard_pdf(entry, self.user)
        entry.refresh_from_db()
        text = self._pdf_text(entry)
        self.assertIn("Cleaning Details", text)
        self.assertIn("Equipment / Method", text)
        self.assertIn("water, soap", text)

    def test_pdf_omits_cleaning_when_absent(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="2",
            description="Test entry",
            weight=Decimal("10"),
            purity=Decimal("90"),
        )
        get_or_build_bincard_pdf(entry, self.user)
        entry.refresh_from_db()
        text = self._pdf_text(entry)
        self.assertNotIn("Cleaning Details", text)

    def test_pdf_rebuilds_when_cleaning_draft_is_posted(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="3",
            description="Test entry",
            weight=Decimal("10"),
            purity=Decimal("90"),
        )
        get_or_build_bincard_pdf(entry, self.user)
        entry.refresh_from_db()
        self.assertFalse(entry.pdf_dirty)

        dr = DailyRecord.objects.create(
            date=timezone.now().date(),
            warehouse=self.wh,
            owner=self.owner,
            seed_type=self.detail,
            lot=entry,
            operation_type=DailyRecord.CLEANING,
            status=DailyRecord.STATUS_DRAFT,
            weight_in=Decimal("10"),
            weight_out=Decimal("9"),
            rejects=Decimal("1"),
            purity_before=Decimal("90"),
            purity_after=Decimal("95"),
            shrink_margin=Decimal("1"),
            recorded_by=self.user,
        )
        entry.refresh_from_db()
        self.assertFalse(entry.pdf_dirty)

        dr.status = DailyRecord.STATUS_POSTED
        dr.save()
        entry.refresh_from_db()
        self.assertTrue(entry.pdf_dirty)

        self.client.force_login(self.user)
        resp = self.client.get(reverse("bincard-pdf", args=[entry.pk]))
        self.assertEqual(resp.status_code, 200)
        entry.refresh_from_db()
        self.assertFalse(entry.pdf_dirty)
        self.assertIsNotNone(entry.pdf_generated_at)
        text = self._pdf_text(entry)
        self.assertIn("Cleaning Details", text)
