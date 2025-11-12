import os
from decimal import Decimal
from uuid import uuid4

import django
os.environ["DJANGO_SETTINGS_MODULE"] = "warehouse_project.settings_test"
django.setup()
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory
import pytest

pytestmark = pytest.mark.django_db

from WareDGT.models import (
    Warehouse,
    SeedTypeDetail,
    SeedTypeBalance,
    Company,
    BinCardEntry,
    BinCardTransaction,
    StockOutRequest,
)
from WareDGT.views import (
    stock_seed_types_available,
    stock_owners_available,
    stock_classes_available,
    stock_specs_available,
    validate_stock_out,
    register_stock_out,
    bin_cards,
)


class StockOutApiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("migrate", verbosity=0)

    def setUp(self):
        User = get_user_model()
        self.manager_user = User.objects.create_user(username="manager", password="pass")
        self.manager_user.profile.role = "OPERATIONS_MANAGER"
        self.manager_user.profile.save()
        self.officer_user = User.objects.create_user(username="officer", password="pass")
        self.officer_user.profile.role = "WAREHOUSE_OFFICER"
        self.officer_user.profile.save()
        self.user = self.manager_user

        # Ensure every test starts with a clean email outbox
        mail.outbox = []

        self.wh = Warehouse.objects.create(
            code="WH1",
            name="Warehouse 1",
            warehouse_type=Warehouse.DGT,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        self.seed = SeedTypeDetail.objects.create(
            symbol="WWSS",
            name="Whitish Wollega Sesame",
            delivery_location=self.wh,
            grade="5",
            origin="ET",
            handling_procedure="",
        )
        self.company = Company.objects.create(name="DGT")
        self.lot = BinCardEntry.objects.create(
            seed_type=self.seed,
            owner=self.company,
            warehouse=self.wh,
            grade="5",
            raw_balance_kg=Decimal("5"),
            rejects_total_kg=Decimal("5"),
            in_out_no="1",
        )
        # Available: 20 qtl cleaned, 5 qtl reject grade 5
        SeedTypeBalance.objects.create(
            warehouse=self.wh,
            owner=self.company,
            seed_type=self.seed,
            purity=Decimal("0"),
            cleaned_kg=Decimal("20"),
            rejects_kg=Decimal("0"),
        )
        SeedTypeBalance.objects.create(
            warehouse=self.wh,
            owner=self.company,
            seed_type=self.seed,
            purity=None,
            cleaned_kg=Decimal("0"),
            rejects_kg=Decimal("5"),
        )
        # Another seed type with zero availability
        self.seed2 = SeedTypeDetail.objects.create(
            symbol="NONE",
            name="No Stock",
            delivery_location=self.wh,
            grade="4",
            origin="ET",
            handling_procedure="",
        )
        SeedTypeBalance.objects.create(
            warehouse=self.wh,
            owner=self.company,
            seed_type=self.seed2,
            purity=None,
            cleaned_kg=Decimal("0"),
            rejects_kg=Decimal("0"),
        )
        self.factory = APIRequestFactory()

    def _new_weighbridge(self, label="wb", content=b"WB"):
        return SimpleUploadedFile(
            f"{label}-{uuid4().hex}.pdf",
            content,
            content_type="application/pdf",
        )

    def _submit_stock_out(self, payload, *, user=None, multipart=False):
        req = self.factory.post(
            "/api/stock/out",
            payload,
            format="multipart" if multipart else "json",
        )
        req.user = user or self.officer_user
        return register_stock_out(req)

    def _approve_request(self, req_obj, *, actor=None):
        self.client.force_login(actor or self.manager_user)
        url = reverse("approve_stockout_request", args=[req_obj.pk]) + f"?t={req_obj.approval_token}"
        return self.client.get(url)

    def test_seed_types_available_only_positive(self):
        req = self.factory.get(
            "/api/stock/seed-types/available",
            {"warehouse": str(self.wh.id)},
        )
        req.user = self.user
        resp = stock_seed_types_available(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["seed_type"], "WWSS")

    def test_owners_available_only_positive(self):
        req = self.factory.get("/api/stock/owners/available")
        req.user = self.user
        resp = stock_owners_available(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["name"], "DGT")

    def test_owners_available_excludes_raw_only(self):
        raw_owner = Company.objects.create(name="RawOnly")
        BinCardEntry.objects.create(
            seed_type=self.seed,
            owner=raw_owner,
            warehouse=self.wh,
            grade="5",
            raw_balance_kg=Decimal("1"),
            rejects_total_kg=Decimal("0"),
            cleaned_total_kg=Decimal("0"),
            in_out_no="99",
        )
        req = self.factory.get("/api/stock/owners/available")
        req.user = self.user
        resp = stock_owners_available(req)
        self.assertEqual(resp.status_code, 200)
        names = [o["name"] for o in resp.data]
        self.assertNotIn("RawOnly", names)


    def test_seed_types_filtered_by_owner(self):
        other = Company.objects.create(name="Other")
        BinCardEntry.objects.create(
            seed_type=self.seed,
            owner=other,
            warehouse=self.wh,
            grade="5",
            raw_balance_kg=Decimal("1"),
            rejects_total_kg=Decimal("1"),
            in_out_no="2",
        )
        req = self.factory.get(
            "/api/stock/seed-types/available",
            {"owner": str(self.company.id), "warehouse": str(self.wh.id)},
        )
        req.user = self.user
        resp = stock_seed_types_available(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["seed_type"], "WWSS")

    def test_class_availability(self):
        req = self.factory.get(
            "/api/stock/classes/available",
            {"seed_type": "WWSS", "warehouse": str(self.wh.id)},
        )
        req.user = self.user
        resp = stock_classes_available(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["cleaned"], "20.00")
        self.assertEqual(resp.data["reject"], "5.00")

    def test_spec_grade_list(self):
        req = self.factory.get(
            "/api/stock/specs/available",
            {"seed_type": "WWSS", "class": "reject", "warehouse": str(self.wh.id)},
        )
        req.user = self.user
        resp = stock_specs_available(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["available_total"], "5.00")
        self.assertNotIn("grades", resp.data)

    def test_specs_available_is_per_warehouse(self):
        wh2 = Warehouse.objects.create(
            code="WH2",
            name="Warehouse 2",
            warehouse_type=Warehouse.DGT,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        SeedTypeBalance.objects.create(
            warehouse=wh2,
            owner=self.company,
            seed_type=self.seed,
            purity=None,
            cleaned_kg=Decimal("0"),
            rejects_kg=Decimal("10"),
        )
        req = self.factory.get(
            "/api/stock/specs/available",
            {"seed_type": "WWSS", "class": "reject", "warehouse": str(self.wh.id)},
        )
        req.user = self.user
        resp = stock_specs_available(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["available_total"], "5.00")

    def test_specs_available_requires_warehouse(self):
        req = self.factory.get(
            "/api/stock/specs/available",
            {"seed_type": "WWSS", "class": "reject"},
        )
        req.user = self.user
        resp = stock_specs_available(req)
        self.assertEqual(resp.status_code, 400)

    def test_specs_available_rejects_non_dgt(self):
        wh = Warehouse.objects.create(
            code="ECX1",
            name="ECX Warehouse",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        req = self.factory.get(
            "/api/stock/specs/available",
            {"seed_type": "WWSS", "class": "reject", "warehouse": str(wh.id)},
        )
        req.user = self.user
        resp = stock_specs_available(req)
        self.assertEqual(resp.status_code, 400)

    def test_validation_endpoint(self):
        # Exceeds
        req = self.factory.post(
            "/api/stock/validate-out",
            {
                "seed_type": "WWSS",
                "class": "reject",
                "quantity": "6",
                "owner": str(self.company.id),
                "warehouse": str(self.wh.id),
            },
            format="json",
        )
        req.user = self.user
        resp = validate_stock_out(req)
        self.assertEqual(resp.status_code, 409)
        # Within
        req2 = self.factory.post(
            "/api/stock/validate-out",
            {
                "seed_type": "WWSS",
                "class": "reject",
                "quantity": "4",
                "owner": str(self.company.id),
                "warehouse": str(self.wh.id),
            },
            format="json",
        )
        req2.user = self.user
        resp2 = validate_stock_out(req2)
        self.assertEqual(resp2.status_code, 200)

    def test_validation_falls_back_to_bincard(self):
        BinCardEntry.objects.create(
            seed_type=self.seed2,
            owner=self.company,
            warehouse=self.wh,
            grade="4",
            raw_balance_kg=Decimal("3"),
            rejects_total_kg=Decimal("3"),
        )
        req = self.factory.post(
            "/api/stock/validate-out",
            {
                "seed_type": "NONE",
                "class": "reject",
                "quantity": "2",
                "owner": str(self.company.id),
                "warehouse": str(self.wh.id),
            },
            format="json",
        )
        req.user = self.user
        resp = validate_stock_out(req)
        self.assertEqual(resp.status_code, 200)

    def test_validate_stock_out_requires_warehouse(self):
        req = self.factory.post(
            "/api/stock/validate-out",
            {
                "seed_type": "WWSS",
                "class": "cleaned",
                "quantity": "1",
                "owner": str(self.company.id),
            },
            format="json",
        )
        req.user = self.user
        resp = validate_stock_out(req)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("warehouse", resp.data["details"])

    def test_validate_stock_out_rejects_non_dgt(self):
        wh = Warehouse.objects.create(
            code="ECX1",
            name="ECX Warehouse",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        req = self.factory.post(
            "/api/stock/validate-out",
            {
                "seed_type": "WWSS",
                "class": "cleaned",
                "quantity": "1",
                "owner": str(self.company.id),
                "warehouse": str(wh.id),
            },
            format="json",
        )
        req.user = self.user
        resp = validate_stock_out(req)
        self.assertEqual(resp.status_code, 400)

    def test_register_stock_out_updates_balance(self):
        payload = {
            "seed_type": "WWSS",
            "class": "reject",
            "quantity": "4",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("pending"))
        self.assertIn("Draft", resp.data.get("message", ""))
        req_obj = StockOutRequest.objects.get()
        approve_resp = self._approve_request(req_obj)
        self.assertEqual(approve_resp.status_code, 302)
        req_obj.refresh_from_db()
        self.assertEqual(req_obj.status, StockOutRequest.APPROVED)
        self.assertEqual(BinCardEntry.objects.count(), 2)

    def test_officer_creates_pending_request(self):
        payload = {
            "seed_type": "WWSS",
            "class": "reject",
            "quantity": "1",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(StockOutRequest.objects.count(), 1)
        self.assertTrue(resp.data.get("pending"))
        self.assertIn("Draft", resp.data.get("message", ""))
        # No immediate stock deduction
        self.assertEqual(BinCardEntry.objects.count(), 1)

    def test_officer_request_notifies_managers_via_email(self):
        self.manager_user.email = "manager@example.com"
        self.manager_user.save(update_fields=["email"])
        payload = {
            "seed_type": "WWSS",
            "stock_class": "cleaned",
            "quantity": "2",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("pending"))
        self.assertIn("Draft", resp.data.get("message", ""))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, "Action required: Stock Out Approval")
        self.assertIn("manager@example.com", message.to)

    def test_manager_decision_emails_officer(self):
        self.officer_user.email = "officer@example.com"
        self.officer_user.save(update_fields=["email"])
        payload = {
            "seed_type": "WWSS",
            "stock_class": "cleaned",
            "quantity": "2",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        pending = StockOutRequest.objects.get()
        mail.outbox.clear()

        resp = self._approve_request(pending)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("Approved", message.subject)
        self.assertEqual(message.to, ["officer@example.com"])

    def test_manager_decline_email_includes_reason(self):
        self.officer_user.email = "officer@example.com"
        self.officer_user.save(update_fields=["email"])
        payload = {
            "seed_type": "WWSS",
            "stock_class": "cleaned",
            "quantity": "2",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        pending = StockOutRequest.objects.get()
        mail.outbox.clear()

        self.client.force_login(self.manager_user)
        decline_url = reverse("decline_stockout_request", args=[pending.pk]) + f"?t={pending.approval_token}"
        resp = self.client.post(decline_url, {"reason": "Incomplete paperwork"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("Declined", message.subject)
        self.assertIn("Incomplete paperwork", message.body)

    def test_register_stock_out_sequence_across_duplicate_seed_types(self):
        """Sequence should continue when API chooses a different SeedTypeDetail with the same symbol."""
        wh2 = Warehouse.objects.create(
            code="WH2",
            name="Warehouse 2",
            warehouse_type=Warehouse.DGT,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        st_unused = SeedTypeDetail.objects.create(
            symbol="DUPSYM",
            name="Dup Unused",
            delivery_location=wh2,
            grade="5",
            origin="ET",
            handling_procedure="",
        )
        st_used = SeedTypeDetail.objects.create(
            symbol="DUPSYM",
            name="Dup Used",
            delivery_location=self.wh,
            grade="5",
            origin="ET",
            handling_procedure="",
        )
        BinCardEntry.objects.create(
            seed_type=st_used,
            owner=self.company,
            warehouse=self.wh,
            grade="5",
            raw_balance_kg=Decimal("5"),
            rejects_total_kg=Decimal("5"),
            in_out_no="1",
        )
        SeedTypeBalance.objects.create(
            warehouse=self.wh,
            owner=self.company,
            seed_type=st_used,
            purity=None,
            cleaned_kg=Decimal("0"),
            rejects_kg=Decimal("5"),
        )
        payload = {
            "seed_type": "DUPSYM",
            "class": "reject",
            "quantity": "1",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        req_obj = StockOutRequest.objects.latest("id")
        self._approve_request(req_obj)
        entry = BinCardEntry.objects.latest("id")
        self.assertEqual(entry.in_out_no, "2")
        # Remaining availability should be 4 qtl
        req2 = self.factory.get(
            "/api/stock/classes/available",
            {"seed_type": "DUPSYM", "warehouse": str(self.wh.id)},
        )
        req2.user = self.manager_user
        resp2 = stock_classes_available(req2)
        self.assertEqual(resp2.data["reject"], "4.00")
        # Original lot remains unchanged
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.rejects_total_kg, Decimal("5"))
        # Second attempt on different symbol still succeeds
        payload2 = {
            "seed_type": "WWSS",
            "class": "reject",
            "quantity": "2",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp3 = self._submit_stock_out(payload2, user=self.officer_user, multipart=True)
        self.assertEqual(resp3.status_code, 200)

    def test_register_stock_out_returns_field_errors(self):
        req = self.factory.post(
            "/api/stock/out",
            {"seed_type": "WWSS"},  # missing required fields
        )
        req.user = self.user
        resp = register_stock_out(req)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("quantity", resp.data["details"])
        self.assertIn("warehouse", resp.data["details"])

    def test_register_stock_out_accepts_stock_class_key(self):
        payload = {
            "seed_type": "WWSS",
            "stock_class": "reject",
            "quantity": "4",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)

    def test_register_stock_out_sets_auto_description(self):
        BinCardEntry.objects.create(
            seed_type=self.seed,
            owner=self.company,
            warehouse=self.wh,
            cleaned_total_kg=Decimal("5"),
            in_out_no="2",
        )
        payload_cleaned = {
            "seed_type": "WWSS",
            "class": "cleaned",
            "quantity": "1",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload_cleaned, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        req_obj = StockOutRequest.objects.latest("id")
        self._approve_request(req_obj)
        entry = BinCardEntry.objects.latest("id")
        self.assertEqual(entry.description, "Cleaned product stock out")

        payload_reject = {
            "seed_type": "WWSS",
            "class": "reject",
            "quantity": "1",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp2 = self._submit_stock_out(payload_reject, user=self.officer_user, multipart=True)
        self.assertEqual(resp2.status_code, 200)
        req_obj2 = StockOutRequest.objects.latest("id")
        self._approve_request(req_obj2)
        entry2 = BinCardEntry.objects.latest("id")
        self.assertEqual(entry2.description, "Reject product stock out")

    def test_register_stock_out_rejects_non_dgt(self):
        wh = Warehouse.objects.create(
            code="ECX1",
            name="ECX Warehouse",
            warehouse_type=Warehouse.ECX,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        req = self.factory.post(
            "/api/stock/out",
            {
                "seed_type": "WWSS",
                "class": "cleaned",
                "quantity": "1",
                "owner": str(self.company.id),
                "warehouse": str(wh.id),
            },
            format="json",
        )
        req.user = self.user
        resp = register_stock_out(req)
        self.assertEqual(resp.status_code, 400)

    def test_register_stock_out_handles_duplicate_seed_types(self):
        """Submitting stock out when multiple SeedTypeDetail records share the same symbol should succeed."""
        wh2 = Warehouse.objects.create(
            code="WH2",
            name="Warehouse 2",
            warehouse_type=Warehouse.DGT,
            capacity_quintals=Decimal("1000"),
            latitude=0,
            longitude=0,
        )
        SeedTypeDetail.objects.create(
            symbol="WWSS",
            name="Duplicate",
            delivery_location=wh2,
            grade="5",
            origin="ET",
            handling_procedure="",
        )
        payload = {
            "seed_type": "WWSS",
            "class": "reject",
            "quantity": "1",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)

    def test_register_stock_out_falls_back_to_bincard(self):
        lot2 = BinCardEntry.objects.create(
            seed_type=self.seed2,
            owner=self.company,
            warehouse=self.wh,
            grade="4",
            raw_balance_kg=Decimal("3"),
            rejects_total_kg=Decimal("3"),
        )
        payload = {
            "seed_type": "NONE",
            "class": "reject",
            "quantity": "2",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        req_obj = StockOutRequest.objects.latest("id")
        self._approve_request(req_obj)
        lot2.refresh_from_db()
        self.assertEqual(lot2.rejects_total_kg, Decimal("1"))

    def test_stock_out_updates_sequence_balance_and_totals(self):
        self.lot.weight = Decimal("10")
        self.lot.cleaned_total_kg = Decimal("5")
        self.lot.balance = Decimal("10")
        self.lot.save(update_fields=["weight", "cleaned_total_kg", "balance"])
        payload = {
            "seed_type": "WWSS",
            "class": "cleaned",
            "quantity": "2",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        req_obj = StockOutRequest.objects.latest("id")
        self._approve_request(req_obj)
        entry = BinCardEntry.objects.latest("id")
        self.assertEqual(entry.in_out_no, "2")
        self.assertEqual(entry.balance, Decimal("8"))
        self.assertEqual(entry.cleaned_total_kg, Decimal("-2"))
        view_req = self.factory.get("/bincard")
        view_req.user = self.manager_user
        resp_view = bin_cards(view_req)
        so_row = [e for e in resp_view.context_data["entries"] if e.id == entry.id][0]
        self.assertEqual(so_row.cleaned_seed_total_qtl, Decimal("1.00"))

    def test_stock_out_sequence_separate_per_owner(self):
        """in_out_no should increment separately for each owner."""
        other = Company.objects.create(name="Other Co")
        # Create an entry for a different owner with a higher sequence number
        BinCardEntry.objects.create(
            seed_type=self.seed,
            owner=other,
            warehouse=self.wh,
            grade="5",
            cleaned_total_kg=Decimal("1"),
            in_out_no="2",
        )

        payload = {
            "seed_type": "WWSS",
            "class": "cleaned",
            "quantity": "1",
            "owner": str(self.company.id),
            "warehouse": str(self.wh.id),
            "weighbridge_certificate": self._new_weighbridge(),
        }
        resp = self._submit_stock_out(payload, user=self.officer_user, multipart=True)
        self.assertEqual(resp.status_code, 200)
        req_obj = StockOutRequest.objects.latest("id")
        self._approve_request(req_obj)
        entry = BinCardEntry.objects.latest("id")
        # Sequence for original owner continues from its own last number (1)
        self.assertEqual(entry.in_out_no, "2")

    def test_decline_stockout_requires_reason(self):
        req_obj = StockOutRequest.objects.create(
            created_by=self.officer_user,
            approval_token="tok123",
            payload={
                "seed_type": str(self.seed.id),
                "stock_class": "cleaned",
                "quantity": "1",
                "owner": str(self.company.id),
                "warehouse": str(self.wh.id),
            },
            warehouse=self.wh,
            owner=self.company,
        )
        self.client.force_login(self.manager_user)
        url = reverse("decline_stockout_request", args=[req_obj.pk]) + f"?t={req_obj.approval_token}"
        # Missing reason should render the form again and keep the request pending
        resp = self.client.post(url, {"reason": ""})
        self.assertEqual(resp.status_code, 200)
        req_obj.refresh_from_db()
        self.assertEqual(req_obj.status, StockOutRequest.PENDING)
        # Providing a reason processes the decline
        resp = self.client.post(url, {"reason": "Incomplete paperwork"})
        self.assertEqual(resp.status_code, 302)
        req_obj.refresh_from_db()
        self.assertEqual(req_obj.status, StockOutRequest.DECLINED)
        self.assertEqual(req_obj.reason, "Incomplete paperwork")

    def test_pending_stockout_reserves_quantity_until_decision(self):
        first_file = SimpleUploadedFile("wb1.pdf", b"WB1", content_type="application/pdf")
        req = self.factory.post(
            "/api/stock/out",
            {
                "seed_type": "WWSS",
                "stock_class": "cleaned",
                "quantity": "12",
                "owner": str(self.company.id),
                "warehouse": str(self.wh.id),
                "weighbridge_certificate": first_file,
            },
            format="multipart",
        )
        req.user = self.officer_user
        resp = register_stock_out(req)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data.get("pending"))

        second_file = SimpleUploadedFile("wb2.pdf", b"WB2", content_type="application/pdf")
        req2 = self.factory.post(
            "/api/stock/out",
            {
                "seed_type": "WWSS",
                "stock_class": "cleaned",
                "quantity": "10",
                "owner": str(self.company.id),
                "warehouse": str(self.wh.id),
                "weighbridge_certificate": second_file,
            },
            format="multipart",
        )
        req2.user = self.officer_user
        resp2 = register_stock_out(req2)
        self.assertEqual(resp2.status_code, 409)
        self.assertIn("exceeds available", resp2.data["error"])

        pending = StockOutRequest.objects.get(status=StockOutRequest.PENDING)
        pending.status = StockOutRequest.DECLINED
        pending.save(update_fields=["status"])

        third_file = SimpleUploadedFile("wb3.pdf", b"WB3", content_type="application/pdf")
        req3 = self.factory.post(
            "/api/stock/out",
            {
                "seed_type": "WWSS",
                "stock_class": "cleaned",
                "quantity": "10",
                "owner": str(self.company.id),
                "warehouse": str(self.wh.id),
                "weighbridge_certificate": third_file,
            },
            format="multipart",
        )
        req3.user = self.officer_user
        resp3 = register_stock_out(req3)
        self.assertEqual(resp3.status_code, 200)
        self.assertTrue(resp3.data.get("pending"))

