"""CUEC (Complementary User Entity Controls) extraction.

User-reported phrasings that the old validator missed:

- "Complementary User Entity Controls"
- "Complementary User-Entity Controls"  (hyphenated)
- "User Control Considerations"
- "Responsibilities of User Entities"
- "User Entity Responsibilities"
- "User Entity Controls"
- Just "CUECs" in a heading

Strategy:

1. Locate a CUEC heading via a variant-tolerant regex.
2. Capture the paragraph / list block that follows. Most reports use a
   bulleted list; some use numbered paragraphs.
3. Emit one ``CUECItem`` per bullet (with page number + a short excerpt).

If no heading is found we still scan for imperative sentences like
*"The user entity is responsible for..."* as a last-resort signal.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from .text_utils import (
    collapse_whitespace,
    dehyphenate,
    excerpt_around,
    page_number_for_offset,
    strip_page_markers,
)
from .types import Confidence, CUECItem, FieldExtraction

logger = logging.getLogger(__name__)


# All the headings SOC 2 reports use for CUEC sections. Ordered most to
# least specific so the highest-confidence heading wins when several
# match (some reports use both variants on the same page).
_CUEC_HEADINGS: list[tuple[str, str]] = [
    (
        r"complementary\s+user[-\s]?entity\s+controls?",
        "complementary_user_entity_controls",
    ),
    (
        r"complementary\s+user[-\s]?organizations?\s+controls?",
        "complementary_user_organization_controls",
    ),
    (
        r"user\s+(?:entity\s+)?control\s+considerations?",
        "user_control_considerations",
    ),
    (
        r"responsibilit(?:y|ies)\s+of\s+(?:the\s+)?user\s+entit(?:y|ies)",
        "responsibilities_of_user_entities",
    ),
    (
        r"user\s+entit(?:y|ies)\s+responsibilit(?:y|ies)",
        "user_entity_responsibilities",
    ),
    (
        r"user\s+entit(?:y|ies)\s+controls?",
        "user_entity_controls",
    ),
    (r"\bcuecs?\b", "cuecs_acronym"),
]


# Regex that matches an entire paragraph/list block. After the heading
# match we grab the next block (up to ~4000 chars) and split it into
# bullets. 4000 is enough for a typical list of 8-20 CUECs but short
# enough that we don't bleed into the next section.
_BLOCK_AFTER_HEADING_CHARS = 4500

# A "bullet" line starts with •, -, *, a digit + period, a lowercase
# letter + paren, or is a capital-leading sentence ≥ 40 chars. We also
# accept lines that begin with a control-framework marker like "UEC-01".
_BULLET_LEADER = re.compile(
    r"^\s*(?:"
    r"[•\-\*·‣◦▪]\s+|"
    r"\d{1,2}[\.\)]\s+|"
    r"[a-zA-Z][\.\)]\s+|"
    r"UEC[-_ ]?\d+[:\-\s]+|"
    r"CUEC[-_ ]?\d+[:\-\s]+"
    r")",
    re.IGNORECASE,
)

_RESPONSIBILITY_SENTENCE = re.compile(
    r"(?:the\s+user\s+entity|user\s+entities|user\s+organizations?|customers?)\s+"
    r"(?:is|are|should|must|shall|will)\s+responsible\s+for\s+[^.]{10,300}\.",
    re.IGNORECASE,
)


@dataclass
class _HeadingHit:
    start: int
    end: int
    variant: str
    heading_text: str


def _iter_heading_hits(text: str) -> Iterable[_HeadingHit]:
    """Yield every CUEC heading hit in order of appearance."""
    hits: list[_HeadingHit] = []
    for pattern, variant in _CUEC_HEADINGS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            hits.append(
                _HeadingHit(
                    start=m.start(),
                    end=m.end(),
                    variant=variant,
                    heading_text=m.group(0),
                )
            )
    hits.sort(key=lambda h: h.start)
    # De-dup overlapping hits within 50 chars (same heading matched by
    # multiple patterns)
    out: list[_HeadingHit] = []
    for h in hits:
        if out and (h.start - out[-1].start) < 80:
            continue
        out.append(h)
    return out


def _clean_bullet(line: str) -> str:
    line = strip_page_markers(line)
    # Drop the leader
    line = _BULLET_LEADER.sub("", line, count=1)
    return collapse_whitespace(dehyphenate(line)).strip(" -•*·‣◦▪:")


def _split_bullets(block: str) -> list[tuple[int, str]]:
    """Split a block of text into (offset_in_block, bullet_text) pairs.

    Uses the bullet leader as a split marker. Keeps the relative offset
    so the caller can convert back into a full-text offset for page
    lookups.
    """
    # Normalise bullet-style glyphs
    block = block.replace("\u2022", "•").replace("\u2023", "•")
    lines = block.splitlines()
    out: list[tuple[int, str]] = []
    running = 0
    current: list[str] = []
    current_offset = 0

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = _clean_bullet(" ".join(current))
        if text and len(text) > 15:
            out.append((current_offset, text))
        current = []

    for line in lines:
        line_len = len(line) + 1  # +1 for the newline
        if _BULLET_LEADER.match(line):
            flush()
            current_offset = running
            current = [line]
        else:
            if current:
                # Continuation of previous bullet
                current.append(line.strip())
        running += line_len
    flush()
    return out


def _extract_from_block(
    full_text: str,
    heading: _HeadingHit,
    block: str,
    block_origin: int,
) -> list[CUECItem]:
    bullets = _split_bullets(block)

    items: list[CUECItem] = []
    if bullets:
        for local_offset, bullet_text in bullets[:40]:  # cap 40 to avoid runaway
            abs_offset = block_origin + local_offset
            page = page_number_for_offset(full_text, abs_offset)
            # Truncate very long bullets to the first ~300 chars of the
            # first sentence so the UI stays readable.
            txt = bullet_text
            first_sentence = re.split(r"(?<=[.!?])\s+", txt, maxsplit=1)[0]
            if first_sentence and len(first_sentence) >= 30:
                txt = first_sentence
            items.append(
                CUECItem(
                    text=txt[:320],
                    page_number=page,
                    heading=heading.variant,
                )
            )
    else:
        # No bullets — fall back to responsibility-sentence extraction
        for m in _RESPONSIBILITY_SENTENCE.finditer(block):
            abs_offset = block_origin + m.start()
            page = page_number_for_offset(full_text, abs_offset)
            items.append(
                CUECItem(
                    text=collapse_whitespace(strip_page_markers(m.group(0)))[:320],
                    page_number=page,
                    heading=heading.variant,
                )
            )
    return items


def _dedupe(items: list[CUECItem]) -> list[CUECItem]:
    seen: set[str] = set()
    out: list[CUECItem] = []
    for it in items:
        key = re.sub(r"[^a-z0-9]", "", it.text.lower())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def extract_cuecs(full_text: str) -> FieldExtraction[list[CUECItem]]:
    """Extract CUEC items from the full report text.

    Returns a FieldExtraction whose ``value`` is a list of :class:`CUECItem`.
    If no CUEC content is found at all, the value is an empty list and
    the confidence is NONE.
    """
    headings = list(_iter_heading_hits(full_text))
    if not headings:
        # Last resort — responsibility sentences anywhere
        fallback_items: list[CUECItem] = []
        for m in _RESPONSIBILITY_SENTENCE.finditer(full_text):
            page = page_number_for_offset(full_text, m.start())
            fallback_items.append(
                CUECItem(
                    text=collapse_whitespace(strip_page_markers(m.group(0)))[:320],
                    page_number=page,
                    heading="responsibility_sentence",
                )
            )
        fallback_items = _dedupe(fallback_items)[:20]
        if fallback_items:
            logger.debug("[EXTRACT][cuecs] fallback: %d responsibility sentences", len(fallback_items))
            return FieldExtraction(
                value=fallback_items,
                confidence=Confidence.LOW,
                method="rule_regex",
                evidence=fallback_items[0].text[:240] if fallback_items else None,
            )
        return FieldExtraction(value=[], confidence=Confidence.NONE, method="missing")

    all_items: list[CUECItem] = []
    best_heading: _HeadingHit | None = None
    for heading in headings:
        block_start = heading.end
        block_end = min(len(full_text), heading.end + _BLOCK_AFTER_HEADING_CHARS)
        block = full_text[block_start:block_end]
        items = _extract_from_block(full_text, heading, block, block_start)
        if items and best_heading is None:
            best_heading = heading
        all_items.extend(items)

    all_items = _dedupe(all_items)[:40]
    if not all_items:
        # Heading present but no bullets could be parsed — still a signal.
        h = headings[0]
        ev = excerpt_around(full_text, h.start, h.end, 200)
        page = page_number_for_offset(full_text, h.start)
        logger.debug("[EXTRACT][cuecs] heading present but no bullets parsed")
        return FieldExtraction(
            value=[],
            confidence=Confidence.LOW,
            method="rule_heading",
            evidence=ev,
            page_number=page,
        )

    ref = best_heading or headings[0]
    page = page_number_for_offset(full_text, ref.start)
    logger.debug(
        "[EXTRACT][cuecs] %d items found under heading %r (page %s)",
        len(all_items), ref.variant, page,
    )
    return FieldExtraction(
        value=all_items,
        confidence=Confidence.HIGH if len(all_items) >= 3 else Confidence.MEDIUM,
        method="rule_heading",
        evidence=all_items[0].text[:240],
        page_number=page,
    )
