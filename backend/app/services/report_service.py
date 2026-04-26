"""Report ingestion and retrieval business logic.

The ingestion pipeline is deliberately **two-phased** so the HTTP upload
request returns quickly:

1. ``process_report_fast`` — synchronous, runs inline during the POST. It
   parses the PDF, runs the deterministic validator, commits the row with
   ``status="processing"``, and persists the parsed text to a temp file so
   the background task can pick it up. Typically 2–5 s.

2. ``process_report_finish`` — runs as a FastAPI ``BackgroundTask`` after
   the response is sent. Opens its own DB session. Does LLM metadata
   augmentation, chunking, embedding, and finally flips the row to
   ``status="ready"``. Can take 30 s to 3 min depending on provider and
   report length.

The frontend polls ``/api/report/{id}`` until ``status=ready`` before
enabling chat. The chat endpoint already rejects requests with 409 when
the report is not ready.
"""
from __future__ import annotations

import gc
import json
import logging
import pickle
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.db import models as dbm
from app.db.database import SessionLocal
from app.models.schemas import (
    CategoryScore,
    CUECDetail,
    ExtractedMetadata,
    FieldConfidence,
    ReportDetail,
    ReportListItem,
    ValidationFinding,
)
from app.parsers import parse_pdf
from app.services.embedding_service import get_embedding_service, iter_chunks_with_pages
from app.validators import SOC2Validator, ValidationResult

# Local import inside the function to avoid a circular import at module load
# (summary_service imports retrieval_service, which is fine, but we keep the
# import lazy to make the dependency graph obvious at the call site).

logger = logging.getLogger(__name__)


