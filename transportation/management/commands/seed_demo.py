from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from decimal import Decimal
import random
from datetime import timedelta

from transportation.models import (
    Staff, Driver, Truck, Trip, TripFinancial, Expense, Invoice, GPSRecord
)


class Command(BaseCommand):
    help = "Populate the database with demo trucks, drivers, trips, GPS, and financials."

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Remove existing demo content first')
        parser.add_argument('--active', type=int, default=3, help='Number of active trips to create')
        parser.add_argument('--completed', type=int, default=8, help='Number of completed trips to create')

    @transaction.atomic
    def handle(self, *args, **opts):
        self.stdout.write(self.style.NOTICE('Seeding demo data...'))
        # 0) Optionally reset demo (only demo-tagged objects)
        if opts['reset']:
            self._reset_demo()

        # 1) Users/Staff
        admin = self._ensure_superuser('admin', 'admin@example.com', 'demo1234')
        manager_user, manager_staff = self._ensure_staff('manager', 'manager@example.com', 'MANAGER')

        # 2) Drivers
        drivers = []
        for i in range(1, 4):
            u, s = self._ensure_staff(f'driver{i}', f'driver{i}@example.com', 'DRIVER')
            d = self._ensure_driver(s, f'DEMO-LIC-{i:03d}')
            drivers.append(d)

        # 3) Trucks
        trucks = []
        for i in range(1, 6):
            plate = f"ET-{1000+i}"
            t = self._ensure_truck(
                plate_number=plate,
                truck_type=random.choice(['Howo', 'Actros', 'FH12', 'Isuzu']),
                capacity_in_tons=Decimal(random.choice([20, 25, 30])),
            )
            trucks.append(t)

        # Assign some drivers to trucks
        for t, d in zip(trucks, drivers):
            if t.driver_id is None:
                t.driver = d
                t.status = 'IN_USE'
                t.is_in_duty = True
                t.save(update_fields=['driver', 'status', 'is_in_duty'])

        # 4) Trips: active and completed
        active_n = int(opts['active'])
        completed_n = int(opts['completed'])
        active_trips = self._make_active_trips(trucks, drivers, active_n)
        completed_trips = self._make_completed_trips(trucks, drivers, completed_n)

        # 5) GPS for trucks (latest snapshot)
        for t in trucks:
            self._ensure_gps_snapshot(t)

        self.stdout.write(self.style.SUCCESS(
            f"Demo seed complete: users={1+1+len(drivers)}, trucks={len(trucks)}, active_trips={len(active_trips)}, completed_trips={len(completed_trips)}"
        ))

    def _reset_demo(self):
        # Remove objects tied to our known demo identifiers
        from transportation.models import GPSRecord
        demo_trucks = Truck.objects.filter(plate_number__startswith='ET-10')
        Trip.objects.filter(truck__in=demo_trucks).delete()
        GPSRecord.objects.filter(group='DEMO').delete()
        # Do not remove trucks or users by default

    def _ensure_superuser(self, username, email, password):
        u, created = User.objects.get_or_create(username=username, defaults={'email': email, 'is_superuser': True, 'is_staff': True})
        if created:
            u.set_password(password)
            u.save()
        elif not u.is_superuser:
            u.is_superuser = True
            u.is_staff = True
            u.save(update_fields=['is_superuser', 'is_staff'])
        return u

    def _ensure_staff(self, username, email, role):
        u, created = User.objects.get_or_create(username=username, defaults={'email': email})
        if created:
            # Non-critical password; for demo use
            u.set_password('demo1234')
            u.is_staff = True
            u.save()
        s, _ = Staff.objects.get_or_create(user=u, defaults={'role': role, 'phone': f'+2519{random.randint(10000000, 99999999)}'})
        if s.role != role:
            s.role = role
            s.save(update_fields=['role'])
        return u, s

    def _ensure_driver(self, staff: Staff, license_no: str):
        d, _ = Driver.objects.get_or_create(staff_profile=staff, defaults={
            'license_number': license_no,
            'years_of_experience': random.randint(1, 12)
        })
        return d

    def _ensure_truck(self, plate_number: str, truck_type: str, capacity_in_tons: Decimal):
        t, created = Truck.objects.get_or_create(
            plate_number=plate_number,
            defaults={
                'truck_type': truck_type,
                'capacity_in_tons': capacity_in_tons,
                'status': random.choice(['AVAILABLE', 'IN_USE', 'MAINTENANCE']),
                'vehicle_type': 'CARGO',
                'mileage_km': random.randint(50000, 180000),
            }
        )
        return t

    def _cities(self):
        # name, lat, lng
        return [
            ('Addis Ababa', 8.9806, 38.7578),
            ('Dire Dawa', 9.6000, 41.8700),
            ('Mekelle', 13.5000, 39.4700),
            ('Bahir Dar', 11.6000, 37.3800),
            ('Djibouti', 11.5880, 43.1456),
        ]

    def _pick_route(self):
        a, b = random.sample(self._cities(), 2)
        return a, b

    def _jitter(self, lat, lng, km=2):
        # Rough jitter ~km
        dlat = (random.random()-0.5) * (km/111.0)
        dlng = (random.random()-0.5) * (km/111.0)
        return lat + dlat, lng + dlng

    def _make_active_trips(self, trucks, drivers, n):
        trips = []
        now = timezone.now()
        for i in range(n):
            truck = random.choice(trucks)
            driver = truck.driver or random.choice(drivers)
            (s_name, s_lat, s_lng), (e_name, e_lat, e_lng) = self._pick_route()
            start = now - timedelta(hours=random.randint(2, 20))
            t = Trip.objects.create(
                truck=truck,
                driver=driver,
                start_location=s_name,
                end_location=e_name,
                start_latitude=s_lat, start_longitude=s_lng,
                end_latitude=e_lat, end_longitude=e_lng,
                start_time=start,
                status=Trip.STATUS_IN_PROGRESS,
                initial_kilometer=max(0, truck.mileage_km - random.randint(10, 300)),
                cargo_type=random.choice(['Cement', 'Steel', 'Grain', 'Machinery']),
                cargo_load=Decimal(random.choice([14, 18, 22, 28])),
                tariff_rate=Decimal(random.choice([2500, 3000, 3500])),
                is_in_duty=True,
            )
            # sprinkle GPS along the way
            self._seed_gps_for_trip(t)
            trips.append(t)
        return trips

    def _make_completed_trips(self, trucks, drivers, n):
        trips = []
        now = timezone.now()
        for i in range(n):
            truck = random.choice(trucks)
            driver = truck.driver or random.choice(drivers)
            (s_name, s_lat, s_lng), (e_name, e_lat, e_lng) = self._pick_route()
            duration_h = random.randint(6, 72)
            start = now - timedelta(days=random.randint(3, 60), hours=duration_h+random.randint(1,6))
            end = start + timedelta(hours=duration_h)
            initial_km = max(0, truck.mileage_km - random.randint(500, 5000))
            final_km = initial_km + random.randint(200, 1800)

            # Create as IN_PROGRESS first
            trip = Trip.objects.create(
                truck=truck,
                driver=driver,
                start_location=s_name,
                end_location=e_name,
                start_latitude=s_lat, start_longitude=s_lng,
                end_latitude=e_lat, end_longitude=e_lng,
                start_time=start,
                initial_kilometer=initial_km,
                final_kilometer=None,
                cargo_type=random.choice(['Cement', 'Steel', 'Grain', 'Machinery']),
                cargo_load=Decimal(random.choice([14, 18, 22, 28])),
                tariff_rate=Decimal(random.choice([2500, 3000, 3500])),
                status=Trip.STATUS_IN_PROGRESS,
            )
            # Financials
            fin, _ = TripFinancial.objects.get_or_create(trip=trip)
            fin.update_financials()
            # Some expenses
            for _ in range(random.randint(2, 5)):
                Expense.objects.create(
                    trip_financial=fin,
                    category=random.choice([c for c, _ in Expense.EXPENSE_CATEGORIES]),
                    amount=Decimal(random.randint(500, 5000)),
                    note=random.choice(['-', 'Fuel stop', 'Toll', 'Snack'])
                )
            fin.update_financials()

            # Invoice first (required by Trip completion rule)
            Invoice.objects.get_or_create(trip=trip, defaults={
                'amount_due': fin.total_revenue or Decimal('0.00'),
                'is_paid': random.choice([True, False])
            })

            # Now complete the trip
            trip.final_kilometer = final_km
            trip.end_time = end
            trip.status = Trip.STATUS_COMPLETED
            trip.distance_traveled = Decimal(final_km - initial_km)
            trip.save()

            # GPS timeline for performance stats
            self._seed_gps_for_trip(trip)
            trips.append(trip)
        return trips

    def _seed_gps_for_trip(self, trip: Trip):
        # generate a handful of GPS points between start and end
        if not trip.start_time:
            return
        if trip.end_time and trip.end_time > trip.start_time:
            total = random.randint(8, 20)
            dt = (trip.end_time - trip.start_time) / total
            curr = trip.start_time
        else:
            # active trip: from start to now
            total = random.randint(6, 14)
            now = timezone.now()
            if now <= trip.start_time:
                return
            dt = (now - trip.start_time) / total
            curr = trip.start_time

        slat, slng = (trip.start_latitude or 8.98), (trip.start_longitude or 38.75)
        elat, elng = (trip.end_latitude or 9.6), (trip.end_longitude or 41.87)
        for i in range(total):
            frac = (i+1)/total
            lat = slat + (elat - slat) * frac
            lng = slng + (elng - slng) * frac
            lat, lng = self._jitter(lat, lng, km=5)
            speed = Decimal(random.choice([0, 0, 20, 35, 50, 60, 70]))
            engine = 'on' if speed > 0 else 'off'
            odometer = Decimal((trip.initial_kilometer or 0) + int(frac * (trip.final_kilometer or ((trip.initial_kilometer or 0)+300))))
            GPSRecord.objects.create(
                truck=trip.truck,
                imei=f'DEMO-IMEI-{trip.truck.plate_number}',
                name=trip.truck.plate_number,
                group='DEMO',
                odometer=odometer,
                engine=engine,
                status='moving' if speed > 0 else 'idle',
                dt_server=curr,
                dt_tracker=curr,
                lat=Decimal(str(round(lat, 6))),
                lng=Decimal(str(round(lng, 6))),
                loc=f'Near {trip.start_location}→{trip.end_location}',
                nearset_zone=None,
                altitude=Decimal('0.00'),
                angle=random.randint(0, 359),
                speed=speed,
                fuel_1=Decimal(random.randint(10, 80)),
                fuel_2=Decimal(random.randint(0, 50)),
                fuel_can_level_percent=None,
                fuel_can_level_value=None,
                params={"src": "seed_demo"},
                custom_fields=None,
            )
            curr = curr + dt

    def _ensure_gps_snapshot(self, truck: Truck):
        # Make sure each truck has at least one recent GPS record
        latest = GPSRecord.objects.filter(truck=truck).order_by('-dt_tracker').first()
        if latest and (timezone.now() - latest.dt_tracker) < timedelta(hours=12):
            return
        # Drop a point near Addis
        base_lat, base_lng = 8.9806, 38.7578
        lat, lng = self._jitter(base_lat, base_lng, km=20)
        GPSRecord.objects.create(
            truck=truck,
            imei=f'DEMO-IMEI-{truck.plate_number}',
            name=truck.plate_number,
            group='DEMO',
            odometer=Decimal(truck.mileage_km or 0),
            engine=random.choice(['on','off']),
            status=random.choice(['moving','idle']),
            dt_server=timezone.now(),
            dt_tracker=timezone.now(),
            lat=Decimal(str(round(lat,6))),
            lng=Decimal(str(round(lng,6))),
            loc='Demo snapshot',
            nearset_zone=None,
            altitude=Decimal('0.00'),
            angle=random.randint(0,359),
            speed=Decimal(random.choice([0, 0, 20, 35, 50])),
            fuel_1=Decimal(random.randint(10, 80)),
            fuel_2=Decimal(random.randint(0, 50)),
            fuel_can_level_percent=None,
            fuel_can_level_value=None,
            params={"src": "seed_demo"},
            custom_fields=None,
        )
