"""Required-section detection.

SOC 2 reports MUST contain: Independent Auditor's Report, Management's
Assertion, System Description, Controls & Tests of Controls. CUECs,
Subservice Organizations, and Results / Exceptions are expected though
occasionally folded into another section.

This extractor returns two lists — present and missing — with canonical
keys (so the validator can map them to human labels and severities).
"""
from __future__ import annotations

import logging
import re

from .text_utils import page_number_for_offset
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)


REQUIRED_SECTIONS: dict[str, list[str]] = {
    "independent_auditor_report": [
        r"independent\s+service\s+auditor'?s?\s+report",
        r"independent\s+auditor'?s?\s+report",
        r"report\s+of\s+independent",
        r"report\s+of\s+the\s+independent",
        r"independent\s+accountant'?s?\s+report",
        r"independent\s+practitioner'?s?\s+report",
        r"auditor'?s?\s+opinion",
        r"section\s+(?:ii|2)\b[^\n]{0,100}(?:opinion|report)",
    ],
    "management_assertion": [
        r"management'?s?\s+assertion",
        r"assertion\s+of\s+.{0,30}management",
        r"written\s+assertion",
        r"assertion\s+by\s+(?:the\s+)?management",
        r"management'?s?\s+report",
        r"assertion\s+(?:report|letter|statement)",
        r"section\s+(?:i|1)\b[^\n]{0,100}assertion",
    ],
    "system_description": [
        r"description\s+of\s+.{0,40}system",
        r"system\s+description",
        r"section\s+(?:iii|3)\b.{0,40}description",
        r"description\s+of\s+(?:the\s+)?services?\s+organization'?s?\s+system",
        r"overview\s+of\s+(?:the\s+)?system",
        r"system\s+overview",
        r"infrastructure\s+and\s+software",
        r"description\s+of\s+services",
    ],
    "controls_and_tests": [
        r"tests?\s+of\s+controls",
        r"description\s+of\s+(?:tests|procedures)",
        r"trust\s+services?\s+criteria.{0,80}controls",
        r"section\s+(?:iv|4)\b.{0,80}controls",
        r"information\s+provided\s+by\s+the\s+service\s+auditor",
        r"control\s+(?:activities|objectives).{0,80}test",
        r"controls?,?\s+tests?,?\s+and\s+results?",
        r"testing\s+(?:performed|procedures)\s+by",
    ],
    "results_and_exceptions": [
        r"results?\s+of\s+(?:tests|testing|procedures)",
        r"test\s+results?",
        r"exceptions?\s+noted",
        r"no\s+exceptions?\s+(?:were\s+)?noted",
        r"no\s+(?:deviations|relevant\s+exceptions)",
        r"deviations?\s+(?:noted|identified)",
        r"observations?\s+(?:noted|identified)",
        r"no\s+(?:relevant\s+)?issues\s+(?:were\s+)?identified",
    ],
    "complementary_user_entity_controls": [
        r"complementary\s+user[- ]entity\s+controls?",
        r"\bcuecs?\b",
        r"user\s+(?:entity\s+)?control\s+considerations?",
        r"user\s+organization\s+controls?",
    ],
    "subservice_organizations": [
        r"subservice\s+organizations?",
        r"carve[- ]out\s+(?:method|approach)",
        r"inclusive\s+method",
        r"third[- ]party\s+service\s+providers?",
        r"sub[- ]?service\s+providers?",
    ],
}


def extract_sections(full_text: str) -> tuple[
    FieldExtraction[list[str]],
    FieldExtraction[list[str]],
    dict[str, int | None],  # key -> page_number
]:
    """Return (present, missing, page_map)."""
    present: list[str] = []
    missing: list[str] = []
    page_map: dict[str, int | None] = {}

    for key, patterns in REQUIRED_SECTIONS.items():
        hit_offset: int | None = None
        for p in patterns:
            m = re.search(p, full_text, re.IGNORECASE)
            if m:
                hit_offset = m.start()
                break
        if hit_offset is not None:
            present.append(key)
            page_map[key] = page_number_for_offset(full_text, hit_offset)
        else:
            missing.append(key)
            page_map[key] = None

    logger.debug("[EXTRACT][sections] present=%s missing=%s", present, missing)
    # Confidence: HIGH for the whole pass — regex against canonical heading
    # strings is very reliable.
    present_fe = FieldExtraction(
        value=present, confidence=Confidence.HIGH, method="rule_heading",
    )
    missing_fe = FieldExtraction(
        value=missing, confidence=Confidence.HIGH, method="rule_heading",
    )
    return present_fe, missing_fe, page_map
