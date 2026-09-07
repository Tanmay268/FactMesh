"""
Converts a number plus a scale word ("crore", "million", ...) into one
canonical base unit, so two claims that used different scales become
directly comparable.

Canonical base units:
- currency values -> plain rupees (or plain units of whatever currency)
- counts / physical quantities with a scale word -> plain units
- percentages -> left as percentage points (never rescaled)
"""
from __future__ import annotations

import re

SCALE_FACTORS: dict[str, float] = {
    "crore": 1e7,
    "cr": 1e7,
    "cr.": 1e7,
    "million": 1e6,
    "mn": 1e6,
    "mn.": 1e6,
    "m": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "bn.": 1e9,
    "lakh": 1e5,
    "lakhs": 1e5,
    "thousand": 1e3,
    "k": 1e3,
}

_SCALE_WORD_PATTERN = re.compile(
    r"\b(crore|cr\.?|million|mn\.?|billion|bn\.?|lakhs?|thousand)\b", re.IGNORECASE
)
CURRENCY_PATTERN = re.compile(r"₹|Rs\.?|INR|US\$|\$|USD|EUR|€", re.IGNORECASE)


def extract_scale(text: str) -> str | None:
    if not text:
        return None
    m = _SCALE_WORD_PATTERN.search(text)
    if not m:
        return None
    return m.group(1).lower().rstrip(".")


def extract_currency(text: str) -> str | None:
    if not text:
        return None
    if re.search(r"₹|Rs\.?|INR", text, re.IGNORECASE):
        return "INR"
    if re.search(r"US\$|USD", text, re.IGNORECASE):
        return "USD"
    if "€" in text or re.search(r"\bEUR\b", text, re.IGNORECASE):
        return "EUR"
    if "$" in text:
        return "USD"
    return None


def to_base_units(value: float | None, scale: str | None, unit: str | None) -> float | None:
    """
    unit == 'percent' is never rescaled -- 18.15% and 18.15 percentage points
    are the same number, scale words don't apply to a ratio.
    """
    if value is None:
        return None
    if unit and unit.lower() in {"percent", "%", "percentage"}:
        return value
    if not scale:
        return value
    factor = SCALE_FACTORS.get(scale.lower().rstrip("."))
    if factor is None:
        return value
    return value * factor


def format_scale_factor(scale: str | None) -> float:
    if not scale:
        return 1.0
    return SCALE_FACTORS.get(scale.lower().rstrip("."), 1.0)
