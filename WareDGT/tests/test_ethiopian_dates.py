from datetime import date
from WareDGT.utils.ethiopian_dates import (
    to_ethiopian_date_str,
    amharic_day_name,
    to_ethiopian_date_str_en,
)


def test_amharic_day_name():
    assert amharic_day_name(date(2024, 12, 25)) == "ረቡዕ"


def test_to_ethiopian_date_str():
    assert to_ethiopian_date_str(date(2024, 12, 25)) == "ረቡዕ 16 ታህሳስ 2017"


def test_to_ethiopian_date_str_pagumen_fallback():
    # 2025-09-07 corresponds to Pagumen (13th month) which triggers the
    # fallback to the Gregorian calendar.
    assert to_ethiopian_date_str(date(2025, 9, 7)) == "እሑድ 7 September 2025"


def test_to_ethiopian_date_str_en():
    assert to_ethiopian_date_str_en(date(2024, 12, 25)) == "Wednesday 16 Tahsas 2017"


def test_to_ethiopian_date_str_en_pagumen_fallback():
    assert to_ethiopian_date_str_en(date(2025, 9, 7)) == "Sunday 7 September 2025"
