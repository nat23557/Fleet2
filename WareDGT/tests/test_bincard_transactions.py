from decimal import Decimal
from django.test import TestCase
from WareDGT.models import (
    Company,
    SeedType,
    Warehouse,
    Commodity,
    BinCard,
    BinCardTransaction,
)


class BinCardTransactionTests(TestCase):
    def setUp(self):
        self.owner = Company.objects.create(name="Owner A")
        self.seed = SeedType.objects.create(code="SES", name="Sesame")
        self.warehouse = Warehouse.objects.create(
            code="W1",
            name="Main",
            warehouse_type=Warehouse.DGT,
            owner=self.owner,
            capacity_quintals=1000,
            footprint_m2=100,
            latitude=0,
            longitude=0,
        )
        self.commodity = Commodity.objects.create(
            seed_type=self.seed,
            origin="ETH",
            grade="A",
        )
        self.bin_card = BinCard.objects.create(
            owner=self.owner,
            commodity=self.commodity,
            warehouse=self.warehouse,
        )

    def test_balance_updates(self):
        BinCardTransaction.objects.create(
            bin_card=self.bin_card, qty_in=Decimal("100"), reference="IN1"
        )
        tx = BinCardTransaction.objects.create(
            bin_card=self.bin_card, qty_out=Decimal("40"), reference="OUT1"
        )
        self.assertEqual(tx.balance, Decimal("60"))
