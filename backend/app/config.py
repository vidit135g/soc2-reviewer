"""Application configuration loaded from environment variables."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "SOC 2 Report Reviewer"
    environment: Literal["development", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api"

    # Database
    database_url: str = (
        "postgresql+psycopg2://soc2:soc2@postgres:5432/soc2_reviewer"
    )

    # Storage
    upload_dir: str = "/tmp/soc2-uploads"
    max_upload_mb: int = 50

    # CORS
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # LLM provider selection — defaults to Ollama so the project is fully
    # open-source and usable with zero paid API keys. Override via env for
    # OpenAI / Anthropic / Groq if you have a key.
    llm_provider: Literal["openai", "anthropic", "groq", "ollama", "stub"] = "ollama"
    llm_model: str = "llama3.2:3b"
    # Hard ceiling on a single LLM completion. Long enough for cloud-provider
    # cold starts and Ollama-on-CPU first-token latency, short enough to
    # surface a 504 back to the proxy well before Next's 5-minute
    # proxyTimeout drops the socket (see frontend/next.config.js).
    # If you're on Ollama + CPU and still timing out, raise this to 300s
    # *and* shrink ``chat_max_tokens`` below.
    llm_timeout_seconds: int = 180

    # Per-call token budget for the chat endpoint. Smaller = faster on
    # Ollama-on-CPU, larger = more thorough answers on cloud providers.
    chat_max_tokens: int = 500

    # Provider API keys (all optional — only needed for the matching provider)
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    # NOTE: inside docker-compose the ollama service is reachable at
    # http://ollama:11434; on a developer laptop with a native Ollama install
    # use http://host.docker.internal:11434 or http://localhost:11434.
    ollama_base_url: str = "http://ollama:11434"

    # Embeddings — local sentence-transformers by default (384-dim BGE-small).
    # Options: "local" (in-process, no network), "ollama" (local server),
    # "openai" (hosted, needs OPENAI_API_KEY).
    embedding_provider: Literal["openai", "local", "ollama"] = "local"
    embedding_model: str = "text-embedding-3-small"  # only used when provider=openai
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384-dim
    ollama_embedding_model: str = "nomic-embed-text"  # 768-dim
    # IMPORTANT: this MUST match the output dim of the configured provider.
    # BGE-small = 384, nomic-embed-text = 768, text-embedding-3-small = 1536.
    # Changing this after chunks exist requires dropping the chunks table.
    embedding_dimensions: int = 384

    # Semantic metadata augmentation (LLM fills regex gaps for paraphrased
    # opinions / coverage windows). Requires an LLM provider that is not
    # "stub". Set to false to disable and rely on regex only.
    semantic_augmentation: bool = True

    # RAG
    chunk_size: int = 1500
    chunk_overlap: int = 200
    top_k: int = 6

    # Rate limiting
    rate_limit_per_minute: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
