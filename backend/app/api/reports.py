"""Report upload, retrieval, and deletion endpoints."""
import logging
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models.schemas import (
    ReportDetail,
    ReportListItem,
    SuggestedQuestions,
    UploadResponse,
)
from app.services import report_service, summary_service
from app.utils.ratelimit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "binary/octet-stream"}


@router.post("/upload", response_model=UploadResponse, tags=["reports"])
@limiter.limit(f"{settings.rate_limit_per_minute}/minute")
async def upload_report(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Upload a SOC 2 report PDF and kick off the ingestion pipeline.

    This returns as soon as parsing and regex validation are done (typically
    2–5 s). LLM augmentation, chunking, and embedding run in a BackgroundTask
    so the HTTP connection isn't held hostage for 60–120 s on large reports.
    The frontend polls ``GET /api/report/{id}`` until ``status=ready``.
    """
    if file.content_type and file.content_type.lower() not in ALLOWED_CONTENT_TYPES:
        if not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported content type: {file.content_type}. Please upload a PDF.",
            )

    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF files are supported.",
        )

    # Read & validate size
    max_bytes = settings.max_upload_mb * 1024 * 1024
    # Read at most one byte beyond the limit so oversized uploads are rejected
    # without buffering the entire request payload in application memory.
    data = await file.read(max_bytes + 1)
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb}MB upload limit.",
        )
    if not data.startswith(b"%PDF"):
        raise HTTPException(
            status_code=415,
            detail="The uploaded file does not appear to be a valid PDF.",
        )

    safe_filename = _sanitize_filename(filename)
    logger.info("Processing upload: %s (%d bytes)", safe_filename, len(data))

    # Phase 1 — inline, returns fast (~2–5 s)
    report = report_service.process_report_fast(
        db, file_bytes=data, filename=safe_filename
    )

    # Phase 2 — kicked off AFTER the response is sent
    if report.status == "processing":
        background_tasks.add_task(
            report_service.process_report_finish, report.id
        )

    detail = report_service.to_detail(report)
    return UploadResponse(
        id=report.id,
        filename=report.filename,
        status=report.status,
        message=(
            "Report queued — regex validation complete, semantic analysis "
            "and embedding in progress."
            if report.status == "processing"
            else report.error_message or "Report processing encountered an issue."
        ),
        metadata=detail.metadata,
        findings=detail.findings,
    )


@router.get("/reports", response_model=list[ReportListItem], tags=["reports"])
def list_reports(db: Session = Depends(get_db)) -> list[ReportListItem]:
    return report_service.list_reports(db)


@router.get("/report/{report_id}", response_model=ReportDetail, tags=["reports"])
def get_report(report_id: UUID, db: Session = Depends(get_db)) -> ReportDetail:
    report = report_service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_service.to_detail(report)


@router.get(
    "/report/{report_id}/questions",
    response_model=SuggestedQuestions,
    tags=["reports"],
)
@limiter.limit("20/minute")
def report_questions(
    request: Request,
    report_id: UUID,
    db: Session = Depends(get_db),
) -> SuggestedQuestions:
    report = report_service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return summary_service.suggest_questions(db, report)


@router.get(
    "/report/{report_id}/summary",
    tags=["reports"],
)
@limiter.limit("10/minute")
def report_summary(
    request: Request,
    report_id: UUID,
    db: Session = Depends(get_db),
):
    report = report_service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return summary_service.generate_summary(db, report)


@router.delete("/report/{report_id}", tags=["reports"])
def delete_report(report_id: UUID, db: Session = Depends(get_db)):
    ok = report_service.delete_report(db, report_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": True}


def _sanitize_filename(name: str) -> str:
    # Strip path components and dangerous characters while preserving a sensible name
    name = name.replace("\\", "/").split("/")[-1]
    cleaned = "".join(c for c in name if c.isalnum() or c in "._- ").strip()
    return cleaned or "upload.pdf"
