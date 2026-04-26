"""Subservice organization extraction.

Subservice orgs are third-party providers a SOC 2 report either
*carves out* (the audit assumes their controls are effective) or
*includes* (their controls are tested alongside). Typical suspects:
AWS, GCP, Azure, Cloudflare, Datadog, Snowflake, etc.

Strategy: find the "subservice organizations" heading / callout, then
match a curated list of known providers within the following ~2000
chars. Also accept a global sweep if the heading is present anywhere —
some reports list providers in a table.
"""
from __future__ import annotations

import logging
import re

from .text_utils import excerpt_around
from .types import Confidence, FieldExtraction

logger = logging.getLogger(__name__)


KNOWN_PROVIDERS: list[tuple[str, list[str]]] = [
    ("Amazon Web Services", [r"\bAmazon\s+Web\s+Services\b", r"\bAWS\b"]),
    ("Google Cloud Platform", [r"\bGoogle\s+Cloud\s+Platform\b", r"\bGCP\b", r"\bGoogle\s+Cloud\b"]),
    ("Microsoft Azure", [r"\bMicrosoft\s+Azure\b", r"\bAzure\b"]),
    ("Cloudflare", [r"\bCloudflare\b"]),
    ("Heroku", [r"\bHeroku\b"]),
    ("Salesforce", [r"\bSalesforce\b"]),
    ("Stripe", [r"\bStripe\b"]),
    ("Datadog", [r"\bDatadog\b"]),
    ("Snowflake", [r"\bSnowflake\b"]),
    ("DigitalOcean", [r"\bDigitalOcean\b"]),
    ("Okta", [r"\bOkta\b"]),
    ("MongoDB Atlas", [r"\bMongoDB\s+Atlas\b"]),
    ("Fastly", [r"\bFastly\b"]),
    ("Twilio", [r"\bTwilio\b"]),
    ("Auth0", [r"\bAuth0\b"]),
]


_SUBSERVICE_HEADING = re.compile(
    r"subservice\s+organizations?|sub[- ]?service\s+providers?|carve[- ]out\s+(?:method|approach)|inclusive\s+method",
    re.IGNORECASE,
)


def extract_subservices(full_text: str) -> FieldExtraction[list[str]]:
    # Find the subservice-org region
    m = _SUBSERVICE_HEADING.search(full_text)
    if not m:
        return FieldExtraction(value=[], confidence=Confidence.NONE, method="missing")

    region_start = m.start()
    region_end = min(len(full_text), m.end() + 3000)
    region = full_text[region_start:region_end]

    found: list[str] = []
    for canonical, patterns in KNOWN_PROVIDERS:
        for p in patterns:
            if re.search(p, region, re.IGNORECASE):
                if canonical not in found:
                    found.append(canonical)
                break

    if not found:
        # Heading was present but we couldn't match a known provider — that's
        # still weak evidence the report has subservice language.
        logger.debug("[EXTRACT][subservices] heading but no known providers")
        return FieldExtraction(
            value=[],
            confidence=Confidence.LOW,
            method="rule_heading",
            evidence=excerpt_around(full_text, m.start(), m.end(), 150),
        )

    logger.debug("[EXTRACT][subservices] %s", found)
    return FieldExtraction(
        value=found,
        confidence=Confidence.HIGH,
        method="rule_composite",
        evidence=excerpt_around(full_text, m.start(), m.end(), 150),
    )
