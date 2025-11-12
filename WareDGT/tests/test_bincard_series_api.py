import os
import django
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import Company, Warehouse, SeedType, Commodity, BinCard, BinCardTransaction


class BinCardSeriesAPITests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass")
        self.client.login(username="tester", password="pass")
        self.company = Company.objects.get(name="DGT")
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
        self.seed = SeedType.objects.create(code="SES", name="Sesame")
        self.commodity = Commodity.objects.create(seed_type=self.seed, origin="OR", grade="1")
        self.bin_card = BinCard.objects.create(owner=self.company, commodity=self.commodity, warehouse=self.wh)
        BinCardTransaction.objects.create(bin_card=self.bin_card, qty_in=10)
        BinCardTransaction.objects.create(bin_card=self.bin_card, qty_out=4)

    def test_series_endpoint_returns_balance(self):
        url = f"/api/bincards/{self.bin_card.id}/series/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[-1]["balance_kg"], 6.0)

    def test_forecast_endpoint_returns_data(self):
        url = f"/api/bincards/{self.bin_card.id}/forecast/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(len(resp.json()) > 0)

    def test_events_endpoint_returns_list(self):
        url = f"/api/bincards/{self.bin_card.id}/events/"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])
