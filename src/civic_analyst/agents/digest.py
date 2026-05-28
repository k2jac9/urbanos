"""City-wide digest — the batch-tier (gpt-oss-120B MoE) workload.

Interactive per-address reads use Nemotron Nano; summarizing the whole city's
risk picture is a heavier, latency-tolerant job, so it runs on the batch model.
"""
from __future__ import annotations

from .llm import LocalLLM, batch_llm

SYSTEM = (
    "You are a municipal operations analyst. Given a ranked list of Toronto "
    "addresses with risk scores and counts, write a 4-sentence briefing for an "
    "inspections manager: the top hotspots, the dominant risk pattern, and where "
    "to deploy inspectors first. Be specific and do not invent addresses."
)


def city_digest(ranked: list[dict], llm: LocalLLM | None = None) -> str:
    llm = llm or batch_llm()
    def addr(r: dict) -> str:
        return r.get("address") or r.get("label") or "?"

    lines = "\n".join(f"- {addr(r)}: risk {r['risk_score']}" for r in ranked[:25])
    try:
        return llm.chat(SYSTEM, f"Ranked addresses:\n{lines}")
    except Exception as exc:  # offline / no model: deterministic fallback
        top = addr(ranked[0]) if ranked else "n/a"
        return f"(batch LLM unavailable: {exc}) Highest-risk address: {top}."
