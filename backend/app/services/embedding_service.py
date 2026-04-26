"""Tiered embedding service — local-first, zero API-key dependency.

Providers, in preference order:

1. **sentence-transformers** (`embedding_provider=local`) — runs in-process,
   no external services. Default model: ``BAAI/bge-small-en-v1.5`` (384-dim,
   strong retrieval quality for English). Model weights download once on
   first use (~90 MB) and cache inside the container.

2. **Ollama** (`embedding_provider=ollama`) — talks to a local Ollama server
   and uses the configured embedding model (default ``nomic-embed-text``,
   768-dim). Useful when you already have Ollama running for chat.

3. **OpenAI** (`embedding_provider=openai`) — only used if an API key is set.
   Default model ``text-embedding-3-small`` (1536-dim).

4. **Deterministic hash fallback** — last resort, used when the configured
   provider fails to initialize (e.g. sentence-transformers package missing
   or no network to download the model). Produces stable, poor-quality
   embeddings so the UI remains functional.

IMPORTANT: the pgvector column is fixed at ``settings.embedding_dimensions``.
Switching providers that produce different dimensions requires dropping the
database (chunks table + HNSW index) and letting it re-create.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from collections.abc import Iterable
from functools import lru_cache
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self) -> None:
        self.dim = settings.embedding_dimensions
        self._provider_name = "hash"  # overwritten on successful init
        self._openai_client = None
        self._st_model = None
        self._ollama_base_url: str | None = None
        self._ollama_model: str | None = None
        self._is_stub = True  # True == semantic-poor fallback in use

        provider = (settings.embedding_provider or "").lower()

        if provider == "openai" and settings.openai_api_key:
            self._init_openai()
        elif provider == "ollama":
            self._init_ollama()
        elif provider in {"local", "sentence-transformers", "sbert", ""}:
            # "local" is the default/zero-config path
            self._init_sentence_transformers()
        else:
            logger.warning(
                "Unknown embedding_provider=%r — falling back to sentence-transformers",
                provider,
            )
            self._init_sentence_transformers()

        if self._is_stub:
            logger.warning(
                "Using deterministic hash embeddings. Retrieval quality will be "
                "poor. Install sentence-transformers or start an Ollama server "
                "to enable real semantic retrieval."
            )

    # -------------------------------------------------------------------------
    # Init branches
    # -------------------------------------------------------------------------

    def _init_openai(self) -> None:
        try:
            from openai import OpenAI

            self._openai_client = OpenAI(api_key=settings.openai_api_key)
            self._provider_name = f"openai/{settings.embedding_model}"
            self._is_stub = False
            logger.info("Embedding service: %s", self._provider_name)
        except Exception as exc:
            logger.warning("OpenAI embedding init failed, falling back: %s", exc)
            self._init_sentence_transformers()

    def _init_sentence_transformers(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; falling back to hash embeddings. "
                "`pip install sentence-transformers` to enable."
            )
            return
        model_name = settings.local_embedding_model
        try:
            self._st_model = SentenceTransformer(model_name)
            produced_dim = int(self._st_model.get_sentence_embedding_dimension() or self.dim)
            if produced_dim != self.dim:
                logger.warning(
                    "Local embedding model '%s' produces %d-dim vectors but "
                    "embedding_dimensions=%d. Set EMBEDDING_DIMENSIONS=%d and "
                    "drop the chunks table to fix.",
                    model_name,
                    produced_dim,
                    self.dim,
                    produced_dim,
                )
            self._provider_name = f"sentence-transformers/{model_name}"
            self._is_stub = False
            logger.info("Embedding service: %s (dim=%d)", self._provider_name, produced_dim)
        except Exception as exc:
            logger.warning(
                "Failed to load sentence-transformers model '%s': %s. "
                "Falling back to hash embeddings.",
                model_name,
                exc,
            )
            self._st_model = None

    def _init_ollama(self) -> None:
        self._ollama_base_url = settings.ollama_base_url.rstrip("/")
        self._ollama_model = settings.ollama_embedding_model
        # Sanity-check the server is reachable; fall through to local if not.
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{self._ollama_base_url}/api/tags")
                r.raise_for_status()
            self._provider_name = f"ollama/{self._ollama_model}"
            self._is_stub = False
            logger.info("Embedding service: %s", self._provider_name)
        except Exception as exc:
            logger.warning(
                "Ollama not reachable at %s (%s); falling back to sentence-transformers",
                self._ollama_base_url,
                exc,
            )
            self._ollama_base_url = None
            self._init_sentence_transformers()

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    @property
    def is_stub(self) -> bool:
        return self._is_stub

    @property
    def provider_name(self) -> str:
        return self._provider_name

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._openai_client is not None:
            return self._embed_openai(texts)
        if self._st_model is not None:
            return self._embed_sbert(texts)
        if self._ollama_base_url is not None:
            return self._embed_ollama(texts)
        return [self._embed_fallback(t) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    # -------------------------------------------------------------------------
    # Provider implementations
    # -------------------------------------------------------------------------

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        assert self._openai_client is not None
        result: list[list[float]] = []
        batch_size = 96
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = self._openai_client.embeddings.create(
                model=settings.embedding_model,
                input=batch,
            )
            for item in resp.data:
                result.append(list(item.embedding))
        return result

    def _embed_sbert(self, texts: list[str]) -> list[list[float]]:
        assert self._st_model is not None
        # sentence-transformers handles batching internally and returns a numpy
        # array; we convert to a plain list of lists for pgvector.
        vectors = self._st_model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,  # unit-length — cosine distance = dot
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vec.astype(float).tolist() for vec in vectors]

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        assert self._ollama_base_url and self._ollama_model
        out: list[list[float]] = []
        # Ollama's /api/embed supports batching since 0.2.x
        with httpx.Client(timeout=120.0) as client:
            for i in range(0, len(texts), 32):
                batch = texts[i : i + 32]
                resp = client.post(
                    f"{self._ollama_base_url}/api/embed",
                    json={"model": self._ollama_model, "input": batch},
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
                embs = data.get("embeddings") or []
                if len(embs) != len(batch):
                    raise RuntimeError(
                        f"Ollama returned {len(embs)} embeddings for {len(batch)} inputs"
                    )
                out.extend([list(v) for v in embs])
        return out

    # -------------------------------------------------------------------------
    # Deterministic hash fallback
    # -------------------------------------------------------------------------

    _WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]{1,}")

    def _embed_fallback(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        words = self._WORD_RE.findall(text.lower())
        if not words:
            return vec
        tokens: list[str] = []
        for i, w in enumerate(words):
            tokens.append(w)
            if i > 0:
                tokens.append(words[i - 1] + "_" + w)

        for tok in tokens:
            h = _hash_bucket(tok, self.dim)
            vec[h] += 1.0 - math.log1p(_common_score(tok)) * 0.2

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


@lru_cache(maxsize=1024)
def _hash_bucket(token: str, dim: int) -> int:
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h, "big") % dim


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "been", "are",
    "was", "were", "will", "would", "could", "should", "shall", "may", "might",
    "its", "it", "a", "an", "of", "to", "in", "on", "at", "by", "is", "as",
    "or", "be", "not", "no", "if", "then", "than", "these", "those", "their",
}


@lru_cache(maxsize=1024)
def _common_score(token: str) -> float:
    return 3.0 if token in _STOPWORDS else 1.0


_embedding_singleton: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_singleton
    if _embedding_singleton is None:
        _embedding_singleton = EmbeddingService()
    return _embedding_singleton


def chunk_text(
    text: str,
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """Split text into overlapping chunks, attempting to respect paragraph breaks."""
    size = chunk_size or settings.chunk_size
    ov = overlap or settings.chunk_overlap
    if not text:
        return []

    # First split on blank lines
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) + 2 <= size:
            buffer = f"{buffer}\n\n{para}" if buffer else para
            continue
        if buffer:
            chunks.append(buffer)
        if len(para) <= size:
            buffer = para
        else:
            # Paragraph is larger than chunk size — split aggressively
            start = 0
            while start < len(para):
                end = min(start + size, len(para))
                chunks.append(para[start:end])
                start = end - ov
                if start < 0:
                    start = 0
            buffer = ""
    if buffer:
        chunks.append(buffer)

    # Apply overlap across chunk boundaries for a bit of smoothing
    overlapped: list[str] = []
    for i, c in enumerate(chunks):
        if i == 0 or ov <= 0:
            overlapped.append(c)
            continue
        prev_tail = chunks[i - 1][-ov:]
        overlapped.append(prev_tail + "\n" + c)
    return overlapped


def iter_chunks_with_pages(
    pages: Iterable[tuple[int, str]],
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[tuple[int, str]]:
    """Chunk text while attempting to attach the most relevant page number.

    Accepts ``(page_number, text)`` tuples. Returns ``(page_number, chunk)`` tuples.

    Safety: guarantees forward progress per iteration even if a caller passes
    ``overlap >= chunk_size`` (which would otherwise produce an infinite loop).
    """
    size = chunk_size or settings.chunk_size
    ov = overlap or settings.chunk_overlap
    if size <= 0:
        size = 1
    # Stride must always advance by at least 1 char; cap overlap to size-1.
    if ov >= size:
        ov = max(0, size - 1)
    stride = size - ov  # guaranteed >= 1

    out: list[tuple[int, str]] = []
    for page_number, page_text in pages:
        page_text = page_text.strip()
        if not page_text:
            continue
        if len(page_text) <= size:
            out.append((page_number, page_text))
            continue
        start = 0
        n = len(page_text)
        while start < n:
            end = min(start + size, n)
            out.append((page_number, page_text[start:end]))
            if end == n:
                break
            start += stride
    return out
