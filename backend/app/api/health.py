"""Health check routes."""
from fastapi import APIRouter

from app import __version__
from app.config import settings
from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        version=__version__,
    )
