"""Trust Service Criteria detection.

SOC 2 scopes one or more of: Security, Availability, Confidentiality,
Processing Integrity, Privacy. Security is always implicit — if any
criterion is present, Security should be too.

Strong signal: the explicit criteria callout (CC1.1, A1.2, C1.1 etc.)
framework references. Weaker signal: narrative mentions tied to a
"trust services" phrase.
"""
from __future__ import annotations

import logging
import re

from .text_utils import excerpt_around
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)


TRUST_CRITERIA: dict[str, list[str]] = {
    "Security": [
        r"\bsecurity\b.{0,80}(?:trust|criteria|principle)",
        r"common\s+criteria",
        r"\bCC[1-9]\.\d",
    ],
    "Availability": [
        r"\bavailability\b.{0,80}(?:trust|criteria|principle|tsc)",
        r"\bA[1-9]\.\d\b",
        r"availability\s+commitment",
    ],
    "Confidentiality": [
        r"\bconfidentiality\b.{0,80}(?:trust|criteria|principle|tsc)",
        r"\bC[1-9]\.\d\b",
        r"confidential\s+information",
    ],
    "Processing Integrity": [
        r"processing\s+integrity",
        r"\bPI[1-9]\.\d\b",
    ],
    "Privacy": [
        r"\bprivacy\b.{0,80}(?:trust|criteria|principle|tsc)",
        r"\bP[1-9]\.\d\b",
        r"privacy\s+notice",
        r"personally\s+identifiable\s+information",
    ],
}


def extract_trust_service_criteria(full_text: str) -> FieldExtraction[list[str]]:
    found: list[str] = []
    evidence_snips: list[str] = []
    haystack = full_text[:200_000]
    for name, patterns in TRUST_CRITERIA.items():
        for p in patterns:
            m = re.search(p, haystack, re.IGNORECASE)
            if m:
                if name not in found:
                    found.append(name)
                    evidence_snips.append(excerpt_around(haystack, m.start(), m.end(), 80))
                break

    if not found:
        return FieldExtraction(value=[], confidence=Confidence.NONE, method="missing")

    # Security is always implicit once any criterion is in scope
    if "Security" not in found:
        found.insert(0, "Security")

    # HIGH if we saw any of the framework reference codes (CC1.1 etc.);
    # MEDIUM otherwise.
    has_codes = any(re.search(r"\b(?:CC|A|C|PI|P)\d\.\d\b", s) for s in evidence_snips)
    conf = Confidence.HIGH if has_codes else Confidence.MEDIUM

    logger.debug("[EXTRACT][criteria] %s (conf=%s)", found, conf.value)
    return FieldExtraction(
        value=found,
        confidence=conf,
        method="rule_regex",
        evidence=evidence_snips[0] if evidence_snips else None,
    )
