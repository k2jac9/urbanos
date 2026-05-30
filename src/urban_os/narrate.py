"""Killer-insight narrator — the one cited sentence the demo is built around.

Reuses civic_analyst's local-LLM client *and* its hallucination-guard pattern:
the simulation computes every figure deterministically; the local model only
gets to phrase them. We whitelist exactly the numbers the simulation produced
and reject any sentence that introduces a number outside that set, falling back
to a correct-by-construction template. So the headline is always grounded in the
run — never a fabricated statistic.

Mirrors the §4 "specific station, specific timing, specific lever, specific
dollars" insight from the build plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from civic_analyst.agents.llm import LocalLLM, interactive_llm

from .optimize import OptResult

_SYSTEM = (
    "You are an urban-operations analyst briefing a city transit operations chief "
    "after a major event. You are given a set of FIGURES computed by a simulation. "
    "Write exactly ONE sentence that states the insight: which station is the "
    "bottleneck, how overloaded it gets and when, and what the recommended "
    "staggered-release intervention saves. Hard rules: use ONLY numbers that appear "
    "in the FIGURES — never invent, round differently, total, or estimate any "
    "number; name the station exactly as given. Output the single sentence and "
    "nothing else."
)


@dataclass
class Insight:
    text: str
    grounded: bool          # True = verified LLM sentence; False = deterministic fallback
    figures: dict


def _ints(s: str) -> set[int]:
    return {int(x) for x in re.findall(r"\d+", s or "")}


def _figures(opt: OptResult, event_end: float) -> dict:
    """Distill the run into the small set of display figures the insight may use."""
    base_peak = opt.baseline_result.peak_congestion()
    best_peak = opt.best_result.peak_congestion()
    base_rho = base_peak["congestion"]
    best_rho = best_peak["congestion"]
    reduction = round((1 - best_rho / base_rho) * 100) if base_rho > 0 else 0
    return {
        "station": base_peak["label"],
        "base_mult": round(base_rho, 1),                       # e.g. 2.5 (×capacity)
        "best_mult": round(best_rho, 1),
        "minutes_after": max(0, round(base_peak["t"] - event_end)),
        "reduction_pct": reduction,
        "release_min": round(float(opt.best_params.get("release_minutes", 0))),
        "baseline_cost_k": round(opt.baseline_J / 1000),       # $k
        "savings_k": round(opt.savings / 1000),                # $k
    }


def _deterministic(f: dict) -> str:
    return (
        f"Doing nothing, {f['station']} peaks at {f['base_mult']}x its safe "
        f"capacity about {f['minutes_after']} minutes after full-time; a "
        f"{f['release_min']}-minute staggered release cuts that peak by "
        f"{f['reduction_pct']}% and saves about ${f['savings_k']}k in "
        f"commuter-delay cost."
    )


def _whitelist(f: dict, deterministic: str) -> set[int]:
    """Every integer the insight is allowed to contain: those in the canonical
    sentence plus the raw figure values (covers alternate phrasings)."""
    allowed = _ints(deterministic)
    for v in f.values():
        if isinstance(v, (int, float)):
            allowed |= _ints(str(v))
    return allowed


def build_insight(
    opt: OptResult, *, event_end: float, llm: LocalLLM | None = None
) -> Insight:
    """Produce the cited one-line insight. Tries the local model, verifies its
    numbers against the whitelist, and falls back to the deterministic sentence
    on any hallucination, malformed output, or offline endpoint."""
    f = _figures(opt, event_end)
    deterministic = _deterministic(f)
    allowed = _whitelist(f, deterministic)

    user = (
        "FIGURES:\n"
        f"- bottleneck station: {f['station']}\n"
        f"- peak load without action: {f['base_mult']}x safe capacity\n"
        f"- timing of peak: {f['minutes_after']} minutes after full-time\n"
        f"- recommended staggered release: {f['release_min']} minutes\n"
        f"- peak reduced by: {f['reduction_pct']}%\n"
        f"- commuter-delay saving: ${f['savings_k']}k"
    )

    try:
        out = (llm or interactive_llm()).chat(_SYSTEM, user, temperature=0.0).strip()
        out = out.split("\n")[0].strip().strip('"')
        grounded = bool(out) and f["station"] in out and not (_ints(out) - allowed)
        if grounded:
            return Insight(text=out, grounded=True, figures=f)
    except Exception:
        pass  # offline / malformed → deterministic fallback
    return Insight(text=deterministic, grounded=False, figures=f)
