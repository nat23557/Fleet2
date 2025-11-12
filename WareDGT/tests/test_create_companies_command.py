import django
import os
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.models import (
    Company,
    Warehouse,
    SeedType,
    Commodity,
    EcxTrade,
    EcxMovement,
    PurchasedItemType,
)


class CreateCompaniesCommandTests(TestCase):
    def test_command_creates_companies_and_assigns_dgt(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester", password="pass")

        wh = Warehouse.objects.create(
            code="EC1",
            name="ECX1",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed = SeedType.objects.create(code="S1", name="Seed")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")

        trade = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=Decimal("10"),
            recorded_by=user,
        )

        item_type = PurchasedItemType.objects.create(seed_type="S1", origin="OR", grade="1")
        movement = EcxMovement.objects.create(
            warehouse=wh,
            item_type=item_type,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=Decimal("10"),
            created_by=user,
        )

        call_command("create_companies")

        dgt = Company.objects.get(name="DGT")
        self.assertTrue(Company.objects.filter(name="BestWay").exists())
        trade.refresh_from_db()
        movement.refresh_from_db()
        self.assertEqual(trade.owner, dgt)
        self.assertEqual(movement.owner, dgt)
