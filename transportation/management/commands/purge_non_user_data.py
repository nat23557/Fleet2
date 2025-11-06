from typing import Iterable, List, Set, Tuple

import os
from django.core.management.base import BaseCommand, CommandError
from django.apps import apps as django_apps
from django.db import transaction


# Default media subdirectories to purge when --purge-media is set.
# These correspond to ImageField/FileField upload_to paths in models.
DEFAULT_PURGE_MEDIA_DIRS = [
    'invoices',
    'operational_expense_images',
    'service_docs',
    'replacement_docs',
    'licenses',
    'accidents',
]


def parse_label(label: str) -> Tuple[str, str]:
    """Parse "app_label.ModelName" into tuple.

    Raises CommandError if malformed.
    """
    try:
        app_label, model_name = label.split('.', 1)
    except ValueError:
        raise CommandError(f"Invalid model label '{label}'. Use 'app_label.ModelName'.")
    return app_label, model_name


class Command(BaseCommand):
    help = (
        "Remove non user-related data. By default, purges transportation domain data "
        "(trips, GPS, invoices, expenses, geofences, accidents, etc.) but keeps "
        "auth users as well as Staff, Driver, and Truck."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes-i-am-sure', action='store_true', dest='confirm',
            help='Actually perform deletions (without this, runs in dry-run mode).'
        )
        parser.add_argument(
            '--dry-run', action='store_true', dest='dry_run',
            help='Show what would be deleted without changing data.'
        )
        parser.add_argument(
            '--purge-trucks', action='store_true', dest='purge_trucks',
            help='Also delete Truck records (and cascading relations).'
        )
        parser.add_argument(
            '--purge-profiles', action='store_true', dest='purge_profiles',
            help='Also delete Staff and Driver records (linked to auth.User).'
        )
        parser.add_argument(
            '--include-model', action='append', default=[], metavar='app.Model',
            help='Additionally include specific models (repeatable).'
        )
        parser.add_argument(
            '--exclude-model', action='append', default=[], metavar='app.Model',
            help='Exclude specific models from purge (repeatable).'
        )
        parser.add_argument(
            '--purge-media', action='store_true', dest='purge_media',
            help='Also remove uploaded media in known domain subfolders (non-user).'
        )
        parser.add_argument(
            '--media-dirs', action='append', default=[], metavar='subdir',
            help='Additional media subdirectories to remove under MEDIA_ROOT (repeatable).'
        )

    def handle(self, *args, **opts):
        dry_run = opts.get('dry_run') or not opts.get('confirm')

        # Determine default target models: transportation domain, excluding user-related
        # Keep Staff, Driver, and Truck by default; purge the rest.
        default_transportation_purge = [
            'transportation.GPSRecord',
            'transportation.Geofence',
            'transportation.MajorAccident',
            'transportation.ServiceRecord',
            'transportation.ReplacedItem',
            'transportation.Cargo',
            'transportation.OperationalExpenseDetail',
            'transportation.Expense',
            'transportation.Invoice',
            'transportation.TripFinancial',
            'transportation.Trip',
            'transportation.OfficeUsage',
        ]

        include_labels: List[str] = list(default_transportation_purge) + list(opts.get('include_model') or [])

        # Optionally add Trucks and Staff/Driver
        if opts.get('purge_trucks'):
            include_labels.append('transportation.Truck')
        if opts.get('purge_profiles'):
            include_labels.extend(['transportation.Staff', 'transportation.Driver'])

        # Remove explicitly excluded models
        exclude_labels: Set[str] = set(opts.get('exclude_model') or [])
        target_labels = [lbl for lbl in include_labels if lbl not in exclude_labels]

        # Resolve labels to model classes (skip missing models gracefully)
        target_models = self._resolve_models(target_labels)
        if not target_models:
            self.stdout.write(self.style.WARNING('No target models resolved. Nothing to do.'))
            return

        # Summarize work
        self.stdout.write(self.style.NOTICE('Planned purge (non user-related data):'))
        for m in target_models:
            self.stdout.write(f"  - {m._meta.label}")

        # Collect row counts before deletion
        counts_before = {m: m.objects.count() for m in target_models}
        total = sum(counts_before.values())
        self.stdout.write(self.style.NOTICE(f"Total rows targeted: {total}"))
        for m, c in counts_before.items():
            self.stdout.write(f"    {m._meta.label}: {c}")

        if dry_run:
            self.stdout.write(self.style.WARNING('Dry-run mode: no deletions performed.'))
            self.stdout.write(self.style.WARNING('Re-run with --yes-i-am-sure to apply.'))
            return

        # Execute deletions in a transaction; order children-first for cleanliness
        with transaction.atomic():
            deleted_summary = {}
            for model in self._order_children_first(target_models):
                qs = model.objects.all()
                # Bulk delete; note: bulk delete does not call each instance.delete()
                deleted, _ = qs.delete()
                deleted_summary[model] = deleted
                self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} rows from {model._meta.label}"))

        # Optional media cleanup
        if opts.get('purge_media'):
            self._purge_media(opts)

        self.stdout.write(self.style.SUCCESS('Purge complete.'))

    # ---- helpers -----------------------------------------------------------
    def _resolve_models(self, labels: Iterable[str]):
        models = []
        for lbl in labels:
            app_label, model_name = parse_label(lbl)
            try:
                model = django_apps.get_model(app_label, model_name)
            except LookupError:
                self.stdout.write(self.style.WARNING(f"Skipping unknown model '{lbl}'."))
                continue
            models.append(model)
        return models

    def _order_children_first(self, models: List[type]) -> List[type]:
        """Return models ordered with likely children first to reduce cascades.

        Not a perfect topological sort, but good enough for our domain schema.
        """
        # Preferred ordering by label (children before parents)
        preferred = [
            'transportation.GPSRecord',
            'transportation.Geofence',
            'transportation.OperationalExpenseDetail',
            'transportation.Expense',
            'transportation.Invoice',
            'transportation.TripFinancial',
            'transportation.Trip',
            'transportation.MajorAccident',
            'transportation.ServiceRecord',
            'transportation.ReplacedItem',
            'transportation.Cargo',
            'transportation.OfficeUsage',
            'transportation.Driver',
            'transportation.Staff',
            'transportation.Truck',
        ]
        index = {name: i for i, name in enumerate(preferred)}
        return sorted(models, key=lambda m: index.get(m._meta.label, len(preferred)))

    def _purge_media(self, opts):
        from django.conf import settings

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            self.stdout.write(self.style.WARNING('MEDIA_ROOT not configured; skipping media purge.'))
            return

        # Directories to remove inside MEDIA_ROOT
        dirs: Set[str] = set(DEFAULT_PURGE_MEDIA_DIRS)
        for d in (opts.get('media_dirs') or []):
            if d:
                dirs.add(d.strip('/'))

        self.stdout.write(self.style.NOTICE(f"Purging media subdirs under {media_root}:"))
        for d in sorted(dirs):
            path = os.path.join(media_root, d)
            if os.path.isdir(path):
                self._rm_tree(path)
                self.stdout.write(self.style.SUCCESS(f"  removed {path}"))
            else:
                self.stdout.write(f"  (missing) {path}")

    def _rm_tree(self, path: str):
        # Best-effort recursive deletion without touching MEDIA_ROOT itself
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except FileNotFoundError:
                    pass
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError:
                    # Directory not empty or other race; ignore
                    pass
        try:
            os.rmdir(path)
        except OSError:
            pass

