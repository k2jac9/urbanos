"""Business-Flow lens — local trade lost to the post-event crush (the sports angle).

When a venue empties, the crowd streams past street-level shops and food premises
clustered around the transit nodes. At comfortable density that footfall is
*revenue* — people stop, queue, buy. Inside a crush it's *lost trade* — you can't
shop shoulder-to-shoulder, so people just leave. This lens prices the trade a
crush destroys, which gives the optimizer's staggered-release lever credit for
the local-business value it preserves, not just the platform crush it eases. That
is the cross-domain link: one intervention, transit + safety + economics.

It is **read-only on the shared crowd fields** (``load``, ``congestion``): it
derives its own ``business`` display field and a per-step lost-trade dollar
figure, and never mutates the dynamics. So it composes additively — adding it to
a lens stack does not change EventSurge or EconomicLens results (covered by a
test). Like EconomicLens it's a ``couple`` + ``observe`` + ``J``-term lens; place
it after the kernel sets ``congestion`` (anywhere in the stack is fine).

Calibration (``SPEND_RATE``, $/person-minute of comfortable footfall) is
synthetic-but-plausible and flagged in provenance — the model's *shape* (trade
falls as a crush forms; spreading the crowd recovers it) is the point, not the
absolute dollars.
"""
from __future__ import annotations

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens
from ..kernel.state import State, Substrate

# Dollars of local trade per person-minute of comfortable (uncongested) footfall.
# Synthetic-but-plausible; flagged in provenance (see README).
SPEND_RATE = 0.30


class BusinessFlow(Lens):
    name = "business_flow"

    def __init__(self, venue_id: str, *, weight: float = 1.0) -> None:
        self.venue_id = venue_id
        self.weight = weight
        self._intensity: np.ndarray | None = None  # retail intensity per node, 0..1

    def configure(self, substrate: Substrate) -> None:
        # Retail sits along the street/station nodes the crowd passes — not the
        # exit sinks (you've left the district) and not the venue itself (people
        # are forming up to leave, not shopping). Intensity ~ node capacity
        # (busier interchanges carry denser retail), normalized to 0..1.
        cap = substrate.capacity.astype(float)
        mask = ~substrate.is_sink.copy()
        mask[substrate.idx(self.venue_id)] = False
        w = np.where(mask, cap, 0.0)
        peak = float(w.max())
        self._intensity = (w / peak) if peak > 0 else w

    @staticmethod
    def _service_factor(rho: np.ndarray) -> np.ndarray:
        # Fraction of footfall that can actually transact: 1.0 at/below comfortable
        # capacity, falling as a crush forms (rho=2.5 → ~0.4, i.e. ~60% lost).
        # Smooth, bounded, auditable — no fragile high-exponent term.
        return 1.0 / (1.0 + np.maximum(0.0, rho - 1.0))

    def couple(self, state: State, t: float) -> None:
        rho = state.fields["congestion"]
        footfall = state.fields["load"]
        dt = float(state.params.get("dt", 1.0))
        potential = self._intensity * footfall * SPEND_RATE * dt   # $ if uncongested
        sf = self._service_factor(rho)
        captured = potential * sf
        lost = potential * (1.0 - sf)
        state.fields["business"] = captured     # display-only field (heatmap layer)
        state.params["_biz_captured_step"] = float(captured.sum())
        state.params["_biz_lost_step"] = float(lost.sum())

    def observe(self, state: State, t: float) -> dict[str, float]:
        return {
            "business_captured": state.params.get("_biz_captured_step", 0.0),
            "business_lost": state.params.get("_biz_lost_step", 0.0),
        }

    def cost(self, result: SimResult) -> float:
        # J term = trade lost to the crush. Minimizing J recovers it — so the same
        # staggered release that eases Union also preserves local business.
        return self.weight * float(sum(result.series("business_lost")))
