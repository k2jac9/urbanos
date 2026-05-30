"""Economic lens — congestion → crowd-safety risk and the dollar cost of delay.

This is the lens that puts a number on the board. Two jobs:

- ``couple``: derive a crowd-safety ``risk`` field from density (``risk = ρ^2.5``,
  the super-linear curve crowd-dynamics work uses for crush risk) and the
  per-step commuter-delay cost from over-capacity crowding.
- ``observe`` / ``cost``: expose peak density and the running delay dollars, and
  contribute the run's total delay cost to the optimizer's objective ``J``.

Delay is modelled transparently as **person-minutes spent beyond comfortable
capacity**: anyone held at a node past its reference occupancy (``load > capacity``)
is waiting, and waiting time costs money. Linear in queue length — no fragile
high-exponent volume-delay term — so the dollar figure is auditable.

Calibration constants are plausibility-checked, not ground-truth-validated, and
are flagged as such (see README provenance).
"""
from __future__ import annotations

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens
from ..kernel.state import State

# Value of commuter time. Synthetic-but-standard ($/hour) — flagged in provenance.
VALUE_OF_TIME = 28.0
# Crush-risk exponent: risk rises super-linearly with density.
_RISK_EXP = 2.5


class EconomicLens(Lens):
    name = "economic"

    def __init__(self, *, weight: float = 1.0) -> None:
        self.weight = weight

    def couple(self, state: State, t: float) -> None:
        rho = state.fields["congestion"]
        # Crowd-safety risk field (drives the heatmap's danger layer).
        state.fields["risk"] = np.power(rho, _RISK_EXP)
        # Person-minutes of delay this step: everyone held beyond a node's
        # comfortable capacity is queueing, and pays dt minutes of delay.
        dt = state.params.get("dt", 1.0)
        queue = np.maximum(0.0, state.fields["load"] - state.substrate.capacity)
        person_min_delay = float(np.sum(queue) * dt)
        state.params["_delay_person_min_step"] = person_min_delay

    def observe(self, state: State, t: float) -> dict[str, float]:
        person_min = state.params.get("_delay_person_min_step", 0.0)
        return {
            "peak_congestion": float(np.max(state.fields["congestion"])),
            "peak_risk": float(np.max(state.fields["risk"])),
            "delay_cost": person_min / 60.0 * VALUE_OF_TIME,
            "in_system": float(state.fields["load"].sum()),
        }

    def cost(self, result: SimResult) -> float:
        """Total commuter-delay dollars over the run — this lens's J term."""
        return float(sum(result.series("delay_cost")))
