"""Air-quality / emissions lens — the crush as a localized pollution spike.

When a crowd jams past capacity, transit dwells, buses idle, and the district's
air gets worse right where the people are. This lens prices that co-benefit:
over-capacity crowding (the same ``queue`` the economic lens already computes) is
treated as **person-minutes of idling exposure**, converted to CO₂e/PM mass, and
charged at a social cost. No new dataset — it's a transparent function of the
crush, like the delay-dollars term, so it's fully auditable.

**Read-only** on the crowd fields and **additive**: it only reads
``load``/``capacity`` and writes its own display field. The staggered-release
lever cuts the crush, so it cuts the emissions term — giving the intervention a
measurable environmental win to put on the board.

Emission factor and social cost are synthetic-but-plausible, flagged in
provenance (order-of-magnitude, not ground-truth-validated).
"""
from __future__ import annotations

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens
from ..kernel.state import State

# kg CO₂e per person-minute of over-capacity idling (transit dwell + bus idle +
# diverted cars crawling). Order-of-magnitude; synthetic, flagged in provenance.
_KG_PER_PERSON_MIN = 0.0018
# Social cost of carbon, $/kg CO₂e (~$185/tonne, mid-range gov estimate).
SOCIAL_COST_PER_KG = 0.185


class EmissionsLens(Lens):
    name = "emissions"

    def __init__(self, *, weight: float = 1.0) -> None:
        self.weight = weight

    def couple(self, state: State, t: float) -> None:
        queue = np.maximum(0.0, state.fields["load"] - state.substrate.capacity)
        dt = float(state.params.get("dt", 1.0))
        # Per-node emissions field this step (drives an air-quality heatmap layer).
        state.fields["emissions"] = queue * _KG_PER_PERSON_MIN * dt
        state.params["_emit_kg_step"] = float(np.sum(state.fields["emissions"]))

    def observe(self, state: State, t: float) -> dict[str, float]:
        kg = state.params.get("_emit_kg_step", 0.0)
        return {
            "emissions_kg": kg,
            "emissions_cost": kg * SOCIAL_COST_PER_KG,
            "peak_emissions": float(np.max(state.fields.get("emissions", np.zeros(1)))),
        }

    def cost(self, result: SimResult) -> float:
        # J term: total idling CO₂e over the run, priced at the social cost.
        return self.weight * SOCIAL_COST_PER_KG * float(sum(result.series("emissions_kg")))
