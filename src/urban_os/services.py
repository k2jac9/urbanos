"""Cross-domain benefit composition (ADR-0022 extraction; ADR-0019 semantics).

The multi-simulation "service" logic that used to live inline in the API route
handlers: the four-lens objective, the shared additive ``cross_domain_benefit``
helper (the single source of truth used by BOTH /lenses and /optimize so they can
never disagree), and the cross-domain panel. Keeping it here makes the route
handlers thin and lets the benefit math be unit-tested without the web layer.
"""
from __future__ import annotations

from .kernel import Simulation
from .learned_dynamics import evaluate as learned_dynamics_evaluate
from .optimize import objective
from .scenarios import default_lens_stack
from .serialize import r as _r

# ADR-0019: every benefit number we surface carries its definition, so the UI (and
# anyone reading the JSON) can label it. The audits found three differently-derived
# "benefit" figures shown unlabeled; these strings are the single source of truth
# for what each one means. Keys here MUST match the keys returned by the endpoints.
BENEFIT_DEFINITIONS: dict[str, str] = {
    "j_avoided": (
        "Reduction in the single combined objective J (the one number the optimizer "
        "minimises). Conservative and double-count-free: this is the honest headline "
        "and equals the narrator's 'net intervention benefit'."
    ),
    "cross_domain_benefit": (
        "Additive sum of the per-domain dollar improvements (transit + public safety "
        "+ local business). Larger than j_avoided because the domains are summed "
        "independently and can overlap — an upper, cross-domain framing, not a single "
        "objective. Computed once and shared by /lenses and /optimize so they agree."
    ),
    "combined_benefit": (
        "Deprecated alias retained for the current UI. On /optimize it equals "
        "cross_domain_benefit; on /lenses it is the four-lens J reduction "
        "(base_J - cur_J). Prefer the explicit j_avoided / cross_domain_benefit keys."
    ),
}


# Headline human metric per supplementary lens: (observed series key, how to
# aggregate it over the run). Dollars come from each lens's own cost(); this is the
# one extra natural-units number the UI shows next to the dollars.
_EXTRA_LENS_METRIC = {
    "ems_access": ("ems_exposure", "sum", "blocked-EMS exposure (person-min·crit)"),
    "emissions": ("emissions_kg", "sum", "idling CO₂e (kg)"),
    "noise_livability": ("noise_exposure", "sum", "residential crush (person-min·res)"),
    "fare_revenue": ("fare_in_system", "peak", "peak riders backed up"),
}


def _agg(series, how):
    if not series:
        return 0.0
    return float(max(series)) if how == "peak" else float(sum(series))


def extra_lens_report(lenses, baseline_result, current_result) -> dict:
    """Baseline/optimized/saved figures for the supplementary display lenses.

    Reads each lens's ``cost`` off the SAME two sims the /lenses endpoint already
    runs (the lenses ride along in the stack but are excluded from ``J``), so this
    adds no extra simulations and cannot move the headline numbers. Each entry also
    carries one human metric in natural units (kg, person-minutes, riders).

    Only the *priced* display lenses (those in ``_EXTRA_LENS_METRIC``) appear here.
    Advisory-only lenses that carry no dollar cost (e.g. the CongestionNowcast
    calibration lens, which reports a trust score rather than a harm) are surfaced
    through their own endpoint block, not as a $0 row that would read as "no harm"."""
    out: dict[str, dict] = {}
    for ln in lenses:
        if ln.name not in _EXTRA_LENS_METRIC:
            continue
        b = float(ln.cost(baseline_result))
        c = float(ln.cost(current_result))
        key, how, label = _EXTRA_LENS_METRIC.get(ln.name, (None, "sum", ln.name))
        entry = {
            "label": label,
            "baseline_cost": _r(b, 2),
            "optimized_cost": _r(c, 2),
            "saved": _r(b - c, 2),
        }
        if key is not None:
            mb = _agg(baseline_result.series(key), how)
            mc = _agg(current_result.series(key), how)
            entry["metric"] = {
                "baseline": _r(mb, 2), "optimized": _r(mc, 2), "saved": _r(mb - mc, 2),
            }
        out[ln.name] = entry
    return out


