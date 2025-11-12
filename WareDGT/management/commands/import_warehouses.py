from decimal import Decimal
import re
from urllib.parse import urlparse, unquote_plus

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from WareDGT.models import Warehouse

# ── Existing ECX markers (unchanged list) ─────────────────────────────────────
WAREHOUSE_MARKERS = [
    {
        "title": 'Addis Ababa(Saris)',
        "lat": '8.95003230',
        "lng": '38.76707410',
        "description": 'Addis Ababa(Saris) warehouse ideal capacity  300,000  Quintals Coffee ',
        "type": 'warehouse'
    },
    {
        "title": 'Dire Dawa',
        "lat": '9.60090000',
        "lng": '41.85010000',
        "description": 'Dire Dawa warehouse ideal capacity 58,000 Quintals  Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Dire Dawa',
        "lat": '9.60090000',
        "lng": '41.85010000',
        "description": 'Dire Dawa warehouse ideal capacity 58,000 Quintals  Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Adama (Nazareth)',
        "lat": '8.52630000',
        "lng": '39.25830000',
        "description": 'Adama (Nazreth) warehouse ideal capacity 50,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Bure',
        "lat": '10.70610500',
        "lng": '37.06686500',
        "description": 'Bure  warehouse ideal capacity 50,000 Quintals',
        "type": 'warehouse'
    },
    {
        "title": 'Nekemte',
        "lat": '9.08930000',
        "lng": '36.55540000',
        "description": 'Nekemte  warehouse ideal capacity 150,000 Quintals Coffee and Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Humera',
        "lat": '14.28040000',
        "lng": '36.61750000',
        "description": 'Humera  warehouse ideal capacity 350,000 Quintals Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Hawassa',
        "lat": '7.05040000',
        "lng": '38.49550000',
        "description": 'Hawassa  warehouse ideal capacity 350,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Jimma',
        "lat": '7.67390000',
        "lng": '36.83580000',
        "description": 'Jimma  warehouse ideal capacity 150,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Bedelle',
        "lat": '8.45410000',
        "lng": '36.35520000',
        "description": 'Bedelle  ideal capacity 100,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Dilla',
        "lat": '6.41260000',
        "lng": '38.30080000',
        "description": 'Dilla ideal capacity 115,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Gimbi',
        "lat": '9.18600000',
        "lng": '35.83340000',
        "description": 'Gimbi ideal capacity 165,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Gondar',
        "lat": '12.60300000',
        "lng": '37.45210000',
        "description": 'Gondar ideal capacity 200,000 Quintals Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Metema',
        "lat": '12.95450000',
        "lng": '36.15730000',
        "description": 'Metema  ideal capacity 240,000 Quintals Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Assossa',
        "lat": '10.06200000',
        "lng": '34.54730000',
        "description": 'Assossa  ideal capacity 50,000 Quintals Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Sodo',
        "lat": '6.85280000',
        "lng": '37.76100000',
        "description": 'Sodo  ideal capacity 60,000 Quintals Coffee and Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Bonga',
        "lat": '7.26719000',
        "lng": '36.24681300',
        "description": 'Bonga  ideal capacity 140,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Abrahajira',
        "lat": '13.00000000',
        "lng": '37.09600000',
        "description": 'Abrahajira ideal capacity 190,000 Quintals Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Dansha',
        "lat": '13.76640000',
        "lng": '36.98340000',
        "description": 'Dansha  ideal capacity 100,000 Quintals Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Shiraro',
        "lat": '14.39700000',
        "lng": '37.77430000',
        "description": 'Shiraro  ideal capacity 50,000 Quintals Sesame',
        "type": 'warehouse'
    },
    {
        "title": 'Pawe',
        "lat": '11.19600000',
        "lng": '36.19600000',
        "description": 'Pawe ideal capacity 320,000 Quintals Coffee',
        "type": 'warehouse'
    },
    {
        "title": 'Kombolcha',
        "lat": '11.08490000',
        "lng": '39.72920000',
        "description": 'Kombolcha  ideal capacity 100,000 Quintals Coffee, sesame, pea and beans',
        "type": 'warehouse'
    },
    {
        "title": 'Hawassa',
        "lat": '7.05040000',
        "lng": '38.49550000',
        "description": 'Hawassa  regional eTrading center ',
        "type": 'eTrade'
    },
    {
        "title": 'Humera',
        "lat": '14.28040000',
        "lng": '36.61750000',
        "description": 'Humera Regional eTrading Center',
        "type": 'eTrade'
    },
    {
        "title": 'Nekempt',
        "lat": '9.08930000',
        "lng": '36.55540000',
        "description": 'Nekempt Regional eTrading center ',
        "type": 'eTrade'
    },
    {
        "title": 'Nekempt',
        "lat": '9.08930000',
        "lng": '36.55540000',
        "description": 'Nekempt Regional eTrading center ',
        "type": 'eTrade'
    },
    {
        "title": 'Bule Hora',
        "lat": '5.63730000',
        "lng": '38.23750000',
        "description": 'Bule Hora Warehouse Ideal Capacity 300,000 Quintals',
        "type": 'warehouse'
    },
    {
        "title": 'Mettu',
        "lat": '8.29610000',
        "lng": '35.58220000',
        "description": 'Mettu  Warehouse ',
        "type": 'warehouse'
    },
]

