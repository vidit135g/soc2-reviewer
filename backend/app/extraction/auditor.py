"""Auditor firm extraction.

Strategy: a known-firm list first (matches any of the Big 4 + common
SOC 2 specialist firms), then a generic "<Name>, LLP" fallback for
firms we don't have in the list yet. Only the first ~8k chars are
considered — any firm name later in the report is almost certainly
referenced (e.g. "we use Schellman for compliance") rather than the
audit firm itself.
"""
from __future__ import annotations

import logging
import re

from .text_utils import excerpt_around
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)

# Canonical display names — the extractor normalises to these. Ordered
# longest-first so "Grant Thornton" matches before a generic "Thornton"
# would.
KNOWN_AUDITORS: list[str] = [
    "PricewaterhouseCoopers", "PwC",
    "Ernst & Young", "EY",
    "Grant Thornton",
    "Prescient Assurance",
    "Insight Assurance",
    "Johanson Group",
    "Sensiba San Filippo", "Sensiba",
    "Moss Adams",
    "360 Advanced",
    "Tugboat Logic",
    "Deloitte", "KPMG", "BDO", "RSM", "Crowe",
    "A-LIGN", "A-lign",
    "Schellman", "Coalfire", "Armanino", "BPM", "Truvantis",
]

# Ensure we match longer names first so "A-LIGN" beats "align" anywhere
KNOWN_AUDITORS.sort(key=len, reverse=True)


# Compile once
_KNOWN_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(a) for a in KNOWN_AUDITORS) + r")\b",
    re.IGNORECASE,
)

# Generic LLP/PLLC fallback
_GENERIC_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z&\.\- ]{2,60}?),?\s+(?:LLP|PLLC|LLC|P\.C\.|CPAs?|LLP\.)\b",
)

# Cover-page footer cue — "prepared by" / "issued by" / "service auditor:"
_AUDITOR_CUE_PATTERN = re.compile(
    r"(?:prepared\s+by|issued\s+by|service\s+auditor[:\s]+|auditor[:\s]+)\s+"
    r"([A-Z][A-Za-z&\.\- ]{2,80}?)(?:\.|,|\n|$)",
    re.IGNORECASE,
)


def extract_auditor(full_text: str) -> FieldExtraction[str]:
    head = full_text[:15_000]

    # Layer 1 — known firms (HIGH)
    m = _KNOWN_PATTERN.search(head)
    if m:
        raw = m.group(1)
        # Canonicalise: find the case-preserving match in our known list
        canonical = next(
            (a for a in KNOWN_AUDITORS if a.lower() == raw.lower()),
            raw,
        )
        logger.debug("[EXTRACT][auditor] known firm hit: %s", canonical)
        return FieldExtraction(
            value=canonical,
            confidence=Confidence.HIGH,
            method="rule_regex",
            evidence=excerpt_around(head, m.start(), m.end(), 80),
        )

    # Layer 2 — "prepared by" cue (MEDIUM)
    m = _AUDITOR_CUE_PATTERN.search(head)
    if m:
        name = m.group(1).strip(" ,.;")
        logger.debug("[EXTRACT][auditor] cue hit: %s", name)
        return FieldExtraction(
            value=name,
            confidence=Confidence.MEDIUM,
            method="rule_heading",
            evidence=excerpt_around(head, m.start(), m.end(), 100),
        )

    # Layer 3 — generic <Name>, LLP (LOW)
    m = _GENERIC_PATTERN.search(head)
    if m:
        name = m.group(1).strip(" ,.")
        logger.debug("[EXTRACT][auditor] generic LLP hit: %s", name)
        return FieldExtraction(
            value=name + ", LLP",
            confidence=Confidence.LOW,
            method="rule_regex",
            evidence=excerpt_around(head, m.start(), m.end(), 80),
        )

    return FieldExtraction(value=None, confidence=Confidence.NONE, method="missing")
