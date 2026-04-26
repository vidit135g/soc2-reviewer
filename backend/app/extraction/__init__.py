"""Per-field metadata extraction for SOC 2 reports.

This package replaces the old inline-regex approach in
``app.validators.soc2_validator`` with specialist extractors that:

- run rule-based detection first (cheap, deterministic, no API needed),
- return a :class:`FieldExtraction` with ``{value, confidence, method,
  evidence, page_number}``,
- defer to the LLM only for low-confidence / missing fields.

Downstream code (the validator, the report service, the UI) talks to
the package through :func:`run_pipeline`.
"""
from .pipeline import (
    PipelineResult,
    bundle_to_cuec_details,
    bundle_to_metadata_dict,
    run_pipeline,
)
from .scoring import ScoringResult, score_report
from .types import (
    Confidence,
    CUECItem,
    ExtractionBundle,
    ExtractionMethod,
    FieldExtraction,
)

__all__ = [
    "Confidence",
    "CUECItem",
    "ExtractionBundle",
    "ExtractionMethod",
    "FieldExtraction",
    "PipelineResult",
    "ScoringResult",
    "bundle_to_cuec_details",
    "bundle_to_metadata_dict",
    "run_pipeline",
    "score_report",
]
