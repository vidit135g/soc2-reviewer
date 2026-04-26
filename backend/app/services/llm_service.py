"""Pluggable LLM provider abstraction.

Supports OpenAI, Anthropic, Groq, and Ollama. The active provider is selected
by the LLM_PROVIDER environment variable and must have a corresponding API
key (except Ollama, which is local).

If no provider is configured, a deterministic stub provider is used so that
the backend still functions end-to-end without network dependencies. Callers
can check ``is_stub`` to degrade gracefully in the UI.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    name: str = "base"
    is_stub: bool = False

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        """Return a text completion."""

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        raw = self.complete(
            system, user,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return _safe_parse_json(raw)


def _safe_parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        # Strip fenced code blocks
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Attempt to find the first JSON object in the string
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    logger.warning("Failed to parse LLM JSON response: %s", text[:200])
    return {}


# -----------------------------------------------------------------------------
# Providers
# -----------------------------------------------------------------------------


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float = 90.0) -> None:
        from openai import OpenAI

        # OpenAI SDK accepts a per-client timeout; without it the default is
        # 10 minutes which is way longer than Next's proxy and our retries
        # tolerate. We bound it tightly so a hung provider becomes a 504, not
        # a dangling socket.
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.model = model

    def complete(self, system: str, user: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024, json_mode: bool = False) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 90.0) -> None:
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key, timeout=timeout)
        self.model = model

    def complete(self, system: str, user: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024, json_mode: bool = False) -> str:
        instructions = system
        if json_mode:
            instructions += "\n\nReturn ONLY a valid JSON object with no prose."
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=instructions,
            messages=[{"role": "user", "content": user}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts)


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str, timeout: float = 90.0) -> None:
        from groq import Groq

        self.client = Groq(api_key=api_key, timeout=timeout)
        self.model = model

    def complete(self, system: str, user: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024, json_mode: bool = False) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # Reachability probe — raises on connection error / bad status so the
        # factory can fall through to StubProvider instead of failing every
        # future request with a 500.
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            tags = r.json().get("models", []) or []
        have_model = any(
            (m.get("name") or m.get("model") or "").startswith(model)
            for m in tags
        )
        if not have_model:
            logger.warning(
                "Ollama is reachable at %s but model '%s' is not pulled. "
                "Run `docker exec -it soc2-ollama ollama pull %s` to enable "
                "LLM features; chat will degrade until the model is present.",
                self.base_url, model, model,
            )

    def complete(self, system: str, user: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024, json_mode: bool = False) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            # Pin the model in RAM indefinitely. Default Ollama behaviour is
            # to evict after 5 minutes of idle, which means the *next* user
            # chat request pays the full model-load cost (30–60s on CPU)
            # before a single token comes back. Pinning trades ~3 GB of RAM
            # for snappy second-and-onwards completions.
            "keep_alive": -1,
        }
        if json_mode:
            payload["format"] = "json"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("message", {}).get("content", "")


class StubProvider(LLMProvider):
    """Deterministic no-network provider used when no API key is configured.

    It produces structured, conservative output so the UI remains functional
    in development and demo environments.
    """

    name = "stub"
    is_stub = True

    def complete(self, system: str, user: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024, json_mode: bool = False) -> str:
        if json_mode:
            if "suggested questions" in system.lower() or "questions" in user.lower()[:200]:
                return json.dumps({
                    "questions": [
                        "What is the report type (Type I or Type II)?",
                        "What is the audit coverage period?",
                        "Were any exceptions identified during testing?",
                        "Are the Security, Availability, and Confidentiality criteria covered?",
                        "Is multi-factor authentication required for privileged access?",
                        "Are backups tested on a defined cadence?",
                        "Which subservice organizations are in scope?",
                        "Has the report expired (older than 12 months)?",
                    ]
                })
            if "summary" in system.lower() or "executive" in user.lower()[:200]:
                return json.dumps({
                    "rating": "Moderate",
                    "executive_summary": (
                        "An LLM provider is not configured, so this summary is a conservative "
                        "placeholder. Configure OPENAI_API_KEY or another provider for a "
                        "narrative summary. Deterministic findings above remain valid."
                    ),
                    "key_strengths": [
                        "Deterministic validation engine ran successfully",
                        "Structured metadata extracted from the report",
                    ],
                    "key_risks": [
                        "LLM-assisted analysis disabled",
                        "Review findings manually against your onboarding checklist",
                    ],
                    "recommended_followups": [
                        "Confirm the auditor's opinion and scope",
                        "Validate coverage period against your requirements",
                    ],
                    "vendor_readiness": "Needs Review",
                })
        # Text mode — used by chat fallback
        return (
            "The LLM provider is not configured in this environment. "
            "Deterministic validation findings are still available. "
            "Configure OPENAI_API_KEY (or another provider) in the backend .env "
            "to enable grounded answers. The question you asked was: "
            + user[:200]
        )


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------


_provider_singleton: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _provider_singleton
    if _provider_singleton is not None:
        return _provider_singleton

    provider = settings.llm_provider
    model = settings.llm_model
    timeout = float(settings.llm_timeout_seconds)

    try:
        if provider == "openai" and settings.openai_api_key:
            _provider_singleton = OpenAIProvider(settings.openai_api_key, model, timeout=timeout)
        elif provider == "anthropic" and settings.anthropic_api_key:
            _provider_singleton = AnthropicProvider(settings.anthropic_api_key, model, timeout=timeout)
        elif provider == "groq" and settings.groq_api_key:
            _provider_singleton = GroqProvider(settings.groq_api_key, model, timeout=timeout)
        elif provider == "ollama":
            # Ollama needs no API key, just a reachable server. The
            # constructor probes /api/tags and raises if unreachable —
            # we catch below and fall through to the stub.
            _provider_singleton = OllamaProvider(settings.ollama_base_url, model, timeout=timeout)
        elif provider == "stub":
            _provider_singleton = StubProvider()
        else:
            logger.warning(
                "LLM provider=%r has no usable credentials; using stub provider. "
                "For zero-config local operation, start the Ollama service "
                "(`docker compose --profile ollama up -d`) and pull the model.",
                provider,
            )
            _provider_singleton = StubProvider()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "Failed to initialize %s provider (%s); falling back to stub. "
            "Fix the provider config or run Ollama locally to enable LLM features.",
            provider, exc,
        )
        _provider_singleton = StubProvider()

    logger.info("LLM provider active: %s", _provider_singleton.name)
    return _provider_singleton
