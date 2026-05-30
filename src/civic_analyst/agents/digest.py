"""City-wide digest — the batch-tier (gpt-oss-120B MoE) workload.

Interactive per-address reads use Nemotron Nano; summarizing the whole city's
risk picture is a heavier, latency-tolerant job, so it runs on the batch model.

The batch call takes ~15s, so we memoize the *real* digest in-process: the graph
is loaded once at startup and doesn't change during a run, so repeated demo
clicks should be instant after the first computation. The cache is keyed on the
rounded ranked scores (a stable signature of the ranked set) so a genuinely
different ranking recomputes rather than serving a stale briefing. The
deterministic offline fallback is *never* cached — that way, once a model
becomes available, the next call still produces (and then caches) a real digest.
"""
from __future__ import annotations

import threading

from .llm import LocalLLM, batch_llm

SYSTEM = (
    "You are a municipal operations analyst. Given a ranked list of Toronto "
    "addresses with risk scores and counts, write a 4-sentence briefing for an "
    "inspections manager: the top hotspots, the dominant risk pattern, and where "
    "to deploy inspectors first. Be specific and do not invent addresses."
)

# Module-level cache: { ranked_signature: real_digest_string }. A dict + lock is
# plenty thread-safe for uvicorn's worker(s); we only ever store real results.
_lock = threading.Lock()
_cache: dict[tuple, str] = {}


def _addr(r: dict) -> str:
    return r.get("address") or r.get("label") or "?"


def _signature(ranked: list[dict]) -> tuple:
    """Stable cache key for the ranked set: (address, rounded score) pairs in order.

    Rounding keeps the key stable against insignificant float jitter while still
    invalidating when the underlying ranking would actually differ (the digest
    only ever consumes the top 25, so the key mirrors that window)."""
    return tuple(
        (_addr(r), round(float(r.get("risk_score", 0.0)), 3)) for r in ranked[:25]
    )


def digest_cached(ranked: list[dict]) -> bool:
    """True iff a real digest for this exact ranked set is already memoized."""
    with _lock:
        return _signature(ranked) in _cache


def city_digest(ranked: list[dict], llm: LocalLLM | None = None) -> str:
    key = _signature(ranked)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    llm = llm or batch_llm()
    lines = "\n".join(f"- {_addr(r)}: risk {r['risk_score']}" for r in ranked[:25])
    try:
        result = llm.chat(SYSTEM, f"Ranked addresses:\n{lines}")
    except Exception as exc:  # offline / no model: deterministic fallback (NOT cached)
        top = _addr(ranked[0]) if ranked else "n/a"
        return f"(batch LLM unavailable: {exc}) Highest-risk address: {top}."

    with _lock:
        _cache[key] = result
    return result
