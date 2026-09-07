from datetime import date

from app.normalize.periods import parse_period


def test_fy_single():
    p = parse_period("FY24")
    assert p.type == "fiscal_year"
    assert p.start == date(2023, 4, 1)
    assert p.end == date(2024, 3, 31)


def test_fy_range():
    p = parse_period("FY 2023-24")
    assert p.type == "fiscal_year"
    assert p.start == date(2023, 4, 1)
    assert p.end == date(2024, 3, 31)


def test_fy_range_and_single_agree():
    assert parse_period("FY24").end == parse_period("FY 2023-24").end
    assert parse_period("FY24").start == parse_period("FY 2023-24").start


def test_year_ended_march():
    p = parse_period("year ended March 31, 2024")
    assert p.type == "fiscal_year"
    assert p.start == date(2023, 4, 1)
    assert p.end == date(2024, 3, 31)


def test_year_ended_matches_fy_label():
    a = parse_period("FY24")
    b = parse_period("for the year ended March 31, 2024")
    assert a.start == b.start
    assert a.end == b.end


def test_quarter():
    p = parse_period("Q4 FY24")
    assert p.type == "fiscal_quarter"
    assert p.start == date(2024, 1, 1)
    assert p.end == date(2024, 3, 31)


def test_quarter_q1():
    p = parse_period("Q1 FY24")
    assert p.start == date(2023, 4, 1)
    assert p.end == date(2023, 6, 30)


def test_nine_months():
    p = parse_period("9M FY22")
    assert p.type == "fiscal_period_partial"
    assert p.start == date(2021, 4, 1)
    assert p.end == date(2021, 12, 31)


def test_nine_months_ended_date_matches_9m_fy_label():
    a = parse_period("nine months ended December 31, 2021")
    b = parse_period("9M FY22")
    assert a.start == b.start
    assert a.end == b.end


def test_calendar_year():
    p = parse_period("CY2024")
    assert p.type == "calendar_year"
    assert p.start == date(2024, 1, 1)
    assert p.end == date(2024, 12, 31)


def test_month_range_within_calendar_year():
    p = parse_period("April-November 2024")
    assert p.type == "custom_range"
    assert p.start == date(2024, 4, 1)
    assert p.end == date(2024, 11, 30)


def test_bare_year_defaults_to_calendar():
    p = parse_period("in 2024 the economy grew")
    assert p.type == "calendar_year"
    assert p.start == date(2024, 1, 1)
    assert p.end == date(2024, 12, 31)


def test_unparseable_returns_none():
    assert parse_period("sometime recently") is None


def test_none_and_empty():
    assert parse_period("") is None
    assert parse_period(None) is None
