"""Killer-insight narrator — the one cited sentence the demo is built around.

Reuses urbanos.risk's local-LLM client *and* its hallucination-guard pattern
(see ``urbanos.risk.agents.verify``): the simulation computes every figure
deterministically; the local model only gets to phrase them. We whitelist
exactly the numbers the simulation produced and reject any sentence that
introduces a number outside that set, falling back to a correct-by-construction
template. So the headline is always grounded in the run — never a fabricated
statistic.

Mirrors the §4 "specific station, specific timing, specific lever, specific
dollars" insight from the build plan.

Guard invariant (held for BOTH the LLM and the fallback path):
    every numeric token in ``insight.text`` is drawn from ``insight.figures``.
``grounded`` is True only for a *verified* LLM sentence; the deterministic
fallback reports ``grounded=False`` but still satisfies the invariant by
construction. The narrator never crashes and never fabricates a number, even
on a degenerate / empty scenario or an offline endpoint.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from urbanos.risk.agents.llm import LocalLLM, interactive_llm

from .optimize import OptResult

_SYSTEM = (
    "You are an urban-operations analyst briefing a city transit operations chief "
    "after a major event. You are given a set of FIGURES computed by a simulation. "
    "Write exactly ONE sentence that states the insight: which station is the "
    "bottleneck, how overloaded it gets and when, the recommended intervention "
    "(staggered release AND shelter coverage), and the NET benefit it delivers. "
    "Hard rules: use ONLY numbers that appear in the FIGURES — never invent, round "
    "differently, total, or estimate any number; name the station exactly as given. "
    "The saving is the NET intervention benefit (the drop in total objective J, "
    "which already nets out the hold penalty and the weather/safety terms) — do NOT "
    "call it a commuter-delay saving. Output the single sentence and nothing else."
)

# A "number" the guard reasons about: a comma-grouped integer (``394,000``), or a
# plain integer / decimal, optionally signed. We keep decimals intact (``2.5``)
# rather than splitting them into ``{2, 5}`` so a figure like 2.5x can never be
# confused with the unrelated integer 25 — and we treat a thousands-grouped integer
# as the single value it denotes (``394,000`` -> 394000), NOT as ``{394, 0}``.
# Splitting on the comma would force the spurious ``0`` group into the whitelist,
# which would let a stray ``0`` substituted for a real figure pass as grounded.
_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?")


def _nums(s: str) -> set[str]:
    """Normalised numeric tokens in ``s`` (e.g. ``"2.50"`` and ``"2.5"`` collapse,
    ``"07"`` and ``"7"`` collapse). Returns canonical string forms so int/float
    figures compare on value, not on their incidental textual rendering."""
    out: set[str] = set()
    for tok in _NUM_RE.findall(s or ""):
        try:
            val = float(tok.replace(",", ""))  # drop thousands separators: 394,000 -> 394000
        except ValueError:  # pragma: no cover - regex guarantees parseability
            continue
        out.add(_canon(val))
    return out


def _canon(val: float) -> str:
    """Canonical string for a number: integral values render without a fractional
    part (``2.0`` -> ``"2"``) so they match how the sentence prints them."""
    if not math.isfinite(val):
        return "nan"
    if float(val).is_integer():
        return str(int(val))
    return repr(round(float(val), 6)).rstrip("0").rstrip(".")


# Years are descriptive context, not simulation outputs; exempt them from the
# whitelist exactly as urbanos.risk's verifier does (1900..2100).
def _is_year(tok: str) -> bool:
    try:
        v = float(tok)
    except ValueError:  # pragma: no cover
        return False
    return v.is_integer() and 1900 <= v <= 2100


def _figures(opt: OptResult, event_end: float) -> dict:
    """Distill the run into the small set of display figures the insight may use.

    Robust to degenerate runs: an empty substrate, a run with no frames, or a
    scenario where nothing ever congests yields ``station=None`` from
    ``peak_congestion`` and a zero peak — we surface that cleanly instead of
    crashing or inventing a station/number downstream."""
    base_peak = opt.baseline_result.peak_congestion()
    best_peak = opt.best_result.peak_congestion()
    base_rho = float(base_peak["congestion"])
    best_rho = float(best_peak["congestion"])
    reduction = round((1 - best_rho / base_rho) * 100) if base_rho > 0 else 0
    # Reduction is a percentage of a peak; clamp to [0, 100] so a numerically
    # noisy best>baseline (which should not happen — baseline is in the search)
    # can never print a negative or >100% "reduction".
    reduction = max(0, min(100, reduction))
    return {
        "station": base_peak["label"],                          # may be None (degenerate)
        "base_mult": round(base_rho, 1),                        # e.g. 2.5 (×capacity)
        "best_mult": round(best_rho, 1),
        "minutes_after": max(0, round(float(base_peak["t"]) - float(event_end))),
        # Absolute clock minute of the peak (the real ``peak.t``) so the sentence
        # can disambiguate "N minutes after full-time" from an absolute clock time.
        # Both are genuine simulation figures, both whitelisted by the guard.
        "peak_t_abs": max(0, round(float(base_peak["t"]))),
        "reduction_pct": reduction,
        "release_min": round(float(opt.best_params.get("release_minutes", 0))),
        # Shelter coverage the optimizer chose, as a whole-number percentage. The
        # narrator reflects BOTH levers; 0 ⇒ no shelter in the recommendation.
        "shelter_pct": max(
            0, min(100, round(float(opt.best_params.get("shelter_fraction", 0)) * 100))
        ),
        "baseline_cost_k": round(float(opt.baseline_J) / 1000),  # $k
        # NET intervention benefit (drop in total J) in $k — already nets the hold
        # penalty + weather/safety terms; never negative (baseline is in the search).
        "savings_k": max(0, round(float(opt.savings) / 1000)),
    }


def _station_phrase(station: object) -> str:
    """The bottleneck name for the sentence. Degenerate runs (no congestion peak)
    have no station; say so plainly rather than printing the literal ``None``."""
    if station is None or not str(station).strip():
        return "no single station"
    return str(station)


def _intervention_phrase(f: dict) -> str:
    """Name both levers the optimizer chose: staggered release always, plus
    shelter coverage when it is part of the recommendation."""
    release = f"a {f['release_min']}-minute staggered release"
    if f["shelter_pct"] > 0:
        return f"{release} with {f['shelter_pct']}% shelter coverage"
    return release


def _deterministic(f: dict) -> str:
    return (
        f"Doing nothing, {_station_phrase(f['station'])} peaks at {f['base_mult']}x "
        f"its safe capacity about {f['minutes_after']} minutes after full-time "
        f"(t={f['peak_t_abs']} min); {_intervention_phrase(f)} cuts that peak by "
        f"{f['reduction_pct']}% for a net intervention benefit of about ${f['savings_k']}k."
    )


# Figures whose value is denominated in *thousands of dollars* (``$k``). The
# sentence prints these as ``$<V>k`` (e.g. savings_k=394 -> "$394k"), but a model
# that doesn't speak the ``$k`` shorthand may instead write the SAME value in full
# (``$394,000`` or ``394000``). Those are not new numbers — they are alternate
# renderings of an already-evidenced figure — so the guard accepts them too (see
# ``_thousands_forms``). Detected by the documented ``_k`` key suffix.
def _is_thousands_key(key: object) -> bool:
    return isinstance(key, str) and key.endswith("_k")


def _thousands_forms(value: float) -> set[str]:
    """Canonical token for the full-dollar rendering of a ``$k`` figure value ``V``.

    A ``$k`` figure is a dollar amount in thousands, so its full form is ``V*1000``.
    A model that doesn't use the ``$k`` shorthand may write that same amount in full,
    grouped (``$394,000``) or un-grouped (``394000``). The comma-aware tokenizer maps
    BOTH renderings to the one value ``V*1000``, so whitelisting that single token
    accepts both — and ONLY that exact value. No fuzz, range, or rounding tolerance;
    and, unlike splitting on the comma, no spurious ``0`` group enters the whitelist,
    so a stray ``0`` substituted for a real figure is still rejected. A non-evidenced
    amount stays rejected: ``$500,000`` -> ``{"500000"}``, not a figure, so flagged."""
    if not math.isfinite(value):
        return set()
    full = int(round(value)) * 1000
    return {_canon(float(full))}


def _whitelist(f: dict) -> set[str]:
    """Every numeric token the insight is allowed to contain: the canonical form
    of each figure value. This is the single source of truth — the deterministic
    sentence is built only from these same values, so it is grounded by
    construction and the LLM sentence is held to the identical set.

    For ``$k``-denominated figures (the ``_k`` keys) we ALSO whitelist the full-dollar
    renderings of the SAME value (``$394k`` ⇔ ``$394,000`` ⇔ ``394000``) so a model
    that writes thousands in full is not mistaken for hallucinating — see
    ``_thousands_forms``. This adds no fuzz/range/rounding tolerance; only the exact
    alternate representations of an already-evidenced number become allowed."""
    allowed: set[str] = set()
    for k, v in f.items():
        if isinstance(v, bool):  # bool is an int subclass; never a figure number
            continue
        if isinstance(v, (int, float)):
            if math.isfinite(float(v)):
                allowed.add(_canon(float(v)))
                if _is_thousands_key(k):
                    allowed |= _thousands_forms(float(v))
    return allowed


def _unverified(text: str, allowed: set[str]) -> set[str]:
    """Numeric tokens in ``text`` that are neither a whitelisted figure nor a year.
    Empty set == grounded (every number traces to the evidence)."""
    return {n for n in _nums(text) if n not in allowed and not _is_year(n)}


def is_grounded(text: str, figures: dict) -> bool:
    """Public guard predicate: does every number in ``text`` come from ``figures``?

    The hallucination-guard invariant in one call — used by ``build_insight`` and
    available to tests/callers that want to assert groundedness directly."""
    return not _unverified(text, _whitelist(figures))


@dataclass
class Insight:
    text: str
    grounded: bool          # True = verified LLM sentence; False = deterministic fallback
    figures: dict


def build_insight(
    opt: OptResult, *, event_end: float, llm: LocalLLM | None = None
) -> Insight:
    """Produce the cited one-line insight. Tries the local model, verifies its
    numbers against the whitelist, and falls back to the deterministic sentence
    on any hallucination, malformed output, or offline endpoint.

    Guarantees: the returned ``text`` never contains a number absent from
    ``figures`` (years excepted), the call never raises on a degenerate run, and
    the output is deterministic + offline-safe (no network required)."""
    f = _figures(opt, event_end)
    deterministic = _deterministic(f)
    allowed = _whitelist(f)
    station = _station_phrase(f["station"])

    # Defensive invariant: the fallback is grounded by construction. If a code
    # change ever broke that, we would rather ship a slightly less specific (but
    # still grounded) sentence than emit an ungrounded headline.
    if _unverified(deterministic, allowed):  # pragma: no cover - construction-guarded
        deterministic = (
            f"{station} is the projected bottleneck; the recommended intervention "
            f"reduces the peak for a net benefit (see figures)."
        )

    user = (
        "FIGURES:\n"
        f"- bottleneck station: {station}\n"
        f"- peak load without action: {f['base_mult']}x safe capacity\n"
        f"- timing of peak: {f['minutes_after']} minutes after full-time "
        f"(absolute clock t={f['peak_t_abs']} min)\n"
        f"- recommended staggered release: {f['release_min']} minutes\n"
        f"- recommended shelter coverage: {f['shelter_pct']}%\n"
        f"- peak reduced by: {f['reduction_pct']}%\n"
        f"- net intervention benefit: ${f['savings_k']}k"
    )

    try:
        out = (llm or interactive_llm()).chat(_SYSTEM, user, temperature=0.0).strip()
        out = out.split("\n")[0].strip().strip('"').strip()
        grounded = (
            bool(out)
            and station in out
            and not _unverified(out, allowed)
        )
        if grounded:
            return Insight(text=out, grounded=True, figures=f)
    except Exception:
        pass  # offline / malformed → deterministic fallback
    return Insight(text=deterministic, grounded=False, figures=f)
