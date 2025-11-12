from django.core.management.base import BaseCommand
from django.utils.text import slugify

from WareDGT.models import SeedTypeDetail, Warehouse

pea_beans_contracts = [
    {
        "Class": "Round White Pea beans A",
        "Delivery Location": "Addis Ababa (AA)",
        "Symbol": "RWPA",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "All areas except those listed under Adama",
    },
    {
        "Class": "Round White Pea beans A",
        "Delivery Location": "Adama (AD)",
        "Symbol": "RWPA",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "East Harergie, West Harergie, East Shewa, Aris, West Arsi",
    },
    {
        "Class": "Round White Pea Beans B",
        "Delivery Location": "Addis Ababa (AA)",
        "Symbol": "RWPB",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "All areas except those listed under Adama",
    },
    {
        "Class": "Round White Pea Beans B",
        "Delivery Location": "Adama (AD)",
        "Symbol": "RWPB",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "East Harergie, West Harergie, East Shewa, Aris, West Arsi",
    },
    {
        "Class": "Round White Pea beans C",
        "Delivery Location": "Addis Ababa (AA)",
        "Symbol": "RWPC",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "All areas except those listed under Adama",
    },
    {
        "Class": "Round White Pea beans C",
        "Delivery Location": "Adama (AD)",
        "Symbol": "RWPC",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "East Harergie, West Harergie, East Shewa, Aris, West Arsi",
    },
    {
        "Class": "Flat White Pea beans A",
        "Delivery Location": "Addis Ababa (AA)",
        "Symbol": "FWPA",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "All areas except those listed under Adama",
    },
    {
        "Class": "Flat White Pea beans A",
        "Delivery Location": "Adama (AD)",
        "Symbol": "FWPA",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "East Harergie, West Harergie, East Shewa, Aris, West Arsi",
    },
    {
        "Class": "Flat White Pea Beans B",
        "Delivery Location": "Addis Ababa (AA)",
        "Symbol": "FWPB",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "All areas except those listed under Adama",
    },
    {
        "Class": "Flat White Pea Beans B",
        "Delivery Location": "Adama (AD)",
        "Symbol": "FWPB",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "East Harergie, West Harergie, East Shewa, Aris, West Arsi",
    },
    {
        "Class": "Flat White Pea beans C",
        "Delivery Location": "Addis Ababa (AA)",
        "Symbol": "FWPC",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "All areas except those listed under Adama",
    },
    {
        "Class": "Flat White Pea beans C",
        "Delivery Location": "Adama (AD)",
        "Symbol": "FWPC",
        "Grades": ["1", "2", "3", "4", "5", "LG"],
        "Origin": "East Harergie, West Harergie, East Shewa, Aris, West Arsi",
    },
]

class Command(BaseCommand):
    help = "Import pea bean seed type details"

    def handle(self, *args, **options):
        corrections = {
            "ADDIS-ABABA-AA": "ADDIS-ABABA-SARIS",
            "ADAMA-AD": "ADAMA-NAZARETH",
        }

        for row in pea_beans_contracts:
            warehouse_code = slugify(row["Delivery Location"]).upper()
            warehouse_code = corrections.get(warehouse_code, warehouse_code)
            try:
                warehouse = Warehouse.objects.get(code=warehouse_code)
            except Warehouse.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Warehouse {warehouse_code} not found; skipping")
                )
                continue
            obj, created = SeedTypeDetail.objects.update_or_create(
                symbol=row["Symbol"],
                delivery_location=warehouse,
                defaults={
                    "name": row["Class"],
                    "grade": ",".join(row.get("Grades", [])),
                    "origin": row.get("Origin", ""),
                    "handling_procedure": "",
                    "category": SeedTypeDetail.BEANS,
                },
            )
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} {obj.symbol} -> {warehouse.code}")

