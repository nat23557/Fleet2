import os
import re
from difflib import get_close_matches
from decimal import Decimal
from datetime import date, timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db.models import IntegerField
from django.db.models.functions import Cast

from WareDGT.models import BinCardEntry, EcxMovement, Company, SeedTypeDetail, Warehouse
from WareDGT.pdf_utils import get_or_build_bincard_pdf


class Command(BaseCommand):
    help = "Save all ECX movements into bin card entries with sequential dates and in_out_no"

    def handle(self, *args, **options):
        weight_path = os.path.join(settings.BASE_DIR, "Weight.png")
        warehouse_path = os.path.join(settings.BASE_DIR, "warehouse.png")
        quality_path = os.path.join(settings.BASE_DIR, "quality.jpg")

        if not all(os.path.exists(p) for p in [weight_path, warehouse_path, quality_path]):
            self.stderr.write(self.style.ERROR("Required document image missing"))
            return

        with open(weight_path, "rb") as f:
            weight_data = f.read()
        with open(warehouse_path, "rb") as f:
            warehouse_data = f.read()
        with open(quality_path, "rb") as f:
            quality_data = f.read()

        # Order movements so sequence is stable
        movements = list(EcxMovement.objects.all().order_by("id"))
        created = 0

        # We only have a single DGT warehouse at the moment
        dgt_wh = Warehouse.objects.filter(warehouse_type=Warehouse.DGT).first()
        if not dgt_wh:
            self.stderr.write(self.style.ERROR("No DGT warehouse found"))
            return

        # Start date from January 1, 2025
        current_date = date(2025, 1, 1)

        for mv in movements:
            # Avoid duplicates if already imported
            if BinCardEntry.objects.filter(ecx_movement=mv).exists():
                continue

            owner = mv.owner or Company.objects.filter(name="DGT").first()
            seed_code = mv.item_type.seed_type or ""

            match = re.match(r"([A-Za-z]+?)(UG|[0-9]+)?$", seed_code)
            base_symbol = match.group(1) if match else seed_code

            seed_detail = SeedTypeDetail.objects.filter(symbol=base_symbol).first()
            if seed_detail is None:
                seed_detail = SeedTypeDetail.objects.filter(category=base_symbol).first()
            if seed_detail is None:
                symbols = list(SeedTypeDetail.objects.values_list("symbol", flat=True))
                close = get_close_matches(base_symbol, symbols, n=1, cutoff=0.8)
                if close:
                    seed_detail = SeedTypeDetail.objects.filter(symbol=close[0]).first()
            if seed_detail is None:
                self.stderr.write(
                    self.style.ERROR(
                        f"No SeedTypeDetail found for '{seed_code}', skipping movement {mv.pk}"
                    )
                )
                continue
            receipts = list(mv.receipt_files.all())

            # Get last numeric in_out_no for this owner/seed_type and increment
            last = (
                BinCardEntry.objects.filter(
                    owner=owner,
                    seed_type=seed_detail,
                    in_out_no__regex=r"^\d+$",
                )
                .annotate(in_out_no_int=Cast("in_out_no", IntegerField()))
                .order_by("-in_out_no_int")
                .first()
            )
            next_no = last.in_out_no_int + 1 if last else 1

            entry = BinCardEntry(
                seed_type=seed_detail,
                owner=owner,
                in_out_no=str(next_no),
                description="input for Export Processing",
                weight=mv.quantity_quintals,
                source_type=BinCardEntry.ECX,
                warehouse=dgt_wh,
                ecx_movement=mv,
                num_bags=int(mv.quantity_quintals),
                car_plate_number="3-A22549 - FSR",
                purity=Decimal("97"),
                unloading_rate_etb_per_qtl=Decimal("7"),
            )
            entry._prefetched_receipts = receipts
            entry.weighbridge_certificate.save("Weight.png", ContentFile(weight_data), save=False)
            entry.warehouse_document.save("warehouse.png", ContentFile(warehouse_data), save=False)
            entry.quality_form.save("quality.jpg", ContentFile(quality_data), save=False)
            entry.save()

            # Assign sequential date
            entry.date = current_date
            BinCardEntry.objects.filter(pk=entry.pk).update(date=entry.date)

            # Move to next day for the next entry
            current_date += timedelta(days=1)

            # Generate PDF summary with attached documents
            if mv.created_by:
                get_or_build_bincard_pdf(entry, mv.created_by)

            created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} bin card entries"))
