import requests
import json
from datetime import datetime
from decimal import Decimal
import logging

from django.utils import timezone
from django.conf import settings
from math import radians, cos, sin, asin, sqrt

from celery import shared_task
from .models import Truck, GPSRecord, Staff, Trip  # Ensure Trip is imported if needed

logger = logging.getLogger(__name__)

def fetch_user_objects():
    """
    Makes an API call to the external GPS endpoint and returns the JSON data.
    """
    url = getattr(settings, 'GPS_API_URL',
                 'https://gps.mellatech.com/mct/api/api.php?api=user&ver=1.0&key=705BDE554443930C7297FEB59B4C3465&cmd=USER_GET_OBJECTS')
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()  # Raises an HTTPError if the response was unsuccessful.
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching GPS data: {e}")
        return None

def process_gps_data(data):
    """
    Processes a list of GPS records from the API.
    For each record:
      - Checks if the new lat/lng/loc differs from the last known GPSRecord for the same truck.
      - Creates a new GPSRecord only if it differs (to avoid duplicates).
      - If the truck has an in-progress Trip, also append the new location info (lat, lng, loc) to trip.route
        if that route’s last point differs.
    
    Returns the number of records successfully created.
    """
    records = data if isinstance(data, list) else [data]
    created_count = 0

    def haversine_m(lat1, lon1, lat2, lon2):
        """Return distance in meters between two WGS84 coords."""
        # convert decimal degrees to radians
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
        lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
        # haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * asin(sqrt(a))
        km = 6371.0 * c
        return km * 1000.0

    MIN_MOVE_M = 20.0  # ignore jitter within 20 meters

    for record in records:
        plate = record.get("name")
        if not plate:
            logger.info("Record skipped: no 'name' (truck plate) provided.")
            continue

        try:
            truck = Truck.objects.get(plate_number=plate)
        except Truck.DoesNotExist:
            logger.info(f"Truck with plate number '{plate}' not found. Skipping record.")
            continue

        try:
            dt_server_raw = record.get("dt_server")
            dt_tracker_raw = record.get("dt_tracker")
            dt_server = datetime.strptime(dt_server_raw, "%Y-%m-%d %H:%M:%S") if dt_server_raw else timezone.now()
            dt_tracker = datetime.strptime(dt_tracker_raw, "%Y-%m-%d %H:%M:%S") if dt_tracker_raw else dt_server

            # Ensure timestamps are timezone-aware so downstream consumers
            # (map playback, analytics) receive consistent ISO strings.
            default_tz = timezone.get_default_timezone()
            if timezone.is_naive(dt_server):
                dt_server = timezone.make_aware(dt_server, default_tz)
            if timezone.is_naive(dt_tracker):
                dt_tracker = timezone.make_aware(dt_tracker, default_tz)
        except Exception as e:
            logger.error(f"Error parsing dates for truck {plate}: {e}")
            continue

        new_lat = Decimal(record.get("lat", "0"))
        new_lng = Decimal(record.get("lng", "0"))
        new_loc = record.get("loc", "")

        last_gps = GPSRecord.objects.filter(truck=truck).order_by('-dt_tracker').first()
        if last_gps and (last_gps.lat == new_lat and last_gps.lng == new_lng and last_gps.loc == new_loc):
            logger.info(f"No location change for '{plate}'. Skipping new record.")
            continue

        try:
            gps_record = GPSRecord.objects.create(
                truck=truck,
                imei=record.get("imei", ""),
                name=plate,
                group=record.get("group"),
                odometer=Decimal(record.get("odometer", "0")),
                engine=record.get("engine", ""),
                status=record.get("status", ""),
                dt_server=dt_server,
                dt_tracker=dt_tracker,
                lat=new_lat,
                lng=new_lng,
                loc=new_loc,
                nearset_zone=record.get("nearset_zone", ""),
                altitude=Decimal(record.get("altitude", "0")),
                angle=int(record.get("angle", "0")),
                speed=Decimal(record.get("speed", "0")),
                fuel_1=Decimal(record.get("fuel_1", "0")),
                fuel_2=Decimal(record.get("fuel_2", "0")),
                fuel_can_level_percent=(Decimal(record.get("fuel_can_level_percent", "0"))
                                        if record.get("fuel_can_level_percent") is not None else None),
                fuel_can_level_value=(Decimal(record.get("fuel_can_level_value", "0"))
                                      if record.get("fuel_can_level_value") is not None else None),
                params=record.get("params", {}),
                custom_fields=record.get("custom_fields", []),
            )
            created_count += 1
            logger.info(f"Created new GPSRecord for {plate} at {new_loc}")
        except Exception as e:
            logger.error(f"Error saving GPSRecord for truck {plate}: {e}")
            continue

        active_trip = Trip.objects.filter(
            truck=truck,
            status=Trip.STATUS_IN_PROGRESS
        ).order_by('-id').first()

        if active_trip:
            route_list = active_trip.route or []
            if route_list:
                last_point = route_list[-1]
                try:
                    last_lat = float(last_point.get("lat", 0.0))
                    last_lng = float(last_point.get("lng", 0.0))
                except Exception:
                    last_lat = last_lng = 0.0

                moved_m = haversine_m(last_lat, last_lng, float(new_lat), float(new_lng))

                # Append only if the truck moved meaningfully or if the last timestamp is very old
                last_ts = last_point.get("timestamp")
                age_s = None
                if last_ts:
                    try:
                        # Parse ISO timestamp robustly
                        from datetime import datetime as _dt
                        last_dt = _dt.fromisoformat(str(last_ts).replace('Z', '+00:00'))
                        age_s = abs((dt_tracker - last_dt).total_seconds())
                    except Exception:
                        age_s = None

                should_append = moved_m >= MIN_MOVE_M or (age_s is not None and age_s >= 300)

                if should_append:
                    route_list.append({
                        "lat": float(new_lat),
                        "lng": float(new_lng),
                        "loc": new_loc,
                        "timestamp": dt_tracker.isoformat(),
                    })
                    active_trip.route = route_list
                    active_trip.save(update_fields=["route"])
                    logger.info(f"Trip #{active_trip.pk} updated route (Δ≈{moved_m:.1f} m) @ {new_loc}")
                else:
                    logger.info(f"Trip #{active_trip.pk} jitter filtered (Δ≈{moved_m:.1f} m), not appending route")
            else:
                active_trip.route = [{
                    "lat": float(new_lat),
                    "lng": float(new_lng),
                    "loc": new_loc,
                    "timestamp": dt_tracker.isoformat(),
                }]
                active_trip.save(update_fields=["route"])
                logger.info(f"Trip #{active_trip.pk} started route @ {new_loc}")

    return created_count

def update_gps_records_sync():
    """Synchronous updater used by views and CLI.

    Fetches from the configured GPS API URL and processes records inline
    so callers immediately see updated locations without requiring a
    running Celery worker.
    """
    logger.info("Starting GPS update (sync)...")
    data = fetch_user_objects()
    if not data:
        logger.info("update_gps_records_sync: No data fetched from the GPS API.")
        return 0
    created_count = process_gps_data(data)
    logger.info(f"update_gps_records_sync: Created {created_count} GPS records.")
    return created_count


@shared_task
def update_gps_records():
    """Celery task wrapper around the synchronous updater."""
    return update_gps_records_sync()
