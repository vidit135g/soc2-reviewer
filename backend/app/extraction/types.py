"""Shared types for the extraction package.

Every per-field extractor returns a :class:`FieldExtraction`. The pipeline
collects them into an :class:`ExtractionBundle` which is converted into an
``ExtractedMetadata`` (Pydantic) for the rest of the app — plus a
``field_confidence`` side-channel so the frontend can show per-field
confidence badges and the LLM augmenter can know which fields to target.

Design goals:

- **One shape everywhere.** Whether a field was pulled by regex, font
  prominence, LLM, or left missing, the extractor returns the same
  dataclass. Nothing upstream has to branch on method.
- **Trustworthy confidence.** ``HIGH`` is reserved for deterministic
  matches with a strong anchor (cover page big-font + LLC suffix, or a
  full ``for the period X through Y`` regex hit). ``MEDIUM`` is for
  heuristic-with-quibbles (title-case line, single date, etc.).
  ``LOW`` is "we guessed" — the LLM fallback should run. ``NONE`` means
  the rule explicitly couldn't find anything — again, LLM fallback.
- **Evidence preserved.** The short excerpt that produced the match is
  kept so the UI can show it on hover and audit logs can justify the
  decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

T = TypeVar("T")


class Confidence(str, Enum):
    """Confidence levels for an extracted field.

    String-based enum so it serialises cleanly through Pydantic JSON
    and the frontend can pattern-match the label directly.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"  # rule ran, found nothing — LLM should attempt

    def is_strong(self) -> bool:
        return self is Confidence.HIGH


# Narrow string literal for the *method* that produced a value. The
# pipeline uses these to decide whether the LLM stage should attempt to
# replace or supplement the rule-based result.
ExtractionMethod = Literal[
    "rule_regex",       # plain regex hit
    "rule_font",        # visual prominence on the cover page
    "rule_heading",     # matched a known heading cue
    "rule_table",       # came out of a pdfplumber table
    "rule_metadata",    # pulled from PDF /Info dict
    "rule_composite",   # combined several rule signals
    "llm",              # LLM augmentation
    "llm_guided",       # LLM with a strong contextual anchor
    "fallback",         # a "best guess" low-confidence default
    "missing",          # nothing found
]


@dataclass
class FieldExtraction(Generic[T]):
    """A single extracted field with metadata.

    Attributes:
        value: The extracted value. ``None`` means no value could be
            determined. The type parameter is whatever the field
            naturally is — str, list[str], date, etc.
        confidence: How much to trust ``value``.
        method: Which extractor produced the result.
        evidence: Short text snippet justifying the match (≤ 300 chars).
            Used by the UI on hover and by the LLM fallback to decide
            whether to override.
        page_number: 1-indexed page where the evidence was found, when
            available.
        alternatives: Other candidates considered with their scores —
            useful for debugging ambiguous cases (multiple LLC names on
            a cover page, two date ranges in the same paragraph, etc.).
    """

    value: T | None = None
    confidence: Confidence = Confidence.NONE
    method: ExtractionMethod = "missing"
    evidence: str | None = None
    page_number: int | None = None
    alternatives: list[tuple[Any, float]] = field(default_factory=list)

    @property
    def is_present(self) -> bool:
        """True if there is *any* value — regardless of confidence."""
        if self.value is None:
            return False
        if isinstance(self.value, (list, str, dict)) and len(self.value) == 0:
            return False
        return True

    @property
    def should_defer_to_llm(self) -> bool:
        """True if the LLM stage should attempt to improve this result.

        We defer to the LLM when:
        - Nothing was found at all, OR
        - Confidence is LOW (i.e. the rule guessed).
        MEDIUM and HIGH are kept as-is; the rule-based extractor beats
        the LLM on deterministic phrasing and we don't want the LLM to
        replace a correct answer with a hallucinated paraphrase.
        """
        return self.confidence in {Confidence.LOW, Confidence.NONE}

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe payload for the schemas / frontend.

        Recursively normalises ``value`` so the result is safe to
        ``json.dumps()`` straight into the ``extracted_json`` JSONB
        column. Specifically: ``date`` -> ISO string, anything with
        a ``to_dict()`` method (e.g. :class:`CUECItem`) is unwrapped,
        and lists are mapped element-wise. Anything else is passed
        through unchanged.
        """

        def _normalise(x: Any) -> Any:
            if isinstance(x, date):
                return x.isoformat()
            # Nested rich types (CUECItem) — let them serialise themselves.
            to_d = getattr(x, "to_dict", None)
            if callable(to_d):
                return to_d()
            if isinstance(x, list):
                return [_normalise(i) for i in x]
            if isinstance(x, dict):
                return {k: _normalise(v) for k, v in x.items()}
            return x

        return {
            "value": _normalise(self.value),
            "confidence": self.confidence.value,
            "method": self.method,
            "evidence": (self.evidence or "")[:300] or None,
            "page_number": self.page_number,
        }


@dataclass
class ExtractionBundle:
    """All extracted fields for a report, keyed by canonical field name.

    The field names mirror ``ExtractedMetadata`` — ``company_name``,
    ``auditor_firm``, ``report_type``, etc. Downstream code pulls the
    ``value`` out for the primary schema and the full dict for the
    confidence side-channel.

    Convenience methods hide the None-checks so callers don't have to
    guard every access.
    """

    fields: dict[str, FieldExtraction[Any]] = field(default_factory=dict)

    def put(self, name: str, fe: FieldExtraction[Any]) -> None:
        self.fields[name] = fe

    def get(self, name: str) -> FieldExtraction[Any]:
        return self.fields.get(name, FieldExtraction())

    def value(self, name: str) -> Any:
        return self.get(name).value

    def low_confidence_fields(self) -> list[str]:
        """Names of fields where the LLM should take another shot."""
        return [n for n, fe in self.fields.items() if fe.should_defer_to_llm]

    def confidence_map(self) -> dict[str, dict[str, Any]]:
        return {n: fe.to_dict() for n, fe in self.fields.items()}


# CUECs get a richer type than a flat list of strings — we want the
# excerpt and page number per item for the UI.
@dataclass
class CUECItem:
    """A single Complementary User Entity Control reference."""

    text: str            # the control statement (first sentence is usually enough)
    page_number: int | None = None
    heading: str | None = None  # which CUEC-variant heading it lived under

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "page_number": self.page_number,
            "heading": self.heading,
        }
