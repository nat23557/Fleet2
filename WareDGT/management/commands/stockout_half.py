from decimal import Decimal
from typing import Iterable, Optional

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from WareDGT.models import SeedTypeBalance, Warehouse, Company
from WareDGT.views import _process_stock_out, _available_qty_qtl


User = get_user_model()


class Command(BaseCommand):
    help = (
        "Load half of the cleaned and reject stocks for every seed type "
        "in the specified DGT warehouse(s) to exercise the stock-out workflow."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--warehouse",
            "-w",
            action="append",
            dest="warehouses",
            default=None,
            help=(
                "Warehouse code or UUID (can be repeated). "
                "If omitted, processes all DGT warehouses."
            ),
        )
        parser.add_argument(
            "--owner",
            "-o",
            dest="owner",
            default=None,
            help=(
                "Limit to a specific owner (UUID or exact company name). "
                "Defaults to all owners."
            ),
        )
        parser.add_argument(
            "--user",
            "-u",
            dest="username",
            default=None,
            help=(
                "Username to attribute created entries to. If omitted, uses "
                "the first superuser or any active staff user."
            ),
        )
        parser.add_argument(
            "--class",
            dest="stock_class",
            choices=["cleaned", "reject", "both"],
            default="both",
            help="Which stock class to process (default: both)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Only print planned actions without creating records",
        )
        parser.add_argument(
            "--list-warehouses",
            action="store_true",
            dest="list_warehouses",
            help="List available DGT warehouse codes and exit",
        )
        parser.add_argument(
            "--min-qtl",
            dest="min_qtl",
            type=float,
            default=0.01,
            help="Skip rows where half is below this threshold (default: 0.01)",
        )

    def _resolve_user(self, username: Optional[str]) -> User:
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist as e:
                raise CommandError(f"User '{username}' not found") from e
        user = User.objects.filter(is_superuser=True, is_active=True).first()
        if user:
            return user
        user = User.objects.filter(is_staff=True, is_active=True).first()
        if user:
            return user
        user = User.objects.filter(is_active=True).first()
        if not user:
            raise CommandError("No active user found to attribute stock outs to.")
        return user

    def _resolve_warehouses(self, options) -> Iterable[Warehouse]:
        import uuid

        wh_args = options.get("warehouses")
        if not wh_args:
            return Warehouse.objects.filter(warehouse_type=Warehouse.DGT).all()
        resolved = []
        for w in wh_args:
            # Try by code (case-insensitive), then by UUID if valid
            obj = Warehouse.objects.filter(code__iexact=w).first()
            if not obj:
                try:
                    uuid.UUID(str(w))
                except Exception:
                    obj = None
                else:
                    obj = Warehouse.objects.filter(id=w).first()
            if not obj:
                available = list(
                    Warehouse.objects.filter(warehouse_type=Warehouse.DGT)
                    .order_by("code")
                    .values_list("code", flat=True)
                )
                raise CommandError(
                    "Warehouse '%s' not found. Available DGT codes: %s"
                    % (w, ", ".join(available) or "<none>")
                )
            if obj.warehouse_type != Warehouse.DGT:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping non-DGT warehouse {obj.code} ({obj.warehouse_type})"
                    )
                )
                continue
            resolved.append(obj)
        return resolved

    def _resolve_owner(self, owner_arg: Optional[str]) -> Optional[Company]:
        if not owner_arg:
            return None
        obj = Company.objects.filter(id=owner_arg).first()
        if obj:
            return obj
        obj = Company.objects.filter(name=owner_arg).first()
        if not obj:
            raise CommandError(
                f"Owner '{owner_arg}' not found by UUID or exact name"
            )
        return obj

    def handle(self, *args, **options):
        # Quick listing mode for convenience
        if options.get("list_warehouses"):
            qs = Warehouse.objects.filter(warehouse_type=Warehouse.DGT).order_by("code")
            for code, name, wid in qs.values_list("code", "name", "id"):
                self.stdout.write(f"{code}\t{name}\t{wid}")
            return

        user = self._resolve_user(options.get("username"))
        warehouses = list(self._resolve_warehouses(options))
        owner_filter = self._resolve_owner(options.get("owner"))
        stock_class_opt = options.get("stock_class")
        dry_run = options.get("dry_run")
        min_qtl = Decimal(str(options.get("min_qtl")))

        if not warehouses:
            self.stdout.write(self.style.WARNING("No DGT warehouses to process."))
            return

        summary_created = {"cleaned": 0, "reject": 0}
        summary_skipped = {"cleaned": 0, "reject": 0}

        for wh in warehouses:
            self.stdout.write(f"Warehouse: {wh.code} ({wh.id})")
            stb_qs = SeedTypeBalance.objects.filter(warehouse=wh)
            if owner_filter is not None:
                stb_qs = stb_qs.filter(owner=owner_filter)
            stb_qs = stb_qs.select_related("seed_type", "owner", "warehouse")

            # Group by (owner, seed symbol) so we stock out once per series
            groups = {}
            for row in stb_qs.iterator():
                owner_obj = row.owner
                owner_id = getattr(owner_obj, "id", None)
                if owner_id is None:
                    # Register stock out workflow requires an explicit owner
                    continue
                seed_symbol = getattr(row.seed_type, "symbol", None) or str(row.seed_type.id)
                key = (owner_id, seed_symbol)
                if key not in groups:
                    groups[key] = {
                        "owner": owner_obj,
                        "seed_symbol": seed_symbol,
                        "has_cleaned": Decimal(row.cleaned_kg) > 0,
                        "has_reject": Decimal(row.rejects_kg) > 0,
                    }
                else:
                    # Track if any purity bucket has stock
                    groups[key]["has_cleaned"] = groups[key]["has_cleaned"] or (Decimal(row.cleaned_kg) > 0)
                    groups[key]["has_reject"] = groups[key]["has_reject"] or (Decimal(row.rejects_kg) > 0)

            for (owner_id, seed_symbol), info in groups.items():
                for cls in ("cleaned", "reject"):
                    if stock_class_opt != "both" and stock_class_opt != cls:
                        continue
                    if not info["has_cleaned"] and cls == "cleaned":
                        summary_skipped[cls] += 1
                        continue
                    if not info["has_reject"] and cls == "reject":
                        summary_skipped[cls] += 1
                        continue

                    available = _available_qty_qtl(seed_symbol, cls, owner_id, wh.id)
                    if available <= 0:
                        summary_skipped[cls] += 1
                        continue
                    half = (available / Decimal("2")).quantize(Decimal("0.01"))
                    if half < min_qtl:
                        summary_skipped[cls] += 1
                        continue

                    data = {
                        "seed_type": seed_symbol,
                        "stock_class": cls,
                        "quantity": half,
                    }
                    if dry_run:
                        self.stdout.write(
                            f"[DRY-RUN] {wh.code} {cls} {seed_symbol} owner={owner_id} qty={half} qtl"
                        )
                        summary_created[cls] += 1
                        continue

                    try:
                        with transaction.atomic():
                            entry = _process_stock_out(
                                data,
                                wh,
                                info["owner"],
                                user,
                                None,
                                None,
                                None,
                            )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Created stock-out entry {entry.id} → {cls} "
                                f"{seed_symbol} {half} qtl @ {wh.code}"
                            )
                        )
                        summary_created[cls] += 1
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"Failed {cls} {seed_symbol} owner={owner_id} "
                                f"qty={half} qtl @ {wh.code}: {e}"
                            )
                        )
                        # Continue to next item without aborting the whole run

        self.stdout.write(
            self.style.SUCCESS(
                "Done. Created: cleaned=%d, reject=%d | Skipped: cleaned=%d, reject=%d"
                % (
                    summary_created["cleaned"],
                    summary_created["reject"],
                    summary_skipped["cleaned"],
                    summary_skipped["reject"],
                )
            )
        )
