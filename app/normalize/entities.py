"""
Decides whether two differently-written names refer to the same entity --
"Delhivery Limited", "the Company", "our Company" and "Delhivery" should all
resolve to one entity, without a hard-coded list of names. This is done with
generic string normalisation plus fuzzy matching, not a lookup table, so it
works on entities the system has never seen.
"""
from __future__ import annotations

import difflib
import re

_GENERIC_SELF_REFERENCES = {
    "the company", "our company", "the group", "our group", "the corporation",
    "the bank", "the fund", "the issuer",
}
_SUFFIX_PATTERN = re.compile(
    r"\b(limited|ltd\.?|private|pvt\.?|inc\.?|corporation|corp\.?|plc|llc|company|co\.?)\b\.?",
    re.IGNORECASE,
)
_PUNCT_PATTERN = re.compile(r"[^\w\s]")


def normalize_entity(name: str) -> str:
    """A comparable key: lowercase, punctuation stripped, common corporate
    suffixes removed, whitespace collapsed."""
    if not name:
        return ""
    text = name.strip().lower()
    if text in _GENERIC_SELF_REFERENCES:
        return "__self__"
    text = _PUNCT_PATTERN.sub(" ", text)
    text = _SUFFIX_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_self_reference(name: str) -> bool:
    return normalize_entity(name) == "__self__"


def entity_similarity(a: str, b: str) -> float:
    """0..1. Self-references (the Company / our Company) are handled by the
    caller resolving them to whichever entity actually filed the document,
    since 'the Company' alone carries no name to compare against."""
    na, nb = normalize_entity(a), normalize_entity(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


SAME_ENTITY_THRESHOLD = 0.82


def same_entity(a: str, b: str) -> bool:
    return entity_similarity(a, b) >= SAME_ENTITY_THRESHOLD
