"""Auditor opinion classification.

Four classes, ordered specific-negative → broadly-positive:

- ``adverse``: the controls were NOT effective / description does NOT fairly present
- ``disclaimer``: "unable to express an opinion"
- ``qualified``: "except for", "with the exception of"
- ``unqualified``: the clean opinion — "fairly presents", "suitably designed",
  "operated effectively", etc.

The old validator's patterns are largely preserved, but the classifier now
returns confidence (HIGH for a canonical phrase hit, MEDIUM for a
paraphrase match) and carries an ``evidence`` excerpt that the UI can
show on hover.
"""
from __future__ import annotations

import logging
import re

from .text_utils import auditor_section, excerpt_around
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)


# Each inner list is (label, patterns, confidence_for_match). Order matters;
# the first matching label wins. The list is duplicated for the auditor
# section and the full text, with full-text matches downgraded one step.

_PATTERNS: list[tuple[str, list[str], Confidence]] = [
    (
        "adverse",
        [
            r"\badverse\s+opinion\b",
            r"in\s+our\s+opinion[^.]{0,300}\b(?:were\s+not|are\s+not|did\s+not|do\s+not)\s+(?:suitably\s+)?(?:designed|operating|operate|effective)",
            r"in\s+our\s+opinion[^.]{0,300}\bnot\s+fairly\s+(?:presented|stated)",
            r"do\s+not\s+(?:fairly\s+)?present",
            r"the\s+description\s+does\s+not\s+fairly\s+present",
            r"were\s+not\s+suitably\s+designed\s+to\s+provide\s+reasonable\s+assurance",
            r"(?:controls|description)[^.]{0,80}\bnot\b[^.]{0,80}\boperating\s+effectively",
            r"the\s+stated\s+(?:control\s+)?objectives\s+were\s+not\s+achieved",
        ],
        Confidence.HIGH,
    ),
    (
        "disclaimer",
        [
            r"\bdisclaimer\s+of\s+opinion\b",
            r"we\s+(?:are\s+unable\s+to|cannot|do\s+not)\s+express\s+an\s+opinion",
            r"scope\s+of\s+(?:our\s+)?(?:work|examination)\s+(?:was|is)\s+not\s+sufficient",
            r"we\s+were\s+unable\s+to\s+obtain\s+sufficient",
            r"we\s+do\s+not\s+express\s+an\s+opinion",
        ],
        Confidence.HIGH,
    ),
    (
        "qualified",
        [
            r"\bqualified\s+opinion\b",
            r"\bexcept\s+for\s+(?:the\s+)?(?:matter|matters|effects?|issue|issues|deviation|deviations)",
            r"(?:our\s+)?opinion\s+is\s+qualified",
            r"qualified\s+with\s+respect\s+to",
            r"with\s+the\s+exception\s+of\s+(?:the\s+)?(?:matter|matters|controls?)",
            r"in\s+our\s+opinion[^.]{0,300}\bexcept\s+(?:for|as)\b",
            r"a\s+(?:material|significant)\s+(?:weakness|deficiency)\s+(?:was|has\s+been)\s+identified",
        ],
        Confidence.HIGH,
    ),
    (
        "unqualified",
        [
            r"\bunqualified\s+opinion\b",
            r"in\s+our\s+opinion[^.]{0,500}(?:fairly\s+presents?|present[s]?\s+fairly|(?:are|is)\s+(?:presented|stated)\s+fairly|(?:are|is)\s+fairly\s+(?:presented|stated))",
            r"in\s+our\s+opinion[^.]{0,500}(?:in\s+all\s+material\s+respects)",
            r"in\s+our\s+opinion[^.]{0,500}(?:suitably\s+designed|operating\s+effectively|operated\s+effectively)",
            r"in\s+our\s+opinion[^.]{0,500}(?:provide[sd]?\s+reasonable\s+assurance)",
            r"in\s+our\s+opinion[^.]{0,500}(?:achieve[sd]?\s+(?:its|the)\s+(?:control\s+)?objectives)",
            r"based\s+on\s+(?:our\s+)?(?:examination|audit|review)[^.]{0,500}(?:suitably\s+designed|operating\s+effectively|operated\s+effectively|fairly\s+(?:presented|stated))",
            r"the\s+controls[^.]{0,200}(?:were|are)[^.]{0,40}(?:suitably\s+designed|operating\s+effectively|operated\s+effectively)",
            r"management'?s?\s+assertion[^.]{0,200}(?:is|are)\s+fairly\s+(?:stated|presented)",
        ],
        Confidence.HIGH,
    ),
]


def _scan(text: str, downgrade: bool = False) -> tuple[str, str, Confidence] | None:
    for label, patterns, conf in _PATTERNS:
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                ev = excerpt_around(text, m.start(), m.end(), padding=150)
                if downgrade and conf is Confidence.HIGH:
                    conf = Confidence.MEDIUM
                return label, ev, conf
    return None


def extract_opinion(full_text: str) -> FieldExtraction[str]:
    # Prefer the auditor section — tight context dramatically reduces false
    # positives from incidental "except for" phrasing elsewhere.
    section = auditor_section(full_text, window=10_000)
    if section:
        hit = _scan(section, downgrade=False)
        if hit:
            label, ev, conf = hit
            logger.debug("[EXTRACT][opinion] section-hit: %s conf=%s", label, conf.value)
            return FieldExtraction(
                value=label,
                confidence=conf,
                method="rule_regex",
                evidence=ev,
            )

    # Fallback to the full text (weaker context → downgrade)
    hit = _scan(full_text[:120_000], downgrade=True)
    if hit:
        label, ev, conf = hit
        logger.debug("[EXTRACT][opinion] full-text-hit: %s conf=%s", label, conf.value)
        return FieldExtraction(
            value=label,
            confidence=conf,
            method="rule_regex",
            evidence=ev,
        )

    logger.debug("[EXTRACT][opinion] no opinion detected")
    return FieldExtraction(value=None, confidence=Confidence.NONE, method="missing")
