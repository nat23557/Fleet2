from django.core.management.base import BaseCommand
from django.utils.text import slugify

from WareDGT.models import SeedTypeDetail, Warehouse

# Dataset of coffee seed types and grades by delivery location
coffee_data = {
    "export_specialty_washed": [
        {"Coffee Contract":"YIRGACHEFE A*","Origin":"Yirgachefe","Symbol":"WYCA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"WENAGO A*","Origin":"Wenago","Symbol":"WWNA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"KOCHERE A*","Origin":"Kochere","Symbol":"WKCA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"GELENA ABAYA A*","Origin":"Gelena/Abaya","Symbol":"WGAA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"YIRGACHEFE B**","Origin":"Yirgachefe","Symbol":"WYCB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"WENAGO B**","Origin":"Wenago","Symbol":"WWNB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"KOCHERE B**","Origin":"Kochere","Symbol":"WKCB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"GELENA ABAYA B**","Origin":"Gelena/Abaya","Symbol":"WGAB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"SIDAMA A","Origin":"Borena (except Gelena/Abaya), Benssa, Guji, Chire, Bona zuria, Arroressa, Arbigona","Symbol":"WSDA","Grades":["Q1","Q2"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA B","Origin":"Aleta Wendo, Dale, Chuko, Dara, Shebedino, Wensho, Loko Abaya, Amaro, Dilla zuria","Symbol":"WSDB","Grades":["Q1","Q2"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA C","Origin":"Kembata & Timbaro, Wollaita","Symbol":"WSDC","Grades":["Q1","Q2"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"SIDAMA D","Origin":"W. Arsi (Nansebo), Arsi (Chole), Bale","Symbol":"WSDD","Grades":["Q1","Q2"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA E","Origin":"S. Omo, Gamogoffa","Symbol":"WSDE","Grades":["Q1","Q2"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"LIMMU A","Origin":"Limmu Seka, Limmu Kossa, Manna, Gomma, Gummay, Seka Chekoressa, Kersa, Shebe, Gera","Symbol":"WLMA","Grades":["Q1","Q2"],"Delivery Centre":"Jimma"},
        {"Coffee Contract":"LIMMU B","Origin":"Bedelle, Noppa, Chorra, Yayo, Alle, Didu, Dedessa","Symbol":"WLMB","Grades":["Q1","Q2"],"Delivery Centre":"Bedelle"},
        {"Coffee Contract":"KAFFA","Origin":"Gimbo, Gewata, Chena","Symbol":"WKF","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"GODERE","Origin":"Mezenger (Godere)","Symbol":"WGD","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"YEKI","Origin":"Yeki","Symbol":"WYK","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"ANDERACHA","Origin":"Anderacha","Symbol":"WAN","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"BENCH MAJI","Origin":"Sheko, S.Bench, N.Bench, Gura ferda, Bero","Symbol":"WBM","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"BEBEKA","Origin":"Bebeka","Symbol":"WBB","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"KELEM WELEGA","Origin":"Kelem Wollega","Symbol":"WKW","Grades":["Q1","Q2"],"Delivery Centre":"Gimbi"},
        {"Coffee Contract":"EAST WELLEGA","Origin":"East Wollega","Symbol":"WEW","Grades":["Q1","Q2"],"Delivery Centre":"Gimbi"},
        {"Coffee Contract":"GIMBI","Origin":"West Wollega","Symbol":"WGM","Grades":["Q1","Q2"],"Delivery Centre":"Gimbi"}
    ],
    "export_commercial_washed": [
        {"Coffee Contract":"YIRGACHEFE A*","Origin":"Yirgachefe, Wenago, Kochere and Gelena Abaya","Symbol":"WYCA","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"YIRGACHEFE B**","Origin":"Yirgachefe, Wenago, Kochere and Gelena Abaya","Symbol":"WYCB","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"SIDAMA A","Origin":"Borena (except Gelena/Abaya), Benssa, Guji, Chire, Bona Zuria, Arroressa, Arbigna, Bale Arsi and W. Arsi","Symbol":"WSDA","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA B","Origin":"Aleta Wendo, Dale, Chiko, Dara, Shebedino, Amaro, Dilla zuria, Wensho and Loko Abaya","Symbol":"WSDB","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA C","Origin":"Kembata & Timbaro, Wellayta, S. Omo and Gamogoffa","Symbol":"WSDC","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"LIMMU A","Origin":"Limmu Seka, Limmu Kossa, Manna, Gomma, Gummay, Seka Chekoressa, Kersa, Shebe and Gera","Symbol":"WLMA","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Jimma"},
        {"Coffee Contract":"LIMMU B","Origin":"Bedelle, Noppa, Chorra, Yayo, Alle, Didu Dedessa","Symbol":"WLMB","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Bedelle"},
        {"Coffee Contract":"KAFFA","Origin":"Gimbo, Gewata, Chena","Symbol":"WKF","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"TEPI","Origin":"Mezenger (Godere) and Sheka","Symbol":"WTP","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"BEBEKA","Origin":"Bench Maji","Symbol":"WBB","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"LEKEMPTI","Origin":"Kelem, East and West Wollega","Symbol":"WLK","Grades":["3 TO 9","UG(p)","UG(np)"],"Delivery Centre":"Gimbi"}
    ],
    "export_specialty_unwashed": [
        {"Coffee Contract":"YIRGACHEFE A*","Origin":"Yirgachefe","Symbol":"UYCA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"WENAGO A*","Origin":"Wenago","Symbol":"UWNA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"KOCHERE A*","Origin":"Kochere","Symbol":"UKCA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"GELENA ABAYA A*","Origin":"Gelena/Abaya","Symbol":"UGAA","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"YIRGACHEFE B**","Origin":"Yirgachefe","Symbol":"UYCB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"WENAGO B**","Origin":"Wenago","Symbol":"UWNB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"KOCHERE B**","Origin":"Kochere","Symbol":"UKCB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"GELENA ABAYA B**","Origin":"Gelena/Abaya","Symbol":"UGAB","Grades":["Q1","Q2"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"SIDAMA A","Origin":"Borena (except Gelena/Abaya), Benssa, Guji, Arroressa, Arbigna, Chire, Bona Zuria","Symbol":"USDA","Grades":["Q1","Q2"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA B","Origin":"Aleta Wendo, Dale, Chuko, Dara, Shebedino, Wensho, Loko Abaya, Amaro, Dilla zuria","Symbol":"USDB","Grades":["Q1","Q2"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA C","Origin":"Kembata & Timbaro, Wollaita","Symbol":"USDC","Grades":["Q1","Q2"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"SIDAMA D","Origin":"Bale, W Arsi (Nansebo), Arsi (Chole)","Symbol":"USDD","Grades":["Q1","Q2"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA E","Origin":"S. Ari, N. Ari, Melo, Denba Gofa, Geze Gofa, Arbaminch Zuria, Basketo, Derashe, Konso, Konta, Gena Bosa, Esera","Symbol":"USDE","Grades":["Q1","Q2"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"JIMMA A","Origin":"Yeki, Anderacha, Sheko, S.Bench, N.Bench, Gura ferda, Bero","Symbol":"UJMA","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"JIMMA B","Origin":"Bedelle, Noppa, Chorra, Yayo, Alle, Didu Dedessa","Symbol":"UJMB","Grades":["Q1","Q2"],"Delivery Centre":"Bedelle"},
        {"Coffee Contract":"HARAR A","Origin":"E.Harar, Gemechisa, Debesso, Gerawa, Gewgew, Dire Dawa Zuria","Symbol":"UHRA","Grades":["Q1","Q2"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"HARAR B","Origin":"W.Hararhe (except Hirna, Gemechisa, Debesso, Messela and Gewgew)","Symbol":"UHRB","Grades":["Q1","Q2"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"HARAR C","Origin":"Arssi Golgolcha","Symbol":"UHRC","Grades":["Q1","Q2"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"HARAR D","Origin":"Bale (Berbere and Delomena)","Symbol":"UHRD","Grades":["Q1","Q2"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"HARAR E","Origin":"Hirna, Messela","Symbol":"UHRE","Grades":["Q1","Q2"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"KELEM WOLLEGA","Origin":"Kelem Wollega","Symbol":"UKW","Grades":["Q1","Q2"],"Delivery Centre":"Gimbi"},
        {"Coffee Contract":"EAST WOLLEGA","Origin":"East Wollega","Symbol":"UEW","Grades":["Q1","Q2"],"Delivery Centre":"Gimbi"},
        {"Coffee Contract":"GIMBI","Origin":"West Wollega","Symbol":"UGM","Grades":["Q1","Q2"],"Delivery Centre":"Gimbi"},
        {"Coffee Contract":"FOREST A","Origin":"Yeki, Anderacha, Sheko, S.Bench, N.Bench, Gura ferda, Bero, Godere, Gembo, Gewata, Chena","Symbol":"UFRA","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"FOREST B","Origin":"S.Ari, N.Ari, Melo, Denba Gofa, Geze Gofa, Arbaminch Zuria, Basketo, Derashe, Konso, Konta, Gena Bosa, Esera","Symbol":"UFRB","Grades":["Q1","Q2"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"BENCH MAJI","Origin":"Yeki, Anderacha, Sheko, S.Bench, N.Bench, Gura ferda, Bero","Symbol":"UBM","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"KAFFA","Origin":"Gembo, Gewata, Chena","Symbol":"UKF","Grades":["Q1","Q2"],"Delivery Centre":"Bonga"}
    ],
    "export_commercial_unwashed": [
        {"Coffee Contract":"YIRGACHEFE A*","Origin":"Yirgachefe, Wenago, Kochere and Gelena Abaya","Symbol":"UYCA","Grades":["3 TO 9","UG"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"YIRGACHEFE B**","Origin":"Yirgachefe, Wenago, Kochere and Gelena Abaya","Symbol":"UYCB","Grades":["3 TO 9","UG"],"Delivery Centre":"Dilla"},
        {"Coffee Contract":"JIMMA A","Origin":"Limmu Seka, Limmu Kossa, Manna, Gomma, Gummay, Seka Chekoressa, Kersa, Shebe and Gera","Symbol":"UJMA","Grades":["3 TO 9","UG"],"Delivery Centre":"Jimma"},
        {"Coffee Contract":"JIMMA B","Origin":"Bedelle, Noppa, Chorra, Yayo, Alle, Didu Dedessa","Symbol":"UJMB","Grades":["3 TO 9","UG"],"Delivery Centre":"Bedelle"},
        {"Coffee Contract":"SIDAMA A","Origin":"Borena (except Gelena/Abaya), Benssa, Guji, Arbigna, Chire, Bona Zuria and Arroressa","Symbol":"USDA","Grades":["3 TO 9","UG"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA B","Origin":"Aleta Wendo, Dale, Chiko, Dara, Shebedino, Amaro, Wensho, Loko Abaya","Symbol":"USDB","Grades":["3 TO 9","UG"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA C","Origin":"Kembata & Timbaro, Wellayta","Symbol":"USDC","Grades":["3 TO 9","UG"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"SIDAMA D","Origin":"Bale, W Arsi (Nansebo), Arsi (Chole)","Symbol":"USDD","Grades":["3 TO 9","UG"],"Delivery Centre":"Hawassa"},
        {"Coffee Contract":"SIDAMA E","Origin":"Debub Omo, Gamo Gofa, Basketo, Derashe, Konso, Konta, Dawro","Symbol":"USDE","Grades":["3 TO 9","UG"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"HARAR A","Origin":"E. Harar, Hirna, Gemechisa, Debesso, Messela, Gerawa, Gewgew and Dire Dawa Zuria","Symbol":"UHRA","Grades":["3 TO 9","UG"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"HARAR B","Origin":"W. Harar (except Hirna, Gemechisa, Debesso, Messela and Gewgew)","Symbol":"UHRB","Grades":["3 TO 9","UG"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"HARAR C","Origin":"Arssi Golgolcha","Symbol":"UHRC","Grades":["3 TO 9","UG"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"HARAR D","Origin":"Bale (Berbere and Delomena)","Symbol":"UHRD","Grades":["3 TO 9","UG"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"NEKEMPTI","Origin":"East and West Wollega and Kelem","Symbol":"ULK","Grades":["3 TO 9","UG"],"Delivery Centre":"Gimbi"},
        {"Coffee Contract":"FOREST A","Origin":"Sheka zone, Bench Maji zone, Mezenger zone and Kaffa zone","Symbol":"UFRA","Grades":["3 TO 9","UG"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"FOREST B","Origin":"Debub Omo, Gamo Gofa, Basketo, Derashe, Konso, Konta, Dawro","Symbol":"UFRB","Grades":["3 TO 9","UG"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"BENCH MAJI","Origin":"Yeki, Anderacha, Sheko, S.Bench, N.Bench, Gura ferda, Bero","Symbol":"UBM","Grades":["3 TO 9","UG"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"KAFFA","Origin":"Gembo, Gewata, Chena","Symbol":"UKF","Grades":["3 TO 9","UG"],"Delivery Centre":"Bonga"}
    ],
    "local_washed": [
        {"Coffee Contract":"SIDAMA","Symbol":"LWSD","Grades":["1 TO 4"],"Delivery Centre":"Hawasa"},
        {"Coffee Contract":"JIMMA","Symbol":"LWJM","Grades":["1 TO 4"],"Delivery Centre":"Jimma"},
        {"Coffee Contract":"FOREST A","Symbol":"LWFRA","Grades":["1 TO 4"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"FOREST B","Symbol":"LWFRB","Grades":["1 TO 4"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"BY PRODUCT","Symbol":"LWBP","Grades":["1 TO 4"],"Delivery Centre":"Addis Ababa"}
    ],
    "local_unwashed": [
        {"Coffee Contract":"SIDAMA","Symbol":"LUSD","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Awasa"},
        {"Coffee Contract":"JIMMA","Symbol":"LUJM","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Jimma"},
        {"Coffee Contract":"WOLLEGA","Symbol":"LUWL","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Gimbi"},
        {"Coffee Contract":"FOREST A","Symbol":"LUFRA","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Bonga"},
        {"Coffee Contract":"FOREST B","Symbol":"LUFRB","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Soddo"},
        {"Coffee Contract":"HARAR","Symbol":"LUHR","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Dire Dawa"},
        {"Coffee Contract":"BY PRODUCT- Addis","Symbol":"LUBPAA","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Addis Ababa"},
        {"Coffee Contract":"BY PRODUCT- Dire Dawa","Symbol":"LUBPDD","Grades":["1 TO 4","5A","5B","5C"],"Delivery Centre":"Dire Dawa"}
    ]
}

class Command(BaseCommand):
    help = "Import coffee seed type details"

    def handle(self, *args, **options):
        corrections = {
            "AWASA": "HAWASSA",
            "HAWASA": "HAWASSA",
            "ADDIS-ABABA": "ADDIS-ABABA-SARIS",
            "SODDO": "SODO",
        }

        for coffee_type, table in coffee_data.items():
            for row in table:
                warehouse_code = slugify(row["Delivery Centre"]).upper()
                warehouse_code = corrections.get(warehouse_code, warehouse_code)
                try:
                    warehouse = Warehouse.objects.get(code=warehouse_code)
                except Warehouse.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f"Warehouse {warehouse_code} not found; skipping"))
                    continue
                obj, created = SeedTypeDetail.objects.update_or_create(
                    symbol=row["Symbol"],
                    delivery_location=warehouse,
                    defaults={
                        "name": row.get("Coffee Contract", row["Symbol"]),
                        "grade": ",".join(row.get("Grades", [])),
                        "origin": row.get("Origin", ""),
                        "handling_procedure": "",
                        "category": SeedTypeDetail.COFFEE,
                        "coffee_type": coffee_type.upper(),
                    },
                )
                action = "Created" if created else "Updated"
                self.stdout.write(f"{action} {obj.symbol} -> {warehouse.code}")