def calibration_report(lenses, result) -> dict:
    """Run-level data-driven calibration figures (Phase 1, advisory-only).

    Finds the ``congestion_nowcast`` lens in the stack (if present) and returns its
    kernel-vs-observed shape-agreement summary off the SAME sim — no extra run, no
    influence on ``J`` or the chosen lever. When the lens is absent or never aligned
    (no observed data), reports ``calibrated: False`` so the UI can say "not
    calibrated" instead of showing a misleading 0.0 fit."""
    nowcast = next((ln for ln in lenses if ln.name == "congestion_nowcast"), None)
    if nowcast is None:
        return {"calibrated": False, "mean_fit": 0.0, "min_fit": 0.0, "n_bins": 0}
    summary = nowcast.calibration_summary()
    return {
        "calibrated": summary["n_bins"] > 0,
        "mean_fit": _r(summary["mean_fit"], 3),
        "min_fit": _r(summary["min_fit"], 3),
        "n_bins": summary["n_bins"],
    }


def learned_dynamics_report(lenses, result) -> dict:
    """Run-level Action-Matching-floor diagnostic (Phase 2, advisory-only — ADR-0028).

    Reuses the observed-count series the ``congestion_nowcast`` lens already carries (no
    extra data plumbing), fits a learned velocity field from those marginals, rolls it
    out, and reports whether the learned field beats the exact kernel at matching the
    observed counts. Like the Phase-1 calibration it runs off the SAME finished sim — no
    extra simulation, no lever, no ``J`` contribution — so it cannot move any headline
    number (honesty #1). Off by default (``URBANOS_LEARNED_DYNAMICS`` unset) → a clean
    ``available: False`` no-op. Every figure is stamped ``provenance="learned/approximate"``
    so it is never mistaken for a kernel-exact number (honesty #3)."""
    nowcast = next((ln for ln in lenses if ln.name == "congestion_nowcast"), None)
    node_counts = getattr(nowcast, "node_counts", None) if nowcast is not None else None
    return learned_dynamics_evaluate(node_counts, result).as_dict()


def four_lens_stack(sc):
    """The full four-lens stack (transit + economic + civic safety + business)."""
    return default_lens_stack(sc, safety=True, business=True)


def four_lens_J(stack, result) -> float:
    """Objective J of a four-lens run = the sum of every lens's cost (the same
    additive objective the optimizer minimises). Native float, no numpy leak."""
    return float(sum(float(ln.cost(result)) for ln in stack))


