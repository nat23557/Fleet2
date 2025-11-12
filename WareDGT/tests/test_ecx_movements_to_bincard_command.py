import os
from decimal import Decimal

import django
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.db.models import IntegerField
from django.db.models.functions import Cast

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import (
    BinCardEntry,
    Company,
    EcxMovement,
    PurchasedItemType,
    SeedTypeDetail,
    Warehouse,
)


class EcxMovementsToBinCardCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.owner = Company.objects.get(name="DGT")
        self.wh = Warehouse.objects.create(
            code="W1",
            name="Warehouse 1",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=0,
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
            seed_type=self.detail.symbol,
            origin="OR",
            grade="1",
            description="",
        )
        BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="2",
            weight=Decimal("1"),
            source_type=BinCardEntry.ECX,
            warehouse=self.wh,
        )
        BinCardEntry.objects.create(
            seed_type=self.detail,
            owner=self.owner,
            in_out_no="10",
            weight=Decimal("1"),
            source_type=BinCardEntry.ECX,
            warehouse=self.wh,
        )

        EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=self.pit,
            net_obligation_receipt_no="n1",
            warehouse_receipt_no="w1",
            quantity_quintals=Decimal("5"),
            created_by=self.user,
            owner=self.owner,
        )
        EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=self.pit,
            net_obligation_receipt_no="n2",
            warehouse_receipt_no="w2",
            quantity_quintals=Decimal("7"),
            created_by=self.user,
            owner=self.owner,
        )

    def test_command_creates_bin_card_entries(self):
        call_command("import_ecx_movements_to_bincard")
        self.assertEqual(EcxMovement.objects.count(), 0)
        entries = (
            BinCardEntry.objects.filter(owner=self.owner, seed_type__category=SeedTypeDetail.SESAME)
            .annotate(num=Cast("in_out_no", IntegerField()))
            .order_by("num")
        )
        self.assertEqual(entries.count(), 4)
        self.assertEqual([e.in_out_no for e in entries], ["2", "10", "11", "12"])
        new_entry = entries[2]
        self.assertEqual(new_entry.description, "input for Export Processing")
        self.assertEqual(new_entry.num_bags, 5)
        self.assertEqual(new_entry.car_plate_number, "3-A22549 - FSR")
        self.assertEqual(new_entry.purity, Decimal("97"))
        self.assertTrue(new_entry.weighbridge_certificate.name.endswith(".png"))
        self.assertTrue(new_entry.warehouse_document.name.endswith(".png"))
        self.assertTrue(new_entry.quality_form.name.endswith(".jpg"))
        self.assertTrue(new_entry.pdf_file.name.endswith(".pdf"))
        self.assertEqual(new_entry.date.year, 2025)
