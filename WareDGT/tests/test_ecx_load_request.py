from decimal import Decimal
import datetime
import django
import os
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.management import call_command
from django.urls import reverse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.models import (
    Warehouse,
    SeedType,
    Commodity,
    EcxTrade,
    UserProfile,
    EcxLoadRequest,
    EcxShipment,
    EcxMovement,
)
from WareDGT.views import WarehouseViewSet, LoadRequestViewSet
from rest_framework.test import APIRequestFactory


class EcxLoadRequestTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.manager = self.User.objects.create_user(
            username="manager", password="pass", email="m@example.com"
        )
        self.manager.profile.role = UserProfile.OPERATIONS_MANAGER
        self.manager.profile.save()
        self.agent = self.User.objects.create_user(username="agent", password="pass")
        agent_profile = self.agent.profile
        agent_profile.role = UserProfile.ECX_AGENT
        agent_profile.save()
        self.wh = Warehouse.objects.create(
            code="EC1",
            name="ECX1",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        agent_profile.warehouses.add(self.wh)
        seed = SeedType.objects.create(code="S1", name="Seed")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")
        self.trade = EcxTrade.objects.create(
            warehouse=self.wh,
            commodity=commodity,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=Decimal("10"),
            purchase_date=datetime.date.today(),
            recorded_by=self.manager,
        )
        # Second warehouse/trade not assigned to agent
        self.wh2 = Warehouse.objects.create(
            code="EC2",
            name="ECX2",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("500"),
            latitude=0,
            longitude=0,
        )
        EcxTrade.objects.create(
            warehouse=self.wh2,
            commodity=commodity,
            net_obligation_receipt_no="N2",
            warehouse_receipt_no="WR2",
            quantity_quintals=Decimal("20"),
            purchase_date=datetime.date.today(),
            recorded_by=self.manager,
        )

    def test_submit_load_request_page_removed(self):
        """Old load request form should be inaccessible and not in sidebar."""
        self.client.login(username="agent", password="pass")
        resp = self.client.get("/ecx-loads/request/", secure=True)
        self.assertEqual(resp.status_code, 404)
        console = self.client.get(reverse("ecx_console"), secure=True)
        self.assertNotContains(console, "Submit ECX Load Request")

    def test_agent_trade_list_filtered(self):
        self.client.login(username="agent", password="pass")
        resp = self.client.get(reverse("ecxtrade_list"), secure=True, follow=True)
        self.assertContains(resp, "WR1")
        self.assertNotContains(resp, "WR2")

    def test_agent_can_submit_request_from_map(self):
        self.client.login(username="agent", password="pass")
        resp = self.client.post(
            reverse("ecx_load_request_from_map"),
            {
                "warehouse_id": self.wh.id,
                "symbol": "S1",
                "grade": "1",
                "trade_ids": [self.trade.id],
                "plombs_count": 1,
                "has_trailer": "on",
                "trailer_count": 1,
            },
            secure=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertJSONEqual(resp.content, {"ok": True})
        self.trade.refresh_from_db()
        self.assertFalse(self.trade.loaded)
        self.assertEqual(EcxLoadRequest.objects.filter(created_by=self.agent).count(), 1)

    def test_agent_direct_load_endpoint_creates_request(self):
        self.client.login(username="agent", password="pass")
        factory = APIRequestFactory()
        data = {
            "symbol": "S1",
            "grade": "1",
            "trade_ids": [str(self.trade.id)],
            "plombs_count": 2,
            "has_trailer": "0",
            "trailer_count": 0,
        }
        req = factory.post(f"/api/warehouses/{self.wh.id}/load/", data, format='multipart')
        req.user = self.agent
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=self.wh.id)
        self.assertEqual(response.status_code, 200)
        self.trade.refresh_from_db()
        self.assertFalse(self.trade.loaded)
        self.assertEqual(EcxLoadRequest.objects.filter(created_by=self.agent).count(), 1)

    def test_manager_can_approve_request_from_list(self):
        """Operations manager can approve an agent's load request via list page link."""
        # Agent submits a load request
        self.client.login(username="agent", password="pass")
        resp = self.client.post(
            reverse("ecx_load_request_from_map"),
            {
                "warehouse_id": self.wh.id,
                "symbol": "S1",
                "grade": "1",
                "trade_ids": [self.trade.id],
                "plombs_count": 1,
                "has_trailer": "on",
                "trailer_count": 1,
            },
            secure=True,
        )
        self.assertEqual(resp.status_code, 200)
        req = EcxLoadRequest.objects.get(created_by=self.agent)

        # Manager reviews and approves using tokenized link
        self.client.login(username="manager", password="pass")
        list_resp = self.client.get(reverse("request_list"), secure=True)
        self.assertContains(list_resp, f"?t={req.approval_token}")
        review_url = reverse("ecxload_request_review", args=[req.id])
        post_resp = self.client.post(
            review_url,
            {"t": req.approval_token, "action": "approve", "note": ""},
            secure=True,
            follow=True,
        )
        self.assertEqual(post_resp.status_code, 200)
        req.refresh_from_db()
        self.trade.refresh_from_db()
        self.assertEqual(req.status, EcxLoadRequest.STATUS_APPROVED)
        self.assertTrue(self.trade.loaded)

    def test_api_approve_creates_shipment_and_is_idempotent(self):
        factory = APIRequestFactory()
        data = {
            "warehouse": str(self.wh.id),
            "symbol": "S1",
            "grade": "1",
            "trade_ids": [str(self.trade.id)],
        }
        req = factory.post("/api/load-requests/", data)
        req.user = self.agent
        resp = LoadRequestViewSet.as_view({"post": "create"})(req)
        self.assertEqual(resp.status_code, 201)
        lr_id = resp.data["id"]
        self.assertEqual(EcxShipment.objects.count(), 0)
        self.assertEqual(EcxMovement.objects.count(), 0)

        # Approve first time
        req2 = factory.post(f"/api/load-requests/{lr_id}/approve/", {})
        req2.user = self.manager
        resp2 = LoadRequestViewSet.as_view({"post": "approve"})(req2, pk=lr_id)
        self.assertEqual(resp2.status_code, 201)
        self.assertEqual(EcxShipment.objects.count(), 1)
        shipment = EcxShipment.objects.first()
        self.assertEqual(EcxMovement.objects.count(), 1)
        mv = EcxMovement.objects.first()
        self.assertEqual(mv.shipment_id, shipment.id)
        self.assertEqual(shipment.total_quantity, mv.quantity_quintals)
        self.assertEqual(mv.net_obligation_receipt_no, self.trade.net_obligation_receipt_no)
        self.assertEqual(mv.warehouse_receipt_no, self.trade.warehouse_receipt_no)


        # Approve again -> 409 and no duplicate shipment
        req3 = factory.post(f"/api/load-requests/{lr_id}/approve/", {})
        req3.user = self.manager
        resp3 = LoadRequestViewSet.as_view({"post": "approve"})(req3, pk=lr_id)
        self.assertEqual(resp3.status_code, 409)
        self.assertEqual(EcxShipment.objects.count(), 1)
        self.assertEqual(EcxShipment.objects.filter(movements__weighed=False).count(), 1)
