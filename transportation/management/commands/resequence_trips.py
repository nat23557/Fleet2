from django.core.management.base import BaseCommand, CommandError
from transportation.models import Trip, Truck
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Assign or fix per-truck sequential trip numbers (truck_trip_number).\n"
        "By default, resequences ALL trucks. Use --truck-id or --plate to target one.\n"
        "Use --dry-run to preview changes without saving."
    )

    def add_arguments(self, parser):
        parser.add_argument('--truck-id', type=int, help='Truck PK to resequence')
        parser.add_argument('--plate', type=str, help='Truck plate_number to resequence')
        parser.add_argument('--start', type=int, default=1, help='Starting number (default: 1)')
        parser.add_argument('--dry-run', action='store_true', help='Preview changes only')
        parser.add_argument('--only-missing', action='store_true', help='Only assign numbers to trips missing truck_trip_number')

    def handle(self, *args, **options):
        truck_id = options.get('truck_id')
        plate = options.get('plate')
        start = options.get('start') or 1
        dry_run = options.get('dry_run')
        only_missing = options.get('only_missing')

        if truck_id and plate:
            raise CommandError('Provide only one of --truck-id or --plate')

        if truck_id:
            trucks = Truck.objects.filter(pk=truck_id)
            if not trucks.exists():
                raise CommandError(f'Truck id={truck_id} not found')
        elif plate:
            trucks = Truck.objects.filter(plate_number=plate)
            if not trucks.exists():
                raise CommandError(f'Truck plate={plate} not found')
        else:
            trucks = Truck.objects.all().order_by('pk')

        total_updated = 0
        for truck in trucks:
            # Order trips deterministically: by start_time if present, then by pk
            trips_qs = Trip.objects.filter(truck=truck).order_by('start_time', 'pk')
            next_no = start
            updated_for_truck = 0
            to_update = []
            for trip in trips_qs:
                if only_missing and trip.truck_trip_number:
                    # Keep sequence in sync even when skipping; do not increment next_no
                    continue
                if trip.truck_trip_number != next_no:
                    to_update.append((trip.pk, trip.truck_trip_number, next_no))
                next_no += 1

            if not to_update:
                self.stdout.write(self.style.SUCCESS(f"Truck {truck.plate_number}: already sequenced"))
                continue

            self.stdout.write(f"Truck {truck.plate_number}: {len(to_update)} updates")
            for pk, old, new in to_update:
                self.stdout.write(f"  Trip {pk}: {old} -> {new}")

            if dry_run:
                continue

            with transaction.atomic():
                for pk, _old, new in to_update:
                    Trip.objects.filter(pk=pk).update(truck_trip_number=new)
            updated_for_truck = len(to_update)
            total_updated += updated_for_truck
            self.stdout.write(self.style.SUCCESS(f"Truck {truck.plate_number}: updated {updated_for_truck} trips"))

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete (no changes saved)."))
        self.stdout.write(self.style.SUCCESS(f"Done. Total trips updated: {total_updated}"))

