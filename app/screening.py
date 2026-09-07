"""
Step 3 of the pipeline: decide which blocks are even worth sending to a
language model, without calling one.

A 100-page report is mostly connective prose ("as discussed in the section
above...") that carries no comparable fact. Scoring blocks with cheap regexes
first means the expensive step (the LLM call) only runs on the fraction of
blocks that actually look fact-bearing, which is what keeps a large PDF's
processing time and cost roughly proportional to its *interesting* content
rather than its page count.
"""
from __future__ import annotations

import re

from app.parsing.segment import Block

NUMBER_PATTERN = re.compile(r"(?<!\w)[\(]?-?[₹$]?\s?\d[\d,]*\.?\d*\s?%?[\)]?")
CURRENCY_PATTERN = re.compile(r"₹|Rs\.?|INR|US\$|\$|crore|cr\b|million|billion|lakh", re.IGNORECASE)
PERIOD_PATTERN = re.compile(
    r"\bFY\s?\d{2,4}\b|\bQ[1-4]\s?FY\s?\d{2,4}\b|\b(19|20)\d{2}[-–](\d{2}|\d{4})\b|"
    r"\byear ended\b|\bnine months\b|\bquarter ended\b|\b(19|20)\d{2}\b",
    re.IGNORECASE,
)
STATE_VERB_PATTERN = re.compile(
    r"\b(resign(ed|ation)?|appoint(ed|ment)?|ceased|cessation|retir(ed|ement)|"
    r"re-?appoint(ed|ment)?|elected|removed|dissolved|superannuat\w*)\b",
    re.IGNORECASE,
)
MIN_TEXT_LEN = 8


def fact_score(block: Block) -> float:
    """0.0 (skip) to a few points (definitely worth extracting)."""
    text = block.text
    if len(text.strip()) < MIN_TEXT_LEN:
        return 0.0

    score = 0.0
    if block.block_type == "table":
        score += 1.5  # tables are almost always fact-dense

    n_numbers = len(NUMBER_PATTERN.findall(text))
    score += min(n_numbers, 6) * 0.4

    if CURRENCY_PATTERN.search(text):
        score += 0.6
    if PERIOD_PATTERN.search(text):
        score += 0.5
    if STATE_VERB_PATTERN.search(text):
        score += 1.2

    # Long blocks with no numbers and no state verbs are pure narrative --
    # don't let their length alone earn them a score.
    if n_numbers == 0 and not STATE_VERB_PATTERN.search(text):
        score *= 0.3

    return round(score, 2)


SCREEN_THRESHOLD = 0.6


def screen_blocks(blocks: list[Block]) -> list[tuple[Block, float]]:
    """Returns (block, score) pairs for blocks that clear the threshold,
    highest score first -- so if a run is time/cost-limited, the most
    promising blocks are processed first."""
    scored = [(b, fact_score(b)) for b in blocks]
    kept = [(b, s) for b, s in scored if s >= SCREEN_THRESHOLD]
    kept.sort(key=lambda x: -x[1])
    return kept
