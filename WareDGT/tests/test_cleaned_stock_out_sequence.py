import os
from decimal import Decimal

os.environ["DJANGO_SETTINGS_MODULE"] = "warehouse_project.settings_test"

import django
django.setup()
from django.core.management import call_command
from django.test import TestCase
import pytest

pytestmark = pytest.mark.django_db

from WareDGT.models import (
    Warehouse,
    SeedTypeDetail,
    Company,
    BinCardEntry,
    CleanedStockOut,
)
from WareDGT.forms import CleanedStockOutForm


class CleanedStockOutSequenceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("migrate", verbosity=0)

    def setUp(self):
        self.wh = Warehouse.objects.create(
            code="W1",
            name="Warehouse 1",
            warehouse_type=Warehouse.DGT,
            capacity_quintals=Decimal("100"),
            latitude=0,
            longitude=0,
        )
        self.seed = SeedTypeDetail.objects.create(
            symbol="ST",
            name="Seed",
            delivery_location=self.wh,
            grade="1",
            origin="ETH",
        )
        self.owner_a = Company.objects.create(name="Owner A")
        self.owner_b = Company.objects.create(name="Owner B")
        BinCardEntry.objects.create(
            seed_type=self.seed,
            owner=self.owner_a,
            warehouse=self.wh,
            grade="1",
            weight=Decimal("1"),
            cleaned_total_kg=Decimal("5"),
        )

    def test_sequence_separate_per_owner(self):
        out_a = CleanedStockOut.objects.create(
            seed_type=self.seed,
            owner=self.owner_a,
            warehouse=self.wh,
            weight=Decimal("1"),
        )
        self.assertEqual(out_a.in_out_no, "2")

        out_b = CleanedStockOut.objects.create(
            seed_type=self.seed,
            owner=self.owner_b,
            warehouse=self.wh,
            weight=Decimal("1"),
        )
        self.assertEqual(out_b.in_out_no, "1")

    def test_form_save_creates_bincard_entry(self):
        form = CleanedStockOutForm(
            data={
                "owner": self.owner_a.pk,
                "seed_type": self.seed.pk,
                "warehouse": self.wh.pk,
                "weight": "2",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        cleaned_out = form.save()
        entry = BinCardEntry.objects.latest("id")
        self.assertEqual(entry.owner, self.owner_a)
        self.assertEqual(entry.warehouse, self.wh)
        self.assertEqual(entry.weight, Decimal("-2"))
        self.assertEqual(entry.cleaned_total_kg, Decimal("-2"))
        self.assertEqual(entry.in_out_no, cleaned_out.in_out_no)
        self.assertEqual(entry.in_out_no, "2")
