"""Test-exception detection.

Test exceptions are the most important "yellow flag" in a SOC 2 Type II
report. We return a tri-state: ``had_exceptions`` True/False and a short
human summary.

Strategy: a "no exceptions noted" phrase near the auditor opinion is a
strong False signal. A "the following exceptions were noted" phrase is
a strong True signal. If both appear, the True signal wins (the
negative boilerplate is the auditor confirming their standard, the
"following" phrase introduces actual findings).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .text_utils import excerpt_around
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)


@dataclass
class ExceptionsSummary:
    had_exceptions: bool
    summary: str


_NO_EXCEPTIONS = re.compile(r"no\s+exceptions?\s+(?:were\s+)?noted", re.IGNORECASE)
# Positive signal requires EITHER an explicit "the following exceptions…"
# lead-in OR a non-negated "exceptions were identified/noted". We use a
# negative lookbehind on "no " to avoid matching the "No exceptions were
# noted" boilerplate that appears in clean audits.
_YES_EXCEPTIONS = re.compile(
    r"(?<!no\s)(?<!no\s\s)"
    r"(?:the\s+following\s+exceptions?|"
    r"exceptions?\s+(?:were|was|have\s+been|has\s+been)\s+(?:noted|identified))",
    re.IGNORECASE,
)
_DEVIATION = re.compile(
    r"(?<!no\s)(?:a\s+)?deviations?\s+(?:was|were|has\s+been)\s+(?:noted|identified|observed)",
    re.IGNORECASE,
)
_ANY_EXCEPTION = re.compile(r"\bexception(?:s)?\b", re.IGNORECASE)


def extract_exceptions(full_text: str) -> FieldExtraction[str]:
    haystack = full_text[:400_000]

    # Count positive and negative mentions
    no_hits = list(_NO_EXCEPTIONS.finditer(haystack))
    yes_hits = list(_YES_EXCEPTIONS.finditer(haystack))
    dev_hits = list(_DEVIATION.finditer(haystack))
    total_ex = len(list(_ANY_EXCEPTION.finditer(haystack)))

    # True signals beat false ones
    if yes_hits or dev_hits:
        m = (yes_hits or dev_hits)[0]
        ev = excerpt_around(haystack, m.start(), m.end(), 180)
        return FieldExtraction(
            value="Exceptions identified during testing — review Section IV.",
            confidence=Confidence.HIGH,
            method="rule_regex",
            evidence=ev,
        )

    # Lots of "exception" occurrences but no "no exceptions" → probably has them
    if total_ex - len(no_hits) > 3:
        return FieldExtraction(
            value="Multiple references to exceptions found — review test results.",
            confidence=Confidence.MEDIUM,
            method="rule_regex",
        )

    if no_hits:
        m = no_hits[0]
        return FieldExtraction(
            value="The report states no exceptions were noted.",
            confidence=Confidence.HIGH,
            method="rule_regex",
            evidence=excerpt_around(haystack, m.start(), m.end(), 150),
        )

    return FieldExtraction(
        value="No explicit exceptions referenced.",
        confidence=Confidence.LOW,
        method="rule_regex",
    )


def exceptions_bool_from_summary(summary: str | None) -> bool:
    """Rough True/False flag derived from the summary — used by the scorer."""
    if not summary:
        return False
    s = summary.lower()
    if "no exceptions" in s or "no explicit" in s:
        return False
    if "exceptions identified" in s or "multiple references" in s:
        return True
    return False
