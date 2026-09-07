"""
The metric registry: how the schema grows on its own as new kinds of facts
show up, instead of the system being built around a fixed list of metrics.

When a claim's raw metric label ("Revenue from Operations") comes in, it is
compared against every metric already registered. Close enough (by string
similarity) and it becomes an alias of an existing metric. Not close, and it
becomes a brand new metric. The registry is visible through /api/schema, so
you can watch it grow as documents are added -- this is what "a schema that
evolves dynamically" means in practice here, rather than a config file
someone edits by hand.

String similarity alone is not a safe judge of "same metric", though --
testing this on the Delhivery earnings deck found it happily merging
"Adjusted EBITDA" with "Adjusted EBITDA margin" (an amount and a percentage)
and would just as happily merge "CPI inflation" with "WPI inflation" (two
different indices) since both pairs share most of their characters. Plain
embeddings turned out no better at telling these apart (tested during
development; a currency amount and its own margin are, after all,
semantically close). So two cheap, targeted guards run before a fuzzy match
is accepted: `_has_conflicting_modifier` blocks a merge across a word like
"margin" or "growth" that only one side has, and `_has_conflicting_acronym`
blocks a merge across two different all-caps acronyms (CPI vs WPI, GDP vs
GVA). Neither is a general solution to metric matching -- both are aimed
squarely at the failure patterns actually observed.

Same idea, reused for entities (app/normalize/entities.py handles the string
side; this module owns the "read/write the registry table" side for both).
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from app.db import dumps, loads, new_id
from app.normalize.entities import normalize_entity

METRIC_ALIAS_THRESHOLD = 0.72

# Words that flip what a number means (a rate/ratio vs. an absolute amount).
# "Adjusted EBITDA" and "Adjusted EBITDA margin" score high on plain string
# similarity (one contains the other almost entirely) but are not the same
# metric -- one is a currency amount, the other a percentage. Refusing to
# merge across one of these words catches that whole failure class cheaply,
# without needing embeddings to get it right. (app/reconcile.py also carries
# an independent safety net at comparison time, in case a pair still slips
# through -- see _incompatible_units there.)
_RATIO_MODIFIER_WORDS = {
    "margin", "ratio", "growth", "rate", "yoy", "qoq", "mom", "average", "avg",
    "ex", "index",
}


def _normalize_metric_text(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _has_conflicting_modifier(a: str, b: str) -> bool:
    words_a = set(a.split()) & _RATIO_MODIFIER_WORDS
    words_b = set(b.split()) & _RATIO_MODIFIER_WORDS
    return words_a != words_b


_ACRONYM_PATTERN = re.compile(r"\b[A-Z]{2,6}\b")


def _has_conflicting_acronym(original_a: str, original_b: str) -> bool:
    """CPI vs WPI, GDP vs GVA: different all-caps acronyms naming different
    things, even though the surrounding words ('inflation', 'growth') and
    therefore the overall string similarity look almost identical."""
    acr_a, acr_b = set(_ACRONYM_PATTERN.findall(original_a)), set(_ACRONYM_PATTERN.findall(original_b))
    return bool(acr_a) and bool(acr_b) and acr_a.isdisjoint(acr_b)


def resolve_metric(conn, raw_label: str, kind: str) -> str:
    """Returns a metric_id, creating a new metric row if nothing close enough
    already exists. `kind` ('numeric' | 'entity_state') keeps the two families
    from ever being merged into one metric, since they compare differently."""
    key = _normalize_metric_text(raw_label)
    rows = conn.execute(
        "SELECT id, canonical_name, aliases_json FROM metrics WHERE kind = ?", (kind,)
    ).fetchall()

    best_id, best_score = None, 0.0
    for row in rows:
        candidates = [row["canonical_name"]] + loads(row["aliases_json"])
        for cand in candidates:
            cand_key = _normalize_metric_text(cand)
            if _has_conflicting_modifier(key, cand_key) or _has_conflicting_acronym(raw_label, cand):
                continue
            score = difflib.SequenceMatcher(None, key, cand_key).ratio()
            if score > best_score:
                best_score, best_id = score, row["id"]

    if best_id and best_score >= METRIC_ALIAS_THRESHOLD:
        row = conn.execute("SELECT aliases_json FROM metrics WHERE id = ?", (best_id,)).fetchone()
        aliases = loads(row["aliases_json"])
        if raw_label not in aliases:
            aliases.append(raw_label)
            conn.execute(
                "UPDATE metrics SET aliases_json = ? WHERE id = ?", (dumps(aliases), best_id)
            )
        return best_id

    new_metric_id = new_id()
    conn.execute(
        "INSERT INTO metrics (id, canonical_name, kind, aliases_json, created_at) VALUES (?, ?, ?, ?, ?)",
        (new_metric_id, raw_label.strip(), kind, dumps([raw_label]), datetime.now(timezone.utc).isoformat()),
    )
    return new_metric_id


def resolve_entity(conn, raw_name: str, fallback_name: str | None = None) -> str:
    """Returns an entity_id. `fallback_name` is the document's own declared
    subject (e.g. its filer's name), used when raw_name is a generic
    self-reference like 'the Company' that carries no name of its own."""
    from app.normalize.entities import is_self_reference

    name = raw_name.strip() if raw_name else ""
    if (not name or is_self_reference(name)) and fallback_name:
        name = fallback_name.strip()
    if not name:
        name = "Unknown"

    key = normalize_entity(name)
    rows = conn.execute("SELECT id, canonical_name, aliases_json FROM entities").fetchall()

    best_id, best_score = None, 0.0
    for row in rows:
        candidates = [row["canonical_name"]] + loads(row["aliases_json"])
        for cand in candidates:
            score = difflib.SequenceMatcher(None, key, normalize_entity(cand)).ratio()
            if score > best_score:
                best_score, best_id = score, row["id"]

    from app.normalize.entities import SAME_ENTITY_THRESHOLD

    if best_id and best_score >= SAME_ENTITY_THRESHOLD:
        row = conn.execute("SELECT aliases_json FROM entities WHERE id = ?", (best_id,)).fetchone()
        aliases = loads(row["aliases_json"])
        if name not in aliases:
            aliases.append(name)
            conn.execute("UPDATE entities SET aliases_json = ? WHERE id = ?", (dumps(aliases), best_id))
        return best_id

    new_entity_id = new_id()
    conn.execute(
        "INSERT INTO entities (id, canonical_name, aliases_json) VALUES (?, ?, ?)",
        (new_entity_id, name, dumps([name])),
    )
    return new_entity_id
