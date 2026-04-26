"""RAG chat service — retrieval-augmented, citation-grounded answers."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.db import models as dbm
from app.models.schemas import ChatCitation, ChatMessageOut, ChatResponse
from app.prompts import CHAT_SYSTEM_PROMPT, build_chat_user_prompt
from app.services.llm_service import get_llm_provider
from app.services.retrieval_service import retrieve, top_excerpts_dicts

logger = logging.getLogger(__name__)

_CONFIDENCE_RE = re.compile(r"Confidence:\s*(high|medium|low)", re.IGNORECASE)


def answer_question(
    db: Session,
    report: dbm.Report,
    message: str,
) -> ChatResponse:
    # 1) Persist user message
    user_msg = dbm.ChatMessage(
        report_id=report.id,
        role="user",
        content=message,
        citations=[],
    )
    db.add(user_msg)
    db.commit()

    # 2) Retrieve top relevant chunks
    retrieved = retrieve(db, report.id, message, top_k=settings.top_k)
    excerpt_dicts = top_excerpts_dicts(retrieved)

    # 3) Call LLM
    # ``settings.chat_max_tokens`` defaults to 500 — generous for grounded
    # answers but small enough that Ollama-on-CPU finishes within the
    # ``llm_timeout_seconds`` budget. Bump in .env for cloud providers.
    provider = get_llm_provider()
    try:
        raw = provider.complete(
            CHAT_SYSTEM_PROMPT,
            build_chat_user_prompt(message, excerpt_dicts),
            temperature=0.15,
            max_tokens=settings.chat_max_tokens,
        )
    except Exception as exc:
        logger.exception("LLM call failed: %s", exc)
        raw = (
            "The analysis service is temporarily unavailable — the model "
            "took too long to respond. Try a shorter question, or switch "
            "to a faster LLM provider via LLM_PROVIDER in backend/.env."
            "\n\nConfidence: low"
        )

    # 4) Extract confidence label and strip it from the visible response
    confidence = "medium"
    conf_match = _CONFIDENCE_RE.search(raw)
    if conf_match:
        confidence = conf_match.group(1).lower()
        raw = _CONFIDENCE_RE.sub("", raw).strip()

    # 5) Build citations that actually appear in the answer (cited)
    cited_indices = _find_citation_indices(raw)
    citations: list[ChatCitation] = []
    for idx in cited_indices:
        if 1 <= idx <= len(retrieved):
            c = retrieved[idx - 1]
            snippet = c.content[:280] + ("…" if len(c.content) > 280 else "")
            citations.append(
                ChatCitation(
                    chunk_id=c.chunk_id,
                    page_number=c.page_number,
                    snippet=snippet,
                    score=round(c.score, 3),
                )
            )
    # If no inline citations, expose top 2 retrieved chunks for transparency
    if not citations:
        for c in retrieved[:2]:
            snippet = c.content[:280] + ("…" if len(c.content) > 280 else "")
            citations.append(
                ChatCitation(
                    chunk_id=c.chunk_id,
                    page_number=c.page_number,
                    snippet=snippet,
                    score=round(c.score, 3),
                )
            )

    # 6) Persist assistant response
    assistant_msg = dbm.ChatMessage(
        report_id=report.id,
        role="assistant",
        content=raw,
        citations=[json.loads(c.model_dump_json()) for c in citations],
    )
    db.add(assistant_msg)
    db.commit()
    db.refresh(assistant_msg)

    return ChatResponse(
        message=ChatMessageOut(
            id=assistant_msg.id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            citations=assistant_msg.citations,
            created_at=assistant_msg.created_at or datetime.now(timezone.utc),
        ),
        citations=citations,
        confidence=confidence,  # type: ignore[arg-type]
    )


def _find_citation_indices(text: str) -> list[int]:
    seen: list[int] = []
    for m in re.finditer(r"\[(\d+)\]", text):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def history(db: Session, report_id: uuid.UUID) -> list[ChatMessageOut]:
    msgs = (
        db.query(dbm.ChatMessage)
        .filter(dbm.ChatMessage.report_id == report_id)
        .order_by(dbm.ChatMessage.created_at.asc())
        .all()
    )
    return [
        ChatMessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            citations=m.citations or [],
            created_at=m.created_at,
        )
        for m in msgs
    ]
