"""
Step 6 of the pipeline: find pairs of claims that are plausibly "about the
same thing" and therefore worth comparing.

Comparing every claim against every other claim does not scale, and most
pairs would be nonsense anyway (Delhivery's fleet size against India's CPI).
Instead, claims are grouped by (entity, canonical metric) -- the metric
registry (app/registry.py) already merged "Revenue from Operations" and
"revenue from services" into one metric, so this grouping is doing most of
the semantic work for free. Only claims inside the same group are ever
compared.

One more filter matters in practice: a metric that recurs across many
quarters in a single presentation (e.g. "Adjusted EBITDA" stated once per
quarter on a trend slide) forms one large group, and naively pairing every
member with every other member mostly produces "these differ because they
cover a different quarter" -- true, but not an interesting fact
relationship, and expensive to reconcile at scale. `_is_interesting_pair`
drops exactly that shape (same document, same metric, different period,
nothing else distinguishing them) while always keeping cross-document pairs
and same-document pairs that differ in basis/segment -- the pairs the
assignment's four cases are actually about.

Incremental by construction: pass `new_document_id` and only pairs touching
that document's claims are produced, and pairs already reconciled (a row
already exists in `relations`) are skipped -- so adding one more document
never re-compares the whole existing knowledge base against itself. This is
what the "add new documents without rebuilding everything" brownie point
means in practice here.
"""
from __future__ import annotations

from itertools import combinations

from app.db import loads

MAX_PAIRS_PER_GROUP = 60


def _existing_pairs(conn) -> set[tuple[str, str]]:
    rows = conn.execute("SELECT claim_id_a, claim_id_b FROM relations").fetchall()
    pairs = set()
    for r in rows:
        a, b = r["claim_id_a"], r["claim_id_b"]
        pairs.add((a, b) if a < b else (b, a))
    return pairs


def _is_interesting_pair(a: dict, b: dict) -> bool:
    same_doc = a["document_id"] == b["document_id"]
    if not same_doc:
        return True  # cross-document comparisons are always the point

    same_period = (a["period_start"], a["period_end"]) == (b["period_start"], b["period_end"])
    if same_period:
        return True  # same document restating the same period -- worth an internal check

    qa, qb = loads(a["qualifiers_json"]) or {}, loads(b["qualifiers_json"]) or {}
    if qa.get("basis") != qb.get("basis") or qa.get("segment") != qb.get("segment"):
        return True  # same document, different scope -- our standalone/consolidated case

    return False  # same document, same metric, just a different quarter: a time series, not a fact relationship


def generate_candidate_pairs(conn, new_document_id: str | None = None) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT id, document_id, entity_id, metric_id, period_start, period_end, qualifiers_json "
        "FROM claims WHERE entity_id IS NOT NULL AND metric_id IS NOT NULL"
    ).fetchall()

    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        key = (r["entity_id"], r["metric_id"])
        groups.setdefault(key, []).append(dict(r))

    existing = _existing_pairs(conn)
    pairs: list[tuple[str, str]] = []
    for members in groups.values():
        if len(members) < 2:
            continue

        group_pairs: list[tuple[str, str]] = []
        for ca, cb in combinations(members, 2):
            if new_document_id and new_document_id not in (ca["document_id"], cb["document_id"]):
                continue
            if not _is_interesting_pair(ca, cb):
                continue
            id_a, id_b = ca["id"], cb["id"]
            key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
            if key in existing:
                continue
            group_pairs.append(key)

        if len(group_pairs) > MAX_PAIRS_PER_GROUP:
            # Safety valve for a metric that still has an unusually large
            # group after the filter above (e.g. many documents all stating
            # one macro figure) -- keep a bounded, deterministic sample
            # rather than letting one metric dominate the whole run.
            group_pairs = group_pairs[:MAX_PAIRS_PER_GROUP]

        for key in group_pairs:
            existing.add(key)
            pairs.append(key)

    return pairs
