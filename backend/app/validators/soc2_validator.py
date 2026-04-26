"""SOC 2 validator.

Thin compatibility layer that delegates metadata extraction to
``app.extraction.run_pipeline`` and scoring to ``app.extraction.score_report``,
then compiles the set of validation findings (info / ok / warning /
critical) that the frontend renders.

Preserved contract: ``SOC2Validator.validate(parsed)`` returns a
:class:`ValidationResult` with ``metadata`` (Pydantic ExtractedMetadata),
``findings``, ``risk_score``, ``risk_rating``, ``report_age_days``.

What's new:
- ``validate`` accepts either a raw ``text`` string (legacy) or a
  ``PDFParseResult`` (preferred) so callers can hand us font-aware
  pages and the table pass.
- ``ValidationResult`` gains ``field_confidence``, ``category_scores``,
  and ``cuec_details`` side-channels.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.extraction import (
    ExtractionBundle,
    PipelineResult,
    bundle_to_cuec_details,
    bundle_to_metadata_dict,
    run_pipeline,
    score_report,
)
from app.extraction.scoring import ScoringResult
from app.models.schemas import ExtractedMetadata, ValidationFinding
from app.parsers.pdf_parser import PDFPage, PDFParseResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    metadata: ExtractedMetadata
    findings: list[ValidationFinding] = field(default_factory=list)
    risk_score: int = 0
    risk_rating: str = "Unknown"
    report_age_days: int | None = None

    # Side-channels (opt-in; backend-internal, surfaced to UI where useful)
    field_confidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    category_scores: dict[str, dict[str, Any]] = field(default_factory=dict)
    cuec_details: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Finding builders — one per field/check. Kept small + data-driven so the
# validator reads like a checklist.
# ---------------------------------------------------------------------------


SECTION_LABELS = {
    "independent_auditor_report": "Independent auditor report",
    "management_assertion": "Management assertion",
    "system_description": "System description",
    "controls_and_tests": "Controls & tests of controls",
    "results_and_exceptions": "Results / exceptions",
    "complementary_user_entity_controls": "Complementary user entity controls (CUECs)",
    "subservice_organizations": "Subservice organizations",
}
CRITICAL_SECTIONS = {
    "independent_auditor_report",
    "management_assertion",
    "system_description",
    "controls_and_tests",
}


def _low_text_finding(text: str) -> list[ValidationFinding]:
    if not text or len(text.strip()) < 1000:
        return [
            ValidationFinding(
                code="low_text_extraction",
                severity="critical",
                title="Very little text extracted",
                detail=(
                    "The uploaded PDF yielded minimal extractable text. "
                    "It may be scanned, image-based, or corrupted."
                ),
            )
        ]
    return []


def _report_type_findings(bundle: ExtractionBundle) -> list[ValidationFinding]:
    rt = bundle.get("report_type").value
    if not rt:
        return [
            ValidationFinding(
                code="unknown_report_type",
                severity="warning",
                title="Could not determine SOC 2 report type",
                detail=(
                    "Unable to detect Type I vs Type II from the report text. "
                    "Verify manually in Section I."
                ),
            )
        ]
    return [
        ValidationFinding(
            code="report_type_detected",
            severity="ok",
            title=f"{rt} report detected",
            detail=(
                "Type II reports cover a period of operating effectiveness; "
                "Type I covers design as of a point in time."
            ),
        )
    ]


def _opinion_findings(bundle: ExtractionBundle) -> list[ValidationFinding]:
    op = bundle.get("opinion").value
    if op is None:
        return [
            ValidationFinding(
                code="missing_opinion",
                severity="critical",
                title="Auditor opinion not detected",
                detail=(
                    "No clear auditor opinion (unqualified / qualified / adverse / "
                    "disclaimer) was identified. Confirm the auditor's report is present."
                ),
            )
        ]
    if op == "unqualified":
        return [
            ValidationFinding(
                code="opinion_unqualified",
                severity="ok",
                title="Unqualified ('clean') opinion",
                detail="The auditor expressed an unqualified opinion — the most favorable outcome.",
            )
        ]
    if op == "qualified":
        return [
            ValidationFinding(
                code="opinion_qualified",
                severity="warning",
                title="Qualified opinion",
                detail=(
                    "The auditor qualified the opinion. Review the 'except for' "
                    "clause to understand the scope of the qualification."
                ),
            )
        ]
    if op in {"adverse", "disclaimer"}:
        return [
            ValidationFinding(
                code=f"opinion_{op}",
                severity="critical",
                title=f"{op.title()} opinion",
                detail=(
                    f"A {op} opinion is a significant finding and indicates serious "
                    "issues with the controls or evidence. Escalate before onboarding."
                ),
            )
        ]
    return []


def _age_findings(
    opinion_date: date | None, today: date
) -> tuple[list[ValidationFinding], int | None]:
    if not opinion_date:
        return [], None
    age_days = (today - opinion_date).days
    if age_days > 365:
        return [
            ValidationFinding(
                code="stale_report",
                severity="critical",
                title=f"Report is {age_days // 30} months old",
                detail=(
                    "The report opinion date is more than 12 months old. Most vendor "
                    "reviewers require a report within the last 12 months, often with "
                    "a bridge letter."
                ),
            )
        ], age_days
    if age_days > 270:
        return [
            ValidationFinding(
                code="approaching_stale",
                severity="warning",
                title="Report approaching staleness",
                detail=(
                    f"The opinion is {age_days} days old. Request a bridge letter or "
                    "a newer report within the next few months."
                ),
            )
        ], age_days
    return [
        ValidationFinding(
            code="report_age_ok",
            severity="ok",
            title="Report age is acceptable",
            detail=f"Opinion date is {age_days} days old — within 12-month window.",
        )
    ], age_days


def _coverage_findings(
    bundle: ExtractionBundle,
) -> list[ValidationFinding]:
    start = bundle.get("coverage_start").value
    end = bundle.get("coverage_end").value
    rt = bundle.get("report_type").value
    findings: list[ValidationFinding] = []

    if not (start and end):
        if rt == "SOC 2 Type II":
            findings.append(
                ValidationFinding(
                    code="missing_coverage_period",
                    severity="warning",
                    title="Coverage period not identified",
                    detail="Could not detect a 'from X through Y' period in the report.",
                )
            )
        return findings

    days = (end - start).days
    if days <= 0:
        return findings  # Type I single-date; no coverage finding
    if days < 90:
        findings.append(
            ValidationFinding(
                code="very_short_coverage",
                severity="critical",
                title=f"Coverage period is only {days} days",
                detail=(
                    "Very short coverage windows limit the evidence of sustained "
                    "operating effectiveness. Many reviewers require at least 6 months."
                ),
            )
        )
    elif days < 180:
        findings.append(
            ValidationFinding(
                code="short_coverage",
                severity="warning",
                title=f"Short coverage period ({days} days)",
                detail=(
                    "Coverage is under 6 months. This is common for an initial Type II "
                    "but should mature to a 12-month window over time."
                ),
            )
        )
    else:
        findings.append(
            ValidationFinding(
                code="coverage_ok",
                severity="ok",
                title=f"Coverage period is {days} days",
                detail="Coverage window is a typical SOC 2 Type II duration.",
            )
        )
    return findings


def _criteria_findings(bundle: ExtractionBundle) -> list[ValidationFinding]:
    crit = bundle.get("trust_service_criteria").value or []
    if not crit:
        return [
            ValidationFinding(
                code="no_criteria_detected",
                severity="warning",
                title="Trust Service Criteria not identified",
                detail="Unable to detect which Trust Service Criteria are in scope.",
            )
        ]
    if "Security" in crit and len(crit) == 1:
        return [
            ValidationFinding(
                code="security_only",
                severity="info",
                title="Security-only scope",
                detail=(
                    "Only the Security criterion appears in scope. This is valid but may "
                    "not meet a reviewer's needs if availability or confidentiality matter."
                ),
            )
        ]
    return [
        ValidationFinding(
            code="criteria_identified",
            severity="ok",
            title=f"Trust Service Criteria: {', '.join(crit)}",
            detail="Detected the following Trust Service Criteria in scope.",
        )
    ]


def _section_findings(bundle: ExtractionBundle) -> list[ValidationFinding]:
    missing = bundle.get("sections_missing").value or []
    out: list[ValidationFinding] = []
    for m in missing:
        severity = "critical" if m in CRITICAL_SECTIONS else "warning"
        out.append(
            ValidationFinding(
                code=f"missing_section_{m}",
                severity=severity,
                title=f"Missing section: {SECTION_LABELS.get(m, m)}",
                detail=(
                    "Could not locate this mandatory section in the report text. "
                    "Confirm it is present — detection may have failed on unusual headings."
                ),
                section=m,
            )
        )
    return out


def _exceptions_findings(bundle: ExtractionBundle) -> list[ValidationFinding]:
    from app.extraction.exceptions import exceptions_bool_from_summary
    ex_fe = bundle.get("exceptions_summary")
    summary = ex_fe.value if isinstance(ex_fe.value, str) else None
    had = exceptions_bool_from_summary(summary)
    if had:
        return [
            ValidationFinding(
                code="exceptions_present",
                severity="warning",
                title="Exceptions identified",
                detail=summary or "Exceptions referenced in the report.",
            )
        ]
    return [
        ValidationFinding(
            code="no_exceptions",
            severity="ok",
            title="No exceptions identified",
            detail=summary or "No explicit exceptions referenced.",
        )
    ]


def _subservice_findings(bundle: ExtractionBundle) -> list[ValidationFinding]:
    subs = bundle.get("subservice_organizations").value or []
    if subs:
        return [
            ValidationFinding(
                code="subservice_orgs_identified",
                severity="info",
                title=f"Subservice organizations: {', '.join(subs)}",
                detail=(
                    "Third-party subservice organizations extend the trust boundary. "
                    "Ensure you review their own SOC 2 reports."
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class SOC2Validator:
    """Runs all deterministic validation via the extraction pipeline."""

    def __init__(self, today: date | None = None) -> None:
        self.today = today or date.today()

    def validate(
        self,
        parsed_or_text: "PDFParseResult | str",
        *,
        use_llm: bool = True,
    ) -> ValidationResult:
        # Accept either a PDFParseResult (preferred) or a raw text string
        # (legacy). When we only have text we synthesise a one-page parse
        # result so extractors that expect ``.pages`` / ``.blocks`` still
        # work (font-prominence rules will effectively no-op).
        if isinstance(parsed_or_text, str):
            logger.warning(
                "[EXTRACT] validator invoked with raw text; font-prominence "
                "heuristics will be unavailable"
            )
            parsed = PDFParseResult(
                page_count=1,
                pages=[PDFPage(number=1, text=parsed_or_text)],
                full_text=parsed_or_text,
            )
            text_for_lowcheck = parsed_or_text
        else:
            parsed = parsed_or_text
            text_for_lowcheck = parsed.full_text

        findings = _low_text_finding(text_for_lowcheck)

        result: PipelineResult = run_pipeline(parsed, use_llm=use_llm)
        bundle = result.bundle

        findings.extend(_report_type_findings(bundle))
        findings.extend(_opinion_findings(bundle))
        age_findings, age_days = _age_findings(bundle.get("opinion_date").value, self.today)
        findings.extend(age_findings)
        findings.extend(_coverage_findings(bundle))
        findings.extend(_criteria_findings(bundle))
        findings.extend(_section_findings(bundle))
        findings.extend(_exceptions_findings(bundle))
        findings.extend(_subservice_findings(bundle))

        # Scoring
        scoring: ScoringResult = score_report(bundle)

        # Build the Pydantic metadata
        md = ExtractedMetadata(**bundle_to_metadata_dict(bundle))

        validation = ValidationResult(
            metadata=md,
            findings=findings,
            risk_score=scoring.total,
            risk_rating=scoring.rating,
            report_age_days=age_days,
            field_confidence=bundle.confidence_map(),
            category_scores=scoring.category_scores,
            cuec_details=bundle_to_cuec_details(bundle),
        )
        logger.info(
            "[EVALUATE] validation done: score=%d rating=%s findings=%d",
            scoring.total, scoring.rating, len(findings),
        )
        return validation
