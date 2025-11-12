from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Dict, Iterable

import requests
from django.db import transaction
from django.utils import timezone

from .models import ExchangeRate


CBE_API = "https://combanketh.et/cbeapi/daily-exchange-rates?_limit=1&_sort=Date%3ADESC"


@dataclass
class Rate:
    code: str
    rate_to_etb: float  # ETB per 1 unit of currency
    date: _dt.date


def _parse_cbe_payload(payload) -> Iterable[Rate]:
    """Yield Rate items from the CBE response structure.

    Example entry fields per currency:
      - cashBuying, cashSelling, transactionalBuying, transactionalSelling
      - currency: { CurrencyCode: "USD", CurrencyName: ... }
    We choose transactionalSelling as the conversion rate to ETB.
    """
    items = payload if isinstance(payload, list) else []
    for rec in items:
        dt_s = rec.get("Date")
        try:
            dt = _dt.date.fromisoformat(dt_s)
        except Exception:
            dt = timezone.now().date()
        for x in rec.get("ExchangeRate", []) or []:
            cur = (x.get("currency") or {}).get("CurrencyCode") or ""
            try:
                rate = float(x.get("transactionalSelling") or x.get("cashSelling") or 0)
            except Exception:
                rate = 0.0
            if not cur or rate <= 0:
                continue
            yield Rate(cur.upper(), rate, dt)


def fetch_cbe_rates(timeout: int = 15) -> Dict[str, Rate]:
    """Download latest daily exchange rates from CBE and return mapping by code.

    If the endpoint is unreachable or invalid, returns an empty dict.
    """
    try:
        r = requests.get(CBE_API, timeout=timeout, headers={"Accept": "application/json"})
        if r.status_code != 200:
            return {}
        data = r.json()
        out: Dict[str, Rate] = {}
        for rate in _parse_cbe_payload(data):
            out[rate.code] = rate
        # Always include ETB at 1.0
        today = next(iter(out.values())).date if out else timezone.now().date()
        out.setdefault("ETB", Rate("ETB", 1.0, today))
        return out
    except Exception:
        return {}


def get_or_update_today_rates() -> Dict[str, float]:
    """Return a simple dict {code: rate_to_etb} for today.

    Tries DB first; if not present, fetches from CBE and stores.
    """
    today = timezone.now().date()
    existing = {r.currency.upper(): float(r.rate) for r in ExchangeRate.objects.filter(date=today)}
    if existing:
        existing.setdefault("ETB", 1.0)
        return existing

    fetched = fetch_cbe_rates()
    if not fetched:
        # fallback to most recent in DB if available
        latest = ExchangeRate.objects.order_by("-date").all()
        latest_map = {}
        for r in latest:
            latest_map.setdefault(r.currency.upper(), float(r.rate))
        if latest_map:
            latest_map.setdefault("ETB", 1.0)
            return latest_map
        return {"ETB": 1.0}

    with transaction.atomic():
        for rate in fetched.values():
            ExchangeRate.objects.update_or_create(
                date=rate.date, currency=rate.code,
                defaults={"rate": rate.rate_to_etb, "source": "CBE"},
            )
    return {code: r.rate_to_etb for code, r in fetched.items()}

