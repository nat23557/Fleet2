import django
import os
from django.core.management import call_command
from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "warehouse_project.settings_test")
django.setup()
call_command("migrate", verbosity=0)

from WareDGT.forms import EcxTradeForm
from WareDGT.models import Company


class EcxTradeFormTests(TestCase):
    def test_owner_defaults_to_dgt(self):
        dgt, _ = Company.objects.get_or_create(name="DGT", defaults={"description": ""})
        form = EcxTradeForm()
        self.assertEqual(form.fields["owner"].initial, dgt.pk)

    def test_bound_form_populates_owner(self):
        dgt, _ = Company.objects.get_or_create(name="DGT", defaults={"description": ""})
        form = EcxTradeForm(data={})
        self.assertEqual(form.data["owner"], str(dgt.pk))
