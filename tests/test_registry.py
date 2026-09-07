import sqlite3

from app.db import SCHEMA
from app.registry import resolve_metric


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def test_paraphrased_metric_merges():
    conn = _conn()
    id1 = resolve_metric(conn, "Revenue from Operations", "numeric")
    id2 = resolve_metric(conn, "revenue from services", "numeric")
    assert id1 == id2


def test_absolute_and_margin_do_not_merge():
    """Regression test for a real bug found while testing on the Delhivery
    earnings deck: "Adjusted EBITDA" and "Adjusted EBITDA margin" scored high
    on plain string similarity and were merging into one metric, which then
    made an absolute currency amount get compared against a percentage."""
    conn = _conn()
    id1 = resolve_metric(conn, "Adjusted EBITDA", "numeric")
    id2 = resolve_metric(conn, "Adjusted EBITDA margin", "numeric")
    assert id1 != id2


def test_service_ebitda_and_its_margin_do_not_merge():
    conn = _conn()
    id1 = resolve_metric(conn, "Service EBITDA", "numeric")
    id2 = resolve_metric(conn, "Service EBITDA margin", "numeric")
    assert id1 != id2


def test_cpi_and_wpi_inflation_do_not_merge():
    """Different indices with near-identical surrounding wording -- string
    similarity alone scores this pair very high (~0.92)."""
    conn = _conn()
    id1 = resolve_metric(conn, "CPI inflation", "numeric")
    id2 = resolve_metric(conn, "WPI inflation", "numeric")
    assert id1 != id2


def test_different_kind_never_merges_even_if_identical_text():
    conn = _conn()
    id1 = resolve_metric(conn, "independent director", "entity_state")
    id2 = resolve_metric(conn, "independent director", "numeric")
    assert id1 != id2
