"""FastAPI entry point for the SOC 2 Report Reviewer backend."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.api import chat as chat_router
from app.api import health as health_router
from app.api import reports as reports_router
from app.config import settings
from app.db.database import init_db
from app.utils.ratelimit import limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _warmup_providers() -> None:
    """Preload the embedding model + LLM provider so the first upload is fast.

    Runs synchronously inside a thread (dispatched from the async lifespan).
    Each step is defensively wrapped — a failure here must never prevent the
    server from coming up.
    """
    try:
        from app.services.embedding_service import get_embedding_service

        es = get_embedding_service()
        # Touch the model with a dummy embed so weights actually load into
        # RAM now (sentence-transformers is lazy on SentenceTransformer()).
        _ = es.embed_one("warmup")
        logger.info("Embedding warmup done: provider=%s dim=%d", es.provider_name, es.dim)
    except Exception as exc:
        logger.warning("Embedding warmup skipped: %s", exc)

    try:
        from app.services.llm_service import get_llm_provider

        p = get_llm_provider()
        logger.info("LLM provider ready: %s (stub=%s)", p.name, p.is_stub)
    except Exception as exc:
        logger.warning("LLM warmup skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting SOC 2 Report Reviewer backend v%s", __version__)
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as exc:
        logger.error("Failed to initialize database: %s", exc)
        # Do not crash on startup — allow /health to still report

    # Fire warmup in the background so /health stays responsive. First
    # upload may still hit the tail end of this if it happens within ~30 s,
    # but subsequent uploads benefit.
    asyncio.create_task(asyncio.to_thread(_warmup_providers))

    yield
    logger.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)
app.state.limiter = limiter

# Register rate-limit handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routes
app.include_router(health_router.router)
app.include_router(reports_router.router, prefix=settings.api_prefix)
app.include_router(chat_router.router, prefix=settings.api_prefix)


@app.get("/", tags=["root"])
def root():
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
    }
