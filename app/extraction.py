"""
Step 4 of the pipeline: turn screened blocks into structured claims, and
enforce the one rule that makes "linked to evidence" a guarantee rather than
a hope -- a claim's quote must be found, verbatim (modulo whitespace), in the
source page. If it isn't, the claim is thrown away and logged as an issue,
never silently dropped.

Claims are requested one *page* at a time, with every screened block on that
page shown together. This is deliberate: a report's numbers are frequently
laid out with the column headers (Q4 FY24, Q4 FY23...) in one text block and
the data rows in the next one down, not ruled together into a single table
object (see architecture.md and the note in app/parsing/tables.py). Sending
the whole page's fact-dense blocks in one call lets the model see the header
next to the row it belongs to, the same way a person reading the page would.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from app.db import dumps, new_id
from app.llm.base import LLMError
from app.normalize.numbers import parse_number
from app.normalize.periods import parse_period
from app.normalize.units import extract_currency, extract_scale, to_base_units
from app.parsing.segment import Block
from app.registry import resolve_entity, resolve_metric

SYSTEM_PROMPT = """You are a careful fact-extraction assistant. You are given several \
numbered text blocks taken from ONE page of a real document (a company filing or an \
institutional economic report). Your job is to find every discrete, checkable FACT \
stated in these blocks -- a number (revenue, a growth rate, a headcount, a count of \
something) or a discrete state (a person appointed, resigned, or ceased to hold a role; \
a rating; a status).

Rules, all of which matter:
1. Every fact you report MUST include a "quote" field that is copied EXACTLY, \
character for character, from the block text you were given (a snippet of a few words \
up to about 25 words is enough -- do not paraphrase it). If you cannot quote it \
verbatim, do not report it.
2. Use the numbered blocks' own context (their section heading trail, any table \
caption or declared units, and the "basis" field if a block is tagged consolidated or \
standalone) to fill in unit, scale and qualifiers -- don't guess randomly.
3. If a table's header block (e.g. "Q4 FY22 | Q4 FY23 | Q3 FY24 | Q4 FY24") appears \
just before a data row block, use the header to say what period each number in the row \
belongs to, and emit ONE fact per (row label, period) pair, quoting the actual number \
from the data-row block as the quote.
4. Do not invent facts, numbers, or people that are not written in the text. Skip \
boilerplate, opinions, and vague narrative ("the industry remains competitive") -- \
only checkable, specific facts.
5. Return ONLY a JSON object of the shape described below. No prose, no markdown fences.

