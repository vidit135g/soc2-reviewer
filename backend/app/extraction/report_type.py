"""Report type classification (SOC 2 Type I vs Type II).

Type II explicitly tests operating effectiveness over a period — its
strong cues are "for the period … through …", "operated effectively
throughout the period", "operating effectiveness of the controls".

Type I tests design as of a point in time — "suitability of the design
of controls as of [date]".
"""
from __future__ import annotations

import logging
import re

from .text_utils import excerpt_around
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)

_TYPE_PATTERNS: list[tuple[str, list[str], Confidence]] = [
    (
        "SOC 2 Type II",
        [
            r"SOC\s*2\s*Type\s*(?:II|2)\b",
            r"Type\s*(?:II|2)\s*(?:SOC\s*2\s*)?report",
            r"Type\s*2\s+examination",
            r"(?:operating|operated)\s+effectively\s+(?:throughout|during|for)\s+the\s+period",
            r"suitability\s+of\s+(?:the\s+)?design\s+(?:and|&)\s+operating\s+effectiveness",
            r"operating\s+effectiveness\s+of\s+(?:the|those|these)\s+controls",
        ],
        Confidence.HIGH,
    ),
    (
        "SOC 2 Type I",
        [
            r"SOC\s*2\s*Type\s*(?:I|1)\b(?!I)",
            r"Type\s*(?:I|1)\s*(?:SOC\s*2\s*)?report(?!s)",
            r"Type\s*1\s+examination",
            r"suitability\s+of\s+(?:the\s+)?design\s+of\s+(?:the\s+)?controls?\s+as\s+of",
            r"design\s+of\s+controls?\s+as\s+of\s+[A-Z][a-z]+",
        ],
        Confidence.HIGH,
    ),
]

# Weaker heuristics — applied only if the explicit patterns fail.
_FALLBACK_TYPE_II = [
    r"\bfor\s+the\s+period\s+[A-Za-z0-9,\.\s]{3,60}(?:through|to)\b",
    r"\boperating\s+effectiveness\b",
]
_FALLBACK_TYPE_I = [
    r"\bas\s+of\s+[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}",
]


def extract_report_type(full_text: str) -> FieldExtraction[str]:
    head = full_text[:60_000]
    for label, patterns, conf in _TYPE_PATTERNS:
        for p in patterns:
            m = re.search(p, head, re.IGNORECASE)
            if m:
                ev = excerpt_around(head, m.start(), m.end(), padding=120)
                logger.debug("[EXTRACT][report_type] %s (canonical)", label)
                return FieldExtraction(
                    value=label, confidence=conf, method="rule_regex", evidence=ev,
                )

    # Fallbacks — medium confidence
    for p in _FALLBACK_TYPE_II:
        m = re.search(p, head, re.IGNORECASE)
        if m:
            logger.debug("[EXTRACT][report_type] Type II (fallback)")
            return FieldExtraction(
                value="SOC 2 Type II",
                confidence=Confidence.MEDIUM,
                method="rule_regex",
                evidence=excerpt_around(head, m.start(), m.end(), 120),
            )
    for p in _FALLBACK_TYPE_I:
        m = re.search(p, head, re.IGNORECASE)
        if m:
            logger.debug("[EXTRACT][report_type] Type I (fallback)")
            return FieldExtraction(
                value="SOC 2 Type I",
                confidence=Confidence.MEDIUM,
                method="rule_regex",
                evidence=excerpt_around(head, m.start(), m.end(), 120),
            )

    logger.debug("[EXTRACT][report_type] none detected")
    return FieldExtraction(value=None, confidence=Confidence.NONE, method="missing")
