"""
Step 7 of the pipeline, and the part the assignment cares most about: given
two claims that plausibly describe the same thing, decide whether they
CORROBORATE, CONTRADICT, are RECONCILED_BY_CONTEXT (they only look like they
disagree once you notice a difference in time / scope / basis), or are
UNRESOLVED (not enough information to say).

The verdict is always produced by explicit, inspectable rules in
`_decide_numeric` / `_decide_entity_state` -- never by asking a model "do
these agree?". A language model is used only afterwards, to put the rule's
reasoning into a plain sentence, constrained to the two quotes and the
dimension diff already computed. This split is what makes the reasoning
auditable: every verdict has a `rule_trace` you can read without an LLM call,
and the explanation can never introduce a fact the rules didn't see.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from app.db import dumps, loads, new_id

VALUE_TOLERANCE = 0.01  # 1% relative difference counts as "the same number"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


_PERCENT_UNITS = {"percent", "%", "percentage", "pct"}


def _incompatible_units(unit_a: str | None, unit_b: str | None) -> bool:
    ua, ub = (unit_a or "").strip().lower(), (unit_b or "").strip().lower()
    if not ua or not ub:
        return False  # an unstated unit isn't evidence of a conflict
    return (ua in _PERCENT_UNITS) != (ub in _PERCENT_UNITS)


def _qualifier_diff(qa: dict, qb: dict) -> dict:
    diff = {}
    for key in set(qa) & set(qb):
        va, vb = str(qa[key]).strip().lower(), str(qb[key]).strip().lower()
        diff[key] = {"a": qa[key], "b": qb[key], "match": va == vb}
    return diff


def _decide_numeric(a: dict, b: dict) -> tuple[str, str | None, dict, list[str]]:
    trace: list[str] = []
    qa, qb = loads(a["qualifiers_json"]) or {}, loads(b["qualifiers_json"]) or {}

    pa_start, pa_end = _parse_date(a["period_start"]), _parse_date(a["period_end"])
    pb_start, pb_end = _parse_date(b["period_start"]), _parse_date(b["period_end"])
    if pa_start and pa_end and pb_start and pb_end:
        period_match = (pa_start == pb_start) and (pa_end == pb_end)
    else:
        period_match = None
    trace.append(f"period: a={a['period_label']!r} b={b['period_label']!r} match={period_match}")

    qual_diff = _qualifier_diff(qa, qb)
    basis_entry = qual_diff.get("basis")
    basis_match = basis_entry["match"] if basis_entry else None
    if basis_entry:
        trace.append(f"basis: a={qa.get('basis')!r} b={qb.get('basis')!r} match={basis_match}")
    other_mismatches = [k for k, v in qual_diff.items() if k != "basis" and not v["match"]]
    if other_mismatches:
        trace.append(f"other qualifiers differ: {other_mismatches}")

    dimension_diff = {
        "period": {"a": a["period_label"], "b": b["period_label"], "match": period_match},
        "qualifiers": qual_diff,
    }

    if period_match is False:
        trace.append("verdict: different periods explain the difference")
        return "RECONCILED_BY_CONTEXT", "time", dimension_diff, trace
    if period_match is None:
        trace.append("verdict: at least one side has no identifiable period -- cannot confirm they are comparable")
        dimension_diff["comparable"] = False
        return "UNRESOLVED", None, dimension_diff, trace
    if basis_match is False:
        trace.append("verdict: different reporting basis (standalone vs consolidated) explains the difference")
        return "RECONCILED_BY_CONTEXT", "scope", dimension_diff, trace
    if other_mismatches:
        trace.append("verdict: different scope/segment explains the difference")
        return "RECONCILED_BY_CONTEXT", "scope", dimension_diff, trace

    va, vb = a["value_normalized"], b["value_normalized"]
    used_normalized = va is not None and vb is not None
    if not used_normalized:
        va, vb = a["value_number"], b["value_number"]
    if va is None or vb is None:
        trace.append("verdict: at least one side has no comparable numeric value")
        dimension_diff["comparable"] = False
        return "UNRESOLVED", None, dimension_diff, trace

    if _incompatible_units(a["value_unit"], b["value_unit"]):
        # A safety net for the metric registry's fuzzy matching: "Adjusted
        # EBITDA" and "Adjusted EBITDA margin" are similar enough in wording
        # that they can end up sharing a metric_id, but one is a currency
        # amount and the other a percentage -- not the same kind of
        # quantity, and a numeric gap between them proves nothing. Refuse to
        # call this a contradiction (or a corroboration) rather than compare
        # numbers that were never comparable in the first place.
        trace.append(
            f"verdict: units are not the same kind of quantity (a: {a['value_unit']!r}, "
            f"b: {b['value_unit']!r}) -- likely two different metrics grouped together; cannot compare"
        )
        dimension_diff["comparable"] = False
        return "UNRESOLVED", None, dimension_diff, trace

    if a["value_unit"] != b["value_unit"] or a["value_scale"] != b["value_scale"]:
        trace.append(
            f"units differ (a: {a['value_scale'] or a['value_unit']}, "
            f"b: {b['value_scale'] or b['value_unit']}); "
            f"{'normalized to a common base unit for comparison' if used_normalized else 'could not normalize -- comparing raw numbers'}"
        )

    denom = max(abs(va), abs(vb), 1e-9)
    rel_diff = abs(va - vb) / denom
    dimension_diff["value_comparison"] = {"a": va, "b": vb, "relative_difference": round(rel_diff, 6)}
    trace.append(f"values: a={va} b={vb} relative_difference={rel_diff:.4%}")

    if rel_diff <= VALUE_TOLERANCE:
        trace.append("verdict: values match within rounding tolerance")
        return "CORROBORATES", None, dimension_diff, trace

    trace.append("verdict: same period, basis and scope, but the values genuinely differ")
    return "CONTRADICTS", None, dimension_diff, trace


def _infer_doc_date(conn, document_id: str) -> date | None:
    row = conn.execute("SELECT meta_json FROM documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        return None
    meta = loads(row["meta_json"]) or {}
    return _parse_date(meta.get("inferred_as_of"))


def _decide_entity_state(conn, a: dict, b: dict) -> tuple[str, str | None, dict, list[str]]:
    trace = []
    sa, sb = (a["state_value"] or "").strip().lower(), (b["state_value"] or "").strip().lower()
    dimension_diff = {"state": {"a": a["state_value"], "b": b["state_value"], "match": sa == sb}}
    trace.append(f"state: a={a['state_value']!r} b={b['state_value']!r}")

    if sa == sb:
        trace.append("verdict: same recorded status")
        return "CORROBORATES", None, dimension_diff, trace

    date_a = _infer_doc_date(conn, a["document_id"])
    date_b = _infer_doc_date(conn, b["document_id"])
    dimension_diff["document_dates"] = {
        "a": date_a.isoformat() if date_a else None,
        "b": date_b.isoformat() if date_b else None,
    }
    if date_a and date_b and date_a != date_b:
        trace.append(f"documents dated {date_a} and {date_b} -- status plausibly changed between them")
        return "RECONCILED_BY_CONTEXT", "time", dimension_diff, trace

    trace.append("verdict: statuses disagree and no document date lets us explain why")
    return "CONTRADICTS", None, dimension_diff, trace


EXPLAIN_SYSTEM_PROMPT = """You explain, in 2-4 short plain-English sentences, why two \
extracted facts were judged to CORROBORATE each other, CONTRADICT each other, be \
RECONCILED BY CONTEXT (they only look like they disagree once you account for time, \
scope, basis or units), or be UNRESOLVED. Use ONLY the two quotes and the comparison \
notes given to you -- never introduce a number, date, or fact that is not in them. \
Write for someone who has not seen the source documents. Return plain text, no markdown."""


def _fallback_explanation(verdict: str, axis: str | None, trace: list[str]) -> str:
    tail = "; ".join(trace[-2:])
    if verdict == "CORROBORATES":
        return f"Both facts describe the same thing and agree once compared on equal terms ({tail})."
    if verdict == "CONTRADICTS":
        return f"Both facts describe the same thing but state different values, with no context found to explain the gap ({tail})."
    if verdict == "RECONCILED_BY_CONTEXT":
        return f"The two facts differ because they cover a different {axis} ({tail})."
    return f"There is not enough shared context to compare these two facts confidently ({tail})."


def _explain_with_llm(adapter, a: dict, b: dict, verdict: str, axis: str | None, trace: list[str]) -> tuple[str, str]:
    if adapter is None:
        return _fallback_explanation(verdict, axis, trace), "rule"
    prompt = (
        f"Verdict: {verdict}" + (f" (axis: {axis})" if axis else "") + "\n\n"
        f"Fact A -- subject: {a['subject']}, metric: {a['metric_raw']}, "
        f"value: {a['value_raw'] or a['state_value']}, period: {a['period_label']}\n"
        f'Quote A: "{a["quote"]}"\n\n'
        f"Fact B -- subject: {b['subject']}, metric: {b['metric_raw']}, "
        f"value: {b['value_raw'] or b['state_value']}, period: {b['period_label']}\n"
        f'Quote B: "{b["quote"]}"\n\n'
        "Comparison notes:\n- " + "\n- ".join(trace)
    )
    try:
        text = adapter.generate(EXPLAIN_SYSTEM_PROMPT, prompt, json_mode=False)
        return text.strip(), "model"
    except Exception:
        return _fallback_explanation(verdict, axis, trace), "rule"


def reconcile_pair(conn, adapter, claim_id_a: str, claim_id_b: str) -> str:
    a = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id_a,)).fetchone()
    b = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id_b,)).fetchone()

    if a["kind"] == "entity_state" and b["kind"] == "entity_state":
        verdict, axis, dimension_diff, trace = _decide_entity_state(conn, a, b)
    elif a["kind"] == "numeric" and b["kind"] == "numeric":
        verdict, axis, dimension_diff, trace = _decide_numeric(a, b)
    else:
        verdict, axis, dimension_diff, trace = "UNRESOLVED", None, {}, ["mismatched claim kinds; cannot compare"]

    # An LLM call is reserved for the verdicts where plain-English nuance
    # actually earns its cost -- a contradiction or a reconciled-by-context
    # case benefits from being phrased well. Bulk CORROBORATES/UNRESOLVED
    # pairs (the majority once a metric recurs across many periods) get a
    # fast, deterministic template instead; app/reconcile.py's
    # regenerate_explanation() can upgrade any specific relation afterwards
    # -- used to polish the handful of cases picked for the demo.
    use_llm = verdict in ("CONTRADICTS", "RECONCILED_BY_CONTEXT")
    explanation, explained_by = _explain_with_llm(adapter if use_llm else None, a, b, verdict, axis, trace)

    relation_id = new_id()
    conn.execute(
        """INSERT INTO relations (
            id, claim_id_a, claim_id_b, verdict, axis, dimension_diff_json,
            rule_trace_json, explanation, explained_by, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            relation_id, claim_id_a, claim_id_b, verdict, axis, dumps(dimension_diff),
            dumps(trace), explanation, explained_by, datetime.now(timezone.utc).isoformat(),
        ),
    )
    return relation_id