Output JSON shape:
{"claims": [
  {
    "source_block": <int, the block number this fact's quote comes from>,
    "kind": "numeric" | "entity_state",
    "subject": "<who/what this is about, e.g. a company name, a country, a person>",
    "metric": "<what is being measured or stated, e.g. 'revenue from operations', \
'independent director', 'CPI inflation'>",
    "quote": "<verbatim text from that block>",
    "value_raw": "<the number exactly as written, e.g. '81,415.38', or null>",
    "unit": "<'INR' | 'USD' | 'percent' | 'count' | 'tonnes' | ... or null>",
    "scale": "<'crore'|'million'|'billion'|'lakh'|'thousand'| null>",
    "state_value": "<for entity_state facts, e.g. 'resigned', 'appointed', 'active', \
'ceased' -- else null>",
    "period_text": "<the period exactly as the document phrases it, e.g. 'FY24', \
'year ended March 31, 2024', 'Q4 FY24', or null if the fact is not period-specific>",
    "qualifiers": {"<free-form key, e.g. 'basis' or 'segment'>": "<value>"},
    "confidence": <0.0-1.0>,
    "notes": "<anything relevant you noticed, e.g. a footnote that changes the \
number's meaning, or null>"
  }
]}
"""

MAX_BLOCK_CHARS = 1200
MAX_PAGE_CHARS = 7000


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def _build_prompt(doc_title: str | None, page_num: int, entries: list[tuple[int, Block]]) -> str:
    lines = [f"Document: {doc_title or 'unknown title'}", f"Page: {page_num}", ""]
    for idx, block in entries:
        meta = []
        if block.section_path:
            meta.append("section: " + " > ".join(block.section_path[-2:]))
        if block.block_type == "table":
            if block.table_caption:
                meta.append(f"table caption: {block.table_caption}")
            if block.table_units:
                meta.append(f"declared units: {block.table_units}")
        if block.basis:
            meta.append(f"basis: {block.basis}")
        meta_str = f" ({'; '.join(meta)})" if meta else ""
        lines.append(f"[Block {idx}]{meta_str} type={block.block_type}")
        lines.append(_clip(block.text, MAX_BLOCK_CHARS))
        lines.append("")
    return "\n".join(lines)


def _extract_json(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start : end + 1])


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _quote_is_grounded(quote: str, block_text: str, page_text: str) -> tuple[bool, str]:
    nq = _normalize_for_match(quote)
    if not nq:
        return False, "empty quote"
    if nq in _normalize_for_match(block_text):
        return True, "matched in source block"
    if nq in _normalize_for_match(page_text):
        return True, "matched elsewhere on source page"
    if nq.lower() in _normalize_for_match(page_text).lower():
        return True, "matched on page (case-insensitive)"
    return False, "quote not found verbatim in source page"


def group_blocks_by_page(scored_blocks: list[tuple[Block, float]]) -> dict[int, list[Block]]:
    by_page: dict[int, list[Block]] = {}
    for block, _score in scored_blocks:
        by_page.setdefault(block.page_num, []).append(block)
    for page_num in by_page:
        by_page[page_num].sort(key=lambda b: b.order_index)
    return by_page


def extract_claims_for_document(
    conn, adapter, document_id: str, doc_title: str | None, fallback_subject: str | None,
    all_blocks_by_page: dict[int, list[Block]],  # ALL blocks (for page_text / grounding), by page
    screened_by_page: dict[int, list[Block]],     # only screened blocks, by page
    block_id_map: dict[int, str],                  # id(block) -> stored block_id
    progress_cb=None,
) -> dict:
    stats = {"pages_processed": 0, "claims_kept": 0, "claims_rejected": 0, "parse_errors": 0}

    for page_num, screened in screened_by_page.items():
        if not screened:
            continue
        entries = [(i + 1, b) for i, b in enumerate(screened)]
        prompt = _build_prompt(doc_title, page_num, entries)
        if len(prompt) > MAX_PAGE_CHARS:
            prompt = prompt[:MAX_PAGE_CHARS] + "\n…[truncated]"

        page_text = "\n".join(b.text for b in all_blocks_by_page.get(page_num, []))

        try:
            raw = adapter.generate(SYSTEM_PROMPT, prompt, json_mode=True)
            data = _extract_json(raw)
        except (LLMError, ValueError, json.JSONDecodeError) as e:
            stats["parse_errors"] += 1
            conn.execute(
                "INSERT INTO issues (id, document_id, block_id, issue_type, detail, raw_payload, created_at) "
                "VALUES (?, ?, NULL, 'parse_error', ?, ?, ?)",
                (new_id(), document_id, f"page {page_num}: {e}", None, datetime.now(timezone.utc).isoformat()),
            )
            if progress_cb:
                progress_cb(page_num, 0, 0)
            continue

        index_to_block = {i: b for i, b in entries}
        for claim in data.get("claims", []):
            src_idx = claim.get("source_block")
            block = index_to_block.get(src_idx)
            quote = (claim.get("quote") or "").strip()

            if block is None:
                stats["claims_rejected"] += 1
                conn.execute(
                    "INSERT INTO issues (id, document_id, block_id, issue_type, detail, raw_payload, created_at) "
                    "VALUES (?, ?, NULL, 'quote_not_found', ?, ?, ?)",
                    (new_id(), document_id, f"page {page_num}: source_block {src_idx} not in prompt",
                     dumps(claim), datetime.now(timezone.utc).isoformat()),
                )
                continue

            ok, reason = _quote_is_grounded(quote, block.text, page_text)
            if not ok:
                stats["claims_rejected"] += 1
                conn.execute(
                    "INSERT INTO issues (id, document_id, block_id, issue_type, detail, raw_payload, created_at) "
                    "VALUES (?, ?, ?, 'quote_not_found', ?, ?, ?)",
                    (new_id(), document_id, block_id_map.get(id(block)), reason, dumps(claim),
                     datetime.now(timezone.utc).isoformat()),
                )
                continue

            _store_claim(conn, document_id, block, block_id_map.get(id(block)), claim, fallback_subject)
            stats["claims_kept"] += 1

        stats["pages_processed"] += 1
        if progress_cb:
            progress_cb(page_num, len(data.get("claims", [])), stats["claims_kept"])

    return stats


def _store_claim(conn, document_id: str, block: Block, block_id: str, claim: dict, fallback_subject: str | None):
    kind = claim.get("kind") or "numeric"
    subject = (claim.get("subject") or "").strip()
    metric_raw = (claim.get("metric") or "").strip()
    qualifiers = claim.get("qualifiers") or {}
    if block.basis and "basis" not in qualifiers:
        qualifiers["basis"] = block.basis

    entity_id = resolve_entity(conn, subject, fallback_subject)
    metric_id = resolve_metric(conn, metric_raw or "unspecified metric", kind)

    value_raw = claim.get("value_raw")
    value_number = parse_number(value_raw) if value_raw else None
    unit = claim.get("unit")
    scale = claim.get("scale") or extract_scale(block.text) or extract_scale(block.table_units or "")
    if not unit:
        unit = extract_currency(block.text) or extract_currency(block.table_units or "")
    value_normalized = to_base_units(value_number, scale, unit) if value_number is not None else None

    period_text = claim.get("period_text")
    period = parse_period(period_text) if period_text else None
    if period is None and period_text is None:
        period = parse_period(" ".join(block.section_path)) or parse_period(block.table_caption or "")

    conn.execute(
        """INSERT INTO claims (
            id, document_id, block_id, kind, subject, entity_id, metric_raw, metric_id,
            value_raw, value_number, value_unit, value_scale, value_normalized, state_value,
            period_label, period_type, period_start, period_end, qualifiers_json,
            quote, page_num, bbox_json, confidence, notes, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            new_id(), document_id, block_id, kind, subject, entity_id, metric_raw, metric_id,
            value_raw, value_number, unit, scale, value_normalized, claim.get("state_value"),
            period.label if period else period_text, period.type if period else None,
            period.start.isoformat() if period and period.start else None,
            period.end.isoformat() if period and period.end else None,
            dumps(qualifiers), claim.get("quote"), block.page_num, dumps(list(block.bbox)),
            claim.get("confidence"), claim.get("notes"), datetime.now(timezone.utc).isoformat(),
        ),
    )
