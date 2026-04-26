"""pgvector-backed chunk retrieval."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import models as dbm
from app.services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    page_number: int | None
    content: str
    score: float


def retrieve(
    db: Session,
    report_id: uuid.UUID,
    query: str,
    *,
    top_k: int = 6,
) -> list[RetrievedChunk]:
    svc = get_embedding_service()
    if not query.strip():
        return []

    emb = svc.embed_one(query)

    # Cosine distance search via pgvector. Lower distance = more similar.
    sql = text(
        """
        SELECT
            id,
            page_number,
            content,
            1 - (embedding <=> CAST(:q AS vector)) AS score
        FROM chunks
        WHERE report_id = :report_id AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:q AS vector)
        LIMIT :k
        """
    )
    # pgvector accepts the Python list via string casting
    rows = db.execute(
        sql,
        {"q": str(emb), "report_id": str(report_id), "k": top_k},
    ).mappings().all()

    return [
        RetrievedChunk(
            chunk_id=r["id"],
            page_number=r["page_number"],
            content=r["content"],
            score=float(r["score"]),
        )
        for r in rows
    ]


def top_excerpts_dicts(chunks: list[RetrievedChunk], max_chars: int = 1400) -> list[dict]:
    """Convert retrieved chunks to dicts for prompt building, trimming long ones."""
    out: list[dict] = []
    for c in chunks:
        snippet = c.content
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars] + "…"
        out.append({
            "chunk_id": str(c.chunk_id),
            "page_number": c.page_number,
            "content": snippet,
            "score": c.score,
        })
    return out


def broad_sample(db: Session, report_id: uuid.UUID, limit: int = 6) -> list[RetrievedChunk]:
    """Return a diverse sample of chunks for summary/questions when no query is specified."""
    rows = (
        db.query(dbm.Chunk)
        .filter(dbm.Chunk.report_id == report_id)
        .order_by(dbm.Chunk.chunk_index)
        .all()
    )
    if not rows:
        return []
    step = max(1, len(rows) // limit)
    sample = rows[::step][:limit]
    return [
        RetrievedChunk(
            chunk_id=r.id,
            page_number=r.page_number,
            content=r.content,
            score=1.0,
        )
        for r in sample
    ]
