"""Chat endpoints — grounded Q&A over a report."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.schemas import ChatMessageIn, ChatMessageOut, ChatResponse
from app.services import chat_service, report_service
from app.utils.ratelimit import limiter

router = APIRouter()


@router.post("/chat/{report_id}", response_model=ChatResponse, tags=["chat"])
@limiter.limit("60/minute")
def chat(
    request: Request,
    report_id: UUID,
    payload: ChatMessageIn,
    db: Session = Depends(get_db),
) -> ChatResponse:
    report = report_service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Report is not ready (status={report.status}).",
        )
    return chat_service.answer_question(db, report, payload.message)


@router.get(
    "/chat/{report_id}/history",
    response_model=list[ChatMessageOut],
    tags=["chat"],
)
def chat_history(report_id: UUID, db: Session = Depends(get_db)) -> list[ChatMessageOut]:
    report = report_service.get_report(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return chat_service.history(db, report_id)
