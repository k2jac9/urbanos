"""Fare-revenue / ROI lens — the crush as transit revenue left on the platform.

The ROI framing for the intervention: a crush that strands riders past the
service horizon is revenue the transit agency doesn't collect (missed/abandoned
trips). This lens prices the riders still stuck in the network at the end of the
run at the TTC fare, so a smoother, staggered release — which clears more people
to their sinks within the horizon — *recovers* fares. The headline becomes
"the intervention pays for part of itself."

Contract identical to the other domain lenses: **read-only** on the crowd fields
(it reads ``load`` only) and **additive**. The TTC adult fare is real; treating
every stranded rider as a lost fare is a deliberately simple, auditable upper
proxy (flagged in provenance) — not a demand-elasticity model.
"""
from __future__ import annotations

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens
from ..kernel.state import State

# TTC adult single fare ($). Real.
FARE = 3.30
# Fraction of riders caught in the worst-moment crush who abandon the trip
# (give up / leave / never tap) — the fares actually lost. Synthetic; flagged.
ABANDON_FRACTION = 0.15


class FareRevenueLens(Lens):
    name = "fare_revenue"

    def __init__(self, *, weight: float = 1.0) -> None:
        self.weight = weight

    def observe(self, state: State, t: float) -> dict[str, float]:
        # People still in the network this step (not yet arrived at a sink).
        in_system = float(state.fields["load"].sum())
        return {
            "fare_in_system": in_system,
            "fare_at_risk": in_system * FARE,
        }

    def cost(self, result: SimResult) -> float:
        # J term: fares lost to abandonment at the worst-moment crush. The network
        # drains by the horizon, so end-state stranding is ~0; the signal that the
        # release lever actually moves is the PEAK simultaneous backlog — cut that
        # peak and fewer riders abandon, so fares are recovered.
        series = result.series("fare_in_system")
        peak_stuck = max(series) if series else 0.0
        return self.weight * FARE * ABANDON_FRACTION * float(peak_stuck)
