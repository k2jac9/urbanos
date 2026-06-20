"""Economic lens — congestion → crowd-safety risk and the dollar cost of delay.

This is the lens that puts a number on the board. Two jobs:

- ``couple``: derive a crowd-safety ``risk`` field from density (``risk = ρ^2.5``,
  the super-linear curve crowd-dynamics work uses for crush risk) and the
  per-step commuter-delay cost from over-capacity crowding.
- ``observe`` / ``cost``: expose peak density and the running delay dollars, and
  contribute the run's total delay cost **and an integrated crowd-safety cost**
  to the optimizer's objective ``J``.

Delay is modelled transparently as **person-minutes spent beyond comfortable
capacity**: anyone held at a node past its reference occupancy (``load > capacity``)
is waiting, and waiting time costs money. Linear in queue length — no fragile
high-exponent volume-delay term — so the dollar figure is auditable.

**Safety cost.** The optimizer used to see only delay + hold + exposure +
staffing, so the crowd-safety ``risk`` field — the whole reason shelter exists —
never entered ``J``: shelter was all-cost and never chosen (audit finding). We
now price the *integrated* risk field (Σ over steps and nodes of ``risk`` × dt)
into ``J`` at ``VALUE_OF_SAFETY`` $/(risk·person·minute). Because WeatherLens
amplifies ``risk`` by ``(1 + 0.6·wet)`` and shelter cuts ``wet``, deploying
shelter now *lowers* this term — giving the shelter lever a real, dollarised
benefit and making it a genuine interior optimum.

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
# Dollar value the objective places on one unit of integrated crowd-safety risk
# (risk-field summed over every node and every minute of the run). This is the
# price that lets the optimizer trade staffing dollars for a safer egress — and
# the term shelter shrinks by dividing the (weather-amplified) risk field.
# Calibrated (ADR-0015) so shelter is chosen above a realistic rain intensity and
# never strictly dominated. Synthetic — flagged in provenance.
VALUE_OF_SAFETY = 350.0


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
        dt = float(state.params.get("dt", 1.0))
        # Integrate the risk field over the network this step. This is read AFTER
        # every lens's couple() has run (observe is the last phase of the loop),
        # so any WeatherLens risk amplification is already baked in — the safety
        # cost therefore *falls* when shelter cuts the wetness multiplier.
        integrated_risk = float(np.sum(state.fields["risk"])) * dt
        return {
            "peak_congestion": float(np.max(state.fields["congestion"])),
            "peak_risk": float(np.max(state.fields["risk"])),
            "delay_cost": person_min / 60.0 * VALUE_OF_TIME,
            "safety_cost": integrated_risk * VALUE_OF_SAFETY,
            "in_system": float(state.fields["load"].sum()),
        }

    def cost(self, result: SimResult) -> float:
        """This lens's J term: commuter-delay dollars + integrated crowd-safety cost.

        ``delay_cost`` prices over-capacity queueing; ``safety_cost`` prices the
        integrated (weather-amplified) risk field. Summing the safety term into
        ``J`` is what gives the shelter lever a benefit the optimizer can see —
        shelter divides the risk field, so it lowers this term."""
        return float(
            sum(result.series("delay_cost")) + sum(result.series("safety_cost"))
        )
