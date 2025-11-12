import os
from decimal import Decimal

import django
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from PyPDF2 import PdfReader

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import (
    Company,
    BinCardEntry,
    Warehouse,
    PurchasedItemType,
    EcxMovement,
    SeedTypeDetail,
)
from WareDGT.forms import BinCardEntryForm
from WareDGT.pdf_utils import get_or_build_bincard_pdf


class UnloadingLaborRateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.owner = Company.objects.get(name="DGT")
        self.wh = Warehouse.objects.create(
            code="W1",
            name="Warehouse 1",
            description="",
            warehouse_type=Warehouse.ECX,
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
        self.pit = PurchasedItemType.objects.create(
            seed_type=SeedTypeDetail.SESAME,
            origin="OR",
            grade="1",
            description="",
        )
        self.mv = EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=self.pit,
            net_obligation_receipt_no="n1",
            warehouse_receipt_no="w1",
            quantity_quintals=Decimal("1"),
            created_by=self.user,
            owner=self.owner,
        )

    def _pdf_text(self, entry):
        reader = PdfReader(entry.pdf_file.path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def test_form_round_trip_and_total(self):
        form = BinCardEntryForm(
            data={
                "owner": self.owner.pk,
                "source_type": BinCardEntry.ECX,
                "ecx_movement": str(self.mv.pk),
                "description": "With labor cost",
                "weight": "10",
                "unloading_rate_etb_per_qtl": "35.00",
                "remark": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        entry = form.save()
        self.assertEqual(entry.unloading_rate_etb_per_qtl, Decimal("35.00"))
        self.assertEqual(entry.unloading_labor_total_etb, Decimal("350.00"))

    def test_pdf_includes_unloading_labor(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="1",
            description="Labor cost",
            weight=Decimal("10"),
            purity=Decimal("90"),
            unloading_rate_etb_per_qtl=Decimal("35.00"),
        )
        get_or_build_bincard_pdf(entry, self.user)
        entry.refresh_from_db()
        text = self._pdf_text(entry)
        self.assertIn("Labor", text)
        self.assertIn("Unloading", text)
        self.assertIn("35", text)
        self.assertIn("Total Labor (ETB)", text)
        self.assertIn("350", text)

        entry2 = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="2",
            description="No labor cost",
            weight=Decimal("5"),
            purity=Decimal("90"),
        )
        get_or_build_bincard_pdf(entry2, self.user)
        text2 = self._pdf_text(entry2)
        self.assertNotIn("Labor", text2)

    def test_pdf_dirty_on_rate_change(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="3",
            description="Initial",
            weight=Decimal("5"),
            purity=Decimal("90"),
            unloading_rate_etb_per_qtl=Decimal("20.00"),
        )
        get_or_build_bincard_pdf(entry, self.user)
        entry.refresh_from_db()
        self.assertFalse(entry.pdf_dirty)

        entry.unloading_rate_etb_per_qtl = Decimal("25.00")
        entry.save()
        entry.refresh_from_db()
        self.assertTrue(entry.pdf_dirty)

        self.client.force_login(self.user)
        resp = self.client.get(reverse("bincard-pdf", args=[entry.pk]))
        self.assertEqual(resp.status_code, 200)
        entry.refresh_from_db()
        self.assertFalse(entry.pdf_dirty)
        text = self._pdf_text(entry)
        self.assertIn("25.00", text)

    def test_import_command_sets_default_unloading_rate(self):
        """Importing ECX movements sets unloading rate to 7 ETB/qtl."""
        call_command("import_ecx_movements_to_bincard")
        entry = BinCardEntry.objects.first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.unloading_rate_etb_per_qtl, Decimal("7"))