def cross_domain_components(
    sc, *, release: float, shelter: float, safety: bool = True, business: bool = True
) -> dict:
    """Additive per-domain dollar improvements of ``(release, shelter)`` vs do-nothing.

    SINGLE SOURCE OF TRUTH for the ``cross_domain_benefit`` headline used by BOTH
    /lenses and /optimize, so the two surfaces can never disagree (contract-tested
    in ``test_benefit_semantics``). Honest framing: this is *additive* across domains
    — the components are summed independently and may overlap, so it is deliberately
    NOT the conservative single-objective number (see ``j_avoided``).

    - transit_savings: J reduction over the optimizer's weather-aware stack.
    - safety_reduction: civic SafetyLens cost avoided (0 when the lens is toggled off).
    - business_recovered: BusinessFlow loss avoided (0 when toggled off).
    """
    # Transit: J over the exact stack the optimizer/narrator search (incl. WeatherLens).
    cur_t, base_t = default_lens_stack(sc, weather=True), default_lens_stack(sc, weather=True)
    cur_tr = Simulation(sc.substrate, cur_t,
        params={"release_minutes": release, "shelter_fraction": shelter}, dt=sc.dt).run(sc.horizon)
    base_tr = Simulation(sc.substrate, base_t,
        params={"release_minutes": 0.0, "shelter_fraction": 0.0}, dt=sc.dt).run(sc.horizon)
    transit_savings = objective(base_tr, base_t) - objective(cur_tr, cur_t)

    # Safety + business: the civic SafetyLens + BusinessFlow at the same levers.
    cur_s, base_s = four_lens_stack(sc), four_lens_stack(sc)
    cur4 = Simulation(sc.substrate, cur_s,
        params={"release_minutes": release, "shelter_fraction": shelter}, dt=sc.dt).run(sc.horizon)
    base4 = Simulation(sc.substrate, base_s,
        params={"release_minutes": 0.0, "shelter_fraction": 0.0}, dt=sc.dt).run(sc.horizon)
    cur_safety = next(ln for ln in cur_s if ln.name == "safety")
    base_safety = next(ln for ln in base_s if ln.name == "safety")
    safety_reduction = (
        float(base_safety.cost(base4)) - float(cur_safety.cost(cur4)) if safety else 0.0
    )
    business_recovered = (
        float(sum(base4.series("business_lost"))) - float(sum(cur4.series("business_lost")))
        if business else 0.0
    )
    total = transit_savings + safety_reduction + business_recovered
    return {
        "transit_savings": transit_savings,
        "safety_reduction": safety_reduction,
        "business_recovered": business_recovered,
        "total": total,
    }


def cross_domain(sc, best_params: dict) -> dict:
    """Per-lens baseline/best panel (display only) at the optimizer's release.

    Two cheap extra sims (baseline vs best); never re-runs the lever search."""
    stack = four_lens_stack(sc)
    safety = next(ln for ln in stack if ln.name == "safety")
    base = Simulation(sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt).run(sc.horizon)
    best = Simulation(sc.substrate, stack, params=dict(best_params), dt=sc.dt).run(sc.horizon)
    base_lost = float(sum(base.series("business_lost")))
    best_lost = float(sum(best.series("business_lost")))
    return {
        "safety": {"baseline": _r(safety.cost(base), 0), "best": _r(safety.cost(best), 0)},
        "business": {"baseline_lost": _r(base_lost, 0), "recovered": _r(base_lost - best_lost, 0)},
    }


def cross_domain_safe(sc, best_params: dict):
    """Never let the cross-domain extras break the core /optimize response."""
    try:
        return cross_domain(sc, best_params)
    except Exception:
        return None


def cross_domain_block(sc, best_params: dict, safety: bool, business: bool) -> dict:
    """Cross-domain panel + the canonical additive benefit at the optimizer's levers.

    The headline ``cross_domain_benefit`` comes from the SHARED
    ``cross_domain_components`` helper — the same one /lenses uses — so both surfaces
    report the identical additive number at the same levers (contract-tested in
    ``test_benefit_semantics``). Toggling a lens off removes its dollars from the
    additive total. ``combined_benefit`` is retained as a deprecated alias for the
    current UI (see ``BENEFIT_DEFINITIONS``)."""
    release = float(best_params.get("release_minutes", 0.0))
    shelter = float(best_params.get("shelter_fraction", 0.0))
    comp = cross_domain_components(
        sc, release=release, shelter=shelter, safety=safety, business=business
    )
    # Per-lens baseline/best panel (display only) — never breaks the core response.
    full = cross_domain_safe(sc, best_params)
    cd = None
    if full:
        cd = {}
        if safety and full.get("safety"):
            cd["safety"] = full["safety"]
        if business and full.get("business"):
            cd["business"] = full["business"]
    return {
        "cross_domain": cd,
        "enabled": {"safety": bool(safety), "business": bool(business)},
        "cross_domain_benefit": _r(comp["total"], 2),
        "cross_domain_components": {k: _r(v, 2) for k, v in comp.items() if k != "total"},
        # Deprecated alias of cross_domain_benefit (see benefit_definitions).
        "combined_benefit": _r(comp["total"], 2),
    }
