from django.core.management.base import BaseCommand

from WareDGT.models import SeedTypeDetail, Warehouse


SEED_TYPES = [
    {
        "name": "Whitish Humera/Gonder Sesame Seed",
        "delivery_code": "HUMERA",
        "symbol": "WHGSS",
        "grade": "1,2,3,4,UG",
        "origin": "Kafta Humera, Wolkait, Asgede Tsimbila, Tahtay Adiyabo, Tsedegie, West Armachiho (Abderafi, Abreha Jira, Korhumer), and surroundings.",
    },
    {
        "name": "Whitish Humera/Gonder Sesame Seed",
        "delivery_code": "METEMA",
        "symbol": "WHGSS",
        "grade": "1,2,3,4,UG",
        "origin": "Metema, Quara and surroundings.",
    },
    {
        "name": "Whitish Humera/Gonder Sesame Seed",
        "delivery_code": "GONDAR",
        "symbol": "WHGSS",
        "grade": "1,2,3,4,UG",
        "origin": "Tach Armachiho, Tsedegie, West Armachiho (Zemene Merik, Meharish) and surroundings.",
    },
    {
        "name": "Mixed Humera/Gonder Sesame Seed",
        "delivery_code": "HUMERA",
        "symbol": "MHGS",
        "grade": "1,2,3,4,UG",
        "origin": "Kafta Humera, Wolkait, Asgede Tsimbila, Tahtay Adiyabo, Tsedegie, West Armachiho (Abderafi, Abreha Jira, Korhumer), and surroundings.",
    },
    {
        "name": "Mixed Humera/Gonder Sesame Seed",
        "delivery_code": "METEMA",
        "symbol": "MHGS",
        "grade": "1,2,3,4,UG",
        "origin": "Metema, Quara and surroundings.",
    },
    {
        "name": "Mixed Humera/Gonder Sesame Seed",
        "delivery_code": "GONDAR",
        "symbol": "MHGS",
        "grade": "1,2,3,4,UG",
        "origin": "Tach Armachiho, Tsedegie, West Armachiho (Zemene Merik, Meharish) and surroundings.",
    },
    {
        "name": "Whitish Wollega Sesame Seed",
        "delivery_code": "ASSOSSA",
        "symbol": "WWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Adabuldeglu, Sirba Abay, Mao Komo, Bambasi, Assossa, Sherkole, Homsha, Mengie, Kumruk, Kamashi, Agelo Meti, Yaso, and surroundings.",
    },
    {
        "name": "Whitish Wollega Sesame Seed",
        "delivery_code": "BURE",
        "symbol": "WWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Bulen, Pawe, Dibate, Dangur, Mandura, Wonbera, Guba and surroundings.",
    },
    {
        "name": "Whitish Wollega Sesame Seed",
        "delivery_code": "NEKEMTE",
        "symbol": "WWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Bologe Genfoy, Kelem Wollega, West Wollega, East Wollega, Horo Gudru Wollega, Illubabor, Jimma and surroundings.",
    },
    {
        "name": "Whitish Wollega Sesame Seed",
        "delivery_code": "ADDIS-ABABA-SARIS",
        "symbol": "WWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Southern Nations and Nationalities People Region (SNNP), Gambella Region.",
    },
    {
        "name": "Mixed Wollega Sesame Seed",
        "delivery_code": "ASSOSSA",
        "symbol": "MWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Adabuldeglu, Sirba Abay, Mao Komo, Bambasi, Assossa, Sherkole, Homsha, Mengie, Kumruk, Kamashi, Agelo Meti, Yaso, and surroundings.",
    },
    {
        "name": "Mixed Wollega Sesame Seed",
        "delivery_code": "BURE",
        "symbol": "MWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Bulen, Pawe, Dibate, Dangur, Mandura, Wonbera, Guba and surroundings.",
    },
    {
        "name": "Mixed Wollega Sesame Seed",
        "delivery_code": "NEKEMTE",
        "symbol": "MWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Bologe Genfoy, Kelem Wollega, West Wollega, East Wollega, Horo Gudru Wollega, Illubabor, Jimma and surroundings.",
    },
    {
        "name": "Mixed Wollega Sesame Seed",
        "delivery_code": "ADDIS-ABABA-SARIS",
        "symbol": "MWSS",
        "grade": "1,2,3,4,5,UG",
        "origin": "Southern Nations and Nationalities People Region (SNNP), Gambella Region.",
    },
    {
        "name": "Reddish Sesame Seed",
        "delivery_code": "ADDIS-ABABA-SARIS",
        "symbol": "RDSS",
        "grade": "1,2,3,4,UG",
        "origin": "Dessie, Belessa, Kemissie, and surroundings.",
    },
    {
        "name": "Mixed Reddish Sesame Seed",
        "delivery_code": "ADDIS-ABABA-SARIS",
        "symbol": "MRSS",
        "grade": "1,2,3,4,UG",
        "origin": "Dessie, Belessa, Kemissie, and surroundings.",
    },
]

PROCEDURE_NOTE = (
    "Sesame Seeds shall have a good natural color, be free of live insects and "
    "visible mould, contain max 10% moisture by weight and comply with ECX "
    "grading tables."
)


class Command(BaseCommand):
    help = "Import predefined ECX seed types"

    def handle(self, *args, **options):
        for data in SEED_TYPES:
            try:
                warehouse = Warehouse.objects.get(code=data["delivery_code"])
            except Warehouse.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(
                        f"Warehouse {data['delivery_code']} not found; skipping"
                    )
                )
                continue
            obj, created = SeedTypeDetail.objects.update_or_create(
                symbol=data["symbol"],
                delivery_location=warehouse,
                defaults={
                    "name": data["name"],
                    "grade": data["grade"],
                    "origin": data["origin"],
                    "handling_procedure": PROCEDURE_NOTE,
                },
            )
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} {obj.symbol}")
