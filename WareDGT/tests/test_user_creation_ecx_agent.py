import os
import django
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.models import Warehouse, UserProfile


class UserCreationECXAgentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="pass")
        self.admin.profile.role = UserProfile.ADMIN
        self.admin.profile.save()
        self.client.login(username="admin", password="pass")
        self.wh = Warehouse.objects.create(
            code="EC1",
            name="ECX1",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("100"),
            latitude=0,
            longitude=0,
        )

    def test_agent_creation_requires_warehouse(self):
        resp = self.client.post(
            reverse("user_create"),
            {
                "username": "agent1",
                "role": UserProfile.ECX_AGENT,
            },
            secure=True,
        )
        self.assertFalse(get_user_model().objects.filter(username="agent1").exists())
        self.assertIn(
            "ECX agents must be assigned to at least one warehouse.",
            resp.context["form"].non_field_errors(),
        )

    def test_agent_assigned_to_warehouse_on_create(self):
        resp = self.client.post(
            reverse("user_create"),
            {
                "username": "agent2",
                "role": UserProfile.ECX_AGENT,
                "warehouses": [self.wh.id],
            },
            follow=True,
            secure=True,
        )
        self.assertEqual(resp.status_code, 200)
        user = get_user_model().objects.get(username="agent2")
        self.assertEqual(user.profile.role, UserProfile.ECX_AGENT)
        self.assertEqual(list(user.profile.warehouses.all()), [self.wh])

    def test_cannot_assign_taken_warehouse_twice(self):
        self.client.post(
            reverse("user_create"),
            {
                "username": "agent3",
                "role": UserProfile.ECX_AGENT,
                "warehouses": [self.wh.id],
            },
            secure=True,
        )
        resp = self.client.post(
            reverse("user_create"),
            {
                "username": "agent4",
                "role": UserProfile.ECX_AGENT,
                "warehouses": [self.wh.id],
            },
            secure=True,
        )
        self.assertFalse(get_user_model().objects.filter(username="agent4").exists())
        self.assertIn("Select a valid choice", resp.context["form"].errors["warehouses"][0])

