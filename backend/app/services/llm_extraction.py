"""LLM-backed semantic metadata augmentation.

The deterministic regex validator handles the canonical SOC 2 phrasing. Real
reports frequently paraphrase — e.g. "the controls were suitably designed and
operated effectively" instead of "unqualified opinion", or "during the audit
window of..." instead of "for the period... through...". This module uses an
LLM (Ollama by default — fully local, no API key) to extract the same metadata
from the auditor-report section, and fills in *only* the fields the regex
engine could not identify.

If no LLM is available the augmentation is a no-op — the regex result is
returned untouched.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from app.models.schemas import ExtractedMetadata
from app.services.llm_service import get_llm_provider

logger = logging.getLogger(__name__)

# We only send the auditor report + management assertion windows to the LLM —
# these contain every field we care about and bound token cost. For a 225-page
# report this is usually the first ~15 pages.
_AUGMENT_MAX_CHARS = 30_000
_OPINION_SECTION_CHARS = 12_000

_AUDITOR_SECTION_ANCHORS = (
    "independent service auditor",
    "independent auditor",
    "independent accountant",
    "auditor's opinion",
    "report of independent",
    "section ii",
    "section 2",
)


def _slice_opinion_region(text: str) -> str:
    """Return the auditor/management-assertion region if identifiable, else the first N chars."""
    head = text[:_AUGMENT_MAX_CHARS]
    lower = head.lower()
    earliest = -1
    for anchor in _AUDITOR_SECTION_ANCHORS:
        idx = lower.find(anchor)
        if idx >= 0 and (earliest == -1 or idx < earliest):
            earliest = idx
    if earliest >= 0:
        start = max(0, earliest - 500)
        return head[start : start + _OPINION_SECTION_CHARS]
    return head[:_OPINION_SECTION_CHARS]


_EXTRACTION_SYSTEM_PROMPT = """You are a SOC 2 audit-report metadata extractor.

Given an excerpt from a SOC 2 report (usually the independent auditor's report and/or management's assertion), extract the following fields. Use ONLY facts stated or clearly implied in the excerpt. Never invent.

Return a single JSON object with EXACTLY these keys. Use null for any field you cannot determine with confidence.

{
  "company_name": "the audited service organization — NOT the auditor firm",
  "auditor_firm": "the CPA firm that issued the report (e.g. Deloitte, KPMG, A-LIGN, Schellman, Coalfire, BDO)",
  "report_type": "SOC 2 Type I" | "SOC 2 Type II" | null,
  "opinion": "unqualified" | "qualified" | "adverse" | "disclaimer" | null,
  "opinion_reasoning": "one sentence quoting or paraphrasing the exact language that led to your opinion classification",
  "opinion_date": "YYYY-MM-DD (the date the auditor signed the report) or null",
  "coverage_start": "YYYY-MM-DD or null (Type II only — start of the examination period)",
  "coverage_end": "YYYY-MM-DD or null (Type II only — end of the examination period)",
  "trust_service_criteria": ["Security", "Availability", "Confidentiality", "Processing Integrity", "Privacy"] — include only those explicitly in scope,
  "subservice_organizations": ["e.g. Amazon Web Services", "Google Cloud"] — third-party providers carved out or included
}

OPINION CLASSIFICATION GUIDE:
- "unqualified" = auditor states the controls were suitably designed AND operating effectively / fairly presented / in all material respects. Look for phrases like "in our opinion, the description fairly presents", "controls were suitably designed and operated effectively", "provide reasonable assurance".
- "qualified" = "except for", "with the exception of", a material weakness identified but the overall system was otherwise effective.
- "adverse" = the controls were NOT operating effectively / did NOT provide reasonable assurance.
- "disclaimer" = "we are unable to express an opinion" or similar.

