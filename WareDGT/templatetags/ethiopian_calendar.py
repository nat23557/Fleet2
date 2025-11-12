from django import template
from datetime import date, datetime
from django.utils import timezone
from WareDGT.utils.ethiopian_dates import to_ethiopian_date_str, amharic_day_name

register = template.Library()

@register.filter
def ethiopian_date(value):
    """Render a Gregorian date or datetime in Ethiopian calendar with Amharic names."""
    if not value:
        return ""
    # The third‑party converter can raise ValueError for some edge dates
    # (e.g., Pagumen day calculation). Avoid breaking templates by
    # falling back to a plain ISO date when conversion fails.
    try:
        return to_ethiopian_date_str(value)
    except Exception:
        # Best‑effort graceful fallback
        try:
            if isinstance(value, datetime):
                return value.strftime("%Y-%m-%d %H:%M")
            if isinstance(value, date):
                return value.isoformat()
        except Exception:
            pass
        return str(value)

@register.filter
def amharic_day(value):
    """Return the Amharic name of the weekday for ``value``."""
    if not value:
        return ""
    return amharic_day_name(value)


@register.filter(name="days_until")
def days_until(value):
    """Return whole days from today until ``value`` (date/datetime).

    Positive for future dates, 0 for today/past.
    """
    if not value:
        return ""
    d = value.date() if isinstance(value, datetime) else value
    try:
        today = timezone.localdate()
        delta = (d - today).days
        return max(delta, 0)
    except Exception:
        return ""


@register.filter(name="days_overdue")
def days_overdue(value):
    """Return whole days since ``value`` (date/datetime) if in the past.

    Positive for past dates, 0 for today/future.
    """
    if not value:
        return ""
    d = value.date() if isinstance(value, datetime) else value
    try:
        today = timezone.localdate()
        delta = (today - d).days
        return max(delta, 0)
    except Exception:
        return ""
