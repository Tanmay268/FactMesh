"""
The pipeline orchestrator. This is what runs when a PDF is uploaded, either
through the API or the CLI below.

Re-uploading the same file is a no-op (matched by sha256), and adding a new
document only links and reconciles ITS claims against the existing knowledge
base -- nothing already stored is re-parsed, re-extracted or re-reconciled.
That is what makes ingesting document N+1 cost roughly the work of one
document, not the whole collection.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.db import dumps, get_connection, init_db, loads, new_id, session
from app.extraction import extract_claims_for_document, group_blocks_by_page
from app.linking import generate_candidate_pairs
from app.llm.factory import get_adapter
from app.parsing.segment import parse_document
from app.reconcile import reconcile_pairs
from app.screening import screen_blocks

COMPANY_NAME_RE = re.compile(
    r"\b([A-Z][A-Za-z&,.\-]+(?:\s+[A-Z][A-Za-z&,.\-]+){0,4}\s+(?:Limited|Ltd\.?))\b"
)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _guess_fallback_subject(blocks) -> str | None:
    names = []
    for b in blocks:
        if b.block_type != "prose":
            continue
        names.extend(m.strip() for m in COMPANY_NAME_RE.findall(b.text))
    if not names:
        return None
    return Counter(names).most_common(1)[0][0]


def _infer_as_of_date(conn, document_id: str) -> str | None:
    rows = conn.execute(
        "SELECT period_end FROM claims WHERE document_id = ? AND period_end IS NOT NULL "
        "AND period_type IN ('fiscal_year', 'calendar_year')",
        (document_id,),
    ).fetchall()
    if not rows:
        return None
    ends = [r["period_end"] for r in rows]
    return Counter(ends).most_common(1)[0][0]


def ingest_pdf(path: str, conn=None, adapter=None, verbose: bool = True) -> dict:
    own_conn = conn is None
    conn = conn or get_connection()
    adapter = adapter or get_adapter()
    try:
        sha = _sha256(path)
        existing = conn.execute("SELECT id FROM documents WHERE sha256 = ?", (sha,)).fetchone()
        if existing:
            if verbose:
                print(f"[skip] {path} already ingested as {existing['id']}")
            return {"document_id": existing["id"], "status": "already_ingested"}

        if verbose:
            print(f"[parse] {path}")
        doc_struct = parse_document(path)
        document_id = new_id()
        filename = Path(path).name
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, publisher, doc_type, title, page_count, uploaded_at, meta_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (document_id, filename, sha, None, doc_struct.doc_type, doc_struct.title,
             doc_struct.page_count, datetime.now(timezone.utc).isoformat(), dumps({})),
        )

        block_id_map: dict[int, str] = {}
        all_blocks_by_page: dict[int, list] = {}
        for b in doc_struct.blocks:
            block_id = new_id()
            block_id_map[id(b)] = block_id
            conn.execute(
                "INSERT INTO blocks (id, document_id, page_num, order_index, block_type, text, "
                "section_path, table_caption, table_units, basis, bbox_json, fact_score) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (block_id, document_id, b.page_num, b.order_index, b.block_type, b.text,
                 dumps(b.section_path), b.table_caption, b.table_units, b.basis, dumps(list(b.bbox)), 0.0),
            )
            all_blocks_by_page.setdefault(b.page_num, []).append(b)

        scored = screen_blocks(doc_struct.blocks)
        for b, score in scored:
            conn.execute("UPDATE blocks SET fact_score = ? WHERE id = ?", (score, block_id_map[id(b)]))
        screened_by_page = group_blocks_by_page(scored)
        n_total_blocks = len(doc_struct.blocks)
        n_screened = sum(len(v) for v in screened_by_page.values())
        if verbose:
            print(f"[screen] {n_screened}/{n_total_blocks} blocks sent for extraction "
                  f"across {len(screened_by_page)} pages")

        fallback_subject = _guess_fallback_subject(doc_struct.blocks)

        def _progress(page_num, n_claims_raw, n_kept_so_far):
            if verbose:
                print(f"  [extract] page {page_num}: kept so far = {n_kept_so_far}", end="\r")

        stats = extract_claims_for_document(
            conn, adapter, document_id, doc_struct.title, fallback_subject,
            all_blocks_by_page, screened_by_page, block_id_map, progress_cb=_progress,
        )
        if verbose:
            print()
            print(f"[extract] done: {stats}")

        as_of = _infer_as_of_date(conn, document_id)
        conn.execute("UPDATE documents SET meta_json = ? WHERE id = ?", (dumps({"inferred_as_of": as_of}), document_id))

        pairs = generate_candidate_pairs(conn, new_document_id=document_id)
        if verbose:
            print(f"[link] {len(pairs)} candidate pairs to reconcile")

        def _rprogress(i, n):
            if verbose:
                print(f"  [reconcile] {i}/{n}", end="\r")

        counts = reconcile_pairs(conn, adapter, pairs, progress_cb=_rprogress)
        if verbose:
            print()
            print(f"[reconcile] {counts}")

        return {
            "document_id": document_id, "status": "ingested", "extract_stats": stats,
            "relation_counts": counts, "blocks_total": n_total_blocks, "blocks_screened": n_screened,
        }
    finally:
        if own_conn:
            conn.commit()
            conn.close()


def main():
    parser = argparse.ArgumentParser(description="Ingest one or more PDFs into the fact knowledge layer.")
    parser.add_argument("paths", nargs="+", help="PDF file paths (glob-expanded by the shell)")
    args = parser.parse_args()

    init_db()
    conn = get_connection()
    adapter = get_adapter()
    print(f"[info] using LLM provider: {adapter.name}")
    try:
        for path in args.paths:
            ingest_pdf(path, conn=conn, adapter=adapter)
            conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
