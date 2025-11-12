from decimal import Decimal
import datetime
import os

import django
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.models import (
    Warehouse,
    SeedType,
    Commodity,
    EcxTrade,
    EcxLoad,
)


class EcxLoadTests(TestCase):
    def test_create_load_marks_trades_loaded(self):
        User = get_user_model()
        user = User.objects.create_user(username="tester", password="pass")

        Warehouse.objects.all().delete()

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

        dummy = SimpleUploadedFile("f.txt", b"content")
        load = EcxLoad.objects.create(
            tracking_no="T1",
            voucher_no="V1",
            voucher_weight=Decimal("25"),
            commodity_type=seed,
            gross_weight=Decimal("25"),
            net_weight=Decimal("24"),
            truck_plate_no="AA-1",
            trailer_plate_no="AA-2",
            no_of_plomps=2,
            trailer_no_of_plomps=2,
            scale_ticket_no="ST1",
            driver_name="Driver",
            driver_license_no="DL1",
            driver_license_image=dummy,
            no_of_bags=50,
            production_year=2024,
            warehouse=wh,
            region="reg",
            zone="zone",
            woreda="woreda",
            specific_area="area",
            date_received=datetime.date.today(),
            supervisor_name="sup",
            supervisor_signed_date=datetime.date.today(),
            client_name="client",
            client_signed_date=datetime.date.today(),
            dispatch_document=dummy,
            weight_certificate=dummy,
        )
        load.trades.set([t1, t2])

        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertTrue(t1.loaded)
        self.assertTrue(t2.loaded)
        self.assertIsNotNone(t1.loaded_at)
        self.assertIsNotNone(t2.loaded_at)

