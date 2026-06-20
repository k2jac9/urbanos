"""Safety lens — the civic risk app, made literal as an Urban-OS kernel lens.

This fulfils the architecture's claim ("the static risk app becomes the
Safety/Public-Services lens on this kernel"): it lifts urbanos.risk's
*address-level* compliance-safety risk onto the substrate as a static per-node
field, then prices the one thing that turns a transit crush into a *public-safety*
event rather than just a delay — a crowd crushing through a district that is
*already* civically high-risk (failed inspections, unsafe premises). So the same
staggered-release lever that eases Union is now also optimized to keep crowds out
of crushes in the least-safe districts.

It connects the two apps: ``node_risk`` is derived by the Toronto adapter from
the urbanos.risk graph (``adapters.civic_safety_by_node``) — real fusion, address
risk → node field. The lens itself is pure (takes the mapping), **read-only** on
the crowd fields, and **additive** (a test asserts it doesn't change the other
lenses). ``VALUE_OF_CIVIC_SAFETY`` is synthetic-but-plausible, flagged in
provenance.
"""
from __future__ import annotations

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens
from ..kernel.state import State, Substrate

# $ per person-minute of over-capacity crowding, scaled by a node's civic-safety
# risk (0..1). Calibrated so the public-safety term is *material but not dominant*
# next to the commuter-delay term (a crush in a high-risk district is a real cost,
# not the whole objective). Synthetic; flagged in provenance.
VALUE_OF_CIVIC_SAFETY = 2.5


class SafetyLens(Lens):
    name = "safety"

    def __init__(self, node_risk: dict[str, float] | None = None, *, weight: float = 1.0) -> None:
        self.node_risk = dict(node_risk or {})
        self.weight = weight
        self._risk: np.ndarray | None = None

    def configure(self, substrate: Substrate) -> None:
        self._risk = np.array(
            [float(self.node_risk.get(nid, 0.0)) for nid in substrate.ids], dtype=float
        )

    def couple(self, state: State, t: float) -> None:
        # Static civic-safety overlay (constant in time): a heatmap layer, and the
        # weight that turns over-capacity crowding into public-safety exposure.
        state.fields["civic_risk"] = self._risk
        queue = np.maximum(0.0, state.fields["load"] - state.substrate.capacity)
        dt = float(state.params.get("dt", 1.0))
        state.params["_civic_exposure_step"] = float(np.sum(self._risk * queue) * dt)

    def observe(self, state: State, t: float) -> dict[str, float]:
        return {
            "civic_exposure": state.params.get("_civic_exposure_step", 0.0),
            "civic_risk_peak": float(np.max(self._risk)) if self._risk is not None else 0.0,
        }

    def cost(self, result: SimResult) -> float:
        # J term: person-minutes of crush weighted by civic-safety risk, priced.
        # The release lever lowers the crush → lowers this term, so the civic data
        # materially shapes the optimized intervention.
        return self.weight * VALUE_OF_CIVIC_SAFETY * float(
            sum(result.series("civic_exposure"))
        )
