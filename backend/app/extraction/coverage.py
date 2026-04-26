"""Coverage-period extraction.

User-reported phrasings that the old validator missed:

- "Jan 1, 2024 to Dec 31, 2024"
- "for the period from January 1, 2024 through December 31, 2024"
- "covering the period January 1, 2024 to December 31, 2024"
- "for the year ended December 31, 2024"
- "as of December 31, 2024, and for the year then ended"
- "for the six months ended June 30, 2024"
- "from 2024-01-01 through 2024-12-31"
- Type-I "as of" single date (no range — use as both start and end)

Strategy: run a battery of patterns in descending specificity, parse the
match, sanity-check (end > start, both dates real), pick the first hit.
Each pattern carries a confidence level so a full "from X through Y" hit
with both endpoint-words matched produces HIGH confidence while a loose
"X to Y" with both being real dates but no cue word produces MEDIUM.
"""
from __future__ import annotations

import logging
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import Callable

from .text_utils import (
    MONTHS,
    auditor_section,
    excerpt_around,
    parse_date_tokens,
    safe_date,
)
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)


@dataclass
class CoverageResult:
    start: date | None
    end: date | None
    evidence: str
    confidence: Confidence
    method_label: str  # for debugging / logs


def _year_end(d: date) -> date:
    return date(d.year, 12, 31)


def _year_start(d: date) -> date:
    return date(d.year, 1, 1)


def _last_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _first_of_month(year: int, month: int) -> date:
    return date(year, month, 1)


def _back_n_months(end: date, n: int) -> date | None:
    """Return the first day of the month that is ``n-1`` months before ``end``.

    For a coverage window of ``n`` months ending on ``end``, the start is
    the first of (end - (n-1) months).
    """
    year = end.year
    month = end.month - (n - 1)
    while month <= 0:
        month += 12
        year -= 1
    return safe_date(year, month, 1)


# ---------------------------------------------------------------------------
# Full range matchers — each produces (start, end) directly
# ---------------------------------------------------------------------------


_RANGE_PATTERNS: list[tuple[re.Pattern[str], Confidence, str]] = [
    (
        re.compile(
            rf"(?:for\s+the\s+period|throughout\s+the\s+period|during\s+the\s+period|over\s+the\s+period|covering\s+the\s+period)\s*"
            rf"(?:from\s+|of\s+|beginning\s+|commencing\s+)?"
            rf"(?P<start>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})\s*"
            rf"(?:through|thru|to|until|ending|ended|and\s+ending|and\s+ended|[-–—])\s*"
            rf"(?P<end>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})",
            re.IGNORECASE,
        ),
        Confidence.HIGH,
        "for_the_period_long",
    ),
    (
        re.compile(
            rf"(?:examination|audit|review|reporting|coverage)\s+period[:\s]+"
            rf"(?P<start>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})\s*"
            rf"(?:through|to|until|ending|[-–—])\s*"
            rf"(?P<end>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})",
            re.IGNORECASE,
        ),
        Confidence.HIGH,
        "examination_period_colon",
    ),
    (
        re.compile(
            r"(?:for\s+the\s+period|during\s+the\s+period|from|covering)\s+"
            r"(?P<start_y>\d{4})-(?P<start_mo>\d{2})-(?P<start_d>\d{2})\s*"
            r"(?:through|to|until|ending|[-–—])\s*"
            r"(?P<end_y>\d{4})-(?P<end_mo>\d{2})-(?P<end_d>\d{2})",
            re.IGNORECASE,
        ),
        Confidence.HIGH,
        "iso_range",
    ),
    (
        re.compile(
            rf"\bfrom\s+(?P<start>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})\s+"
            rf"(?:through|to|until)\s+"
            rf"(?P<end>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})",
            re.IGNORECASE,
        ),
        Confidence.HIGH,
        "from_X_through_Y",
    ),
    (
        re.compile(
            rf"(?P<start>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})\s*"
            rf"(?:through|thru|to|[-–—])\s*"
            rf"(?P<end>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})",
            re.IGNORECASE,
        ),
        Confidence.MEDIUM,
        "loose_X_through_Y",
    ),
]


# ---------------------------------------------------------------------------
# "Year ended" / "N months ended" — end-date only, infer start
# ---------------------------------------------------------------------------


