import os
import datetime
from decimal import Decimal

import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.db import models
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory

call_command("migrate", verbosity=0)

from WareDGT.models import (
    Warehouse,
    SeedType,
    Commodity,
    EcxTrade,
    PurchasedItemType,
    EcxMovement,
    EcxMovementReceiptFile,
    EcxTradeReceiptFile,
    EcxShipment,
)
from WareDGT.views import WarehouseViewSet


class LoadStockEndpointTests(TestCase):
    def test_partial_load_splits_trade(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

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

        t1 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=Decimal("10"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )
        t2 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N2",
            warehouse_receipt_no="WR2",
            quantity_quintals=Decimal("15"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/",
            {"symbol": "S1", "grade": "1", "quantity": "17"},
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        # A single movement should be recorded for this truck load
        mv = EcxMovement.objects.first()
        self.assertEqual(EcxMovement.objects.count(), 1)
        self.assertEqual(mv.net_obligation_receipt_no, "N1, N2")
        self.assertEqual(mv.warehouse_receipt_no, "WR1-v1, WR2-v1")
        self.assertEqual(mv.quantity_quintals, Decimal("17"))

        # Only one aggregate movement should be recorded
        self.assertEqual(EcxMovement.objects.count(), 1)

        trades = list(
            EcxTrade.objects.order_by("warehouse_receipt_no", "warehouse_receipt_version")
        )
        self.assertEqual(len(trades), 3)

        t1.refresh_from_db()
        t2.refresh_from_db()
        loaded = [t.loaded for t in trades]
        quantities = [t.quantity_quintals for t in trades]
        self.assertEqual(loaded.count(True), 2)
        self.assertIn(Decimal("7"), quantities)
        self.assertIn(Decimal("8"), quantities)
        self.assertIn(Decimal("10"), quantities)
        remaining_trade = wh.ecx_trades.get(loaded=False)
        self.assertEqual(remaining_trade.quantity_quintals, Decimal("8"))
        self.assertEqual(remaining_trade.warehouse_receipt_version, 2)
        remaining = (
            wh.ecx_trades.filter(loaded=False)
            .aggregate(total=models.Sum("quantity_quintals"))["total"]
        )
        self.assertEqual(remaining, Decimal("8"))

    def test_partial_load_with_selected_trade_and_quantity(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester_part", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="ECX", name="ECXW", warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"), latitude=0, longitude=0
        )
        seed = SeedType.objects.create(code="S2", name="Seed2")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")

        trade = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N3",
            warehouse_receipt_no="WR3",
            quantity_quintals=Decimal("100"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/",
            {"symbol": "S2", "grade": "1", "quantity": "5", "trade_ids": [str(trade.id)]},
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        mv = EcxMovement.objects.first()
        self.assertEqual(mv.quantity_quintals, Decimal("5"))
        self.assertEqual(mv.warehouse_receipt_no, "WR3-v1")

        trades = list(
            EcxTrade.objects.order_by("warehouse_receipt_no", "warehouse_receipt_version")
        )
        self.assertEqual(len(trades), 2)
        loaded = [t for t in trades if t.loaded]
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].quantity_quintals, Decimal("5"))
        remaining = [t for t in trades if not t.loaded][0]
        self.assertEqual(remaining.quantity_quintals, Decimal("95"))
        self.assertEqual(remaining.warehouse_receipt_version, 2)

    def test_quantity_exceeds_selected_stock_returns_error(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester_err", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="ECZ", name="ECXW2", warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"), latitude=0, longitude=0
        )
        seed = SeedType.objects.create(code="S3", name="Seed3")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")

        trade = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N4",
            warehouse_receipt_no="WR4",
            quantity_quintals=Decimal("20"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/",
            {"symbol": "S3", "grade": "1", "quantity": "25", "trade_ids": [str(trade.id)]},
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Quantity exceeds selected stock", response.data["error"])
        trade.refresh_from_db()
        self.assertFalse(trade.loaded)
        self.assertEqual(EcxMovement.objects.count(), 0)

    def test_preview_lists_trades_and_does_not_load(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester2", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="EC2",
            name="ECX2",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed = SeedType.objects.create(code="S1", name="Seed")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")

        today = datetime.date.today()
        t1 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=Decimal("4"),
            purchase_date=today - datetime.timedelta(days=15),
            recorded_by=user,
        )
        t2 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N2",
            warehouse_receipt_no="WR2",
            quantity_quintals=Decimal("6"),
            purchase_date=today - datetime.timedelta(days=5),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/?preview=1",
            {"symbol": "S1", "grade": "1", "quantity": "10"},
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        data = response.data
        self.assertEqual(
            [t["warehouse_receipt_no"] for t in data["trades"]],
            ["WR1-v1", "WR2-v1"],
        )
        self.assertIn("purchase_date", data["trades"][0])
        self.assertIn("net_obligation_receipt_no", data["trades"][0])
        self.assertIn("available_trades", data)
        self.assertEqual(len(data["available_trades"]), 2)

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertFalse(t1.loaded)
        self.assertFalse(t2.loaded)
        self.assertEqual(EcxMovement.objects.count(), 0)

    def test_preview_with_specific_trade_ids(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester3", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="EC3",
            name="ECX3",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed = SeedType.objects.create(code="S1", name="Seed")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")

        t1 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=Decimal("4"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )
        t2 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N2",
            warehouse_receipt_no="WR2",
            quantity_quintals=Decimal("6"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/?preview=1",
            {
                "symbol": "S1",
                "grade": "1",
                "quantity": "6",
                "trade_ids": [str(t2.id)],
            },
            format="multipart",
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        data = response.data
        self.assertEqual(
            [t["warehouse_receipt_no"] for t in data["trades"]],
            ["WR2-v1"],
        )
        self.assertIn("available_trades", data)
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertFalse(t1.loaded)
        self.assertFalse(t2.loaded)

    def test_preview_with_selected_trade_and_partial_quantity(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester_prev_part", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="EC4",
            name="ECX4",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed = SeedType.objects.create(code="S4", name="Seed4")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")

        trade = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N5",
            warehouse_receipt_no="WR5",
            quantity_quintals=Decimal("100"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/?preview=1",
            {
                "symbol": "S4",
                "grade": "1",
                "quantity": "5",
                "trade_ids": [str(trade.id)],
            },
            format="multipart",
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        data = response.data
        self.assertEqual(data["total_quantity"], "5")
        self.assertEqual(
            [t["warehouse_receipt_no"] for t in data["trades"]],
            ["WR5-v1"],
        )
        self.assertEqual(data["trades"][0]["quantity"], "5")
        self.assertEqual(len(data["available_trades"]), 1)
        self.assertEqual(
            data["available_trades"][0]["warehouse_receipt_no"],
            "WR5-v2",
        )
        self.assertEqual(data["available_trades"][0]["quantity"], "95.00")

        trade.refresh_from_db()
        self.assertFalse(trade.loaded)
        self.assertEqual(trade.quantity_quintals, Decimal("100"))
        self.assertEqual(EcxMovement.objects.count(), 0)

    def test_file_upload_creates_movement_receipt(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester_file", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="EC5",
            name="ECX5",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed = SeedType.objects.create(code="S5", name="Seed5")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="1")

        trade = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N6",
            warehouse_receipt_no="WR6",
            quantity_quintals=Decimal("10"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        file = SimpleUploadedFile("r.jpg", b"content", content_type="image/jpeg")

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/",
            {
                "symbol": "S5",
                "grade": "1",
                "quantity": "10",
                "trade_ids": [str(trade.id)],
                "file": file,
            },
            format="multipart",
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(EcxMovement.objects.count(), 1)
        self.assertEqual(EcxMovementReceiptFile.objects.count(), 1)
        self.assertEqual(EcxTradeReceiptFile.objects.count(), 0)

    def test_multi_grade_load_creates_separate_movements(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester_multi", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="EC7",
            name="ECX7",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed = SeedType.objects.create(code="S7", name="Seed7")
        commodity_a = Commodity.objects.create(seed_type=seed, origin="OR", grade="A")
        commodity_b = Commodity.objects.create(seed_type=seed, origin="OR", grade="B")

        t1 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity_a,
            net_obligation_receipt_no="NA",
            warehouse_receipt_no="WRA",
            quantity_quintals=Decimal("10"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )
        t2 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity_b,
            net_obligation_receipt_no="NB",
            warehouse_receipt_no="WRB",
            quantity_quintals=Decimal("5"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/",
            {"symbol": "S7", "quantity": "15", "trade_ids": [str(t1.id), str(t2.id)]},
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        # One shipment with two movements (one per grade)
        self.assertEqual(EcxShipment.objects.count(), 1)
        self.assertEqual(EcxMovement.objects.count(), 2)
        grades = set(EcxMovement.objects.values_list("item_type__grade", flat=True))
        self.assertEqual(grades, {"A", "B"})
        total_qty = EcxMovement.objects.aggregate(total=models.Sum("quantity_quintals"))["total"]
        self.assertEqual(total_qty, Decimal("15"))

    def test_multi_seed_load_creates_single_shipment(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester_multi_seed", password="pass")
        user.profile.role = "ECX_OFFICER"
        user.profile.save()

        wh = Warehouse.objects.create(
            code="EC8",
            name="ECX8",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed_a = SeedType.objects.create(code="SA", name="SeedA")
        seed_b = SeedType.objects.create(code="SB", name="SeedB")
        commodity_a = Commodity.objects.create(seed_type=seed_a, origin="OR", grade="A")
        commodity_b = Commodity.objects.create(seed_type=seed_b, origin="OR", grade="A")

        t1 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity_a,
            net_obligation_receipt_no="NA",
            warehouse_receipt_no="WRA",
            quantity_quintals=Decimal("5"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )
        t2 = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity_b,
            net_obligation_receipt_no="NB",
            warehouse_receipt_no="WRB",
            quantity_quintals=Decimal("7"),
            purchase_date=datetime.date.today(),
            recorded_by=user,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/",
            {"quantity": "12", "trade_ids": [str(t1.id), str(t2.id)]},
        )
        req.user = user
        response = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(EcxShipment.objects.count(), 1)
        shipment = EcxShipment.objects.first()
        self.assertEqual(shipment.symbol, None)
        self.assertEqual(EcxMovement.objects.count(), 2)
        symbols = set(EcxMovement.objects.values_list("item_type__seed_type", flat=True))
        self.assertEqual(symbols, {"SA", "SB"})
        total_qty = EcxMovement.objects.aggregate(total=models.Sum("quantity_quintals"))["total"]
        self.assertEqual(total_qty, Decimal("12"))

    def test_ecx_agent_sees_no_shipments(self):
        User = get_user_model()
        officer = User.objects.create_user(username="off", password="pass")
        officer.profile.role = "ECX_OFFICER"
        officer.profile.save()
        agent = User.objects.create_user(username="agent", password="pass")
        agent.profile.role = "ECX_AGENT"
        agent.profile.save()

        wh = Warehouse.objects.create(
            code="EC9",
            name="ECX9",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        seed = SeedType.objects.create(code="S9", name="Seed9")
        commodity = Commodity.objects.create(seed_type=seed, origin="OR", grade="A")
        EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N9",
            warehouse_receipt_no="WR9",
            quantity_quintals=Decimal("3"),
            purchase_date=datetime.date.today(),
            recorded_by=officer,
        )

        factory = APIRequestFactory()
        req = factory.post(
            f"/api/warehouses/{wh.id}/load/",
            {"symbol": "S9", "quantity": "3"},
        )
        req.user = officer
        resp = WarehouseViewSet.as_view({"post": "load_stock"})(req, pk=wh.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(EcxShipment.objects.count(), 1)

        self.client.force_login(agent)
        response = self.client.get("/stock-movements/", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No movements recorded.")

