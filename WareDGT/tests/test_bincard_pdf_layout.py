import os
import datetime
from decimal import Decimal

import django
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.core.files import File
from django.test import TestCase
from django.utils import timezone
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from PyPDF2 import PdfReader
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()

from WareDGT.models import (
    Company,
    BinCardEntry,
    Warehouse,
    PurchasedItemType,
    EcxMovement,
    SeedTypeDetail,
    EcxMovementReceiptFile,
    SeedType,
    StockMovement,
    QualityAnalysis,
    DailyRecord,
    QualityCheck,
)
from WareDGT.pdf_utils import generate_bincard_pdf, get_or_build_bincard_pdf

pytestmark = pytest.mark.django_db


class BinCardPDFLayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_companies")

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

    def _parse_positions(self, pdf_path):
        page_layout = next(extract_pages(pdf_path))
        positions = {}
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                for line in element:
                    text = line.get_text().strip()
                    if text:
                        positions[text] = (line.x0, line.x1)
        return page_layout.width, positions

    def test_pdf_without_optional_sections(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="1",
            description="Test entry",
            weight=Decimal("10"),
            purity=Decimal("90"),
            car_plate_number="AA-123",
            grade="1",
        )
        generate_bincard_pdf(entry, self.user)
        reader = PdfReader(entry.pdf_file.path)
        self.assertEqual(len(reader.pages), 1)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Balance Summary (qtls)", text)
        self.assertNotIn("ECX Movement", text)
        self.assertNotIn("Latest Daily Record", text)
        self.assertNotIn("Labor", text)
        self.assertIn("Car Plate Number", text)
        self.assertIn("AA-123", text)
        self.assertIn("Grade", text)
        self.assertIn("Seed Type & Grade", text)
        self.assertNotIn("Weight In", text)
        width, pos = self._parse_positions(entry.pdf_file.path)
        self.assertLess(pos["Date"][0], pos[str(entry.date)][0])
        self.assertGreater(pos[str(entry.date)][0] - pos["Date"][0], 100)
        bs_center = (pos["Balance Summary (qtls)"][0] + pos["Balance Summary (qtls)"][1]) / 2
        self.assertAlmostEqual(bs_center, width / 2, delta=40)

        # snapshot: later entries should not change existing PDF
        BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="later",
            description="Later entry",
            weight=Decimal("5"),
            purity=Decimal("90"),
            grade="1",
        )
        get_or_build_bincard_pdf(entry, self.user)
        reader = PdfReader(entry.pdf_file.path)
        text2 = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertNotIn("15.00", text2)

    def test_description_none(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            warehouse=self.wh,
            in_out_no="1",
            description="",
            weight=Decimal("10"),
            purity=Decimal("90"),
            grade="1",
        )
        entry.description = None
        generate_bincard_pdf(entry, self.user)
        reader = PdfReader(entry.pdf_file.path)
        self.assertEqual(len(reader.pages), 1)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Description", text)
        self.assertNotIn("None", text)

    def test_long_item_type_on_new_line(self):
        long_origin = (
            "Tach Armachiho, Tsedegie, West Armachiho (Zemene Merik, Meharish) a"
        )
        pit = PurchasedItemType.objects.create(
            seed_type="WHGSS",
            origin=long_origin,
            grade="1",
            description="",
        )
        mv = EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=pit,
            net_obligation_receipt_no="n1",
            warehouse_receipt_no="w1",
            quantity_quintals=Decimal("1"),
            created_by=self.user,
            owner=self.owner,
        )
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            ecx_movement=mv,
            in_out_no="long",
            description="Long item type",
            weight=Decimal("5"),
            purity=Decimal("90"),
            grade="1",
        )
        generate_bincard_pdf(entry, self.user)
        reader = PdfReader(entry.pdf_file.path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn(f"Item Type\n{pit.code}", text)
        self.assertNotIn(f"Item Type {pit.code}", text)

    def test_pdf_with_sections_and_images(self):
        wh = Warehouse.objects.create(
            code="W1",
            name="Warehouse 1",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("100"),
            footprint_m2=Decimal("100"),
            latitude=0,
            longitude=0,
        )
        pit = PurchasedItemType.objects.create(
            seed_type=SeedTypeDetail.SESAME,
            origin="OR",
            grade="1",
            description="",
        )
        mv = EcxMovement.objects.create(
            warehouse=wh,
            item_type=pit,
            net_obligation_receipt_no="n1",
            warehouse_receipt_no="w1",
            quantity_quintals=Decimal("1"),
            created_by=self.user,
            owner=self.owner,
        )
        with open("logo.png", "rb") as fh:
            EcxMovementReceiptFile.objects.create(
                movement=mv, image=File(fh, name="receipt.png")
            )
        receipts = list(mv.receipt_files.all())
        detail = SeedTypeDetail.objects.create(
            category=SeedTypeDetail.SESAME,
            symbol="SES",
            name="Sesame",
            delivery_location=wh,
            grade="1",
            origin="ETH",
        )
        with open("Image.png", "rb") as f1, open("Weight.png", "rb") as f2:
            entry = BinCardEntry.objects.create(
                seed_type=detail,
                owner=self.owner,
                ecx_movement=mv,
                in_out_no="2",
                description="Full entry",
                weight=Decimal("5"),
                purity=Decimal("90"),
                weighbridge_certificate=File(f1),
                warehouse_document=File(f2),
                car_plate_number="AA-123",
                unloading_rate_etb_per_qtl=Decimal("1"),
                grade="1",
            )
        seed = SeedType.objects.create(code=SeedTypeDetail.SESAME, name="Sesame")
        sm = StockMovement.objects.create(
            movement_type=StockMovement.INBOUND,
            ticket_no="t1",
            ticket_date=datetime.date.today(),
            enter_time=timezone.now(),
            exit_time=timezone.now(),
            plate_no="AA",
            supplier=self.owner,
            receiver=self.user,
            warehouse=wh,
            seed_type=seed,
            owner=self.owner,
            gross_weight=Decimal("10"),
            tare_weight=Decimal("1"),
            net_weight=Decimal("9"),
            num_bags=1,
        )
        QualityAnalysis.objects.create(
            movement=sm,
            first_sound_weight=Decimal("1"),
            first_foreign_weight=Decimal("0.1"),
            first_purity_percent=Decimal("99"),
            second_test_datetime=timezone.now(),
            second_sound_weight=Decimal("1"),
            second_foreign_weight=Decimal("0.1"),
            total_bags=1,
            sampled_bags=1,
            second_purity_percent=Decimal("98"),
        )
        dr = DailyRecord.objects.create(
            plant=self.owner,
            date=datetime.date.today(),
            warehouse=wh,
            seed_type=detail,
            lot=entry,
            owner=self.owner,
            operation_type=DailyRecord.CLEANING,
            weight_in=Decimal("1"),
            weight_out=Decimal("0"),
            rejects=Decimal("0.2"),
            purity_before=Decimal("90"),
            purity_after=Decimal("90"),
            laborers=1,
            cleaning_labor_rate_etb_per_qtl=Decimal("2"),
            reject_weighing_rate_etb_per_qtl=Decimal("3"),
            recorded_by=self.user,
            status=DailyRecord.STATUS_POSTED,
        )
        QualityCheck.objects.create(
            daily_record=dr,
            weight_sound_g=Decimal("10"),
            weight_reject_g=Decimal("0.5"),
            timestamp=timezone.now(),
        )
        generate_bincard_pdf(entry, self.user)
        reader = PdfReader(entry.pdf_file.path)
        self.assertEqual(len(reader.pages), 4)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        for header in [
            "ECX Movement",
            "Quality Analysis",
            "Cleaning Details",
            "Labor",
            "Balance Summary (qtls)",
            "Hourly QC (Posted Cleaning)",
        ]:
            self.assertIn(header, text)
        self.assertIn("Cleaning", text)
        self.assertIn("Reject Weighing", text)
        self.assertIn("Total Labor (ETB)", text)
        self.assertIn("ECX Receipt", text)
        self.assertNotIn("Latest Daily Record", text)
        self.assertIn("Car Plate Number", text)
        self.assertIn("AA-123", text)

        # Ensure ECX receipt files are embedded as attachments in the PDF
        embedded = (
            reader.trailer["/Root"].get("/Names", {}).get("/EmbeddedFiles", {}).get("/Names", [])
        )
        attached = [embedded[i] for i in range(0, len(embedded), 2)]
        self.assertTrue(any(name.startswith("receipt") for name in attached))

    def test_ecx_receipt_is_first_full_image_page(self):
        pit = PurchasedItemType.objects.create(
            seed_type=SeedTypeDetail.SESAME,
            origin="OR",
            grade="1",
            description="",
        )
        mv = EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=pit,
            net_obligation_receipt_no="n1",
            warehouse_receipt_no="w1",
            quantity_quintals=Decimal("1"),
            created_by=self.user,
            owner=self.owner,
        )
        with open("logo.png", "rb") as fh:
            EcxMovementReceiptFile.objects.create(
                movement=mv, image=File(fh, name="receipt_test.png")
            )
        receipts = list(mv.receipt_files.all())
        with open("Image.png", "rb") as f1, open("Weight.png", "rb") as f2:
            entry = BinCardEntry.objects.create(
                seed_type=self.detail,
                owner=self.owner,
                ecx_movement=mv,
                in_out_no="5",
                description="Order test",
                weight=Decimal("5"),
                purity=Decimal("90"),
                weighbridge_certificate=File(f1),
                warehouse_document=File(f2),
                grade="1",
            )
        generate_bincard_pdf(entry, self.user)
        reader = PdfReader(entry.pdf_file.path)
        texts = [page.extract_text() or "" for page in reader.pages]
        receipt_idx = next(i for i, t in enumerate(texts) if "Figure: ECX Receipt" in t)
        wb_idx = next(i for i, t in enumerate(texts) if "Figure: Weighbridge" in t)
        self.assertLess(receipt_idx, wb_idx)
        self.assertNotIn("Figure: Weighbridge", texts[receipt_idx])
        self.assertNotIn("Figure: Warehouse Doc", texts[receipt_idx])

    def test_reject_weighing_row_omitted_when_rate_missing(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="3",
            description="No reject rate",
            weight=Decimal("5"),
            purity=Decimal("90"),
            unloading_rate_etb_per_qtl=Decimal("1"),
            grade="1",
        )
        DailyRecord.objects.create(
            plant=self.owner,
            date=datetime.date.today(),
            warehouse=self.wh,
            seed_type=self.detail,
            lot=entry,
            owner=self.owner,
            operation_type=DailyRecord.CLEANING,
            weight_in=Decimal("1"),
            weight_out=Decimal("0"),
            rejects=Decimal("0.5"),
            purity_before=Decimal("90"),
            purity_after=Decimal("90"),
            cleaning_labor_rate_etb_per_qtl=Decimal("2"),
            recorded_by=self.user,
            status=DailyRecord.STATUS_POSTED,
        )
        generate_bincard_pdf(entry, self.user)
        text = "\n".join(
            page.extract_text() or "" for page in PdfReader(entry.pdf_file.path).pages
        )
        self.assertIn("Labor", text)
        self.assertNotIn("Reject Weighing", text)

    def test_pdf_generation_fails_without_ecx_receipt(self):
        pit = PurchasedItemType.objects.create(
            seed_type=SeedTypeDetail.SESAME,
            origin="OR",
            grade="1",
            description="",
        )
        mv = EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=pit,
            net_obligation_receipt_no="n2",
            warehouse_receipt_no="w2",
            quantity_quintals=Decimal("1"),
            created_by=self.user,
            owner=self.owner,
        )
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            ecx_movement=mv,
            source_type=BinCardEntry.ECX,
            in_out_no="4",
            description="Missing receipt",
            weight=Decimal("5"),
            purity=Decimal("90"),
            grade="1",
        )
        with self.assertRaises(ValueError):
            generate_bincard_pdf(entry, self.user)
    def test_reject_weighing_row_included_with_legacy_rate(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="4",
            description="Legacy reject rate",
            weight=Decimal("5"),
            purity=Decimal("90"),
            unloading_rate_etb_per_qtl=Decimal("1"),
            grade="1",
        )
        DailyRecord.objects.create(
            plant=self.owner,
            date=datetime.date.today(),
            warehouse=self.wh,
            seed_type=self.detail,
            lot=entry,
            owner=self.owner,
            operation_type=DailyRecord.CLEANING,
            weight_in=Decimal("1"),
            weight_out=Decimal("0"),
            rejects=Decimal("0.4"),
            purity_before=Decimal("90"),
            purity_after=Decimal("90"),
            reject_labor_payment_per_qtl=Decimal("4"),
            recorded_by=self.user,
            status=DailyRecord.STATUS_POSTED,
        )
        generate_bincard_pdf(entry, self.user)
        text = "\n".join(
            page.extract_text() or "" for page in PdfReader(entry.pdf_file.path).pages
        )
        self.assertIn("Reject Weighing", text)

    def test_weighbridge_attachments_displayed_and_embedded(self):
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="7",
            description="Attachment test",
            weight=Decimal("5"),
            purity=Decimal("90"),
            grade="1",
            warehouse=self.wh,
        )
        with open("Image.png", "rb") as f1, open("Weight.png", "rb") as f2:
            entry.attachments.create(
                kind="weighbridge", file=File(f1, name="wb1.png")
            )
            entry.attachments.create(
                kind="weighbridge", file=File(f2, name="wb2.png")
            )
        generate_bincard_pdf(entry, self.user)
        reader = PdfReader(entry.pdf_file.path)
        texts = [page.extract_text() or "" for page in reader.pages]
        count = sum(t.count("Figure: Weighbridge") for t in texts)
        self.assertEqual(count, 2)
        embedded = (
            reader.trailer["/Root"].get("/Names", {}).get("/EmbeddedFiles", {}).get("/Names", [])
        )
        attached = [embedded[i] for i in range(0, len(embedded), 2)]
        self.assertTrue(any(name.startswith("wb") for name in attached))

    def test_weighbridge_certificate_copied_from_ecx_movement(self):
        pit = PurchasedItemType.objects.create(
            seed_type="SES", origin="ETH", grade="1"
        )
        with open("Weight.png", "rb") as f1:
            mv = EcxMovement.objects.create(
                warehouse=self.wh,
                item_type=pit,
                net_obligation_receipt_no="n2",
                warehouse_receipt_no="w2",
                quantity_quintals=Decimal("5"),
                created_by=self.user,
                owner=self.owner,
                weighbridge_certificate=File(f1, name="wb.png"),
            )
        entry = BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            ecx_movement=mv,
            in_out_no="9",
            description="Movement cert",
            weight=Decimal("5"),
            purity=Decimal("90"),
            grade="1",
            warehouse=self.wh,
        )
        entry.refresh_from_db()
        self.assertTrue(entry.weighbridge_certificate)

        generate_bincard_pdf(entry, self.user)
        texts = [page.extract_text() or "" for page in PdfReader(entry.pdf_file.path).pages]
        self.assertTrue(any("Figure: Weighbridge" in t for t in texts))
