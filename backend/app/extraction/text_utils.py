"""Shared text-processing helpers used across extractors.

Lives here rather than inside each extractor so:

- the same MONTHS / date regexes are reused without subtle drift,
- section locators (auditor report, management assertion, CUEC heading)
  are tested once, used everywhere,
- the :class:`PageAwareText` helper keeps `[page N]` markers aligned so
  every extractor can resolve evidence → page number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable

# ---------------------------------------------------------------------------
# Date helpers — lifted from the old validator so behaviour is preserved.
# ---------------------------------------------------------------------------

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

_DATE_LONG = re.compile(rf"\b(?P<m>{MONTHS})\.?\s+(?P<d>\d{{1,2}}),?\s+(?P<y>\d{{4}})\b")
_DATE_ISO = re.compile(r"\b(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})\b")
_DATE_SLASH = re.compile(r"\b(?P<mo>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})\b")

_MONTH_NUM: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def safe_date(y: int, m: int, d: int) -> date | None:
    """Build a ``date`` or return ``None`` on invalid components."""
    try:
        return date(y, m, d)
    except (ValueError, OverflowError):
        return None


def parse_month_name(name: str) -> int | None:
    return _MONTH_NUM.get(name.lower().strip(" ."))


def parse_date_tokens(tokens: dict[str, str]) -> date | None:
    """Parse a regex groupdict produced by one of the date patterns."""
    if "m" in tokens and "d" in tokens and "y" in tokens:
        month = parse_month_name(tokens["m"])
        if month is None:
            return None
        try:
            return safe_date(int(tokens["y"]), month, int(tokens["d"]))
        except ValueError:
            return None
    if {"y", "mo", "d"} <= tokens.keys():
        try:
            return safe_date(int(tokens["y"]), int(tokens["mo"]), int(tokens["d"]))
        except ValueError:
            return None
    return None


def iter_dates(text: str) -> Iterable[tuple[int, date]]:
    """Yield ``(char_offset, date)`` pairs from ``text``.

    Sorted by offset ascending so callers can pick the first / last /
    nearest match without re-sorting.
    """
    hits: list[tuple[int, date]] = []
    for pattern in (_DATE_LONG, _DATE_ISO, _DATE_SLASH):
        for m in pattern.finditer(text):
            parsed = parse_date_tokens(m.groupdict())
            if parsed:
                hits.append((m.start(), parsed))
    hits.sort(key=lambda x: x[0])
    return hits


# ---------------------------------------------------------------------------
# Section locators — find the auditor / management / CUEC regions so we
# can keep regex backtracking bounded and avoid false positives in
# boilerplate.
# ---------------------------------------------------------------------------


AUDITOR_HEADINGS = [
    r"independent service auditor'?s? report",
    r"independent auditor'?s? report",
    r"report of independent",
    r"independent accountant'?s? report",
    r"independent practitioner'?s? report",
    r"\bsection\s+(?:ii|2)\b[^\n]{0,100}(?:opinion|report)",
]

MANAGEMENT_HEADINGS = [
    r"management'?s? assertion",
    r"management'?s? report",
    r"assertion of .{0,30}management",
    r"written assertion",
    r"\bsection\s+(?:i|1)\b[^\n]{0,100}assertion",
]


def find_section(text: str, headings: list[str], window: int = 8000) -> tuple[int, str] | None:
    """Return ``(start_offset, section_text)`` for the first matching heading.

    ``window`` controls how many characters after the heading form the
    "section". 8k is enough to capture the auditor report + assertion
    without bleeding into Section IV tests-of-controls text.
    """
    for pat in headings:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.start(), text[m.start(): m.start() + window]
    return None


def auditor_section(text: str, window: int = 8000) -> str | None:
    hit = find_section(text, AUDITOR_HEADINGS, window)
    return hit[1] if hit else None


def management_section(text: str, window: int = 6000) -> str | None:
    hit = find_section(text, MANAGEMENT_HEADINGS, window)
    return hit[1] if hit else None


# ---------------------------------------------------------------------------
# Page-number resolution.
# ---------------------------------------------------------------------------

_PAGE_MARKER = re.compile(r"\[page (\d+)\]")


def page_number_for_offset(full_text: str, offset: int) -> int | None:
    """Given a character offset in ``full_text`` that contains ``[page N]``
    markers (produced by the PDF parser), return the page number the
    offset falls within. Returns ``None`` if no marker precedes it."""
    if offset < 0 or offset > len(full_text):
        return None
    last_page: int | None = None
    for m in _PAGE_MARKER.finditer(full_text, 0, offset + 1):
        try:
            last_page = int(m.group(1))
        except ValueError:
            continue
    return last_page


def strip_page_markers(text: str) -> str:
    return _PAGE_MARKER.sub("", text)


# ---------------------------------------------------------------------------
# Text tidying.
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")
_MULTISPACE_HYPHEN = re.compile(r"-\s+")


def collapse_whitespace(s: str) -> str:
    return _WHITESPACE.sub(" ", s).strip()


def dehyphenate(s: str) -> str:
    """Join hyphenated line breaks — 'con-\\ntrol' → 'control'."""
    return _MULTISPACE_HYPHEN.sub("-", s)


def excerpt_around(text: str, start: int, end: int, padding: int = 120) -> str:
    """Return a tidy snippet around a match — useful for `evidence`."""
    a = max(0, start - padding)
    b = min(len(text), end + padding)
    return collapse_whitespace(strip_page_markers(text[a:b]))


# ---------------------------------------------------------------------------
# Legal-entity suffixes — used by the company-name extractor and general
# normalisation.
# ---------------------------------------------------------------------------

ENTITY_SUFFIX_PATTERN = (
    r"(?:"
    r"Inc\.?|Incorporated|LLC|L\.L\.C\.|L\.P\.|LP|LLP|Ltd\.?|Limited|"
    r"Corp\.?|Corporation|Co\.?|Company|PLC|GmbH|AG|SE|S\.A\.|"
    r"Holdings?|Group|Technologies|Technology|Systems?|Solutions?|"
    r"Services?|Software"
    r")"
)


@dataclass
class PageAwareText:
    """Tiny helper that pairs the full concatenated text with the
    already-computed pages list.

    Passed to every extractor so they don't have to independently
    recompute page boundaries.
    """

    full_text: str
    pages: list[tuple[int, str]]  # [(page_num, page_text)]

    def iter_cover_lines(self, max_pages: int = 3, max_lines: int = 60) -> Iterable[tuple[int, str]]:
        """Yield ``(page_num, line)`` for the first few pages. Used by
        the company-name extractor's heuristic layer."""
        yielded = 0
        for page_num, text in self.pages[:max_pages]:
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                yield page_num, line
                yielded += 1
                if yielded >= max_lines:
                    return
