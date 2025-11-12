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
    Warehouse,
    PurchasedItemType,
    EcxMovement,
    Company,
    SeedTypeDetail,
    UserProfile,
)


class EcxMovementApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester_api", password="pass")
        self.user.profile.role = UserProfile.WAREHOUSE_OFFICER
        self.user.profile.save()
        self.client.login(username="tester_api", password="pass")
        self.owner = Company.objects.get(name="DGT")
        self.other = Company.objects.get(name="BestWay")
        self.wh = Warehouse.objects.create(
            code="W1",
            name="Warehouse 1",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("0"),
            latitude=0,
            longitude=0,
        )
        self.pit = PurchasedItemType.objects.create(
            seed_type=SeedTypeDetail.SESAME,
            origin="OR",
            grade="1",
            description="",
        )
        self.mv1 = EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=self.pit,
            net_obligation_receipt_no="n1",
            warehouse_receipt_no="w1",
            quantity_quintals=Decimal("1"),
            created_by=self.user,
            owner=self.owner,
        )
        self.mv2 = EcxMovement.objects.create(
            warehouse=self.wh,
            item_type=self.pit,
            net_obligation_receipt_no="n2",
            warehouse_receipt_no="w2",
            quantity_quintals=Decimal("1"),
            created_by=self.user,
            owner=self.other,
        )
        self.mv1.weighed = True
        self.mv1.save()
        self.mv2.weighed = True
        self.mv2.save()

    def test_filter_by_owner(self):
        url = reverse("ecxmovement-list")
        response = self.client.get(url, {"owner": self.owner.pk})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        ids = [mv["id"] for mv in data]
        self.assertIn(self.mv1.id, ids)
        self.assertNotIn(self.mv2.id, ids)
        self.assertIn("display", data[0])
