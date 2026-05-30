"""Intervention optimizer — search lens-declared levers to minimize ``J``.

``J = Σ wₚ·Jₚ`` over the lenses' ``cost`` terms. P0 does an exhaustive grid
search over the (small, discrete) lever space; that is correct and trivially
deterministic, and it is the seam where **cuOpt** drops in on the GX10 for the
larger joint-lever problem (the search is isolated behind ``optimize`` so the
solver can be swapped without touching lenses or the kernel).

"Do nothing" is the first value of every lever (convention: index 0), so the
baseline is always part of the search and the reported saving is honest.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from .kernel.loop import SimResult
from .kernel.operators import Lens, Lever
from .kernel.state import Substrate


def objective(result: SimResult, lenses: list[Lens]) -> float:
    """The weighted cost ``J`` of a finished run."""
    return float(sum(lens.weight * lens.cost(result) for lens in lenses))


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

    @property
    def savings(self) -> float:
        """Dollars (or J units) the chosen intervention saves vs. doing nothing."""
        return self.baseline_J - self.best_J

    def to_dict(self) -> dict:
        return {
            "baseline": {"params": self.baseline_params, "J": self.baseline_J},
            "best": {"params": self.best_params, "J": self.best_J},
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

    grids = [lv.values for lv in levers]
    for combo in itertools.product(*grids) if levers else [()]:
        params = dict(base)
        for lv, val in zip(levers, combo):
            params[lv.name] = val
        result = run(params)
        J = objective(result, lenses)
        trials.append({"params": {lv.name: params[lv.name] for lv in levers}, "J": J})
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
    )
