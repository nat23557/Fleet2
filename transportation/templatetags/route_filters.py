from __future__ import annotations

import re
from django import template

register = template.Library()


def _first_token(text: str) -> str:
    """Return the part before the first comma; fallback to the whole string.

    Strips whitespace. Works with multi‑language strings.
    """
    if not text:
        return ""
    part = (text or "").split(",", 1)[0].strip()
    return part or (text or "").strip()


def _initial(text: str) -> str:
    """Return the first non‑space character (uppercased when applicable)."""
    for ch in (text or "").strip():
        # Use simple whitespace check; keep unicode letters/numerals as is
        if not ch.isspace():
            try:
                return ch.upper()
            except Exception:
                return ch
    return ""


@register.filter(name="route_initials")
def route_initials(route: object) -> str:
    """Abbreviate a route string like "Start, details → End, details" to "S → E".

    - Splits on the unicode arrow (→) or common ASCII variants (->).
    - For each side, takes text before the first comma, then picks its initial.
    - Falls back gracefully if the pattern isn’t present.
    """
    if route is None:
        return ""
    s = str(route)
    parts = re.split(r"\s*(?:→|->)\s*", s)
    if len(parts) >= 2:
        start = _first_token(parts[0])
        end = _first_token(parts[-1])
        return f"{_initial(start)} → {_initial(end)}"
    # Fallback: use first token’s initial
    token = _first_token(s)
    ini = _initial(token)
    return ini

