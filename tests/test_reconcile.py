"""
Tests for the rule engine that decides CORROBORATES / CONTRADICTS /
RECONCILED_BY_CONTEXT / UNRESOLVED. These rules are the part of the system
that must be objectively correct -- the LLM only writes prose around them --
so they get real unit tests, unlike the extraction step which depends on a
live model.
"""
import sqlite3

import pytest

from app.db import SCHEMA, dumps, new_id
from app.reconcile import reconcile_pair


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    yield c
    c.close()


def _insert_document(conn, meta=None):
    doc_id = new_id()
    conn.execute(
        "INSERT INTO documents (id, filename, sha256, page_count, uploaded_at, meta_json) "
        "VALUES (?, 'x.pdf', ?, 1, '2024-01-01', ?)",
        (doc_id, new_id(), dumps(meta or {})),
    )
    return doc_id


def _insert_block(conn, document_id):
    block_id = new_id()
    conn.execute(
        "INSERT INTO blocks (id, document_id, page_num, order_index, block_type, text) "
        "VALUES (?, ?, 1, 1, 'prose', 'x')",
        (block_id, document_id),
    )
    return block_id


def _insert_claim(conn, document_id, block_id, **kwargs):
    claim_id = new_id()
    defaults = dict(
        kind="numeric", subject="Acme", entity_id="e1", metric_raw="revenue", metric_id="m1",
        value_raw=None, value_number=None, value_unit=None, value_scale=None, value_normalized=None,
        state_value=None, period_label=None, period_type=None, period_start=None, period_end=None,
        qualifiers_json="{}", quote="some quote", page_num=1, bbox_json="[]",
        confidence=0.9, notes=None, created_at="2024-01-01",
    )
    defaults.update(kwargs)
    conn.execute(
        """INSERT INTO claims (
            id, document_id, block_id, kind, subject, entity_id, metric_raw, metric_id,
            value_raw, value_number, value_unit, value_scale, value_normalized, state_value,
            period_label, period_type, period_start, period_end, qualifiers_json,
            quote, page_num, bbox_json, confidence, notes, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (claim_id, document_id, block_id, *defaults.values()),
    )
    return claim_id


def test_corroborates_same_period_close_values():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1, doc2 = _insert_document(conn), _insert_document(conn)
    b1, b2 = _insert_block(conn, doc1), _insert_block(conn, doc2)
    a = _insert_claim(conn, doc1, b1, value_raw="8,142", value_number=8142, value_unit="INR",
                       value_scale="crore", value_normalized=81420000000.0,
                       period_label="FY24", period_type="fiscal_year",
                       period_start="2023-04-01", period_end="2024-03-31")
    b = _insert_claim(conn, doc2, b2, value_raw="81,415.38", value_number=81415.38, value_unit="INR",
                       value_scale="million", value_normalized=81415380000.0,
                       period_label="FY24", period_type="fiscal_year",
                       period_start="2023-04-01", period_end="2024-03-31")
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "CORROBORATES"


def test_contradicts_same_period_different_values():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1, doc2 = _insert_document(conn), _insert_document(conn)
    b1, b2 = _insert_block(conn, doc1), _insert_block(conn, doc2)
    a = _insert_claim(conn, doc1, b1, value_raw="6.5", value_number=6.5, value_unit="percent",
                       value_normalized=6.5, period_label="FY25", period_type="fiscal_year",
                       period_start="2024-04-01", period_end="2025-03-31")
    b = _insert_claim(conn, doc2, b2, value_raw="7.8", value_number=7.8, value_unit="percent",
                       value_normalized=7.8, period_label="FY25", period_type="fiscal_year",
                       period_start="2024-04-01", period_end="2025-03-31")
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "CONTRADICTS"


def test_reconciled_by_context_different_periods():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1, doc2 = _insert_document(conn), _insert_document(conn)
    b1, b2 = _insert_block(conn, doc1), _insert_block(conn, doc2)
    a = _insert_claim(conn, doc1, b1, value_raw="74,540.82", value_number=74540.82, value_unit="INR",
                       value_scale="million", value_normalized=74540820000.0,
                       period_label="FY24", period_type="fiscal_year",
                       period_start="2023-04-01", period_end="2024-03-31")
    b = _insert_claim(conn, doc2, b2, value_raw="66,586.61", value_number=66586.61, value_unit="INR",
                       value_scale="million", value_normalized=66586610000.0,
                       period_label="FY23", period_type="fiscal_year",
                       period_start="2022-04-01", period_end="2023-03-31")
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "RECONCILED_BY_CONTEXT"
    assert row["axis"] == "time"


def test_reconciled_by_context_standalone_vs_consolidated():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1 = _insert_document(conn)
    b1 = _insert_block(conn, doc1)
    a = _insert_claim(conn, doc1, b1, value_raw="74,540.82", value_number=74540.82,
                       value_unit="INR", value_scale="million", value_normalized=74540820000.0,
                       period_label="FY24", period_type="fiscal_year",
                       period_start="2023-04-01", period_end="2024-03-31",
                       qualifiers_json=dumps({"basis": "standalone"}))
    b = _insert_claim(conn, doc1, b1, value_raw="81,415.38", value_number=81415.38,
                       value_unit="INR", value_scale="million", value_normalized=81415380000.0,
                       period_label="FY24", period_type="fiscal_year",
                       period_start="2023-04-01", period_end="2024-03-31",
                       qualifiers_json=dumps({"basis": "consolidated"}))
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "RECONCILED_BY_CONTEXT"
    assert row["axis"] == "scope"


def test_unresolved_when_period_unknown_on_both_sides():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1, doc2 = _insert_document(conn), _insert_document(conn)
    b1, b2 = _insert_block(conn, doc1), _insert_block(conn, doc2)
    a = _insert_claim(conn, doc1, b1, value_raw="100", value_number=100, value_normalized=None)
    b = _insert_claim(conn, doc2, b2, value_raw="200", value_number=200, value_normalized=None)
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "UNRESOLVED"


def test_entity_state_corroborates_same_status():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1, doc2 = _insert_document(conn), _insert_document(conn)
    b1, b2 = _insert_block(conn, doc1), _insert_block(conn, doc2)
    a = _insert_claim(conn, doc1, b1, kind="entity_state", state_value="Independent Director")
    b = _insert_claim(conn, doc2, b2, kind="entity_state", state_value="independent director")
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "CORROBORATES"


def test_entity_state_reconciled_by_time_when_documents_dated_differently():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1 = _insert_document(conn, meta={"inferred_as_of": "2022-03-31"})
    doc2 = _insert_document(conn, meta={"inferred_as_of": "2024-03-31"})
    b1, b2 = _insert_block(conn, doc1), _insert_block(conn, doc2)
    a = _insert_claim(conn, doc1, b1, kind="entity_state", state_value="active")
    b = _insert_claim(conn, doc2, b2, kind="entity_state", state_value="resigned")
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "RECONCILED_BY_CONTEXT"
    assert row["axis"] == "time"


def test_entity_state_contradicts_when_no_date_context():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    doc1, doc2 = _insert_document(conn), _insert_document(conn)
    b1, b2 = _insert_block(conn, doc1), _insert_block(conn, doc2)
    a = _insert_claim(conn, doc1, b1, kind="entity_state", state_value="active")
    b = _insert_claim(conn, doc2, b2, kind="entity_state", state_value="resigned")
    rel_id = reconcile_pair(conn, None, a, b)
    row = conn.execute("SELECT * FROM relations WHERE id=?", (rel_id,)).fetchone()
    assert row["verdict"] == "CONTRADICTS"
