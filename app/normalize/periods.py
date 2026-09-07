"""
Parses the many ways a filing writes a time period into one shape: a start
date, an end date, and a period type. Two claims are only "about the same
period" if their (start, end) match exactly -- everything else (FY24 vs
FY 2023-24 vs "year ended March 31, 2024") is just a different spelling of
the same dates and should normalise down to one.

Assumption, stated plainly: fiscal years here follow the Indian convention
(April 1 - March 31), because every document in scope is India-focused. A
document that used a different fiscal calendar (say, US federal Oct-Sep)
would be mis-parsed by this module -- that is a real limitation, not
something the module can detect on its own, and it is called out in
context.md.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTH_NAME_RE = "|".join(MONTHS.keys())


@dataclass
class Period:
    label: str
    type: str  # fiscal_year | fiscal_quarter | fiscal_period_partial | calendar_year | custom_range
    start: date | None
    end: date | None


def _fy_end_year(digits: str) -> int:
    n = int(digits)
    if n < 100:
        return 2000 + n
    return n


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _fy_bounds(end_year: int) -> tuple[date, date]:
    """Indian FY: 1 Apr (end_year-1) to 31 Mar (end_year)."""
    return date(end_year - 1, 4, 1), date(end_year, 3, 31)


# Filings write the end-date either "Month Day, Year" (common in Indian
# filings, US-style) or "Day Month Year" (UK-style) -- both are supported.
_DATE_MDY_RE = re.compile(rf"({MONTH_NAME_RE})\.?\s+(\d{{1,2}}),?\s+(\d{{4}})", re.IGNORECASE)
_DATE_DMY_RE = re.compile(rf"(\d{{1,2}})\s+({MONTH_NAME_RE})\.?,?\s+(\d{{4}})", re.IGNORECASE)
_EXPLICIT_ENDED_RE = re.compile(
    rf"(nine\s+months?|six\s+months?|three\s+months?|quarter|year|period)\s+ended\s+(.{{0,30}})",
    re.IGNORECASE,
)


def _parse_date_either_order(text: str) -> tuple[int, int, int] | None:
    """Returns (year, month, day) from either date word order, or None."""
    m = _DATE_MDY_RE.search(text)
    if m:
        return int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))
    m = _DATE_DMY_RE.search(text)
    if m:
        return int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))
    return None
_Q_FY_RE = re.compile(r"\bQ([1-4])\s?[- ]?\s?FY\s?'?(\d{2,4})\b", re.IGNORECASE)
_NM_FY_RE = re.compile(r"\b(9|6|3)\s?M\s?FY\s?'?(\d{2,4})\b", re.IGNORECASE)
_FY_RANGE_RE = re.compile(r"\bFY\s?'?(\d{2,4})\s?[-–/]\s?(\d{2,4})\b", re.IGNORECASE)
_FY_SINGLE_RE = re.compile(r"\bFY\s?'?(\d{2,4})\b", re.IGNORECASE)
_CY_RE = re.compile(r"\bCY\s?'?(\d{4})\b|\bcalendar year\s+(\d{4})\b", re.IGNORECASE)
_MONTH_RANGE_RE = re.compile(
    rf"({MONTH_NAME_RE})\.?\s*[-–—]\s*({MONTH_NAME_RE})\.?\s+(\d{{4}})", re.IGNORECASE
)
_BARE_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")

_DURATION_TO_QUARTERS = {
    "quarter": 1, "three months": 1,
    "six months": 2,
    "nine months": 3,
    "year": 4, "period": 4,
}


def _fy_quarter_bounds(end_year: int, quarter: int) -> tuple[date, date]:
    """Indian FY quarters: Q1=Apr-Jun, Q2=Jul-Sep, Q3=Oct-Dec, Q4=Jan-Mar."""
    start_month = [(4, end_year - 1), (7, end_year - 1), (10, end_year - 1), (1, end_year)][quarter - 1]
    month, year = start_month
    start = date(year, month, 1)
    end_month = month + 2
    end_year_actual = year
    if end_month > 12:
        end_month -= 12
        end_year_actual += 1
    end = _month_end(end_year_actual, end_month)
    return start, end


def parse_period(text: str) -> Period | None:
    if not text:
        return None

    m = _EXPLICIT_ENDED_RE.search(text)
    if m:
        duration_words, rest = m.group(1), m.group(2)
        parsed = _parse_date_either_order(rest)
        if parsed:
            year_i, month, day = parsed
            end = date(year_i, month, day)
            duration_key = re.sub(r"\s+", " ", duration_words.lower().rstrip("s"))
            if "nine" in duration_key:
                months_back, ptype = 9, "fiscal_period_partial"
            elif "six" in duration_key:
                months_back, ptype = 6, "fiscal_period_partial"
            elif "three" in duration_key or "quarter" in duration_key:
                months_back, ptype = 3, "fiscal_quarter"
            else:
                months_back, ptype = 12, "fiscal_year"
            start_month_index = month - months_back + 1
            start_year = year_i
            while start_month_index <= 0:
                start_month_index += 12
                start_year -= 1
            start = date(start_year, start_month_index, 1)
            return Period(label=m.group(0), type=ptype, start=start, end=end)

    m = _Q_FY_RE.search(text)
    if m:
        quarter, fy_digits = int(m.group(1)), m.group(2)
        end_year = _fy_end_year(fy_digits)
        start, end = _fy_quarter_bounds(end_year, quarter)
        return Period(label=m.group(0), type="fiscal_quarter", start=start, end=end)

    m = _NM_FY_RE.search(text)
    if m:
        n_months, fy_digits = int(m.group(1)), m.group(2)
        end_year = _fy_end_year(fy_digits)
        fy_start, _ = _fy_bounds(end_year)
        end_month = fy_start.month - 1 + n_months
        end_year_actual = fy_start.year
        while end_month > 12:
            end_month -= 12
            end_year_actual += 1
        end = _month_end(end_year_actual, end_month)
        return Period(label=m.group(0), type="fiscal_period_partial", start=fy_start, end=end)

    m = _FY_RANGE_RE.search(text)
    if m:
        end_year = _fy_end_year(m.group(2))
        start, end = _fy_bounds(end_year)
        return Period(label=m.group(0), type="fiscal_year", start=start, end=end)

    m = _CY_RE.search(text)
    if m:
        year = int(m.group(1) or m.group(2))
        return Period(label=m.group(0), type="calendar_year", start=date(year, 1, 1), end=date(year, 12, 31))

    m = _MONTH_RANGE_RE.search(text)
    if m:
        m1, m2, year = MONTHS[m.group(1).lower()], MONTHS[m.group(2).lower()], int(m.group(3))
        start = date(year, m1, 1)
        end = _month_end(year, m2)
        return Period(label=m.group(0), type="custom_range", start=start, end=end)

    m = _FY_SINGLE_RE.search(text)
    if m:
        end_year = _fy_end_year(m.group(1))
        start, end = _fy_bounds(end_year)
        return Period(label=m.group(0), type="fiscal_year", start=start, end=end)

    m = _BARE_YEAR_RE.search(text)
    if m:
        year = int(m.group(0))
        return Period(label=m.group(0), type="calendar_year", start=date(year, 1, 1), end=date(year, 12, 31))

    return None
