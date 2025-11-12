import os
import django
from decimal import Decimal
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)
call_command("create_companies")

from WareDGT.models import (
    UserProfile,
    Company,
    Warehouse,
    SeedTypeDetail,
    BinCardEntry,
)


class SmDashboardApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="pass")
        self.admin.profile.role = UserProfile.ADMIN
        self.admin.profile.save()
        self.client.login(username="admin", password="pass")

    def test_kpi_endpoint_structure(self):
        response = self.client.get("/api/dashboard/system-manager/kpis/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("cards", data)
        self.assertEqual(len(data["cards"]), 5)

    def test_forbidden_for_non_admin(self):
        User = get_user_model()
        u = User.objects.create_user(username="u1", password="pass")
        u.profile.role = UserProfile.WAREHOUSE_OFFICER
        u.profile.save()
        self.client.logout()
        self.client.login(username="u1", password="pass")
        response = self.client.get("/api/dashboard/system-manager/kpis/")
        self.assertEqual(response.status_code, 403)

    def test_negative_stock_anomaly(self):
        owner = Company.objects.first()
        wh = Warehouse.objects.create(
            code="W1",
            name="W1",
            warehouse_type=Warehouse.DGT,
            owner=owner,
            capacity_quintals=Decimal("100"),
            latitude=0,
            longitude=0,
        )
        sd = SeedTypeDetail.objects.create(
            symbol="S1",
            name="Seed1",
            delivery_location=wh,
            grade="G1",
            origin="OR",
        )
        BinCardEntry.objects.create(
            seed_type=sd,
            owner=owner,
            in_out_no="X",
            weight=Decimal("-1"),
        )
        response = self.client.get("/api/dashboard/system-manager/anomalies/")
        ids = [a["id"] for a in response.json()["alerts"]]
        self.assertIn("ANOM_NEG_STOCK", ids)

    def test_sidebar_dashboard_link(self):
        response = self.client.get("/")
        self.assertContains(response, reverse("sm_dashboard"))
        self.client.logout()
        User = get_user_model()
        u = User.objects.create_user(username="u2", password="pass")
        u.profile.role = UserProfile.WAREHOUSE_OFFICER
        u.profile.save()
        self.client.login(username="u2", password="pass")
        response = self.client.get("/")
        self.assertContains(response, reverse("dashboard"))
        self.assertNotContains(response, reverse("sm_dashboard"))

    def test_weighbridge_operator_sidebar_links(self):
        User = get_user_model()
        op = User.objects.create_user(username="op", password="pass")
        op.profile.role = UserProfile.WEIGHBRIDGE_OPERATOR
        op.profile.save()
        self.client.logout()
        self.client.login(username="op", password="pass")
        response = self.client.get("/")
        self.assertContains(response, reverse("dashboard"))
        self.assertContains(response, reverse("stock_movements"))

