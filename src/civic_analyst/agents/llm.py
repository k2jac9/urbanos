"""Local LLM client against an OpenAI-compatible endpoint.

On the GX10 this is Ollama (http://localhost:11434/v1) serving a small-active model
(Nemotron Nano, or gpt-oss-120B MoE). Everything runs on-device — no cloud, the
whole privacy/sovereignty pitch. Kept dependency-free (httpx only) so it also runs
in CI without a model present (callers handle the offline fallback).
"""
from __future__ import annotations

import httpx

from ..config import settings


class LocalLLM:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self._timeout = timeout

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        """Single-turn chat completion. Raises httpx errors if the endpoint is down."""
        payload = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


def interactive_llm() -> LocalLLM:
    """Small-active model (Nemotron Nano) for low-latency calls."""
    return LocalLLM(model=settings.llm_model)


def batch_llm() -> LocalLLM:
    """Larger MoE model (gpt-oss-120B) for heavier batch reasoning, with a longer timeout."""
    return LocalLLM(model=settings.llm_batch_model, timeout=600.0)
