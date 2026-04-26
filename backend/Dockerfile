FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # sentence-transformers / HuggingFace model cache. Persisted via a named
    # docker volume so the BGE-small weights (~90 MB) only download once.
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/sentence-transformers \
    # Keep Torch CPU-only and single-threaded by default; docker-compose
    # overrides OMP/MKL thread counts for this container.
    TORCH_HOME=/app/.cache/torch

WORKDIR /app

# System deps for PyMuPDF, pdfplumber (needs libgl for some image ops)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        poppler-utils \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-create the cache dir so a non-root bind mount / volume attaches cleanly.
RUN mkdir -p /app/.cache/huggingface /app/.cache/torch

COPY app ./app

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
