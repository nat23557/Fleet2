from __future__ import annotations

"""
Delete all domain/sample data while preserving user-related tables.

Defaults:
 - Purges only the `WareDGT` app tables
 - Preserves Django auth/group/permission/contenttypes/sessions tables
 - Preserves `WareDGT.UserProfile`

Supports:
 - --dry-run: show what would be truncated without executing
 - --include-app: repeatable option to add other app labels to purge
 - --preserve: repeatable `app_label.ModelName` to preserve additionally

This is safer than dropping the whole database when you must keep user
credentials and roles intact.
"""

from typing import Iterable, List, Set

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def _quote(name: str) -> str:
    return connection.ops.quote_name(name)


class Command(BaseCommand):
    help = (
        "Purge data for domain apps while keeping user-related tables. "
        "By default affects only the 'WareDGT' app and preserves auth + "
        "UserProfile."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the list of tables that would be truncated",
        )
        parser.add_argument(
            "--include-app",
            action="append",
            dest="apps",
            default=None,
            help="App label to include in purge (repeat for multiple). Default: WareDGT",
        )
        parser.add_argument(
            "--preserve",
            action="append",
            dest="preserve_models",
            default=None,
            help="Extra models to preserve (format: app_label.ModelName). Repeatable.",
        )

    def handle(self, *args, **opts):
        dry_run: bool = bool(opts.get("dry_run"))
        app_labels: List[str] = opts.get("apps") or ["WareDGT"]
        preserve_specs: List[str] = opts.get("preserve_models") or []

        # Resolve models for default preservation set
        preserve_models = self._default_preserve_models()
        # Add any caller-provided models
        preserve_models.update(self._resolve_model_specs(preserve_specs))

        # Build purge table set from selected apps, excluding preserved models
        purge_tables = self._collect_app_tables(app_labels, exclude_models=preserve_models)
        # Filter to existing base tables (exclude views, skip missing)
        purge_tables = self._filter_existing_base_tables(purge_tables)

        if not purge_tables:
            self.stdout.write(self.style.WARNING("No tables to purge (nothing to do)."))
            return

        engine = connection.settings_dict.get("ENGINE", "")
        mysql = "mysql" in engine

        # Some core tables we should never touch directly
        system_tables = {"django_migrations"}
        purge_tables -= system_tables

        if dry_run:
            self.stdout.write("Would purge tables (in arbitrary order):")
            for t in sorted(purge_tables):
                self.stdout.write(f" - {t}")
            return

        with connection.cursor() as cursor:
            if mysql:
                cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
            try:
                for table in purge_tables:
                    try:
                        cursor.execute(f"TRUNCATE TABLE {_quote(table)};")
                    except Exception as exc:
                        # Skip missing or non-truncatable (e.g., view) tables gracefully
                        self.stderr.write(f"Skipping {table}: {exc}")
            finally:
                if mysql:
                    cursor.execute("SET FOREIGN_KEY_CHECKS=1;")

        self.stdout.write(self.style.SUCCESS(f"Purged {len(purge_tables)} table(s)."))

    # ---- helpers ----

    def _default_preserve_models(self) -> Set[type]:
        """Core models to keep: auth, contenttypes, sessions, UserProfile."""
        keep: Set[type] = set()
        # Auth core
        try:
            from django.contrib.auth.models import User, Group, Permission  # type: ignore

            keep.update({User, Group, Permission})
            # M2M through tables for user<->groups and user/ group permissions
            keep.add(User.groups.through)
            keep.add(User.user_permissions.through)
            keep.add(Group.permissions.through)
        except Exception:
            pass

        # Content types
        try:
            from django.contrib.contenttypes.models import ContentType  # type: ignore

            keep.add(ContentType)
        except Exception:
            pass

        # Sessions
        try:
            from django.contrib.sessions.models import Session  # type: ignore

            keep.add(Session)
        except Exception:
            pass

        # Admin log (harmless to keep)
        try:
            from django.contrib.admin.models import LogEntry  # type: ignore

            keep.add(LogEntry)
        except Exception:
            pass

        # Project-specific user profile
        try:
            UserProfile = django_apps.get_model("WareDGT", "UserProfile")
            keep.add(UserProfile)
        except Exception:
            pass

        return keep

    def _resolve_model_specs(self, specs: Iterable[str]) -> Set[type]:
        out: Set[type] = set()
        for spec in specs or []:
            try:
                app_label, model_name = spec.split(".")
                model = django_apps.get_model(app_label, model_name)
                out.add(model)
            except Exception:
                raise CommandError(f"Invalid --preserve model spec: {spec}")
        return out

    def _collect_app_tables(self, app_labels: Iterable[str], exclude_models: Set[type]) -> Set[str]:
        tables: Set[str] = set()
        for label in app_labels:
            try:
                app_config = django_apps.get_app_config(label)
            except LookupError:
                raise CommandError(f"Unknown app label: {label}")

            for model in app_config.get_models(include_auto_created=True):
                # Skip unmanaged or proxy models (often views/readonly)
                if not getattr(model._meta, "managed", True):
                    continue
                if getattr(model._meta, "proxy", False):
                    continue
                if model in exclude_models:
                    continue
                # Skip auto through models for preserved relations
                if getattr(model, "_meta", None) and getattr(model._meta, "auto_created", False):
                    # If either side model is preserved, keep the through-table too
                    rel = getattr(model, "_meta", None)
                    try:
                        src = rel.auto_created
                        dst = rel.concrete_model
                        if src in exclude_models or dst in exclude_models:
                            continue
                    except Exception:
                        pass

                # Main table
                tables.add(model._meta.db_table)

                # M2M tables declared on this model
                for m2m in model._meta.local_many_to_many:
                    try:
                        through = m2m.remote_field.through
                        # Skip unmanaged through tables
                        if not getattr(through._meta, "managed", True):
                            continue
                        if through in exclude_models:
                            continue
                        tables.add(through._meta.db_table)
                    except Exception:
                        pass
        return tables

    def _filter_existing_base_tables(self, tables: Iterable[str]) -> Set[str]:
        """Return only existing base tables (exclude views, missing)."""
        engine = connection.settings_dict.get("ENGINE", "")
        existing: Set[str] = set()
        if "mysql" in engine:
            with connection.cursor() as cursor:
                cursor.execute("SHOW FULL TABLES")
                rows = cursor.fetchall()
                # Row format: (table_name, table_type)
                base = {r[0] for r in rows if len(r) >= 2 and str(r[1]).upper() == "BASE TABLE"}
                existing = base
        else:
            # Fallback to Django introspection (may include views on some backends)
            try:
                names = set(connection.introspection.table_names())
                existing = names
            except Exception:
                existing = set()

        return set(t for t in tables if t in existing)
