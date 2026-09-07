"""
Turns a raw number as written in a filing into a plain float.

The one thing every finance PDF does that a naive float(...) gets wrong:
accountants write a negative number in parentheses. `(452.3)` means -452.3,
not "452.3 in brackets". This module is the single place that rule lives.
"""
from __future__ import annotations

import re

_CLEAN_PATTERN = re.compile(r"[^\d.\-]")


def parse_number(raw: str) -> float | None:
    """
    '81,415.38'   -> 81415.38
    '(452.3)'     -> -452.3
    '₹(452) Cr'   -> -452.0
    '18,540'      -> 18540.0
    '18.15%'      -> 18.15
    '-'  or ''    -> None
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text or text in {"-", "–", "—", "NA", "N/A", "n/a"}:
        return None

    is_negative = False
    if "(" in text and ")" in text:
        is_negative = True
    if text.startswith("-") or text.startswith("−"):
        is_negative = True

    cleaned = _CLEAN_PATTERN.sub("", text)
    cleaned = cleaned.replace(",", "")
    cleaned = cleaned.strip("-")  # we track sign ourselves; avoid double negatives
    if not cleaned or cleaned == ".":
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return -value if is_negative and value != 0 else value
