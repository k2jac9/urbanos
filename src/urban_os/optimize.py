"""Intervention optimizer — search lens-declared levers to minimize ``J``.

``J = Σ wₚ·Jₚ`` over the lenses' ``cost`` terms. P0 does an exhaustive grid
search over the (small, discrete) lever space; that is correct and trivially
deterministic. ``OptResult.solver`` records which solver produced the answer
(currently always ``"grid"``).

**On cuOpt (honest scoping):** cuOpt solves structured LP / MILP / routing
problems, NOT a black-box *simulation-in-the-loop* search — here ``J`` is produced
by running the kernel for each lever combo, which cuOpt cannot evaluate. So cuOpt
is *not* a drop-in for this optimizer; using it would require reformulating the
intervention as an LP/MILP (or a min-cost-flow on the capacitated substrate, which
cugraph/cuOpt's network solver could take). That reformulation is a real next step,
deliberately not faked here. The two RAPIDS accelerators that DO genuinely fit are
wired: ``nx-cugraph`` for the substrate shortest-paths bake (``kernel/state.py``)
and ``cuDF`` (via Polars' GPU engine) for the civic ingest (``ingest/loader.py``).

**On Modulus/PhysicsNeMo (honest scoping, ADR-0027):** at *city scale* this grid is
intractable, which is where a learned **surrogate** of ``J(levers)`` belongs. The
``surrogate`` seam wires that interface with the exact kernel as the reference — when
``URBANOS_SURROGATE=1`` and a trained PhysicsNeMo checkpoint is present, it predicts
``J`` per combo and records the prediction alongside the exact value (so accuracy is
visible), but ``best`` is ALWAYS chosen by the exact kernel ``J`` — an approximate
number can never reach the UI. Default off → byte-identical to the pure grid.

"Do nothing" is the first value of every lever (convention: index 0), so the
baseline is always part of the search and the reported saving is honest.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from . import surrogate as _surrogate
from .kernel.loop import SimResult
from .kernel.operators import Lens, Lever
from .kernel.state import Substrate


def objective(result: SimResult, lenses: list[Lens]) -> float:
    """The weighted cost ``J`` of a finished run."""
    return float(sum(lens.weight * lens.cost(result) for lens in lenses))


# The cost terms the UI/narrator surface so the optimizer's pick is reproducible
# from on-screen numbers (audit finding: the hold and shelter/safety costs were
# invisible, so "longer is always better by the heatmap" could not be reconciled
# with the optimizer's choice). Each maps to a per-step metric series the lenses
# already emit; ``total`` is just their sum and equals ``J`` (weights are 1.0 in
# the demo stack, asserted by the cost-decomposition test).
_COST_TERMS = ("delay", "hold", "exposure", "staffing", "safety")


def cost_breakdown(result: SimResult, lenses: list[Lens]) -> dict[str, float]:
    """Decompose ``J`` into its named dollar terms for transparency.

    Returns ``{delay, hold, exposure, staffing, safety, total}``. ``total`` is the
    sum of the five terms and equals ``objective(result, lenses)`` for the demo
    three-lens stack (all weights 1.0). Terms are derived from the per-step metric
    series the lenses emit, so this never re-runs the simulation.

    - **delay**: commuter-delay dollars (over-capacity queueing) — EconomicLens.
    - **safety**: integrated crowd-safety risk priced into ``J`` — EconomicLens.
    - **exposure**: rain-exposure discomfort for the unsheltered — WeatherLens.
    - **staffing**: cost of running shelter over the in-system rained-on load.
    - **hold**: staggered-release hold cost (orderly waiting) — EventSurge.
    """
    delay = float(sum(result.series("delay_cost")))
    safety = float(sum(result.series("safety_cost")))
    exposure = float(sum(result.series("exposure_cost")))
    total = objective(result, lenses)
    # Staffing is the part of the weather-lens cost beyond exposure; hold is the
    # remainder of J once the economic + weather terms are accounted for. Deriving
    # them by subtraction keeps the lenses the single source of truth for their
    # own ``cost`` (no formula is duplicated here) while still naming every term.
    staffing = max(0.0, total - delay - safety - exposure - _hold_cost(result, lenses))
    hold = _hold_cost(result, lenses)
    breakdown = {
        "delay": delay,
        "hold": hold,
        "exposure": exposure,
        "staffing": staffing,
        "safety": safety,
    }
    breakdown["total"] = total
    return breakdown


def _hold_cost(result: SimResult, lenses: list[Lens]) -> float:
    """The staggered-release hold dollars: the EventSurge lens's whole cost term
    (it contributes only the hold penalty to ``J``)."""
    for lens in lenses:
        if getattr(lens, "name", "") == "event_surge":
            return float(lens.weight * lens.cost(result))
    return 0.0


@dataclass
class OptResult:
    levers: list[Lever]
    baseline_params: dict
    baseline_result: SimResult
    baseline_J: float
    best_params: dict
    best_result: SimResult
    best_J: float
    trials: list[dict] = field(default_factory=list)  # [{params, J}]
    # Per-run J decomposition (delay/hold/exposure/staffing/safety/total) for the
    # do-nothing baseline and the chosen intervention — surfaced so the UI/narrator
    # can show WHY the optimizer picks its answer (audit finding). None for
    # directly-constructed OptResults; ``optimize()`` always fills them.
    baseline_breakdown: dict | None = None
    best_breakdown: dict | None = None
    # Which solver produced this result. Always "grid" today (the honest,
    # deterministic exhaustive search). A future cuOpt LP/MILP reformulation would
    # set "cuopt" — see the module docstring for why cuOpt is not a drop-in.
    solver: str = "grid"
    # Which backend produced the J *predictions*: "none" (exact kernel only — the
    # honest default) or "physicsnemo" (a trained Modulus/PhysicsNeMo surrogate also
    # ran, recorded per-trial as J_surrogate). The surrogate never changes ``best``.
    surrogate_backend: str = "none"

    @property
    def savings(self) -> float:
        """Dollars (or J units) the chosen intervention saves vs. doing nothing."""
        return self.baseline_J - self.best_J

    def to_dict(self) -> dict:
        return {
            "baseline": {
                "params": self.baseline_params,
                "J": self.baseline_J,
                "breakdown": self.baseline_breakdown,
            },
            "best": {
                "params": self.best_params,
                "J": self.best_J,
                "breakdown": self.best_breakdown,
            },
            "savings": self.savings,
            "levers": [{"name": lv.name, "label": lv.label} for lv in self.levers],
            "trials": self.trials,
        }


def optimize(
    substrate: Substrate,
    lenses: list[Lens],
    horizon: int,
    *,
    dt: float = 1.0,
    beta: float = 1.8,
    base_params: dict | None = None,
) -> OptResult:
    """Grid-search every lever combination; return the J-minimizing intervention
    alongside the do-nothing baseline. Lenses are reused across trials (their
    ``configure`` is idempotent); each trial builds a fresh ``Simulation`` so no
    state leaks between runs."""
    # Imported here to avoid a kernel→optimizer import cycle at module load.
    from .kernel.loop import Simulation

    levers = [lv for lens in lenses for lv in lens.levers()]
    base = dict(base_params or {})

    def run(params: dict) -> SimResult:
        sim = Simulation(substrate, lenses, params=params, dt=dt, beta=beta)
        return sim.run(horizon)

    # Baseline: every lever at its do-nothing (first) value.
    baseline_params = dict(base)
    for lv in levers:
        baseline_params.setdefault(lv.name, lv.values[0])
    baseline_result = run(baseline_params)
    baseline_J = objective(baseline_result, lenses)

    best_params, best_result, best_J = baseline_params, baseline_result, baseline_J
    trials: list[dict] = []

    # Optional PhysicsNeMo/Modulus surrogate (ADR-0027). None unless URBANOS_SURROGATE=1
    # *and* a trained checkpoint is present — then it predicts J per combo for
    # transparency, but never changes which combo wins (exact kernel decides).
    sur = _surrogate.JSurrogate.load([lv.name for lv in levers])
    _surrogate.SURROGATE_BACKEND = "physicsnemo" if sur is not None else "none"

    grids = [lv.values for lv in levers]
    for combo in itertools.product(*grids) if levers else [()]:
        params = dict(base)
        for lv, val in zip(levers, combo):
            params[lv.name] = val
        result = run(params)
        J = objective(result, lenses)
        trial = {"params": {lv.name: params[lv.name] for lv in levers}, "J": J}
        if sur is not None:  # advisory only — recorded next to the exact J
            try:
                trial["J_surrogate"] = sur.predict(params)
            except Exception:
                pass
        trials.append(trial)
        if J < best_J:
            best_params, best_result, best_J = params, result, J

    return OptResult(
        levers=levers,
        baseline_params=baseline_params,
        baseline_result=baseline_result,
        baseline_J=baseline_J,
        best_params=best_params,
        best_result=best_result,
        best_J=best_J,
        trials=trials,
        baseline_breakdown=cost_breakdown(baseline_result, lenses),
        best_breakdown=cost_breakdown(best_result, lenses),
        solver="grid",
        surrogate_backend=_surrogate.SURROGATE_BACKEND,
    )
