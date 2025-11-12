from django.core.management.base import BaseCommand
from WareDGT.models import DashboardConfig


class Command(BaseCommand):
    help = "Seed default System Manager dashboard configs"

    def handle(self, *args, **options):
        defaults = {
            "WAREHOUSE_OFFICER": {
                "show_qc_pending": True,
                "show_shrinkage_card": True,
            },
            "ECX_OFFICER": {
                "show_trade_pipeline": True,
                "show_qc_pending": False,
            },
            "OPERATIONS_MANAGER": {
                "show_forecasts": True,
                "show_risks": True,
            },
        }
        for role, widgets in defaults.items():
            DashboardConfig.objects.update_or_create(
                role=role, defaults={"widgets": widgets}
            )
        self.stdout.write(self.style.SUCCESS("Dashboard config seeded."))
