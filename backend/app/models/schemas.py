"""Pydantic request/response schemas."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


class ValidationFinding(BaseModel):
    code: str
    severity: Literal["info", "ok", "warning", "critical"]
    title: str
    detail: str
    section: str | None = None


class ExtractedMetadata(BaseModel):
    company_name: str | None = None
    auditor_firm: str | None = None
    report_type: str | None = None
    opinion: str | None = None
    opinion_date: date | None = None
    coverage_start: date | None = None
    coverage_end: date | None = None
    trust_service_criteria: list[str] = Field(default_factory=list)
    sections_present: list[str] = Field(default_factory=list)
    sections_missing: list[str] = Field(default_factory=list)
    subservice_organizations: list[str] = Field(default_factory=list)
    complementary_user_entity_controls: list[str] = Field(default_factory=list)
    exceptions_summary: str | None = None


class FieldConfidence(BaseModel):
    """Per-field provenance surfaced to the UI as a confidence pill.

    Mirrors :class:`app.extraction.types.FieldExtraction.to_dict()`. The
    ``value`` key is included so a single confidence record can stand on
    its own (the UI reads it back when rendering hover tooltips).
    """

    # ``ignore`` is the Pydantic default but be explicit about it: extractors
    # may add diagnostic fields (e.g. alternative candidates) we don't want
    # to leak through this schema.
    model_config = ConfigDict(extra="ignore")

    value: Any = None
    confidence: Literal["high", "medium", "low", "none"]
    method: str | None = None
    evidence: str | None = None
    page_number: int | None = None


class CategoryScore(BaseModel):
    """One of the five weighted scoring categories.

    ``points`` is the awarded points (0..weight). ``ratio`` is
    ``points/weight`` clamped to [0, 1] — handy for rendering progress
    bars without recomputing on the client. Field names match the dict
    produced by ``app.extraction.scoring.score_report``.
    """

    model_config = ConfigDict(extra="ignore")

    points: float
    weight: float
    ratio: float
    reasons: list[str] = Field(default_factory=list)


class CUECDetail(BaseModel):
    """A single complementary user-entity control with provenance.

    Field names match :class:`app.extraction.types.CUECItem.to_dict()`.
    """

    model_config = ConfigDict(extra="ignore")

    text: str
    page_number: int | None = None
    heading: str | None = None


class UploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    message: str
    metadata: ExtractedMetadata
    findings: list[ValidationFinding]


class ReportListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    company_name: str | None
    report_type: str | None
    opinion: str | None
    uploaded_at: datetime
    status: str


class ReportDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_size_bytes: int
    page_count: int
    status: str
    error_message: str | None = None

    company_name: str | None
    auditor_firm: str | None
    report_type: str | None
    opinion: str | None
    opinion_date: date | None
    coverage_start: date | None
    coverage_end: date | None

    uploaded_at: datetime
    updated_at: datetime

    metadata: ExtractedMetadata
    findings: list[ValidationFinding]
    risk_score: int
    risk_rating: Literal["Strong", "Moderate", "Weak", "Unknown"]
    report_age_days: int | None = None

    # Provenance side-channels (optional — older rows pre-confidence-engine
    # may not have these populated).
    field_confidence: dict[str, FieldConfidence] = Field(default_factory=dict)
    category_scores: dict[str, CategoryScore] = Field(default_factory=dict)
    cuec_details: list[CUECDetail] = Field(default_factory=list)


class SuggestedQuestions(BaseModel):
    questions: list[str]


class ChatMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatCitation(BaseModel):
    chunk_id: uuid.UUID
    page_number: int | None
    snippet: str
    score: float


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class ChatResponse(BaseModel):
    message: ChatMessageOut
    citations: list[ChatCitation]
    confidence: Literal["high", "medium", "low"]


class ReportSummary(BaseModel):
    rating: Literal["Strong", "Moderate", "Weak", "Unknown"]
    executive_summary: str
    key_strengths: list[str]
    key_risks: list[str]
    recommended_followups: list[str]
    vendor_readiness: Literal["Ready", "Needs Review", "Not Ready", "Unknown"]
    generated_at: datetime
