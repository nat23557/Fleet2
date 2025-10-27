from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from decimal import Decimal
import random
from datetime import datetime, timedelta

from transportation.models import (
    Staff, Driver, Truck, Trip, TripFinancial, Expense, Invoice
)


class Command(BaseCommand):
    help = "Create a focused set of sample trips in the previous full week to exercise Weekly Story Mode."

    def add_arguments(self, parser):
        parser.add_argument('--reset-week', action='store_true', help='Delete trips in the target week before seeding')
        parser.add_argument('--trucks', type=int, default=3, help='Number of trucks to involve')
        parser.add_argument('--trips', type=int, default=10, help='Number of completed trips to generate')

    @transaction.atomic
    def handle(self, *args, **opts):
        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        dow = today.weekday()  # Mon=0..Sun=6
        monday = today - timedelta(days=dow + 7)
        sunday = monday + timedelta(days=6)
        week_start = timezone.make_aware(datetime(monday.year, monday.month, monday.day, 0, 0, 0), tz)
        week_end = timezone.make_aware(datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59), tz)

        if opts['reset_week']:
            Trip.objects.filter(end_time__gte=week_start, end_time__lte=week_end).delete()

        # Ensure a manager and a few drivers
        manager_user, manager_staff = self._ensure_staff('manager', 'manager@example.com', 'MANAGER')
        drivers = []
        for i in range(1, 4):
            u, s = self._ensure_staff(f'story_driver{i}', f'story_driver{i}@example.com', 'DRIVER')
            d = self._ensure_driver(s, f'STORY-LIC-{i:03d}')
            drivers.append(d)

        # Ensure trucks
        trucks = []
        for i in range(opts['trucks']):
            t = self._ensure_truck(f"ST-{2000+i}", random.choice(['Howo','Actros','FH12']), Decimal(random.choice([20,25,30])))
            # attach a driver if free
            if not t.driver_id and i < len(drivers):
                t.driver = drivers[i]
                t.status = 'IN_USE'
                t.is_in_duty = True
                t.save(update_fields=['driver', 'status', 'is_in_duty'])
            trucks.append(t)

        # Predefined lanes to create clear best/worst routes
        lanes = [
            ('Addis Ababa', 'Mekelle'),
            ('Dire Dawa', 'Mekelle'),
            ('Addis Ababa', 'Djibouti'),
        ]

        def pick_times():
            # random day within the week
            day_offset = random.randint(0, 6)
            start_hour = random.randint(6, 18)
            duration_h = random.randint(8, 48)
            start = timezone.make_aware(datetime(monday.year, monday.month, monday.day + day_offset, start_hour, 0, 0), tz)
            end = start + timedelta(hours=duration_h)
            return start, end

        trips = []
        strong_lane = lanes[2]  # Addis→Djibouti good margin
        weak_lane = lanes[0]    # Addis→Mekelle poor margin to trigger suggestions

        for i in range(opts['trips']):
            truck = random.choice(trucks)
            driver = truck.driver or random.choice(drivers)
            lane = random.choices([strong_lane, weak_lane, lanes[1]], weights=[3, 3, 2])[0]
            s_name, e_name = lane
            start, end = pick_times()
            initial_km = max(0, truck.mileage_km - random.randint(300, 3000))
            dist = random.randint(300, 1700)
            final_km = initial_km + dist

            trip = Trip.objects.create(
                truck=truck,
                driver=driver,
                start_location=s_name,
                end_location=e_name,
                start_time=start,
                initial_kilometer=initial_km,
                status=Trip.STATUS_IN_PROGRESS,
                cargo_type=random.choice(['Cement','Steel','Grain','Machinery']),
                cargo_load=Decimal(random.choice([14,18,22,28])),
                tariff_rate=Decimal(random.choice([2500, 3000, 3500])),
            )

            fin, _ = TripFinancial.objects.get_or_create(trip=trip)
            fin.update_financials()

            # Expenses: craft lanes with different economics
            base_expense = Decimal(dist) * Decimal(random.choice([8, 10, 12]))  # ETB/km baseline spend
            # Poor margin for weak lane; good margin for strong lane
            if lane == weak_lane:
                base_expense *= Decimal('1.25')
            elif lane == strong_lane:
                base_expense *= Decimal('0.75')

            # Add granular expenses in categories
            categories = [c for c, _ in Expense.EXPENSE_CATEGORIES]
            remaining = base_expense
            for j in range(3):
                part = (base_expense / 3) * Decimal(random.uniform(0.8, 1.2))
                remaining -= part
                Expense.objects.create(
                    trip_financial=fin,
                    category=random.choice(categories),
                    amount=max(part, Decimal('100.00')),
                    note='story sample'
                )
            fin.update_financials()

            # Invoice before completion (model rule enforces this)
            Invoice.objects.get_or_create(trip=trip, defaults={
                'amount_due': fin.total_revenue or Decimal('0.00'),
                'is_paid': random.choice([False, False, True]),  # bias to unpaid
            })

            # Complete the trip
            trip.final_kilometer = final_km
            trip.end_time = end
            trip.status = Trip.STATUS_COMPLETED
            trip.distance_traveled = Decimal(dist)
            trip.save()

            # Recompute with actuals
            fin.update_financials()
            trips.append(trip)

        # Also create at least one negative-profit trip for emphasis
        if trips:
            t = random.choice(trips)
            fin = TripFinancial.objects.get(trip=t)
            # Inject a heavy expense
            Expense.objects.create(trip_financial=fin, category=categories[0], amount=Decimal('200000.00'), note='outlier')
            fin.update_financials()

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(trips)} completed trips across {len(trucks)} trucks for week {monday}–{sunday}."
        ))

    def _ensure_staff(self, username, email, role):
        u, created = User.objects.get_or_create(username=username, defaults={'email': email})
        if created:
            u.set_password('demo1234')
            u.is_staff = True
            u.save()
        s, _ = Staff.objects.get_or_create(user=u, defaults={'role': role})
        if s.role != role:
            s.role = role
            s.save(update_fields=['role'])
        return u, s

    def _ensure_driver(self, staff: Staff, license_no: str):
        d, _ = Driver.objects.get_or_create(staff_profile=staff, defaults={'license_number': license_no, 'years_of_experience': random.randint(1, 10)})
        return d

    def _ensure_truck(self, plate_number: str, truck_type: str, capacity_in_tons: Decimal):
        t, _ = Truck.objects.get_or_create(
            plate_number=plate_number,
            defaults={
                'truck_type': truck_type,
                'capacity_in_tons': capacity_in_tons,
                'status': 'IN_USE',
                'vehicle_type': 'CARGO',
                'mileage_km': random.randint(70000, 160000),
            }
        )
        return t