# Word-number → int
_WORD_NUM = {
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


_YEAR_ENDED_RE = re.compile(
    rf"(?:for\s+the\s+)?(?:fiscal\s+)?year\s+(?:then\s+)?(?:ended|ending)\s+"
    rf"(?P<end>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})",
    re.IGNORECASE,
)

_N_MONTHS_ENDED_RE = re.compile(
    rf"(?:for\s+the\s+)?(?P<n>\d{{1,2}}|{'|'.join(_WORD_NUM.keys())})"
    rf"[-\s]months?\s+(?:then\s+)?(?:ended|ending)\s+"
    rf"(?P<end>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})",
    re.IGNORECASE,
)


def _parse_long_date(s: str) -> date | None:
    from .text_utils import _DATE_LONG
    m = _DATE_LONG.search(s)
    return parse_date_tokens(m.groupdict()) if m else None


def _year_ended_match(text: str) -> CoverageResult | None:
    m = _YEAR_ENDED_RE.search(text)
    if not m:
        return None
    end = _parse_long_date(m.group("end"))
    if not end:
        return None
    start = safe_date(end.year - 1, end.month, end.day)
    # But if end is Dec 31, a "year ended" conventionally means Jan 1 – Dec 31
    if end.month == 12 and end.day == 31:
        start = date(end.year, 1, 1)
    if not start:
        return None
    return CoverageResult(
        start=start,
        end=end,
        evidence=excerpt_around(text, m.start(), m.end(), 100),
        confidence=Confidence.HIGH,
        method_label="year_ended",
    )


def _n_months_ended_match(text: str) -> CoverageResult | None:
    m = _N_MONTHS_ENDED_RE.search(text)
    if not m:
        return None
    raw = m.group("n").lower()
    n = _WORD_NUM.get(raw)
    if n is None:
        try:
            n = int(raw)
        except ValueError:
            return None
    end = _parse_long_date(m.group("end"))
    if not end or n <= 0 or n > 24:
        return None
    start = _back_n_months(end, n)
    if not start:
        return None
    return CoverageResult(
        start=start,
        end=end,
        evidence=excerpt_around(text, m.start(), m.end(), 100),
        confidence=Confidence.HIGH,
        method_label=f"{n}_months_ended",
    )


# ---------------------------------------------------------------------------
# "as of X" — Type-I single-date case
# ---------------------------------------------------------------------------


_AS_OF_RE = re.compile(
    rf"\bas\s+of\s+(?P<end>(?:{MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}})",
    re.IGNORECASE,
)


def _as_of_match(text: str) -> CoverageResult | None:
    m = _AS_OF_RE.search(text)
    if not m:
        return None
    end = _parse_long_date(m.group("end"))
    if not end:
        return None
    # For Type I, the "coverage" is a single date. Record start == end so
    # the downstream "days = end - start" calc yields 0 and the scorer can
    # recognise it as a point-in-time exam rather than a missing window.
    return CoverageResult(
        start=end,
        end=end,
        evidence=excerpt_around(text, m.start(), m.end(), 100),
        confidence=Confidence.MEDIUM,
        method_label="as_of_type1",
    )


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


def _try_range_patterns(text: str) -> CoverageResult | None:
    for pattern, conf, label in _RANGE_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        groups = m.groupdict()
        if {"start_y", "start_mo", "start_d", "end_y", "end_mo", "end_d"} <= groups.keys():
            start = safe_date(int(groups["start_y"]), int(groups["start_mo"]), int(groups["start_d"]))
            end = safe_date(int(groups["end_y"]), int(groups["end_mo"]), int(groups["end_d"]))
        else:
            start = _parse_long_date(groups["start"] or "")
            end = _parse_long_date(groups["end"] or "")
        if not (start and end):
            continue
        if end <= start:
            continue
        # Sanity: reject absurd windows (> 3 years) — likely matched across docs
        if (end - start).days > 3 * 366:
            continue
        return CoverageResult(
            start=start,
            end=end,
            evidence=excerpt_around(text, m.start(), m.end(), 100),
            confidence=conf,
            method_label=label,
        )
    return None


_MATCHERS: list[Callable[[str], "CoverageResult | None"]] = [
    _try_range_patterns,
    _year_ended_match,
    _n_months_ended_match,
    _as_of_match,
]


def extract_coverage(full_text: str) -> tuple[FieldExtraction[date], FieldExtraction[date]]:
    """Return ``(coverage_start, coverage_end)`` as two FieldExtractions.

    We prefer matches inside the auditor's report section (tighter
    context, fewer false positives). If nothing hits there, we widen to
    the first 40k chars of the full text.
    """
    haystack_priority = []
    section = auditor_section(full_text, window=8000)
    if section:
        haystack_priority.append(("auditor_section", section))
    haystack_priority.append(("head_40k", full_text[:40_000]))
    haystack_priority.append(("full_text", full_text))

    for where, hay in haystack_priority:
        for matcher in _MATCHERS:
            res = matcher(hay)
            if not res or not res.start or not res.end:
                continue
            logger.debug(
                "[EXTRACT][coverage] hit via %s (%s) in %s: %s – %s",
                matcher.__name__, res.method_label, where, res.start, res.end,
            )
            start_fe = FieldExtraction(
                value=res.start,
                confidence=res.confidence,
                method="rule_regex",
                evidence=res.evidence,
            )
            end_fe = FieldExtraction(
                value=res.end,
                confidence=res.confidence,
                method="rule_regex",
                evidence=res.evidence,
            )
            return start_fe, end_fe

    logger.debug("[EXTRACT][coverage] no coverage window found")
    missing = FieldExtraction[date](value=None, confidence=Confidence.NONE, method="missing")
    return missing, FieldExtraction[date](value=None, confidence=Confidence.NONE, method="missing")
