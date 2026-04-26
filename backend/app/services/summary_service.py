"""Summary and suggested-question generation using the LLM + deterministic findings.

Summary and questions are **cached in ``Report.extracted_json``** after
the first generation. The ingestion background task pre-warms that cache
once embedding finishes (see ``report_service.process_report_finish``),
so by the time the frontend sees ``status="ready"`` the API endpoints
return instantly — no 30–60 s LLM call holding the HTTP connection open
behind the Next.js proxy. Cache misses fall through to a live LLM call
as a defensive fallback, but on the happy path that never runs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db import models as dbm
from app.models.schemas import ReportSummary, SuggestedQuestions
from app.prompts import (
    QUESTIONS_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_questions_user_prompt,
    build_summary_user_prompt,
)
from app.services.llm_service import get_llm_provider
from app.services.retrieval_service import broad_sample, top_excerpts_dicts

logger = logging.getLogger(__name__)


DEFAULT_QUESTIONS = [
    "Is this a SOC 2 Type I or Type II report, and what is the coverage period?",
    "Which Trust Service Criteria are in scope?",
    "Were any exceptions identified during control testing?",
    "Is multi-factor authentication required for all privileged access?",
    "How frequently are user access reviews performed?",
    "Which subservice organizations are relied upon and what is their SOC 2 status?",
    "When did the auditor's opinion issue, and is the report still within a 12-month window?",
    "What complementary user entity controls (CUECs) apply to us as a customer?",
]


# ---------------------------------------------------------------------------
# Public API — endpoints call these. They always check the cache first.
# ---------------------------------------------------------------------------

def suggest_questions(db: Session, report: dbm.Report) -> SuggestedQuestions:
    cached = _cached_questions(report)
    if cached is not None:
        return cached

    result = _compose_questions(db, report)
    _persist_questions(db, report, result)
    return result


def generate_summary(db: Session, report: dbm.Report) -> ReportSummary:
    cached = _cached_summary(report)
    if cached is not None:
        return cached

    result = _compose_summary(db, report)
    _persist_summary(db, report, result)
    return result


# ---------------------------------------------------------------------------
# Pre-warming — called from the ingestion background task so the first user
# click on "Summary" / "Suggested questions" is an instant DB read.
# ---------------------------------------------------------------------------

def precache_for_report(db: Session, report: dbm.Report) -> None:
    """Generate summary + questions and stash them on the report row.

    Runs inside ``process_report_finish`` after chunks are embedded.
    Failures are logged but never re-raised — a missing cache just
    means the endpoint will generate live on first request (and may
    time out, but the report itself is still usable).
    """
    try:
        q = _compose_questions(db, report)
        _persist_questions(db, report, q)
        logger.info("[%s] precache: questions ready (%d)", report.id, len(q.questions))
    except Exception as exc:
        logger.warning("[%s] precache: questions failed: %s", report.id, exc)

    try:
        s = _compose_summary(db, report)
        _persist_summary(db, report, s)
        logger.info("[%s] precache: summary ready (rating=%s)", report.id, s.rating)
    except Exception as exc:
        logger.warning("[%s] precache: summary failed: %s", report.id, exc)


# ---------------------------------------------------------------------------
# Cache read / write helpers
# ---------------------------------------------------------------------------

def _cached_questions(report: dbm.Report) -> SuggestedQuestions | None:
    data: dict[str, Any] = report.extracted_json or {}
    cached = data.get("questions")
    if not isinstance(cached, list) or not cached:
        return None
    cleaned = [str(q).strip() for q in cached if isinstance(q, str) and str(q).strip()]
    if not cleaned:
        return None
    return SuggestedQuestions(questions=cleaned[:10])


def _cached_summary(report: dbm.Report) -> ReportSummary | None:
    data: dict[str, Any] = report.extracted_json or {}
    cached = data.get("summary")
    if not isinstance(cached, dict):
        return None
    try:
        return ReportSummary.model_validate(cached)
    except Exception as exc:
        logger.warning("[%s] cached summary failed validation: %s", report.id, exc)
        return None


def _persist_questions(
    db: Session, report: dbm.Report, value: SuggestedQuestions
) -> None:
    # Reassign the whole dict so SQLAlchemy's JSON column picks up the change.
    # (plain JSON columns don't track in-place mutations.)
    base: dict[str, Any] = dict(report.extracted_json or {})
    base["questions"] = list(value.questions)
    report.extracted_json = base
    db.commit()


def _persist_summary(
    db: Session, report: dbm.Report, value: ReportSummary
) -> None:
    base: dict[str, Any] = dict(report.extracted_json or {})
    base["summary"] = value.model_dump(mode="json")
    report.extracted_json = base
    db.commit()


# ---------------------------------------------------------------------------
# Live generation (the expensive path — runs at most once per report)
# ---------------------------------------------------------------------------

def _compose_questions(db: Session, report: dbm.Report) -> SuggestedQuestions:
    data: dict[str, Any] = report.extracted_json or {}
    metadata = data.get("metadata") or {}
    findings = data.get("findings") or []

    excerpts = top_excerpts_dicts(broad_sample(db, report.id, limit=6))

    provider = get_llm_provider()
    try:
        payload = provider.complete_json(
            QUESTIONS_SYSTEM_PROMPT,
            build_questions_user_prompt(metadata, findings, excerpts),
            temperature=0.3,
            max_tokens=700,
        )
        questions = payload.get("questions") or []
        questions = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
        if not questions:
            raise ValueError("empty questions list")
    except Exception as exc:
        logger.warning("Suggested questions generation failed: %s — using defaults", exc)
        questions = list(DEFAULT_QUESTIONS)

    return SuggestedQuestions(questions=questions[:10])


def _compose_summary(db: Session, report: dbm.Report) -> ReportSummary:
    data: dict[str, Any] = report.extracted_json or {}
    metadata = data.get("metadata") or {}
    findings = data.get("findings") or []
    risk_score = int(data.get("risk_score") or 0)
    risk_rating = data.get("risk_rating") or "Unknown"

    excerpts = top_excerpts_dicts(broad_sample(db, report.id, limit=6))

    provider = get_llm_provider()
    try:
        payload = provider.complete_json(
            SUMMARY_SYSTEM_PROMPT,
            build_summary_user_prompt(metadata, findings, excerpts, risk_score),
            temperature=0.2,
            max_tokens=900,
        )
    except Exception as exc:
        logger.warning("Summary generation failed: %s", exc)
        payload = {}

    rating = payload.get("rating") or risk_rating
    if rating not in {"Strong", "Moderate", "Weak", "Unknown"}:
        rating = risk_rating

    executive_summary = payload.get("executive_summary")
    if not executive_summary:
        executive_summary = _fallback_summary(metadata, findings, risk_score, risk_rating)

    key_strengths = _as_list(payload.get("key_strengths")) or _strengths_from_findings(findings)
    key_risks = _as_list(payload.get("key_risks")) or _risks_from_findings(findings)
    followups = _as_list(payload.get("recommended_followups")) or DEFAULT_QUESTIONS[:4]

    vendor_readiness = payload.get("vendor_readiness")
    if vendor_readiness not in {"Ready", "Needs Review", "Not Ready", "Unknown"}:
        vendor_readiness = _readiness_from_rating(rating)

    return ReportSummary(
        rating=rating,  # type: ignore[arg-type]
        executive_summary=executive_summary,
        key_strengths=key_strengths[:5],
        key_risks=key_risks[:5],
        recommended_followups=followups[:5],
        vendor_readiness=vendor_readiness,  # type: ignore[arg-type]
        generated_at=datetime.now(timezone.utc),
    )


def _as_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _strengths_from_findings(findings: list[dict[str, Any]]) -> list[str]:
    return [f["title"] for f in findings if f.get("severity") == "ok"][:5]


def _risks_from_findings(findings: list[dict[str, Any]]) -> list[str]:
    criticals = [f["title"] for f in findings if f.get("severity") == "critical"]
    warnings = [f["title"] for f in findings if f.get("severity") == "warning"]
    return (criticals + warnings)[:5] or ["No significant risks detected by deterministic scan."]


def _readiness_from_rating(rating: str) -> str:
    return {
        "Strong": "Ready",
        "Moderate": "Needs Review",
        "Weak": "Not Ready",
    }.get(rating, "Unknown")


def _fallback_summary(
    metadata: dict[str, Any],
    findings: list[dict[str, Any]],
    risk_score: int,
    risk_rating: str,
) -> str:
    report_type = metadata.get("report_type") or "Unknown report type"
    opinion = metadata.get("opinion") or "unspecified opinion"
    company = metadata.get("company_name") or "the audited organization"
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    warnings = sum(1 for f in findings if f.get("severity") == "warning")
    return (
        f"{report_type} for {company} with an {opinion} opinion. "
        f"Deterministic validation scored this report {risk_score}/100 ({risk_rating}), "
        f"flagging {critical} critical and {warnings} warning items. "
        "Configure an LLM provider for a narrative assessment; the structured findings remain valid."
    )
