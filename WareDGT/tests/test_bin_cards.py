import os
from decimal import Decimal
from datetime import date

import django
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from PyPDF2 import PdfReader

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import (
    Company,
    BinCardEntry,
    BinCardAttachment,
    SeedTypeDetail,
    Warehouse,
    PurchasedItemType,
    EcxMovement,
    EcxMovementReceiptFile,
    remove_ecx_movement,
)
from WareDGT.forms import BinCardEntryForm
from WareDGT.pdf_utils import get_or_build_bincard_pdf
from django.db.models.signals import post_save


class BinCardViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.client.login(username="tester", password="pass")
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
            quantity_quintals=1,
            created_by=self.user,
            owner=self.owner,
        )
        EcxMovementReceiptFile.objects.create(
            movement=self.mv,
            image=SimpleUploadedFile("r.jpg", b"file", content_type="image/jpeg"),
        )
        self.mv.weighed = True
        self.mv.save()

    def test_list_page_has_register_link_without_form(self):
        url = reverse("bin_cards")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Register stock")
        self.assertNotContains(response, 'id="id_ecx_movement"')

    def test_register_page_shows_form(self):
        url = reverse("bin_cards") + "?register=1"
        response = self.client.get(url)
        self.assertContains(response, 'id="id_ecx_movement"')
        self.assertContains(response, "DGT")
        self.assertContains(response, "BestWay")
        self.assertContains(response, "Other")

    def test_register_out_page_shows_form(self):
        url = reverse("bin_cards") + "?register_out=1"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Outbound stock form should expose seed type selector
        self.assertContains(response, 'id="seedType"')
        # Quantity input should also be present
        self.assertContains(response, 'id="quantity"')
        # Outbound form should not hide fields on load
        self.assertContains(response, 'if (!ownerEl) return;')
        # Owner options should be rendered
        self.assertContains(
            response,
            f'<option value="{self.owner.id}">{self.owner.name}</option>'
        )


    def test_list_page_handles_existing_movement(self):
        url = reverse("bin_cards")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_post_creates_entry(self):
        url = reverse("bin_cards")
        data = {
            "owner": self.owner.pk,
            "source_type": BinCardEntry.ECX,
            "ecx_movement": str(self.mv.pk),
            "description": "Test entry",
            "weight": "10",
            "remark": "",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BinCardEntry.objects.count(), 1)
        entry = BinCardEntry.objects.first()
        self.assertEqual(entry.balance, Decimal("10"))
        self.assertEqual(entry.grade, self.pit.grade)
        self.assertEqual(EcxMovement.objects.count(), 0)
        self.assertTrue(entry.pdf_file.name.endswith(".pdf"))
        self.assertTrue(os.path.exists(entry.pdf_file.path))

        reader = PdfReader(entry.pdf_file.path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("ECX Movement", text)
        self.assertIn("Balance Summary", text)


    def test_pdf_generation_links_receipts_when_missing(self):
        """PDF builder should pull ECX receipts from the movement if the post-save
        signal didn't attach them."""
        # Temporarily disable the signal that normally copies receipt files so we
        # can simulate a missing attachment scenario.
        post_save.disconnect(remove_ecx_movement, sender=BinCardEntry)
        try:
            mv = EcxMovement.objects.create(
                warehouse=self.wh,
                item_type=self.pit,
                net_obligation_receipt_no="n4",
                warehouse_receipt_no="w4",
                quantity_quintals=1,
                created_by=self.user,
                owner=self.owner,
            )
            EcxMovementReceiptFile.objects.create(
                movement=mv,
                image=SimpleUploadedFile("r.jpg", b"file", content_type="image/jpeg"),
            )
            entry = BinCardEntry.objects.create(
                seed_type=self.detail,
                owner=self.owner,
                source_type=BinCardEntry.ECX,
                ecx_movement=mv,
                weight=Decimal("10"),
                description="auto",
            )
        finally:
            # Restore the signal to avoid side effects for other tests.
            post_save.connect(remove_ecx_movement, sender=BinCardEntry)

        # No attachments should have been created because the signal was
        # disconnected above.
        self.assertEqual(
            entry.attachments.filter(kind=BinCardAttachment.Kind.ECX_RECEIPT).count(),
            0,
        )
        # Calling the PDF helper should now link the receipts and delete the
        # movement.
        get_or_build_bincard_pdf(entry, self.user)
        self.assertEqual(
            entry.attachments.filter(kind=BinCardAttachment.Kind.ECX_RECEIPT).count(),
            1,
        )
        self.assertIsNone(BinCardEntry.objects.get(pk=entry.pk).ecx_movement)

    def test_initial_stock_balance_snapshot(self):
        e1 = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="s1",
            description="",
            weight=Decimal("10"),
            grade="1",
        )
        e2 = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="s2",
            description="",
            weight=Decimal("5"),
            grade="1",
        )
        e3 = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="s3",
            description="",
            weight=Decimal("7"),
            grade="2",
        )


        self.assertEqual(e1.initial_stock_balance_type_qtl, Decimal("10"))
        self.assertEqual(e1.initial_stock_balance_grade_qtl, Decimal("10"))
        self.assertEqual(e2.initial_stock_balance_type_qtl, Decimal("15"))
        self.assertEqual(e2.initial_stock_balance_grade_qtl, Decimal("15"))
        self.assertEqual(e3.initial_stock_balance_type_qtl, Decimal("22"))
        self.assertEqual(e3.initial_stock_balance_grade_qtl, Decimal("7"))


    def test_selected_warehouse_is_saved(self):
        url = reverse("bin_cards")
        data = {
            "owner": self.owner.pk,
            "source_type": BinCardEntry.ECX,
            "ecx_movement": str(self.mv.pk),
            "description": "Test entry",
            "weight": "10",
            "remark": "",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        entry = BinCardEntry.objects.first()
        self.assertEqual(entry.warehouse, self.wh)

    def test_owner_defaults_to_dgt(self):
        url = reverse("bin_cards")
        data = {
            "source_type": BinCardEntry.ECX,
            "ecx_movement": str(self.mv.pk),
            "description": "Default owner",
            "weight": "1",
            "remark": "",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        entry = BinCardEntry.objects.first()
        self.assertEqual(entry.owner.name, "DGT")

    def test_default_companies_seeded(self):
        self.assertTrue(Company.objects.filter(name="DGT").exists())
        self.assertTrue(Company.objects.filter(name="BestWay").exists())
        self.assertTrue(Company.objects.filter(name="Other").exists())

    def test_ecx_movement_queryset_filtered_by_owner(self):
        other = Company.objects.get(name="BestWay")
        wh2 = Warehouse.objects.create(
            code="W2",
            name="Warehouse 2",
            description="",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=0,
            footprint_m2=0,
            latitude=0,
            longitude=0,
        )
        mv_other = EcxMovement.objects.create(
            warehouse=wh2,
            item_type=self.pit,
            net_obligation_receipt_no="n2",
            warehouse_receipt_no="w2",
            quantity_quintals=1,
            created_by=self.user,
            owner=other,
        )
        mv_other.weighed = True
        mv_other.save()
        form = BinCardEntryForm(data={"owner": self.owner.pk})
        qs = form.fields["ecx_movement"].queryset
        self.assertIn(self.mv, qs)
        self.assertNotIn(mv_other, qs)

    def test_running_totals_increment_per_entry(self):
        e1 = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="a1",
            description="",
            weight=Decimal("0"),
            cleaned_total_kg=Decimal("10"),
            rejects_total_kg=Decimal("1"),
        )
        e2 = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="a2",
            description="",
            weight=Decimal("0"),
            cleaned_total_kg=Decimal("5"),
            rejects_total_kg=Decimal("0.5"),
        )
        e1.date = date(2024, 1, 1)
        e1.save(update_fields=["date"])
        e2.date = date(2024, 1, 2)
        e2.save(update_fields=["date"])

        response = self.client.get(reverse("bin_cards"))
        entries = list(response.context["entries"])

        self.assertEqual(entries[0].cleaned_seed_total, Decimal("15"))
        self.assertEqual(entries[1].cleaned_seed_total, Decimal("10"))
        self.assertEqual(entries[0].reject_seed_total, Decimal("1.5"))
        self.assertEqual(entries[1].reject_seed_total, Decimal("1"))

    def test_totals_display_in_quintals(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="a1",
            description="",
            weight=Decimal("0"),
            cleaned_total_kg=Decimal("50"),
            rejects_total_kg=Decimal("5"),
        )

        response = self.client.get(reverse("bin_cards"))
        entries = list(response.context["entries"])
        two_places = Decimal("0.01")
        self.assertEqual(entries[0].cleaned_total_qtl, Decimal("50").quantize(two_places))
        self.assertEqual(entries[0].rejects_total_qtl, Decimal("5").quantize(two_places))

    def test_stock_out_row_shows_negative_cleaned_value(self):
        BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="a1",
            description="",
            weight=Decimal("0"),
            cleaned_total_kg=Decimal("5"),
        )
        BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="a2",
            description="",
            weight=Decimal("-3"),
            cleaned_total_kg=Decimal("-3"),
        )
        response = self.client.get(reverse("bin_cards"))
        self.assertRegex(
            response.content.decode(),
            r"<td>-3\.00</td>\s*<td>0\.00</td>",
        )

    def test_stock_out_row_shows_negative_reject_value(self):
        BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="b1",
            description="",
            weight=Decimal("0"),
            rejects_total_kg=Decimal("5"),
        )
        BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="b2",
            description="",
            weight=Decimal("-3"),
            rejects_total_kg=Decimal("-3"),
        )
        response = self.client.get(reverse("bin_cards"))
        self.assertRegex(
            response.content.decode(),
            r"<td>0\.00</td>\s*<td>-3\.00</td>",
        )

    def test_running_balance_falls_back_to_stored_balance(self):
        first = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="c1",
            description="Initial stock",
            weight=Decimal("500"),
            balance=Decimal("500"),
        )
        first.date = date(2024, 1, 1)
        first.save(update_fields=["date"])

        second = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="c2",
            description="Cleaned product stock out",
            weight=Decimal("200"),
            balance=Decimal("700"),
        )
        # Simulate legacy data where the running balance is persisted correctly
        # but the weight was stored with the wrong sign.
        BinCardEntry.objects.filter(pk=second.pk).update(
            weight=Decimal("200"),
            balance=Decimal("300"),
            cleaned_total_kg=Decimal("-200"),
        )
        second.refresh_from_db()
        second.date = date(2024, 1, 2)
        second.save(update_fields=["date"])

        response = self.client.get(reverse("bin_cards"))
        entries = list(response.context["entries"])
        self.assertEqual(entries[0].display_balance_qtl, Decimal("500.00"))
        self.assertEqual(entries[1].display_balance_qtl, Decimal("300.00"))
