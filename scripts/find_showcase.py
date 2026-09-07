"""
One-off helper: after a full ingest run, pick out good candidate relations for
each of the assignment's four required cases, so they can be reviewed and
polished (via app.reconcile.regenerate_explanation) before recording the demo.

Not part of the running app -- this is a development tool, run once:
    python scripts/find_showcase.py
"""
from __future__ import annotations

import json

from app.db import get_connection, loads


def _fmt_claim(c) -> str:
    val = c["value_raw"] or c["state_value"]
    return f"{c['subject']} | {c['metric_raw']} | {val} {c['value_unit'] or ''} | {c['period_label']} | p{c['page_num']}"


def main():
    conn = get_connection()

    print("=" * 70)
    print("CASE 1 candidates -- CORROBORATES, cross-document, different scale")
    print("=" * 70)
    rows = conn.execute(
        """SELECT r.id, r.explanation, a.id as a_id, b.id as b_id
           FROM relations r
           JOIN claims a ON a.id = r.claim_id_a
           JOIN claims b ON b.id = r.claim_id_b
           WHERE r.verdict = 'CORROBORATES' AND a.document_id != b.document_id
             AND a.value_scale IS NOT b.value_scale
           LIMIT 15"""
    ).fetchall()
    for r in rows:
        a = conn.execute("SELECT * FROM claims WHERE id=?", (r["a_id"],)).fetchone()
        b = conn.execute("SELECT * FROM claims WHERE id=?", (r["b_id"],)).fetchone()
        print(f"\nrelation_id={r['id']}")
        print(" A:", _fmt_claim(a), "| quote:", a["quote"][:100])
        print(" B:", _fmt_claim(b), "| quote:", b["quote"][:100])
        print(" explanation:", r["explanation"])

    print("\n" + "=" * 70)
    print("CASE 2 candidates -- CONTRADICTS, cross-document preferred")
    print("=" * 70)
    rows = conn.execute(
        """SELECT r.id, r.explanation, r.dimension_diff_json, a.id as a_id, b.id as b_id
           FROM relations r
           JOIN claims a ON a.id = r.claim_id_a
           JOIN claims b ON b.id = r.claim_id_b
           WHERE r.verdict = 'CONTRADICTS' AND a.document_id != b.document_id
           LIMIT 20"""
    ).fetchall()
    for r in rows:
        a = conn.execute("SELECT * FROM claims WHERE id=?", (r["a_id"],)).fetchone()
        b = conn.execute("SELECT * FROM claims WHERE id=?", (r["b_id"],)).fetchone()
        diff = loads(r["dimension_diff_json"])
        rel = diff.get("value_comparison", {}).get("relative_difference")
        print(f"\nrelation_id={r['id']}  rel_diff={rel}")
        print(" A:", _fmt_claim(a), "| quote:", a["quote"][:100])
        print(" B:", _fmt_claim(b), "| quote:", b["quote"][:100])
        print(" explanation:", r["explanation"])

    print("\n" + "=" * 70)
    print("CASE 2 alt -- entity_state CONTRADICTS (e.g. director status)")
    print("=" * 70)
    rows = conn.execute(
        """SELECT r.id, r.explanation, a.id as a_id, b.id as b_id
           FROM relations r
           JOIN claims a ON a.id = r.claim_id_a
           JOIN claims b ON b.id = r.claim_id_b
           WHERE r.verdict = 'CONTRADICTS' AND a.kind = 'entity_state'
           LIMIT 15"""
    ).fetchall()
    for r in rows:
        a = conn.execute("SELECT * FROM claims WHERE id=?", (r["a_id"],)).fetchone()
        b = conn.execute("SELECT * FROM claims WHERE id=?", (r["b_id"],)).fetchone()
        print(f"\nrelation_id={r['id']}")
        print(" A:", _fmt_claim(a), "| quote:", a["quote"][:120])
        print(" B:", _fmt_claim(b), "| quote:", b["quote"][:120])
        print(" explanation:", r["explanation"])

    print("\n" + "=" * 70)
    print("CASE 3 candidates -- RECONCILED_BY_CONTEXT, axis=scope, same document")
    print("=" * 70)
    rows = conn.execute(
        """SELECT r.id, r.explanation, r.axis, a.id as a_id, b.id as b_id
           FROM relations r
           JOIN claims a ON a.id = r.claim_id_a
           JOIN claims b ON b.id = r.claim_id_b
           WHERE r.verdict = 'RECONCILED_BY_CONTEXT' AND r.axis = 'scope'
             AND a.document_id = b.document_id
           LIMIT 15"""
    ).fetchall()
    for r in rows:
        a = conn.execute("SELECT * FROM claims WHERE id=?", (r["a_id"],)).fetchone()
        b = conn.execute("SELECT * FROM claims WHERE id=?", (r["b_id"],)).fetchone()
        print(f"\nrelation_id={r['id']}")
        print(" A:", _fmt_claim(a), "| quote:", a["quote"][:120])
        print(" B:", _fmt_claim(b), "| quote:", b["quote"][:120])
        print(" explanation:", r["explanation"])

    print("\n" + "=" * 70)
    print("CASE 4 material -- rejected/failed extractions (issues table)")
    print("=" * 70)
    rows = conn.execute("SELECT issue_type, COUNT(*) n FROM issues GROUP BY issue_type").fetchall()
    for r in rows:
        print(f" {r['issue_type']}: {r['n']}")
    sample = conn.execute(
        "SELECT * FROM issues WHERE issue_type='quote_not_found' LIMIT 5"
    ).fetchall()
    for s in sample:
        print("\n issue:", s["detail"][:200])

    conn.close()


if __name__ == "__main__":
    main()
