import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import Warehouse, Company, SeedType, Commodity, EcxTrade, UserProfile
from WareDGT.views import EcxTradeListView


class EcxTradeListViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="u", password="p")
        self.user.profile.role = UserProfile.ECX_OFFICER
        self.user.profile.save()
        self.client.login(username="u", password="p")

        self.wh = Warehouse.objects.create(
            code="EC1",
            name="EC1",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=1,
            latitude=0,
            longitude=0,
        )
        self.owner, _ = Company.objects.get_or_create(name="DGT")
        seed = SeedType.objects.create(code="S", name="Seed")
        commodity = Commodity.objects.create(seed_type=seed, origin="O", grade="1")
        EcxTrade.objects.create(
            warehouse=self.wh,
            commodity=commodity,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=1,
            purchase_date=timezone.localdate(),
            recorded_by=self.user,
            owner=self.owner,
        )

    def test_context_contains_filters(self):
        rf = RequestFactory()
        request = rf.get(reverse("ecxtrade_list"))
        request.user = self.user
        response = EcxTradeListView.as_view()(request)
        response.render()
        self.assertIn("warehouses", response.context_data)
        self.assertIn("owners", response.context_data)
        self.assertIn(self.wh, list(response.context_data["warehouses"]))
        self.assertIn(self.owner, list(response.context_data["owners"]))

    def test_warehouse_names_do_not_show_type(self):
        response = self.client.get(reverse("ecxtrade_list"))
        self.assertContains(response, self.wh.code)
        self.assertNotContains(response, f"{self.wh.code} ({self.wh.get_warehouse_type_display()})")
        self.assertNotContains(response, "(DGT)")