def ensure_upload_dir() -> Path:
    p = Path(settings.upload_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_upload(file_bytes: bytes, filename: str) -> Path:
    target_dir = ensure_upload_dir()
    safe_name = f"{uuid.uuid4().hex}__{filename}"
    path = target_dir / safe_name
    path.write_bytes(file_bytes)
    return path


def _parsed_cache_path(report_id: uuid.UUID) -> Path:
    """Where process_report_fast drops the parsed PDF for the background task."""
    d = ensure_upload_dir() / "parsed-cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{report_id}.pkl"


def process_report_fast(
    db: Session,
    *,
    file_bytes: bytes,
    filename: str,
) -> dbm.Report:
    """Phase 1 — save, parse, validate, and commit regex-only metadata.

    Runs synchronously inline with the upload POST. Target: 2–5 s.

    Stashes the parsed PDF to a pickle in the uploads dir so that
    ``process_report_finish`` — which runs in a FastAPI BackgroundTask on
    its own DB session — can pick up exactly the same text without
    re-parsing the PDF. The cache file is deleted once the background
    task finishes (or on failure).
    """
    t0 = time.perf_counter()
    path = save_upload(file_bytes, filename)
    file_size = len(file_bytes)
    del file_bytes  # release from this frame — bytes are on disk now

    report = dbm.Report(
        filename=filename,
        file_size_bytes=file_size,
        status="processing",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    report_id = report.id

    try:
        # ---- Stage 1: parse --------------------------------------------------
        logger.info("[%s] stage=parse start path=%s", report_id, path)
        t = time.perf_counter()
        parsed = parse_pdf(path)
        report.page_count = parsed.page_count
        logger.info(
            "[%s] stage=parse done pages=%d chars=%d elapsed=%.2fs",
            report_id, parsed.page_count, len(parsed.full_text),
            time.perf_counter() - t,
        )

        # ---- Stage 2: validate (rule-only; LLM defers to phase 2) -------------
        # We explicitly pass the PDFParseResult so the extractors can use
        # font-prominence (cover page) and table data. LLM fallback is
        # deferred to process_report_finish to keep this phase fast (<5s).
        t = time.perf_counter()
        try:
            validator = SOC2Validator()
            result = validator.validate(parsed, use_llm=False)
        except Exception as exc:
            logger.exception("[%s][VALIDATE] validator crashed: %s", report_id, exc)
            result = ValidationResult(
                metadata=ExtractedMetadata(),
                findings=[
                    ValidationFinding(
                        code="validator_error",
                        severity="critical",
                        title="Automated validation failed",
                        detail=(
                            "The deterministic validator encountered an error "
                            "while analyzing this report. Metadata was not "
                            "extracted; you can still chat with the report."
                        ),
                    )
                ],
                risk_score=0,
                risk_rating="Unknown",
            )
        logger.info(
            "[%s][VALIDATE] done findings=%d score=%d rating=%s elapsed=%.2fs",
            report_id, len(result.findings), result.risk_score,
            result.risk_rating, time.perf_counter() - t,
        )

        # ---- Stage 3: hydrate + commit metadata (regex-only for now) --------
        _hydrate_report(report, result, augmentation=None)
        report.status = "processing"  # stays processing — finish flips to ready
        db.commit()
        db.refresh(report)

        # ---- Stash parsed PDF for the background task ------------------------
        # We persist the whole PDFParseResult (it's all plain dataclasses of
        # primitives) so phase 2 can re-run the extraction pipeline with
        # `use_llm=True` and gain access to the same font/block metadata
        # we used in phase 1. That keeps rule behaviour identical across
        # phases and lets the LLM fallback operate on the full structure.
        try:
            cache = _parsed_cache_path(report_id)
            with cache.open("wb") as fh:
                pickle.dump(parsed, fh, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info("[%s][PARSE] parsed cache written: %s", report_id, cache.name)
        except Exception as exc:
            logger.exception("[%s][PARSE] failed to stash parsed cache: %s", report_id, exc)
            raise

        logger.info(
            "[%s] process_report_fast done total=%.2fs",
            report_id, time.perf_counter() - t0,
        )
    except Exception as exc:
        logger.exception("[%s] process_report_fast failed: %s", report_id, exc)
        try:
            db.rollback()
            fresh = db.get(dbm.Report, report_id)
            if fresh is not None:
                fresh.status = "failed"
                fresh.error_message = str(exc)[:2000]
                db.commit()
                db.refresh(fresh)
                report = fresh
        except Exception:
            logger.exception("[%s] failed to mark report as failed", report_id)
    finally:
        # Always release the upload PDF — we already have parsed text in the
        # pickle cache and chunks in memory for the BG task.
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.warning("[%s] failed to delete temp upload %s", report_id, path)

    return report


def process_report_finish(report_id: uuid.UUID) -> None:
    """Phase 2 — LLM augmentation + chunking + embedding.

    Runs in a FastAPI BackgroundTask **after** the upload response has been
    sent. Opens its own DB session (the request session is already closed).
    Reads the parsed-text pickle written by phase 1 instead of re-parsing
    the PDF. Never raises; any failure is logged and the report is flipped
    to ``status="failed"`` with an error message.
    """
    t0 = time.perf_counter()
    cache = _parsed_cache_path(report_id)
    db = SessionLocal()
    try:
        report = db.get(dbm.Report, report_id)
        if report is None:
            logger.warning("[%s] finish: report row missing; abort", report_id)
            return
        if not cache.exists():
            logger.warning("[%s] finish: parsed cache missing at %s", report_id, cache)
            report.status = "failed"
            report.error_message = "Parsed text cache was missing; re-upload the report."
            db.commit()
            return

        with cache.open("rb") as fh:
            parsed = pickle.load(fh)
        full_text: str = parsed.full_text
        page_inputs: list[tuple[int, str]] = [
            (p.number, p.text) for p in parsed.pages if p.text
        ]
        logger.info(
            "[%s][PARSE] finish: loaded cache chars=%d pages=%d",
            report_id, len(full_text), len(page_inputs),
        )

        # ---- Stage 2b: re-run the full extraction pipeline WITH LLM fallback.
        # Phase 1 ran rules-only for a fast upload response. Now we have
        # time to let the LLM fill any LOW / NONE confidence fields the
        # rules couldn't extract. The pipeline handles its own rule pass
        # + LLM pass + rescoring in one shot, so we don't need to do
        # incremental merging anymore.
        t = time.perf_counter()
        try:
            validator = SOC2Validator()
            result = validator.validate(
                parsed,
                use_llm=bool(settings.semantic_augmentation),
            )
        except Exception as exc:
            logger.exception("[%s][EXTRACT] pipeline crashed: %s", report_id, exc)
            # Fall back to what phase 1 persisted — don't lose data.
            extracted: dict[str, Any] = report.extracted_json or {}
            result = ValidationResult(
                metadata=ExtractedMetadata(**(extracted.get("metadata") or {})),
                findings=[ValidationFinding(**f) for f in (extracted.get("findings") or [])],
                risk_score=int(extracted.get("risk_score") or 0),
                risk_rating=extracted.get("risk_rating") or "Unknown",
                report_age_days=extracted.get("report_age_days"),
                field_confidence=extracted.get("field_confidence") or {},
                category_scores=extracted.get("category_scores") or {},
                cuec_details=extracted.get("cuec_details") or [],
            )
        logger.info(
            "[%s][EXTRACT] finish: score=%d rating=%s findings=%d elapsed=%.2fs",
            report_id, result.risk_score, result.risk_rating,
            len(result.findings), time.perf_counter() - t,
        )

        _hydrate_report(report, result, augmentation=None)
        db.commit()

        # ---- Stage 4: chunk --------------------------------------------------
        t = time.perf_counter()
        del full_text, parsed
        chunk_pairs = iter_chunks_with_pages(page_inputs)
        del page_inputs
        gc.collect()
        logger.info(
            "[%s][CHUNK] done chunks=%d elapsed=%.2fs",
            report_id, len(chunk_pairs), time.perf_counter() - t,
        )

        # ---- Stage 5: embed + persist ---------------------------------------
        if chunk_pairs:
            embedding_service = get_embedding_service()
            batch = 64
            total = len(chunk_pairs)
            t = time.perf_counter()
            for start in range(0, total, batch):
                slice_pairs = chunk_pairs[start : start + batch]
                vectors = embedding_service.embed_many(
                    [c for _, c in slice_pairs]
                )
                for offset, ((page_num, content), emb) in enumerate(
                    zip(slice_pairs, vectors)
                ):
                    db.add(
                        dbm.Chunk(
                            report_id=report_id,
                            chunk_index=start + offset,
                            page_number=page_num,
                            content=content,
                            embedding=emb,
                        )
                    )
                db.flush()
                logger.info(
                    "[%s] stage=embed batch=%d-%d/%d elapsed=%.2fs",
                    report_id, start, min(start + batch, total), total,
                    time.perf_counter() - t,
                )

        # ---- Stage 6: pre-warm summary + suggested questions --------------
        # Doing this here means the moment the frontend sees status="ready",
        # the /summary and /questions endpoints are instant DB reads rather
        # than 30–60 s LLM calls that would blow past the Next.js proxy
        # timeout and surface as ECONNRESET / "socket hang up" in the UI.
        t = time.perf_counter()
        from app.services import summary_service  # lazy to avoid cycles
        summary_service.precache_for_report(db, report)
        logger.info(
            "[%s] stage=precache done elapsed=%.2fs",
            report_id, time.perf_counter() - t,
        )

        report.status = "ready"
        report.error_message = None
        db.commit()
        logger.info(
            "[%s] finish complete status=ready total=%.2fs",
            report_id, time.perf_counter() - t0,
        )
    except Exception as exc:
        logger.exception("[%s] process_report_finish failed: %s", report_id, exc)
        try:
            db.rollback()
            fresh = db.get(dbm.Report, report_id)
            if fresh is not None:
                fresh.status = "failed"
                fresh.error_message = str(exc)[:2000]
                db.commit()
        except Exception:
            logger.exception("[%s] failed to mark report as failed", report_id)
    finally:
        try:
            cache.unlink(missing_ok=True)
        except Exception:
            logger.warning("[%s] failed to delete parsed cache %s", report_id, cache)
        db.close()


# Legacy alias — some code paths or tests might still reach in for the old
# single-phase entry point. Kept as a trivial wrapper so they keep working
# (sync, blocking, as before).
def process_report(
    db: Session, *, file_bytes: bytes, filename: str
) -> dbm.Report:
    report = process_report_fast(db, file_bytes=file_bytes, filename=filename)
    process_report_finish(report.id)
    db.refresh(report)
    return report


def _json_safe(obj: Any) -> Any:
    """Coerce a Python value into something Postgres' JSONB encoder accepts.

    Each extractor *should* return JSON-clean primitives, but defensive
    normalisation here means a single rogue dataclass / date / set
    doesn't poison the entire report row with a TypeError on UPDATE.
    """
    import datetime as _dt

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (_dt.date, _dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in obj]
    # Dataclasses / Pydantic / ad-hoc objects with their own dict shape.
    to_d = getattr(obj, "to_dict", None)
    if callable(to_d):
        try:
            return _json_safe(to_d())
        except Exception:
            pass
    md = getattr(obj, "model_dump", None)
    if callable(md):
        try:
            return _json_safe(md(mode="json"))
        except Exception:
            pass
    # Last resort — stringify so the UPDATE still succeeds and we can debug
    # which type leaked through from the logs.
    logger.warning(
        "[hydrate] coercing non-JSON-safe value to str: type=%s",
        type(obj).__name__,
    )
    return str(obj)


def _hydrate_report(
    report: dbm.Report,
    result: ValidationResult,
    augmentation: dict[str, Any] | None = None,
) -> None:
    md = result.metadata
    report.company_name = md.company_name
    report.auditor_firm = md.auditor_firm
    report.report_type = md.report_type
    report.opinion = md.opinion
    report.opinion_date = md.opinion_date
    report.coverage_start = md.coverage_start
    report.coverage_end = md.coverage_end

    extracted: dict[str, Any] = {
        "metadata": json.loads(md.model_dump_json()),
        "findings": [json.loads(f.model_dump_json()) for f in result.findings],
        "risk_score": result.risk_score,
        "risk_rating": result.risk_rating,
        "report_age_days": result.report_age_days,
        # Side-channels surfaced to the UI for confidence badges + score
        # breakdown. Safe to be missing on older rows — frontend treats
        # them as optional. We pass them through ``_json_safe`` so a
        # nested CUECItem / date / dataclass can never crash the UPDATE.
        "field_confidence": _json_safe(result.field_confidence or {}),
        "category_scores": _json_safe(result.category_scores or {}),
        "cuec_details": _json_safe(result.cuec_details or []),
    }
    if augmentation:
        # Strip large/noisy fields before persisting
        extracted["augmentation"] = {
            "augmented_fields": augmentation.get("augmented_fields") or [],
            "opinion_reasoning": augmentation.get("opinion_reasoning"),
            "skipped": bool(augmentation.get("skipped")),
        }
    report.extracted_json = extracted


# NOTE: _refresh_findings was removed along with the old ad-hoc augment-then-
# merge logic. The phase-2 finish step now re-runs the whole extraction +
# scoring pipeline (rule + LLM) in one call, so incremental merging is no
# longer needed.


def list_reports(db: Session, limit: int = 50) -> list[ReportListItem]:
    rows = (
        db.query(dbm.Report)
        .order_by(desc(dbm.Report.uploaded_at))
        .limit(limit)
        .all()
    )
    return [ReportListItem.model_validate(r) for r in rows]


def get_report(db: Session, report_id: uuid.UUID) -> dbm.Report | None:
    return db.get(dbm.Report, report_id)


def to_detail(report: dbm.Report) -> ReportDetail:
    data: dict[str, Any] = report.extracted_json or {}
    metadata = ExtractedMetadata(**(data.get("metadata") or {}))
    findings = [ValidationFinding(**f) for f in (data.get("findings") or [])]

    # Provenance side-channels — older rows may not have these. Coerce loosely
    # so a malformed row doesn't break the whole detail endpoint.
    field_confidence: dict[str, FieldConfidence] = {}
    for key, val in (data.get("field_confidence") or {}).items():
        if not isinstance(val, dict):
            continue
        try:
            field_confidence[key] = FieldConfidence(**val)
        except Exception:
            logger.warning("[%s] dropping malformed field_confidence[%s]", report.id, key)

    category_scores: dict[str, CategoryScore] = {}
    for key, val in (data.get("category_scores") or {}).items():
        if not isinstance(val, dict):
            continue
        try:
            category_scores[key] = CategoryScore(**val)
        except Exception:
            logger.warning("[%s] dropping malformed category_scores[%s]", report.id, key)

    cuec_details: list[CUECDetail] = []
    for item in (data.get("cuec_details") or []):
        if not isinstance(item, dict):
            continue
        try:
            cuec_details.append(CUECDetail(**item))
        except Exception:
            logger.warning("[%s] dropping malformed cuec_details entry", report.id)

    return ReportDetail(
        id=report.id,
        filename=report.filename,
        file_size_bytes=report.file_size_bytes,
        page_count=report.page_count,
        status=report.status,
        error_message=report.error_message,
        company_name=report.company_name,
        auditor_firm=report.auditor_firm,
        report_type=report.report_type,
        opinion=report.opinion,
        opinion_date=report.opinion_date,
        coverage_start=report.coverage_start,
        coverage_end=report.coverage_end,
        uploaded_at=report.uploaded_at,
        updated_at=report.updated_at,
        metadata=metadata,
        findings=findings,
        risk_score=int(data.get("risk_score") or 0),
        risk_rating=data.get("risk_rating") or "Unknown",
        report_age_days=data.get("report_age_days"),
        field_confidence=field_confidence,
        category_scores=category_scores,
        cuec_details=cuec_details,
    )


def delete_report(db: Session, report_id: uuid.UUID) -> bool:
    report = db.get(dbm.Report, report_id)
    if not report:
        return False
    db.delete(report)
    db.commit()
    return True
