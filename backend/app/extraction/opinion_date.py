"""Opinion (report) date extraction.

Every SOC 2 auditor's report is dated. The date appears near the end of
Section II, usually preceded by "Dated: ", "Date: ", "Report date: ", or
just trailing "Month Day, Year" on a line by itself above the firm
signature.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from .text_utils import auditor_section, excerpt_around, iter_dates, parse_date_tokens
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)


_DATE_CUE = re.compile(
    r"(?:report\s+date|date\s+of\s+(?:this\s+)?report|date\s+of\s+issuance|issued\s+on|signed\s+on|"
    r"dated)[:\s]+(?P<tail>[^\n]{5,80})",
    re.IGNORECASE,
)


def extract_opinion_date(full_text: str) -> FieldExtraction[date]:
    # Layer 1 — explicit "dated" / "report date:" cue
    m = _DATE_CUE.search(full_text[:120_000])
    if m:
        for _, d in iter_dates(m.group("tail")):
            ev = excerpt_around(full_text, m.start(), m.end(), 100)
            logger.debug("[EXTRACT][opinion_date] cue hit: %s", d)
            return FieldExtraction(
                value=d, confidence=Confidence.HIGH, method="rule_regex", evidence=ev,
            )

    # Layer 2 — last date in the auditor section (they sign off at the end)
    section = auditor_section(full_text, window=8000)
    if section:
        dates = list(iter_dates(section))
        if dates:
            _, d = dates[-1]
            logger.debug("[EXTRACT][opinion_date] last-date-in-section: %s", d)
            return FieldExtraction(
                value=d,
                confidence=Confidence.MEDIUM,
                method="rule_regex",
                evidence=section[-300:],
            )

    logger.debug("[EXTRACT][opinion_date] not detected")
    return FieldExtraction(value=None, confidence=Confidence.NONE, method="missing")
