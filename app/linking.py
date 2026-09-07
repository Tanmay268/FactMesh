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

Incremental by construction: pass `new_document_id` and only pairs touching
that document's claims are produced, and pairs already reconciled (a row
already exists in `relations`) are skipped -- so adding one more document
never re-compares the whole existing knowledge base against itself. This is
what the "add new documents without rebuilding everything" brownie point
means in practice here.
"""
from __future__ import annotations

from itertools import combinations


def _existing_pairs(conn) -> set[tuple[str, str]]:
    rows = conn.execute("SELECT claim_id_a, claim_id_b FROM relations").fetchall()
    pairs = set()
    for r in rows:
        a, b = r["claim_id_a"], r["claim_id_b"]
        pairs.add((a, b) if a < b else (b, a))
    return pairs


def generate_candidate_pairs(conn, new_document_id: str | None = None) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT id, document_id, entity_id, metric_id FROM claims "
        "WHERE entity_id IS NOT NULL AND metric_id IS NOT NULL"
    ).fetchall()

    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for r in rows:
        key = (r["entity_id"], r["metric_id"])
        groups.setdefault(key, []).append((r["id"], r["document_id"]))

    existing = _existing_pairs(conn)
    pairs: list[tuple[str, str]] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        for (id_a, doc_a), (id_b, doc_b) in combinations(members, 2):
            if new_document_id and new_document_id not in (doc_a, doc_b):
                continue
            key = (id_a, id_b) if id_a < id_b else (id_b, id_a)
            if key in existing:
                continue
            pairs.append(key)
            existing.add(key)
    return pairs