Return ONLY the JSON object, no prose, no markdown fences.
"""


def _build_user_prompt(excerpt: str, missing_fields: list[str]) -> str:
    focus = (
        "Fields still missing (focus on these): " + ", ".join(missing_fields)
        if missing_fields
        else "Extract all fields."
    )
    return (
        f"{focus}\n\n"
        "REPORT EXCERPT:\n"
        "-----\n"
        f"{excerpt}\n"
        "-----\n\n"
        "Return the JSON object."
    )


def _parse_iso_date(v: Any) -> date | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


_OPINIONS = {"unqualified", "qualified", "adverse", "disclaimer"}
_TYPES = {"SOC 2 Type I", "SOC 2 Type II"}
_VALID_CRITERIA = {"Security", "Availability", "Confidentiality", "Processing Integrity", "Privacy"}


def augment_metadata(
    full_text: str,
    metadata: ExtractedMetadata,
) -> tuple[ExtractedMetadata, dict[str, Any]]:
    """Fill in metadata fields the regex engine could not identify.

    Returns the (possibly updated) metadata and a diagnostic dict listing which
    fields were filled and the auditor's reasoning.
    """
    diag: dict[str, Any] = {"augmented_fields": [], "opinion_reasoning": None, "skipped": False}

    provider = get_llm_provider()
    if provider.is_stub:
        logger.info("LLM augmentation skipped: no provider configured (using stub)")
        diag["skipped"] = True
        return metadata, diag

    missing: list[str] = []
    if not metadata.company_name:
        missing.append("company_name")
    if not metadata.auditor_firm:
        missing.append("auditor_firm")
    if not metadata.report_type:
        missing.append("report_type")
    if not metadata.opinion:
        missing.append("opinion")
    if not metadata.opinion_date:
        missing.append("opinion_date")
    if not metadata.coverage_start:
        missing.append("coverage_start")
    if not metadata.coverage_end:
        missing.append("coverage_end")
    if not metadata.trust_service_criteria:
        missing.append("trust_service_criteria")

    # Even if everything was regex-extracted, still ask for opinion_reasoning
    # because users benefit from the quoted evidence. But only call the LLM if
    # we have at least SOMETHING to learn — skip if the regex got the 3 big
    # ones (opinion, type, coverage).
    must_call = bool(missing) or (metadata.opinion is None)
    if not must_call:
        logger.info("LLM augmentation skipped: regex extracted all high-value fields")
        return metadata, diag

    excerpt = _slice_opinion_region(full_text)
    if len(excerpt) < 200:
        logger.warning("Auditor region too short to augment (%d chars)", len(excerpt))
        diag["skipped"] = True
        return metadata, diag

    try:
        payload = provider.complete_json(
            _EXTRACTION_SYSTEM_PROMPT,
            _build_user_prompt(excerpt, missing),
            temperature=0.1,
            max_tokens=800,
        )
    except Exception as exc:
        logger.warning("LLM metadata augmentation failed: %s", exc)
        diag["skipped"] = True
        diag["error"] = str(exc)
        return metadata, diag

    if not isinstance(payload, dict) or not payload:
        logger.warning("LLM augmentation returned empty/invalid payload")
        diag["skipped"] = True
        return metadata, diag

    diag["opinion_reasoning"] = payload.get("opinion_reasoning")

    # ---- Merge: only fill fields that were None/empty --------------------
    changes = metadata.model_copy()
    filled: list[str] = []

    def fill_str(field: str, transform=None):
        current = getattr(changes, field, None)
        if current:
            return
        v = payload.get(field)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in {"null", "none", "unknown"}:
            value = v.strip()
            if transform:
                value = transform(value)
            setattr(changes, field, value)
            filled.append(field)

    def fill_date(field: str):
        current = getattr(changes, field, None)
        if current:
            return
        d = _parse_iso_date(payload.get(field))
        if d:
            setattr(changes, field, d)
            filled.append(field)

    fill_str("company_name")
    fill_str("auditor_firm")

    # report_type — validate against whitelist
    if not changes.report_type:
        rt = payload.get("report_type")
        if isinstance(rt, str) and rt.strip() in _TYPES:
            changes.report_type = rt.strip()
            filled.append("report_type")

    # opinion — validate against whitelist
    if not changes.opinion:
        op = payload.get("opinion")
        if isinstance(op, str) and op.strip().lower() in _OPINIONS:
            changes.opinion = op.strip().lower()
            filled.append("opinion")

    fill_date("opinion_date")
    fill_date("coverage_start")
    fill_date("coverage_end")

    # criteria — whitelist each item
    if not changes.trust_service_criteria:
        raw = payload.get("trust_service_criteria")
        if isinstance(raw, list):
            criteria = [c for c in raw if isinstance(c, str) and c in _VALID_CRITERIA]
            # Security is always implicit if any criteria are listed
            if criteria and "Security" not in criteria:
                criteria.insert(0, "Security")
            if criteria:
                changes.trust_service_criteria = criteria
                filled.append("trust_service_criteria")

    # subservices — free-form strings, dedup preserving order, cap 20
    if not changes.subservice_organizations:
        raw = payload.get("subservice_organizations")
        if isinstance(raw, list):
            seen: set[str] = set()
            subs: list[str] = []
            for s in raw:
                if isinstance(s, str) and s.strip() and s.strip() not in seen:
                    seen.add(s.strip())
                    subs.append(s.strip())
            if subs:
                changes.subservice_organizations = subs[:20]
                filled.append("subservice_organizations")

    # Coverage-end sanity: must be after coverage-start
    if changes.coverage_start and changes.coverage_end and changes.coverage_end <= changes.coverage_start:
        logger.warning("LLM returned invalid coverage window; discarding")
        changes.coverage_start = metadata.coverage_start
        changes.coverage_end = metadata.coverage_end
        filled = [f for f in filled if f not in {"coverage_start", "coverage_end"}]

    diag["augmented_fields"] = filled
    if filled:
        logger.info(
            "LLM augmented %d field(s): %s",
            len(filled),
            ", ".join(filled),
        )
    return changes, diag
