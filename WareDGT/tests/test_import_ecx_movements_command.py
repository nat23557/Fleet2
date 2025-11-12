import os
import datetime
from decimal import Decimal

import django
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models import DateField, ExpressionWrapper, F
from django.test import TestCase
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.models import (
    Warehouse,
    SeedType,
    Commodity,
    EcxTrade,
    EcxMovement,
    EcxMovementReceiptFile,
)


class ImportEcxMovementsCommandTests(TestCase):
    def test_command_marks_trades_loaded_and_updates_overdue(self):
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

        trade = EcxTrade.objects.create(
            warehouse=wh,
            commodity=commodity,
            net_obligation_receipt_no="N1",
            warehouse_receipt_no="WR1",
            quantity_quintals=Decimal("10"),
            purchase_date=datetime.date.today() - datetime.timedelta(days=15),
            recorded_by=user,
        )

        today = timezone.localdate()
        overdue_before = (
            EcxTrade.objects.filter(loaded=False)
            .annotate(
                last_pickup=ExpressionWrapper(
                    F("purchase_date") + datetime.timedelta(days=5),
                    output_field=DateField(),
                )
            )
            .filter(last_pickup__lt=today)
            .count()
        )
        self.assertEqual(overdue_before, 1)

        image_path = os.path.join(settings.BASE_DIR, "Image.png")
        call_command("import_ecx_movements", "--user", user.username, "--image", image_path)

        trade.refresh_from_db()
        self.assertTrue(trade.loaded)
        self.assertIsNotNone(trade.loaded_at)
        self.assertEqual(EcxMovement.objects.count(), 1)
        mv = EcxMovement.objects.get()
        self.assertEqual(mv.net_obligation_receipt_no, "N1")
        self.assertEqual(EcxMovementReceiptFile.objects.count(), 1)

        overdue_after = (
            EcxTrade.objects.filter(loaded=False)
            .annotate(
                last_pickup=ExpressionWrapper(
                    F("purchase_date") + datetime.timedelta(days=5),
                    output_field=DateField(),
                )
            )
            .filter(last_pickup__lt=today)
            .count()
        )
        self.assertEqual(overdue_after, 0)
