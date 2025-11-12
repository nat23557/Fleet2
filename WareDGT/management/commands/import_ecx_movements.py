# manage.py command: register ECX movements and remove loaded stock from warehouse

import os
from datetime import timedelta
import logging

from django.apps import apps
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import DateField, ExpressionWrapper, F, Q
from django.utils import timezone

from WareDGT.models import (
    EcxTrade,
    EcxMovement,
    EcxMovementReceiptFile,
    PurchasedItemType,
    Company,
)

logger = logging.getLogger(__name__)

# These constants must point to the stock model that feeds the warehouse map
# in the ECX console. If your installation uses a different app/model name
# (e.g. "WarehouseStock", "EcxHolding", etc.), update them to match and
# rerun the command so loaded rows disappear from the map. You can also pass
# ``--stock-model app_label.ModelName`` at runtime to override these values.
STOCK_APP_LABEL = "WareDGT"
STOCK_MODEL_NAME = "EcxStock"  # set to the model used by the warehouse map


class Command(BaseCommand):
    help = (
        "Register EcxMovement records for all unloaded EcxTrade entries, "
        "attach a receipt image, mark trades as loaded, and remove the "
        "corresponding warehouse stock rows."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            help="Username to assign as created_by. Defaults to the first user.",
        )
        parser.add_argument(
            "--image",
            default="Image.png",
            help="Path to image file to attach to each movement.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Run without writing changes (log what would happen).",
        )
        parser.add_argument(
            "--stock-model",
            help=(
                "Override the stock model used for warehouse map removal; "
                "format as 'app_label.ModelName'."
            ),
        )

    def handle(self, *args, **options):
        username = options.get("user")
        image_path = options.get("image")
        dry_run = bool(options.get("dry_run"))
        stock_model_label = options.get("stock_model")

        if not os.path.exists(image_path):
            raise CommandError(f"Image file not found: {image_path}")

        # Resolve user
        User = get_user_model()
        if username:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"User '{username}' not found")
        else:
            user = User.objects.first()
            if not user:
                raise CommandError("No users exist to assign created_by")

        with open(image_path, "rb") as f:
            image_data = f.read()
        image_name = os.path.basename(image_path)

        # Try to resolve stock model dynamically
        StockModel = None
        try:
            if stock_model_label:
                StockModel = apps.get_model(stock_model_label)
            else:
                StockModel = apps.get_model(STOCK_APP_LABEL, STOCK_MODEL_NAME)
        except Exception:
            if stock_model_label:
                raise CommandError(f"Stock model '{stock_model_label}' not found")
            logger.warning(
                "Stock model %s.%s not found; will skip stock removal.",
                STOCK_APP_LABEL,
                STOCK_MODEL_NAME,
            )

        created_movements = 0
        removed_stock_rows = 0

        trades = EcxTrade.objects.filter(loaded=False).order_by("purchase_date")

        # Use a transaction per trade to keep things consistent
        for trade in trades:
            with transaction.atomic():
                wr_no_versioned = f"{trade.warehouse_receipt_no}-v{trade.warehouse_receipt_version}"

                # Skip if movement already exists
                exists = EcxMovement.objects.filter(
                    net_obligation_receipt_no=trade.net_obligation_receipt_no,
                    warehouse_receipt_no=wr_no_versioned,
                ).exists()
                if exists:
                    continue

                # Build or fetch PurchasedItemType
                item_type, _ = PurchasedItemType.objects.get_or_create(
                    seed_type=trade.commodity.seed_type.code,
                    origin=trade.commodity.origin,
                    grade=trade.commodity.grade,
                )

                # Create the movement
                if not dry_run:
                    movement = EcxMovement.objects.create(
                        warehouse=trade.warehouse,
                        item_type=item_type,
                        net_obligation_receipt_no=trade.net_obligation_receipt_no,
                        warehouse_receipt_no=wr_no_versioned,
                        quantity_quintals=trade.quantity_quintals,
                        purchase_date=trade.purchase_date,
                        created_by=user,
                        owner=trade.owner or Company.objects.filter(name="ThermoFam Trading PLC").first(),
                    )

                    EcxMovementReceiptFile.objects.create(
                        movement=movement,
                        image=ContentFile(image_data, name=image_name),
                    )

                # Mark trade as loaded
                if not dry_run:
                    trade.loaded = True
                    trade.loaded_at = timezone.now()
                    trade.save(update_fields=["loaded", "loaded_at"])

                created_movements += 1

                # -------- Remove matching warehouse stock rows --------
                if StockModel is not None:
                    removed = self._remove_stock_for_trade(StockModel, trade, wr_no_versioned, dry_run)
                    removed_stock_rows += removed

        # Overdue count stays the same logic
        today = timezone.localdate()
        overdue_count = (
            EcxTrade.objects.filter(loaded=False)
            .annotate(
                last_pickup=ExpressionWrapper(
                    F("purchase_date") + timedelta(days=5),
                    output_field=DateField(),
                )
            )
            .filter(last_pickup__lt=today)
            .count()
        )

        msg = (
            f"Created {created_movements} ECX movement(s). "
            f"Removed {removed_stock_rows} warehouse stock row(s). "
            f"Remaining overdue pickups: {overdue_count}."
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] " + msg))
        else:
            self.stdout.write(self.style.SUCCESS(msg))

    # ---- helpers ----

    def _remove_stock_for_trade(self, StockModel, trade, wr_no_versioned, dry_run=False):
        """
        Remove (or soft-remove) stock rows that correspond to the given trade.

        The warehouse map typically displays stock rows that are flagged as
        active (e.g. ``is_active=True`` or ``status='AVAILABLE'``). Update the
        filters and update/delete logic below so it targets the same fields your
        map uses; otherwise loaded stock may continue to appear in the ECX
        console. After adjusting, rerun this command.
        """
        field_names = {f.name for f in StockModel._meta.get_fields()}

        qs = StockModel.objects.all()

        # Match on as many of these as your model supports
        if "warehouse" in field_names:
            qs = qs.filter(warehouse=trade.warehouse)

        # Warehouse receipt (either split or combined)
        if "warehouse_receipt_no" in field_names:
            qs = qs.filter(warehouse_receipt_no=str(trade.warehouse_receipt_no))
        elif "wr_no" in field_names:
            qs = qs.filter(wr_no=str(trade.warehouse_receipt_no))
        elif "warehouse_receipt" in field_names:
            qs = qs.filter(warehouse_receipt=str(trade.warehouse_receipt_no))
        elif "wr_key" in field_names:
            qs = qs.filter(wr_key=wr_no_versioned)

        if "warehouse_receipt_version" in field_names:
            qs = qs.filter(warehouse_receipt_version=trade.warehouse_receipt_version)

        if "net_obligation_receipt_no" in field_names:
            qs = qs.filter(net_obligation_receipt_no=trade.net_obligation_receipt_no)

        if "commodity" in field_names:
            qs = qs.filter(commodity=trade.commodity)
        else:
            # Sometimes item type fields exist instead
            # e.g., seed_type/origin/grade combo
            if "seed_type" in field_names:
                qs = qs.filter(seed_type=trade.commodity.seed_type)
            if "origin" in field_names:
                qs = qs.filter(origin=trade.commodity.origin)
            if "grade" in field_names:
                qs = qs.filter(grade=trade.commodity.grade)

        if "owner" in field_names and trade.owner_id:
            qs = qs.filter(owner=trade.owner)

        # Nothing matched? Log and return
        count = qs.count()
        if count == 0:
            logger.info(
                "No warehouse stock rows matched for trade WR %s (versioned %s).",
                trade.warehouse_receipt_no, wr_no_versioned
            )
            return 0

        # Prefer soft-delete if supported
        soft_deleted = 0
        if "is_active" in field_names:
            if not dry_run:
                soft_deleted = qs.update(is_active=False)
            logger.info("Soft-deactivated %d stock row(s) via is_active=False", soft_deleted)
            return soft_deleted

        if "is_loaded" in field_names:
            if not dry_run:
                soft_deleted = qs.update(is_loaded=True, loaded_at=timezone.now())
            logger.info("Flagged %d stock row(s) as loaded", soft_deleted)
            return soft_deleted

        if "status" in field_names:
            # Try to mark as moved/loaded if a status field exists
            try:
                if not dry_run:
                    soft_deleted = qs.update(status="LOADED")
                logger.info("Updated status='LOADED' on %d stock row(s)", soft_deleted)
                return soft_deleted
            except Exception:
                pass  # fall through to hard delete

        # Hard delete fallback
        if not dry_run:
            deleted, _ = qs.delete()
        else:
            deleted = count
        logger.info("Deleted %d stock row(s) for WR %s", deleted, trade.warehouse_receipt_no)
        return deleted
