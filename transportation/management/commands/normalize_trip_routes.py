from django.core.management.base import BaseCommand
from transportation.models import Trip


class Command(BaseCommand):
    help = (
        "Normalize trip.route by sorting points by timestamp (ascending) "
        "with original order as tiebreaker, and dropping consecutive duplicates."
    )

    def add_arguments(self, parser):
        parser.add_argument('--trip', type=int, help='Trip ID to normalize (optional)')

    def handle(self, *args, **options):
        trip_id = options.get('trip')
        qs = Trip.objects.all()
        if trip_id:
            qs = qs.filter(pk=trip_id)

        total = 0
        fixed = 0
        for trip in qs.iterator():
            total += 1
            route = list(trip.route or [])
            if len(route) < 2:
                continue

            cleaned = []
            # normalize + keep original index
            for idx, p in enumerate(route):
                try:
                    lat = float(p.get('lat'))
                    lng = float(p.get('lng'))
                except Exception:
                    continue
                cleaned.append({
                    'lat': lat,
                    'lng': lng,
                    'loc': p.get('loc') or '',
                    'timestamp': p.get('timestamp'),
                    '_i': idx,
                })

            if len(cleaned) < 2:
                continue

            def sort_key(p):
                t = p.get('timestamp')
                if t:
                    try:
                        from datetime import datetime as _dt
                        return (0, _dt.fromisoformat(str(t).replace('Z', '+00:00')), p['_i'])
                    except Exception:
                        pass
                return (1, p['_i'], p['_i'])

            cleaned.sort(key=sort_key)

            # drop consecutive duplicates within ~1m (approx by lat/lng threshold)
            deduped = []
            last_lat = last_lng = None
            for p in cleaned:
                if last_lat is not None:
                    if abs(p['lat'] - last_lat) < 1e-5 and abs(p['lng'] - last_lng) < 1e-5:
                        continue
                deduped.append({k: v for k, v in p.items() if k != '_i'})
                last_lat, last_lng = p['lat'], p['lng']

            if deduped != trip.route:
                trip.route = deduped
                trip.save(update_fields=['route'])
                fixed += 1
                self.stdout.write(self.style.SUCCESS(f"Normalized trip #{trip.pk} (points: {len(route)} -> {len(deduped)})"))

        self.stdout.write(self.style.NOTICE(f"Processed {total} trip(s). Updated {fixed} trip(s)."))

