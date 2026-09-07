"""
Turns the raw output of pdf_reader + tables into the list of "blocks" that get
stored in the database -- each one carrying the context it inherits from the
document (section headings above it, a table's own caption and declared
units, and which reporting basis -- standalone or consolidated -- it sits
under, if the document says so nearby).

This inherited context is what later lets the reconciliation step recognise
"these two numbers differ because one is standalone and one is consolidated"
instead of just seeing two different numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.parsing.pdf_reader import read_pdf
from app.parsing.tables import extract_tables

BASIS_PATTERN = re.compile(r"\b(consolidated|standalone)\b", re.IGNORECASE)
HEADING_MAX_CHARS = 110


@dataclass
class Block:
    page_num: int
    order_index: int
    block_type: str  # 'prose' | 'table'
    text: str
    section_path: list[str]
    table_caption: str | None
    table_units: str | None
    basis: str | None
    bbox: tuple[float, float, float, float]


@dataclass
class DocumentStructure:
    page_count: int
    title: str | None
    doc_type: str | None
    blocks: list[Block] = field(default_factory=list)


def _overlaps(a, b, threshold: float = 0.6) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return False
    inter = (ix1 - ix0) * (iy1 - iy0)
    area_a = max(1.0, (ax1 - ax0) * (ay1 - ay0))
    return (inter / area_a) >= threshold


def _guess_doc_type(first_pages_text: str) -> str | None:
    text = first_pages_text.lower()
    checks = [
        ("prospectus", "prospectus"),
        ("annual report", "annual_report"),
        ("article iv", "imf_article_iv"),
        ("economic survey", "economic_survey"),
        ("earnings presentation", "earnings_presentation"),
        ("investor presentation", "earnings_presentation"),
        ("q4", "earnings_presentation"),
    ]
    for needle, label in checks:
        if needle in text:
            return label
    return None


def _guess_title(pages, body_font_size: float) -> str | None:
    for page in pages[:2]:
        candidates = [b for b in page.blocks if b.max_font_size > body_font_size * 1.3]
        candidates.sort(key=lambda b: -b.max_font_size)
        for b in candidates:
            t = " ".join(b.text.split())
            if 4 < len(t) < 140:
                return t
    return None


def _body_font_size(pages) -> float:
    """
    The font size most of the document's running text is set in. A plain
    median-of-blocks is misleading here: a single block is one paragraph (or
    one line, on a tightly laid-out page), so a document with lots of small
    tables and footnotes ends up with more *blocks* at small sizes than at
    body size, even though body size covers far more *characters*. Weighting
    each block's size by how much text it holds fixes that.
    """
    weighted: list[tuple[float, int]] = []
    for p in pages:
        for b in p.blocks:
            if b.max_font_size > 0 and b.text.strip():
                weighted.append((round(b.max_font_size, 1), len(b.text)))
    if not weighted:
        return 10.0
    weighted.sort(key=lambda x: x[0])
    total = sum(w for _, w in weighted)
    half = total / 2
    running = 0
    for size, w in weighted:
        running += w
        if running >= half:
            return size
    return weighted[-1][0]


def parse_document(path: str) -> DocumentStructure:
    page_count, pages = read_pdf(path)
    tables_by_page = extract_tables(path)

    body_font_size = _body_font_size(pages)

    first_text = "\n".join(b.text for p in pages[:3] for b in p.blocks)
    doc_type = _guess_doc_type(first_text)
    title = _guess_title(pages, body_font_size)

    blocks: list[Block] = []
    section_stack: list[tuple[float, str]] = []  # (font_size, heading_text)
    current_basis: str | None = None
    order = 0

    for page in pages:
        page_tables = tables_by_page.get(page.page_num, [])
        table_bboxes = [t.bbox for t in page_tables]

        for rb in page.blocks:
            is_heading = (
                rb.max_font_size > body_font_size * 1.15
                and len(rb.text.strip()) < HEADING_MAX_CHARS
                and not rb.text.strip().endswith(".")
                and "\n" not in rb.text.strip()
            )
            if is_heading:
                while section_stack and section_stack[-1][0] <= rb.max_font_size:
                    section_stack.pop()
                section_stack.append((rb.max_font_size, rb.text.strip()))

            m = BASIS_PATTERN.search(rb.text)
            if m:
                current_basis = m.group(1).lower()

            if any(_overlaps(rb.bbox, tb, 0.6) for tb in table_bboxes):
                continue  # this prose block is really inside a table; skip, table block covers it

            order += 1
            blocks.append(
                Block(
                    page_num=page.page_num,
                    order_index=order,
                    block_type="prose",
                    text=rb.text,
                    section_path=[h for _, h in section_stack],
                    table_caption=None,
                    table_units=None,
                    basis=current_basis,
                    bbox=rb.bbox,
                )
            )

        for t in page_tables:
            m = BASIS_PATTERN.search((t.caption or "") + " " + t.grid_text[:200])
            table_basis = m.group(1).lower() if m else current_basis
            order += 1
            blocks.append(
                Block(
                    page_num=page.page_num,
                    order_index=order,
                    block_type="table",
                    text=t.grid_text,
                    section_path=[h for _, h in section_stack],
                    table_caption=t.caption,
                    table_units=t.units_hint,
                    basis=table_basis,
                    bbox=t.bbox,
                )
            )

    return DocumentStructure(page_count=page_count, title=title, doc_type=doc_type, blocks=blocks)
