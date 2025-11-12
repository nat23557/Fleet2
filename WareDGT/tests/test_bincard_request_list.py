import os
import django
from decimal import Decimal
from django.core.management import call_command
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
pytestmark = pytest.mark.django_db

from WareDGT.models import (
    Warehouse,
    BinCardEntryRequest,
    UserProfile,
    Company,
    StockOutRequest,
)


class RequestListBincardTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("migrate", verbosity=0)

    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_user(username="manager", password="pass")
        self.manager.profile.role = UserProfile.OPERATIONS_MANAGER
        self.manager.profile.save()
        self.officer = User.objects.create_user(username="officer", password="pass")
        self.officer.profile.role = UserProfile.WAREHOUSE_OFFICER
        self.officer.profile.save()
        self.agent = User.objects.create_user(username="agent", password="pass")
        self.agent.profile.role = UserProfile.ECX_AGENT
        self.agent.profile.save()

        self.wh = Warehouse.objects.create(
            code="W1",
            name="Main",
            warehouse_type=Warehouse.DGT,
            capacity_quintals=Decimal("100"),
            latitude=0,
            longitude=0,
        )

        self.req_officer = BinCardEntryRequest.objects.create(
            created_by=self.officer,
            approval_token="tok1",
            payload={"weight": 1},
            warehouse=self.wh,
            direction="IN",
        )
        self.req_agent = BinCardEntryRequest.objects.create(
            created_by=self.agent,
            approval_token="tok2",
            payload={"weight": 2},
            warehouse=self.wh,
            direction="OUT",
        )

        self.company = Company.objects.create(name="DGT")
        self.stock_req = StockOutRequest.objects.create(
            created_by=self.officer,
            approval_token="stok1",
            payload={"seed_type": "WWSS", "quantity": 1, "owner": str(self.company.id), "warehouse": str(self.wh.id)},
            warehouse=self.wh,
            owner=self.company,
        )

    def test_manager_sees_only_officer_requests(self):
        self.client.login(username="manager", password="pass")
        resp = self.client.get(reverse("request_list"), secure=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"?t={self.req_officer.approval_token}")
        self.assertNotContains(resp, f"?t={self.req_agent.approval_token}")
        self.assertContains(resp, f"?t={self.stock_req.approval_token}")
