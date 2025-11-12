import os
from decimal import Decimal
import django
os.environ["DJANGO_SETTINGS_MODULE"] = "warehouse_project.settings_test"
django.setup()

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
import pytest
from WareDGT.models import (
    Warehouse,
    Company,
    SeedTypeDetail,
    PurchasedItemType,
    EcxMovement,
    BinCardEntry,
)

pytestmark = pytest.mark.django_db


class ImportBincardCommandTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("migrate", verbosity=0)

    def test_import_assigns_dgt_warehouse(self):
        User = get_user_model()
        user = User.objects.create_user(username="u", password="p")
        ecx_wh = Warehouse.objects.create(
            code="ECX1",
            name="ECX Warehouse",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("100"),
            latitude=0,
            longitude=0,
        )
        dgt_wh = Warehouse.objects.create(
            code="DGT1",
            name="DGT Warehouse",
            warehouse_type=Warehouse.DGT,
            capacity_quintals=Decimal("100"),
            latitude=0,
            longitude=0,
        )
        Company.objects.create(name="DGT")
        pit = PurchasedItemType.objects.create(seed_type="WHSS", origin="ET", grade="5", description="")
        SeedTypeDetail.objects.create(
            symbol="WHSS",
            name="White Sesame",
            delivery_location=ecx_wh,
            grade="5",
            origin="ET",
            handling_procedure="",
        )
        mv = EcxMovement.objects.create(
            warehouse=ecx_wh,
            item_type=pit,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="W1",
            quantity_quintals=Decimal("10"),
            created_by=user,
        )
        call_command("import_ecx_movements_to_bincard")
        entry = BinCardEntry.objects.get(ecx_movement=mv)
        assert entry.warehouse == dgt_wh
