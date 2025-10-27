from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from transportation.models import Trip, Truck


class Command(BaseCommand):
    help = (
        "Assign per-truck trip sequence numbers to existing trips (Trip.truck_trip_number).\n"
        "By default, fills only missing numbers per truck in chronological order.\n"
        "Use --resequence to rewrite numbers for each truck from 1..N."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--truck",
            action="append",
            dest="trucks",
            help="Limit to a specific truck by plate number or ID (can be repeated).",
        )
        parser.add_argument(
            "--resequence",
            action="store_true",
            help="Rewrite numbers 1..N for each truck, overriding existing values.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show planned changes without saving.",
        )
        parser.add_argument(
            "--order-by",
            default="start_time",
            choices=["start_time", "end_time", "pk"],
            help="Field to order trips within a truck before assigning numbers.",
        )

    def handle(self, *args, **opts):
        trucks_qs = Truck.objects.all()
        truck_filters = opts.get("trucks") or []
        resequence = bool(opts.get("resequence"))
        dry_run = bool(opts.get("dry_run"))
        order_by = opts.get("order_by") or "start_time"

        if truck_filters:
            q = Q()
            ids = []
            plates = []
            for t in truck_filters:
                t = str(t).strip()
                if t.isdigit():
                    ids.append(int(t))
                else:
                    plates.append(t)
            if ids:
                q |= Q(id__in=ids)
            if plates:
                q |= Q(plate_number__in=plates)
            trucks_qs = trucks_qs.filter(q)
            if not trucks_qs.exists():
                self.stdout.write(self.style.WARNING("No trucks matched the provided filters."))
                return

        if order_by == "start_time":
            order_fields = ["start_time", "pk"]
        elif order_by == "end_time":
            order_fields = ["end_time", "pk"]
        else:
            order_fields = ["pk"]

        total_trucks = trucks_qs.count()
        total_trips = 0
        total_updated = 0

        self.stdout.write(
            self.style.NOTICE(
                f"Processing {total_trucks} truck(s); resequence={'yes' if resequence else 'no'}, dry-run={'yes' if dry_run else 'no'}"
            )
        )

        for truck in trucks_qs.order_by("pk"):
            trips_qs = Trip.objects.filter(truck=truck).order_by(*order_fields)
            trip_count = trips_qs.count()
            total_trips += trip_count
            if trip_count == 0:
                continue

            updated = 0
            updates_preview = []

            # Perform updates inside a transaction per truck to keep constraints safe
            with transaction.atomic():
                if resequence and not dry_run:
                    # Clear numbers first to avoid unique collisions during resequencing
                    Trip.objects.filter(truck=truck).update(truck_trip_number=None)

                if resequence:
                    next_seq = 1
                    for trip in trips_qs.iterator():
                        desired = next_seq
                        if dry_run:
                            updates_preview.append((trip.pk, trip.truck_trip_number, desired))
                        else:
                            Trip.objects.filter(pk=trip.pk).update(truck_trip_number=desired)
                        updated += 1
                        next_seq += 1
                else:
                    # Only fill missing; assign the smallest available number not used yet
                    used_numbers = set(
                        Trip.objects.filter(truck=truck, truck_trip_number__isnull=False)
                        .values_list("truck_trip_number", flat=True)
                    )
                    next_seq = 1
                    for trip in trips_qs.iterator():
                        if trip.truck_trip_number is not None:
                            continue
                        while next_seq in used_numbers:
                            next_seq += 1
                        desired = next_seq
                        if dry_run:
                            updates_preview.append((trip.pk, trip.truck_trip_number, desired))
                        else:
                            Trip.objects.filter(pk=trip.pk).update(truck_trip_number=desired)
                        used_numbers.add(desired)
                        updated += 1
                        next_seq += 1

            total_updated += updated
            label = getattr(truck, "plate_number", None) or f"Truck#{truck.pk}"
            msg = f"{label}: trips={trip_count}, updated={updated}"
            self.stdout.write(self.style.SUCCESS(msg) if updated else msg)

            if dry_run and updates_preview:
                # Show first few updates for visibility
                self.stdout.write("  Planned changes (first 10):")
                for pk, old, new in updates_preview[:10]:
                    self.stdout.write(f"    Trip id={pk}: {old} -> {new}")
                extra = len(updates_preview) - 10
                if extra > 0:
                    self.stdout.write(f"    ... and {extra} more")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Trucks processed={total_trucks}, trips={total_trips}, updated={total_updated}"
            )
        )
