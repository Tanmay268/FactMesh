"""
The metric registry: how the schema grows on its own as new kinds of facts
show up, instead of the system being built around a fixed list of metrics.

When a claim's raw metric label ("Revenue from Operations") comes in, it is
compared against every metric already registered. Close enough (by simple
string similarity, with an embedding assist when available) and it becomes an
alias of an existing metric. Not close, and it becomes a brand new metric.
The registry is visible through /api/schema, so you can watch it grow as
documents are added -- this is what "a schema that evolves dynamically"
means in practice here, rather than a config file someone edits by hand.

Same idea, reused for entities (app/normalize/entities.py handles the string
side; this module owns the "read/write the registry table" side for both).
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timezone

from app.db import dumps, loads, new_id
from app.normalize.entities import normalize_entity

METRIC_ALIAS_THRESHOLD = 0.80


def _normalize_metric_text(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


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
            score = difflib.SequenceMatcher(None, key, _normalize_metric_text(cand)).ratio()
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
