from datetime import date, datetime
from ethiopian_date import EthiopianDateConverter

AMHARIC_DAY_NAMES = [
    "ሰኞ",
    "ማክሰኞ",
    "ረቡዕ",
    "ሐሙስ",
    "አርብ",
    "ቅዳሜ",
    "እሑድ",
]

# Transliterations of Ethiopian day names using the Latin alphabet. These are
# useful when the output needs to be readable by people who cannot read
# Amharic script – for example in generated PDF documents.
ENGLISH_DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

AMHARIC_MONTH_NAMES = [
    "",
    "መስከረም",
    "ጥቅምት",
    "ኅዳር",
    "ታህሳስ",
    "ጥር",
    "የካቲት",
    "መጋቢት",
    "ሚያዝያ",
    "ግንቦት",
    "ሰኔ",
    "ሐምሌ",
    "ነሐሴ",
    "ጳጉሜን",
]

# English transliterations of Ethiopian month names. The first element is a
# placeholder so the month numbers line up with list indices (Meskerem is
# month 1, Pagumen is month 13).
ENGLISH_MONTH_NAMES = [
    "",
    "Meskerem",
    "Tikimt",
    "Hidar",
    "Tahsas",
    "Tir",
    "Yekatit",
    "Megabit",
    "Miazia",
    "Ginbot",
    "Sene",
    "Hamle",
    "Nehase",
    "Pagumen",
]

def _convert(value: date) -> tuple[str, str, int, int]:
    """Return day name, month name, day number, year for an Ethiopian date.

    Parameters
    ----------
    value: date
        Gregorian date to convert.
    """
    try:
        eth = EthiopianDateConverter.date_to_ethiopian(value)
        day_name = AMHARIC_DAY_NAMES[value.weekday()]
        month_name = AMHARIC_MONTH_NAMES[eth.month]
        return day_name, month_name, eth.day, eth.year
    except ValueError:
        # ``ethiopian_date`` fails for Pagumen (month 13) because Python's
        # ``datetime.date`` does not accept a month value of 13. When this
        # happens we gracefully fall back to the Gregorian date.
        day_name = AMHARIC_DAY_NAMES[value.weekday()]
        month_name = value.strftime("%B")
        return day_name, month_name, value.day, value.year

def to_ethiopian_date_str(value: date | datetime) -> str:
    """Return a formatted Ethiopian date string in Amharic.

    Examples
    --------
    >>> to_ethiopian_date_str(date(2024, 12, 25))
    'ረቡዕ 16 ታህሳስ 2017'
    """
    if isinstance(value, datetime):
        d = value.date()
        time_part = value.strftime("%H:%M")
    else:
        d = value
        time_part = ""
    day_name, month_name, day, year = _convert(d)
    result = f"{day_name} {day} {month_name} {year}"
    if time_part:
        result = f"{result} {time_part}"
    return result


def to_ethiopian_date_str_en(value: date | datetime) -> str:
    """Return a formatted Ethiopian date string using English transliterations."""
    if isinstance(value, datetime):
        d = value.date()
        time_part = value.strftime("%H:%M")
    else:
        d = value
        time_part = ""
    try:
        eth = EthiopianDateConverter.date_to_ethiopian(d)
        day_name = ENGLISH_DAY_NAMES[d.weekday()]
        month_name = ENGLISH_MONTH_NAMES[eth.month]
        result = f"{day_name} {eth.day} {month_name} {eth.year}"
    except ValueError:
        # Fall back to the Gregorian calendar when the Ethiopian conversion
        # fails (e.g. for Pagumen, the 13th month).
        result = f"{ENGLISH_DAY_NAMES[d.weekday()]} {d.day} {d.strftime('%B')} {d.year}"
    if time_part:
        result = f"{result} {time_part}"
    return result

def amharic_day_name(value: date | datetime) -> str:
    """Return the Amharic name of the weekday for ``value``."""
    d = value.date() if isinstance(value, datetime) else value
    return AMHARIC_DAY_NAMES[d.weekday()]