CAPACITY_RE = re.compile(r"([\d,]+)\s*Quintals", re.IGNORECASE)

# ── Your DGT site (from Google Maps link) ─────────────────────────────────────
DGT_MAPS_URL = "https://www.google.com/maps/place/Desalegn+G%2FMariam+Trading+-+cleaning+plant+%E1%88%9B%E1%89%A0%E1%8C%A0%E1%88%AA%E1%8B%AB+%E1%89%A4%E1%89%B5/@8.9000591,38.7584797,110m/data=!3m1!1e3!4m6!3m5!1s0x164b830df35dc00f:0x84b6b30039c62e8f!8m2!3d8.9002407!4d38.7588279!16s%2Fg%2F11sssqrwq6?entry=ttu"
DGT_AREA_M2 = Decimal("2000")
DGT_LAT = Decimal("8.9002407")
DGT_LNG = Decimal("38.7588279")

def extract_name_from_maps(url: str) -> str:
    """
    Extract the place name from a Google Maps /place/<name>/@... URL.
    """
    try:
        path = urlparse(url).path  # e.g., '/maps/place/Desalegn+.../@8.9,...'
        if "/place/" in path:
            segment = path.split("/place/")[1]
            name_part = segment.split("/@")[0]
            return unquote_plus(name_part)
    except Exception:
        pass
    return "DGT Cleaning Plant"

def estimate_capacity_quintals(area_m2: Decimal,
                               stack_height_m: Decimal = Decimal("4.0"),
                               bulk_density_t_per_m3: Decimal = Decimal("0.60"),
                               utilization: Decimal = Decimal("0.70")) -> Decimal:
    """
    Estimate storage capacity from floor area.
    tons = area * height * density * utilization
    quintals = tons * 10
    """
    tons = area_m2 * stack_height_m * bulk_density_t_per_m3 * utilization
    return (tons * Decimal("10")).quantize(Decimal("1"))

class Command(BaseCommand):
    help = (
        "Import predefined warehouses: ECX markers + a primary local warehouse. "
        "Defaults to 'Alem International Warehouse' (type DGT). Use --site dgt to import the original DGT site."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--site",
            choices=["alem", "dgt"],
            default="alem",
            help="Which primary local warehouse to import: 'alem' (default) or 'dgt'.",
        )
        parser.add_argument(
            "--alem-name",
            default="Alem International Warehouse",
            help="Display name to use when --site=alem.",
        )

    def handle(self, *args, **options):
        site = options.get("site") or "alem"
        alem_name = options.get("alem_name") or "Alem International Warehouse"

        # 1) Create/Update the primary local warehouse (Alem by default)
        if site == "alem":
            name = alem_name
            code = slugify(name).upper()
            capacity = estimate_capacity_quintals(DGT_AREA_M2)
            # Reuse known coordinates for now; can be updated later via admin
            lat, lng = DGT_LAT, DGT_LNG
            obj, created = Warehouse.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "description": f"{name} • Imported as primary local warehouse",
                    "warehouse_type": Warehouse.DGT,
                    "capacity_quintals": capacity,
                    "latitude": lat,
                    "longitude": lng,
                },
            )
            tag = "ALEM"
        else:
            dgt_name = extract_name_from_maps(DGT_MAPS_URL)
            code = slugify(dgt_name).upper()
            capacity = estimate_capacity_quintals(DGT_AREA_M2)
            obj, created = Warehouse.objects.update_or_create(
                code=code,
                defaults={
                    "name": dgt_name,
                    "description": f"{dgt_name} • Imported from Google Maps • Estimated from ~{DGT_AREA_M2} m²",
                    "warehouse_type": Warehouse.DGT,
                    "capacity_quintals": capacity,
                    "latitude": DGT_LAT,
                    "longitude": DGT_LNG,
                },
            )
            tag = "DGT"

        if created:
            self.stdout.write(self.style.SUCCESS(f"[{tag}] Created {obj.code} ({capacity} quintals est.)"))
        else:
            self.stdout.write(self.style.WARNING(f"[{tag}] Updated {obj.code} ({capacity} quintals est.)"))

        # 2) Import ECX warehouses from the marker list (skip non-warehouses)
        for marker in WAREHOUSE_MARKERS:
            if marker.get("type") != "warehouse":
                continue
            code = slugify(marker["title"]).upper()
            capacity = self._parse_capacity(marker.get("description", ""))
            obj, created = Warehouse.objects.get_or_create(
                code=code,
                defaults={
                    "name": marker["title"],
                    "description": marker.get("description", ""),
                    "warehouse_type": Warehouse.ECX,  # ECX for all existing markers
                    "capacity_quintals": capacity,
                    "latitude": Decimal(marker["lat"]),
                    "longitude": Decimal(marker["lng"]),
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"[ECX] Created {obj.code}"))
            else:
                self.stdout.write(f"[ECX] Skipped existing {obj.code}")

    def _parse_capacity(self, description: str) -> Decimal:
        match = CAPACITY_RE.search(description or "")
        if match:
            return Decimal(match.group(1).replace(",", ""))
        return Decimal("0")
