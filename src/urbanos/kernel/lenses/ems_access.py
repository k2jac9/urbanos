"""EMS / emergency-access lens — the crush as a public-safety *response-time* cost.

A post-event crush doesn't only delay commuters; it chokes the streets an
ambulance or fire truck needs to reach an incident. This lens prices that: it
builds a static per-node **EMS-criticality** field (proximity to downtown
hospitals), then charges the objective for over-capacity crowding that lands on
the most response-critical nodes — exactly the corridors EMS must traverse.

Same shape as :class:`SafetyLens`: **read-only** on the crowd fields, **additive**
(it only reads ``load``/``capacity`` and writes its own display field), so it
never perturbs the other lenses. The staggered-release lever shrinks the crush,
so it shrinks this term too — the optimizer now also keeps emergency lanes open.

Hospital coordinates are real downtown Toronto facilities; the dollar weight is
synthetic-but-plausible and flagged in provenance (not ground-truth-validated).
"""
from __future__ import annotations

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens
from ..kernel.state import State, Substrate

# Real downtown Toronto emergency facilities (lat, lng).
_HOSPITALS = [
    (43.6531, -79.3776),  # St. Michael's Hospital
    (43.6585, -79.3886),  # Toronto General
    (43.6575, -79.3889),  # Mount Sinai
    (43.6577, -79.3839),  # SickKids
]
# Proximity decay (degrees ~ 1.1 km): how fast EMS-criticality falls with distance.
_DECAY = 0.012
# $ per (criticality · person-minute) of crush on a response-critical node.
# Calibrated material-but-not-dominant next to commuter delay. Synthetic; flagged.
VALUE_OF_EMS_DELAY = 4.0


class EmsAccessLens(Lens):
    name = "ems_access"

    def __init__(self, *, weight: float = 1.0) -> None:
        self.weight = weight
        self._crit: np.ndarray | None = None

    def configure(self, substrate: Substrate) -> None:
        crit = np.zeros(substrate.n)
        for plat, plng in _HOSPITALS:
            dlat = substrate.lat - plat
            dlng = (substrate.lng - plng) * np.cos(np.radians(plat))
            d = np.sqrt(dlat * dlat + dlng * dlng)
            crit += np.exp(-d / _DECAY)
        peak = float(crit.max())
        self._crit = crit / peak if peak > 0 else crit  # normalise to 0..1

    def couple(self, state: State, t: float) -> None:
        # Static EMS-criticality overlay (a heatmap layer) + the weight that turns
        # over-capacity crowding into blocked-emergency-access exposure.
        state.fields["ems_access"] = self._crit
        queue = np.maximum(0.0, state.fields["load"] - state.substrate.capacity)
        dt = float(state.params.get("dt", 1.0))
        state.params["_ems_exposure_step"] = float(np.sum(self._crit * queue) * dt)

    def observe(self, state: State, t: float) -> dict[str, float]:
        return {
            "ems_exposure": state.params.get("_ems_exposure_step", 0.0),
            "ems_crit_peak": float(np.max(self._crit)) if self._crit is not None else 0.0,
        }

    def cost(self, result: SimResult) -> float:
        # J term: crush person-minutes weighted by EMS-criticality, priced.
        return self.weight * VALUE_OF_EMS_DELAY * float(sum(result.series("ems_exposure")))
