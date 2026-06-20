"""Digest memoization: a real digest is computed once, then served from cache.

Offline-safe — uses a counting stub LLM, never a real network call.
"""
import urbanos.risk.agents.digest as digest
from urbanos.risk.agents.digest import city_digest, digest_cached


class _CountingLLM:
    """Stand-in for the batch LLM that records how many times it was invoked."""

    def __init__(self, reply: str = "BRIEFING") -> None:
        self.calls = 0
        self.reply = reply

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        self.calls += 1
        return self.reply


class _BoomLLM:
    """Stand-in that always fails — exercises the offline fallback path."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        self.calls += 1
        raise RuntimeError("no model")


def _reset_cache() -> None:
    with digest._lock:
        digest._cache.clear()


def test_real_digest_is_cached_after_first_call():
    _reset_cache()
    # Two-index ranked rows (ADR 0014): each carries an independent safety + activity.
    ranked = [
        {"label": "100 Queen St W", "risk_safety": 0.593, "risk_activity": 0.113},
        {"label": "200 Bay St", "risk_safety": 0.0, "risk_activity": 0.4},
    ]
    llm = _CountingLLM()

    assert not digest_cached(ranked)
    first = city_digest(ranked, llm=llm)
    assert first == "BRIEFING"
    assert llm.calls == 1
    assert digest_cached(ranked)

    # Second identical call must hit the cache — the LLM is NOT re-invoked.
    second = city_digest(ranked, llm=llm)
    assert second == "BRIEFING"
    assert llm.calls == 1


def test_different_ranking_recomputes():
    _reset_cache()
    base = [{"label": "100 Queen St W", "risk_safety": 0.593, "risk_activity": 0.113}]
    changed = [{"label": "100 Queen St W", "risk_safety": 0.3, "risk_activity": 0.113}]
    llm = _CountingLLM()

    city_digest(base, llm=llm)
    city_digest(changed, llm=llm)  # different safety score → different key → recompute
    assert llm.calls == 2


def test_fallback_is_never_cached():
    _reset_cache()
    ranked = [{"label": "100 Queen St W", "risk_safety": 0.593, "risk_activity": 0.113}]
    boom = _BoomLLM()

    out = city_digest(ranked, llm=boom)
    assert "batch LLM unavailable" in out
    assert "100 Queen St W" in out
    # The deterministic fallback must NOT be cached, so a later real model can win.
    assert not digest_cached(ranked)
    assert boom.calls == 1

    # Once a model is available, the next call produces and caches a real digest.
    good = _CountingLLM()
    real = city_digest(ranked, llm=good)
    assert real == "BRIEFING"
    assert digest_cached(ranked)
