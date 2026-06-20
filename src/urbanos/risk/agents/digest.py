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

import re
import threading

from .llm import LocalLLM, batch_llm

SYSTEM = (
    "You are a municipal operations analyst. You are given TWO independent priority "
    "lists of Toronto addresses: a FOOD SAFETY list (ranked by adverse inspection "
    "visits) and a CONSTRUCTION ACTIVITY list (ranked by open building permits). "
    "These are SEPARATE risk axes — never blend or total them. Write a 4-sentence "
    "briefing for an inspections manager: name the top food-safety hotspots and the "
    "top construction-activity hotspots SEPARATELY, and say where to deploy health "
    "inspectors vs building inspectors first. Be specific and do not invent "
    "addresses. Do not editorialize about data completeness (e.g. missing fields, "
    "postal codes, or null values) — report only on risk."
)

# Raw DineSafe labels embed a literal "None" street-direction token, e.g.
# "142 Parliament St None M5A 2Z1" — the postal code IS present after it. Left
# in, the LLM misreads the stray token as a missing postal code. Strip any
# standalone "None"/"NONE" word (not substrings like "Noneworth") and collapse
# the resulting whitespace, keeping the street number and postal code intact.
_NONE_TOKEN = re.compile(r"\bnone\b", flags=re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean_label(label: str) -> str:
    """Remove a stray standalone 'None' token from a display label."""
    if not label:
        return label
    return _WS.sub(" ", _NONE_TOKEN.sub(" ", label)).strip()

# Module-level cache: { ranked_signature: real_digest_string }. A dict + lock is
# plenty thread-safe for uvicorn's worker(s); we only ever store real results.
_lock = threading.Lock()
_cache: dict[tuple, str] = {}


def _addr(r: dict) -> str:
    return _clean_label(r.get("address") or r.get("label") or "?")


def _safety(r: dict) -> float:
    return round(float(r.get("risk_safety", 0.0)), 3)


def _activity(r: dict) -> float:
    return round(float(r.get("risk_activity", 0.0)), 3)


def _priorities(ranked: list[dict], score, top: int = 25) -> list[tuple[str, float]]:
    """The top addresses on one axis, hottest-first, dropping zero-risk sites — a
    standalone priority list for that axis (Safety or Activity), per ADR 0014 §7."""
    rows = [(_addr(r), score(r)) for r in ranked]
    rows = [(a, s) for a, s in rows if s > 0]
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:top]


def _signature(ranked: list[dict]) -> tuple:
    """Stable cache key for the ranked set: BOTH per-axis priority lists (ADR 0014).

    Rounding keeps the key stable against insignificant float jitter while still
    invalidating when either axis's ranking would actually differ (the digest
    only ever consumes the top 25 of each list, so the key mirrors that window)."""
    return (
        tuple(_priorities(ranked, _safety)),
        tuple(_priorities(ranked, _activity)),
    )


def digest_cached(ranked: list[dict]) -> bool:
    """True iff a real digest for this exact ranked set is already memoized."""
    with _lock:
        return _signature(ranked) in _cache


def _axis_block(title: str, rows: list[tuple[str, float]]) -> str:
    if not rows:
        return f"{title}: (none on record)"
    body = "\n".join(f"- {a}: {s}" for a, s in rows)
    return f"{title}:\n{body}"


def city_digest(ranked: list[dict], llm: LocalLLM | None = None) -> str:
    key = _signature(ranked)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    safety = _priorities(ranked, _safety)
    activity = _priorities(ranked, _activity)
    llm = llm or batch_llm()
    user = (
        _axis_block("FOOD SAFETY priorities (by adverse inspection visits)", safety)
        + "\n\n"
        + _axis_block("CONSTRUCTION ACTIVITY priorities (by open permits)", activity)
    )
    try:
        result = llm.chat(SYSTEM, user)
    except Exception as exc:  # offline / no model: deterministic fallback (NOT cached)
        top_s = safety[0][0] if safety else "n/a"
        top_a = activity[0][0] if activity else "n/a"
        return (f"(batch LLM unavailable: {exc}) Top food-safety site: {top_s}; "
                f"top construction-activity site: {top_a}.")

    with _lock:
        _cache[key] = result
    return result
