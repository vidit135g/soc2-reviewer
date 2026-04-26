"""Extraction pipeline orchestrator.

Contract: given a :class:`PDFParseResult`, return an
:class:`ExtractionBundle` with a :class:`FieldExtraction` for every
canonical metadata field. Rule-based extractors run first; the optional
LLM stage only fires on fields whose confidence is LOW or NONE.

This is the single entry point the rest of the app uses — it's the
boundary between "how do we extract SOC 2 metadata" and "how do we turn
that into Pydantic schemas + validation findings + a risk score".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.parsers.pdf_parser import PDFParseResult

from .auditor import extract_auditor
from .company import extract_company_name
from .coverage import extract_coverage
from .criteria import extract_trust_service_criteria
from .cuecs import extract_cuecs
from .exceptions import extract_exceptions
from .opinion import extract_opinion
from .opinion_date import extract_opinion_date
from .report_type import extract_report_type
from .sections import extract_sections
from .subservices import extract_subservices
from .types import Confidence, CUECItem, ExtractionBundle, FieldExtraction

logger = logging.getLogger(__name__)

# Field names the pipeline emits. Order here is the order they appear in
# logs / debugging output. Keep aligned with ExtractedMetadata.
FIELD_ORDER: list[str] = [
    "company_name",
    "auditor_firm",
    "report_type",
    "opinion",
    "opinion_date",
    "coverage_start",
    "coverage_end",
    "trust_service_criteria",
    "sections_present",
    "sections_missing",
    "complementary_user_entity_controls",
    "subservice_organizations",
    "exceptions_summary",
]


@dataclass
class PipelineResult:
    """Full pipeline output: the bundle, plus per-stage timing and a map
    of which fields the LLM touched."""

    bundle: ExtractionBundle
    stage_timings_ms: dict[str, float]
    sections_pages: dict[str, int | None]
    llm_augmented_fields: list[str]


def run_rule_extractors(parsed: PDFParseResult) -> tuple[ExtractionBundle, dict[str, int | None], dict[str, float]]:
    """Phase 1 — deterministic per-field extractors. No LLM."""
    bundle = ExtractionBundle()
    timings: dict[str, float] = {}

    def time_it(name: str, fn):  # type: ignore[no-untyped-def]
        t = time.perf_counter()
        result = fn()
        timings[name] = (time.perf_counter() - t) * 1000
        return result

    logger.info("[EXTRACT] rule-based phase start")

    bundle.put("company_name", time_it("company_name", lambda: extract_company_name(parsed)))
    bundle.put("auditor_firm", time_it("auditor_firm", lambda: extract_auditor(parsed.full_text)))
    bundle.put("report_type", time_it("report_type", lambda: extract_report_type(parsed.full_text)))
    bundle.put("opinion", time_it("opinion", lambda: extract_opinion(parsed.full_text)))
    bundle.put("opinion_date", time_it("opinion_date", lambda: extract_opinion_date(parsed.full_text)))

    cov_start_fe, cov_end_fe = time_it("coverage", lambda: extract_coverage(parsed.full_text))
    bundle.put("coverage_start", cov_start_fe)
    bundle.put("coverage_end", cov_end_fe)

    bundle.put(
        "trust_service_criteria",
        time_it("trust_service_criteria", lambda: extract_trust_service_criteria(parsed.full_text)),
    )

    sections_present_fe, sections_missing_fe, sections_pages = time_it(
        "sections", lambda: extract_sections(parsed.full_text),
    )
    bundle.put("sections_present", sections_present_fe)
    bundle.put("sections_missing", sections_missing_fe)

    bundle.put("complementary_user_entity_controls", time_it("cuecs", lambda: extract_cuecs(parsed.full_text)))
    bundle.put("subservice_organizations", time_it("subservices", lambda: extract_subservices(parsed.full_text)))
    bundle.put("exceptions_summary", time_it("exceptions", lambda: extract_exceptions(parsed.full_text)))

    summary_line = ", ".join(
        f"{name}={bundle.get(name).confidence.value}" for name in FIELD_ORDER
    )
    logger.info("[EXTRACT] rule-based phase done: %s", summary_line)
    return bundle, sections_pages, timings


# ---------------------------------------------------------------------------
# LLM fallback for low-confidence fields.
# ---------------------------------------------------------------------------


# Fields the LLM is allowed to fill when rules failed. We do NOT let the
# LLM override high-confidence rule matches — that would be a regression
# risk (LLM paraphrasing correct regex answers).
_LLM_FIELDS = {
    "company_name",
    "auditor_firm",
    "report_type",
    "opinion",
    "opinion_date",
    "coverage_start",
    "coverage_end",
    "trust_service_criteria",
    "subservice_organizations",
}


def run_llm_fallback(
    bundle: ExtractionBundle,
    full_text: str,
) -> list[str]:
    """Phase 2 — LLM augmentation for LOW / NONE fields.

    Delegates to the existing ``app.services.llm_extraction.augment_metadata``
    for the actual LLM call so we reuse its provider abstraction, prompt,
    and whitelisting. Fields filled by the LLM are flagged with
    ``confidence=MEDIUM`` and ``method="llm"``.
    """
    low_fields = [f for f in bundle.low_confidence_fields() if f in _LLM_FIELDS]
    if not low_fields:
        logger.info("[EXTRACT][llm] skipped — all fields at MEDIUM+ confidence")
        return []

    # Lazy import to avoid circular dependency (llm_extraction imports schemas
    # which are unrelated, but the guard is cheap).
    from app.models.schemas import ExtractedMetadata
    from app.services.llm_extraction import augment_metadata

    # Build a Pydantic view with ONLY the high/medium-confidence rule values
    # so the LLM augmenter's "only fill missing" logic targets the fields we
    # actually want.
    md_dict: dict[str, Any] = {}
    for name in FIELD_ORDER:
        fe = bundle.get(name)
        if fe.should_defer_to_llm:
            continue  # force the LLM to fill this
        if name in {"sections_present", "sections_missing", "exceptions_summary"}:
            continue  # never LLM-managed
        if fe.is_present:
            md_dict[name] = fe.value

    md_in = ExtractedMetadata(**md_dict)
    logger.info("[EXTRACT][llm] attempting fill for %s", low_fields)
    t = time.perf_counter()
    try:
        md_out, diag = augment_metadata(full_text, md_in)
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("[EXTRACT][llm] augmentation crashed: %s", exc)
        return []
    elapsed_ms = (time.perf_counter() - t) * 1000
    logger.info("[EXTRACT][llm] done in %.0fms; filled=%s", elapsed_ms, diag.get("augmented_fields"))

    filled: list[str] = []
    opinion_reasoning = diag.get("opinion_reasoning")
    for field in diag.get("augmented_fields") or []:
        val = getattr(md_out, field, None)
        if val is None or (isinstance(val, (list, str)) and not val):
            continue
        # Opinion gets special treatment — keep the reasoning in evidence.
        evidence = opinion_reasoning if field == "opinion" and opinion_reasoning else None
        bundle.put(
            field,
            FieldExtraction(
                value=val,
                confidence=Confidence.MEDIUM,
                method="llm",
                evidence=evidence,
            ),
        )
        filled.append(field)
    return filled


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def run_pipeline(
    parsed: PDFParseResult,
    *,
    use_llm: bool = True,
) -> PipelineResult:
    """Full extraction: rules + optional LLM fallback."""
    bundle, sections_pages, timings = run_rule_extractors(parsed)

    llm_filled: list[str] = []
    if use_llm:
        t = time.perf_counter()
        try:
            llm_filled = run_llm_fallback(bundle, parsed.full_text)
        except Exception as exc:  # pragma: no cover
            logger.exception("[EXTRACT][llm] wrapper failed: %s", exc)
        timings["llm"] = (time.perf_counter() - t) * 1000

    return PipelineResult(
        bundle=bundle,
        stage_timings_ms=timings,
        sections_pages=sections_pages,
        llm_augmented_fields=llm_filled,
    )


# ---------------------------------------------------------------------------
# Bundle → ExtractedMetadata helpers.
# ---------------------------------------------------------------------------


def bundle_to_metadata_dict(bundle: ExtractionBundle) -> dict[str, Any]:
    """Build a dict suitable for ``ExtractedMetadata(**d)``.

    CUECs are flattened to a list of short strings so the existing
    Pydantic field (``complementary_user_entity_controls: list[str]``)
    continues to work; the richer :class:`CUECItem` objects live in the
    field-confidence side-channel for the UI.
    """
    d: dict[str, Any] = {}

    def v(name: str) -> Any:
        return bundle.get(name).value

    d["company_name"] = v("company_name")
    d["auditor_firm"] = v("auditor_firm")
    d["report_type"] = v("report_type")
    d["opinion"] = v("opinion")
    d["opinion_date"] = v("opinion_date")
    d["coverage_start"] = v("coverage_start")
    d["coverage_end"] = v("coverage_end")

    d["trust_service_criteria"] = v("trust_service_criteria") or []
    d["sections_present"] = v("sections_present") or []
    d["sections_missing"] = v("sections_missing") or []
    d["subservice_organizations"] = v("subservice_organizations") or []

    cuecs_raw = v("complementary_user_entity_controls") or []
    cuec_strings: list[str] = []
    for item in cuecs_raw:
        if isinstance(item, CUECItem):
            cuec_strings.append(item.text)
        elif isinstance(item, str):
            cuec_strings.append(item)
    d["complementary_user_entity_controls"] = cuec_strings

    ex_fe = bundle.get("exceptions_summary")
    d["exceptions_summary"] = ex_fe.value if isinstance(ex_fe.value, str) else None

    return d


def bundle_to_cuec_details(bundle: ExtractionBundle) -> list[dict[str, Any]]:
    """Rich CUEC items for the UI side-channel (text + page + heading)."""
    raw = bundle.get("complementary_user_entity_controls").value or []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, CUECItem):
            out.append(item.to_dict())
    return out