def regenerate_explanation(conn, adapter, relation_id: str) -> None:
    """Force a fresh LLM-written explanation for one existing relation,
    regardless of its verdict. Used to polish the small number of relations
    picked out as the four showcase cases, without paying LLM cost on every
    one of the (potentially thousands of) bulk relations in a full run."""
    rel = conn.execute("SELECT * FROM relations WHERE id = ?", (relation_id,)).fetchone()
    a = conn.execute("SELECT * FROM claims WHERE id = ?", (rel["claim_id_a"],)).fetchone()
    b = conn.execute("SELECT * FROM claims WHERE id = ?", (rel["claim_id_b"],)).fetchone()
    trace = loads(rel["rule_trace_json"])
    explanation, explained_by = _explain_with_llm(adapter, a, b, rel["verdict"], rel["axis"], trace)
    conn.execute(
        "UPDATE relations SET explanation = ?, explained_by = ? WHERE id = ?",
        (explanation, explained_by, relation_id),
    )


def reconcile_pairs(conn, adapter, pairs: list[tuple[str, str]], progress_cb=None) -> dict:
    counts = {"CORROBORATES": 0, "CONTRADICTS": 0, "RECONCILED_BY_CONTEXT": 0, "UNRESOLVED": 0}
    for i, (id_a, id_b) in enumerate(pairs):
        relation_id = reconcile_pair(conn, adapter, id_a, id_b)
        row = conn.execute("SELECT verdict FROM relations WHERE id = ?", (relation_id,)).fetchone()
        counts[row["verdict"]] += 1
        if progress_cb:
            progress_cb(i + 1, len(pairs))
    return counts
