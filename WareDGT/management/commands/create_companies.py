from django.core.management.base import BaseCommand

from WareDGT.models import Company, EcxTrade, EcxMovement


class Command(BaseCommand):
    help = (
        "Ensure ThermoFam Trading PLC exists and set it as the owner of all "
        "ECX trades and movements. Optionally include legacy DGT/BestWay entries."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--owner",
            default="ThermoFam Trading PLC",
            help="Company name to set as owner for all ECX trades/movements.",
        )
        parser.add_argument(
            "--include-legacy",
            action="store_true",
            help="Also ensure legacy companies like DGT and BestWay exist (not set as owner).",
        )

    def handle(self, *args, **options):
        owner_name = options.get("owner") or "ThermoFam Trading PLC"
        include_legacy = bool(options.get("include_legacy"))

        owner, _ = Company.objects.get_or_create(name=owner_name)

        if include_legacy:
            Company.objects.get_or_create(name="DGT")
            Company.objects.get_or_create(name="BestWay")
            Company.objects.get_or_create(name="Other", defaults={"description": ""})

        EcxTrade.objects.update(owner=owner)
        EcxMovement.objects.update(owner=owner)

        self.stdout.write(
            self.style.SUCCESS(f"Companies ensured and ownership moved to {owner_name}")
        )
