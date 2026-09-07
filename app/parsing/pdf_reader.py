"""
Low-level PDF access. Everything here talks to PyMuPDF and hands back plain
dicts -- nothing above this module needs to know a PDF library exists.

The one thing worth explaining is column detection. PyMuPDF already groups
text into layout blocks (roughly: a paragraph, or one column-width chunk of a
two-column page) with a bounding box each. A plain top-to-bottom sort of those
blocks is right for single-column pages, but wrong for two-column ones: it
reads the first line of the left column, then the first line of the right
column (because they are at the same height), and welds two unrelated
sentences together. `order_blocks` fixes this by checking whether a page's
blocks cluster into a left group and a right group, and if so, sorting all of
the left group before all of the right group.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf

HEADER_ZONE_PT = 65
FOOTER_ZONE_PT = 65
MAX_HEADER_FOOTER_CHARS = 90


@dataclass
class RawBlock:
    page_num: int  # 1-indexed
    bbox: tuple[float, float, float, float]
    text: str
    max_font_size: float
    is_bold: bool
    column: int  # 0 = left/only, 1 = right


@dataclass
class PageInfo:
    page_num: int
    width: float
    height: float
    is_two_column: bool
    blocks: list[RawBlock] = field(default_factory=list)


def _block_text_and_font(block: dict) -> tuple[str, float, bool]:
    lines_out = []
    max_size = 0.0
    bold_votes = 0
    span_count = 0
    for line in block.get("lines", []):
        parts = []
        for span in line.get("spans", []):
            parts.append(span.get("text", ""))
            size = span.get("size", 0.0)
            if size > max_size:
                max_size = size
            span_count += 1
            font_name = span.get("font", "").lower()
            if "bold" in font_name or (span.get("flags", 0) & 16):
                bold_votes += 1
        lines_out.append("".join(parts))
    text = "\n".join(l for l in lines_out if l.strip())
    is_bold = span_count > 0 and bold_votes / span_count > 0.6
    return text, max_size, is_bold


def _looks_like_header_or_footer(bbox, text, page_height) -> bool:
    y0, y1 = bbox[1], bbox[3]
    if len(text.strip()) == 0:
        return True
    if len(text.strip()) > MAX_HEADER_FOOTER_CHARS:
        return False
    in_header_zone = y1 <= HEADER_ZONE_PT
    in_footer_zone = y0 >= page_height - FOOTER_ZONE_PT
    return in_header_zone or in_footer_zone


def _detect_two_column(blocks: list[dict], page_width: float) -> bool:
    """A page is treated as two-column when most blocks are narrow (less than
    ~58% of page width) and they clearly split into a left group and a right
    group. Wide blocks (a table or a paragraph spanning the full page width)
    are allowed to exist on an otherwise two-column page -- see the module
    docstring in segment.py for how those are handled, and the known
    limitation recorded in context.md when a wide block sits between columns.
    """
    if not blocks:
        return False
    narrow = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) < 0.58 * page_width]
    if len(narrow) < 0.6 * len(blocks):
        return False
    mid = page_width / 2
    centers = [(b["bbox"][0] + b["bbox"][2]) / 2 for b in narrow]
    left = sum(1 for c in centers if c < mid)
    right = sum(1 for c in centers if c >= mid)
    return left >= 1 and right >= 1


def read_pdf(path: str) -> tuple[int, list[PageInfo]]:
    doc = pymupdf.open(path)
    pages: list[PageInfo] = []
    try:
        for i, page in enumerate(doc):
            page_num = i + 1
            width, height = page.rect.width, page.rect.height
            raw = page.get_text("dict")
            candidate_blocks = []
            for b in raw.get("blocks", []):
                if b.get("type", 0) != 0:
                    continue  # skip images
                text, font_size, is_bold = _block_text_and_font(b)
                if not text.strip():
                    continue
                candidate_blocks.append(
                    {"bbox": tuple(b["bbox"]), "text": text, "font_size": font_size, "bold": is_bold}
                )

            body_blocks = [
                b for b in candidate_blocks
                if not _looks_like_header_or_footer(b["bbox"], b["text"], height)
            ]

            two_col = _detect_two_column(body_blocks, width)
            mid = width / 2

            def sort_key(b):
                if two_col:
                    center = (b["bbox"][0] + b["bbox"][2]) / 2
                    col = 0 if center < mid else 1
                    return (col, b["bbox"][1])
                return (b["bbox"][1], b["bbox"][0])

            body_blocks.sort(key=sort_key)

            page_blocks = []
            for b in body_blocks:
                center = (b["bbox"][0] + b["bbox"][2]) / 2
                col = 0 if (not two_col or center < mid) else 1
                page_blocks.append(
                    RawBlock(
                        page_num=page_num,
                        bbox=b["bbox"],
                        text=b["text"],
                        max_font_size=b["font_size"],
                        is_bold=b["bold"],
                        column=col,
                    )
                )
            pages.append(
                PageInfo(page_num=page_num, width=width, height=height, is_two_column=two_col, blocks=page_blocks)
            )
        return len(doc), pages
    finally:
        doc.close()
