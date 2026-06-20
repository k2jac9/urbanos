"""Unit tests for urbanos.risk.agents.llm.LocalLLM.chat.

This is a real demo-failure surface: the narrator wraps chat() in a guard that
catches httpx errors and falls back to the deterministic path. These tests pin
the three behaviours that guard depends on:
  * 200 happy path returns the assistant content,
  * a timeout raises httpx.TimeoutException,
  * a 500 raises httpx.HTTPStatusError (via raise_for_status()).

We swap the real transport for an httpx.MockTransport by monkeypatching
httpx.Client so no network/model is needed (CI is offline).
"""
from __future__ import annotations

import httpx
import pytest

from urbanos.risk.agents.llm import LocalLLM


def _patch_transport(monkeypatch, handler):
    """Force every httpx.Client(...) constructed inside chat() to use a
    MockTransport with `handler`, preserving any other kwargs (timeout)."""
    real_client = httpx.Client

    def _factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", _factory)


def test_chat_happy_path_returns_content(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello from the model"}}]},
        )

    _patch_transport(monkeypatch, handler)
    llm = LocalLLM(base_url="http://test/v1", model="m", api_key="k")
    out = llm.chat(system="sys", user="usr")

    assert out == "hello from the model"
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer k"


def test_chat_timeout_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    _patch_transport(monkeypatch, handler)
    llm = LocalLLM(base_url="http://test/v1", model="m", api_key="k")

    with pytest.raises(httpx.TimeoutException):
        llm.chat(system="sys", user="usr")


def test_chat_http_500_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    _patch_transport(monkeypatch, handler)
    llm = LocalLLM(base_url="http://test/v1", model="m", api_key="k")

    with pytest.raises(httpx.HTTPStatusError):
        llm.chat(system="sys", user="usr")


def test_chat_omits_reasoning_effort_when_empty(monkeypatch):
    """reasoning_effort="" must omit the field (strict OpenAI endpoints reject
    unknown/empty values) — the batch tier relies on this."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    _patch_transport(monkeypatch, handler)
    llm = LocalLLM(base_url="http://test/v1", model="m", api_key="k", reasoning_effort="")
    llm.chat(system="sys", user="usr")

    assert "reasoning_effort" not in captured["payload"]
    assert captured["payload"]["model"] == "m"


def test_chat_includes_reasoning_effort_when_set(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    _patch_transport(monkeypatch, handler)
    llm = LocalLLM(
        base_url="http://test/v1", model="m", api_key="k", reasoning_effort="none"
    )
    llm.chat(system="sys", user="usr")

    assert captured["payload"]["reasoning_effort"] == "none"
