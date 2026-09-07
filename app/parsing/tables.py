"""
Table extraction via pdfplumber, which is better than PyMuPDF at finding the
ruled grid of a table. A table's meaning depends on its row and column
headers, not on the words next to it on the page -- so tables are pulled out
as their own block type, rendered as a small pipe-delimited grid, rather than
being left as loose prose text that an LLM would have to re-guess the
structure of.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber

UNIT_PATTERN = re.compile(
    r"(?:in|amounts?\s+in|figures?\s+in|₹|Rs\.?|INR)\s*"
    r"(₹|Rs\.?|INR)?\s*"
    r"(crore|cr\.?|million|mn\.?|billion|bn\.?|lakh|lakhs|thousand|%|percent)",
    re.IGNORECASE,
)


@dataclass
class RawTable:
    page_num: int
    bbox: tuple[float, float, float, float]
    grid_text: str
    caption: str | None
    units_hint: str | None


def _render_grid(rows: list[list[str | None]]) -> str:
    lines = []
    for row in rows:
        cells = [(c or "").strip().replace("\n", " ") for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def _find_units_hint(*texts: str) -> str | None:
    for text in texts:
        if not text:
            continue
        m = UNIT_PATTERN.search(text)
        if m:
            return m.group(0).strip()
    return None


def extract_tables(path: str) -> dict[int, list[RawTable]]:
    """Returns {page_num (1-indexed): [RawTable, ...]}"""
    result: dict[int, list[RawTable]] = {}
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            try:
                tables = page.find_tables()
            except Exception:
                tables = []
            if not tables:
                continue
            page_tables = []
            full_text = page.extract_text() or ""
            for t in tables:
                try:
                    rows = t.extract()
                except Exception:
                    continue
                if not rows or not any(any(c for c in r) for r in rows):
                    continue
                # A real data table has at least two columns (a label column
                # plus at least one value column). Single-column "tables" are
                # almost always pdfplumber mistaking a text box or a running
                # header/footer for a ruled grid.
                max_cols = max((len(r) for r in rows), default=0)
                if max_cols < 2 or len(rows) < 2:
                    continue
                grid_text = _render_grid(rows)
                if not grid_text.strip():
                    continue
                # caption candidate: text on the page just above the table's top edge
                caption = None
                best_gap = None
                for line in (page.extract_text_lines() or []):
                    if line["bottom"] <= t.bbox[1]:
                        gap = t.bbox[1] - line["bottom"]
                        if gap >= 0 and (best_gap is None or gap < best_gap) and gap < 40:
                            best_gap = gap
                            caption = line["text"].strip()
                units_hint = _find_units_hint(caption or "", full_text[:400])
                page_tables.append(
                    RawTable(
                        page_num=page_num,
                        bbox=tuple(t.bbox),
                        grid_text=grid_text,
                        caption=caption,
                        units_hint=units_hint,
                    )
                )
            if page_tables:
                result[page_num] = page_tables
    return result
