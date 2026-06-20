"""Noise / livability lens — the crush as a disturbance dumped on where people live.

A post-event surge is loudest exactly where it's least welcome: the residential
blocks. This lens lifts a per-node **residential weight** onto the substrate and
prices over-capacity crowding that lands on the most-residential nodes as a
livability cost (noise, disturbance, complaints). Same contract as
:class:`SafetyLens`: **read-only** on the crowd fields, **additive**, so the
staggered-release lever — which thins the crush — also lowers this term, making
the optimizer route the surge away from where people sleep.

Grounding: when constructed via ``scenarios.extra_display_lenses(sc)`` the weight is
the REAL civic **Activity** overlay (``adapters.civic_activity_by_node`` — building
permits + business licences fused to nodes by proximity, ADR-0014), the same
address→node fusion ``SafetyLens`` uses for its safety overlay. Constructed bare
(no mapping) it falls back to a deterministic synthetic-but-flagged field so the
lens still runs offline/in unit tests. The dollar weight is synthetic-but-plausible,
flagged in provenance.
"""
from __future__ import annotations

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens
from ..kernel.state import State, Substrate

# $ per (residential-weight · person-minute) of over-capacity crowding. Calibrated
# material-but-not-dominant next to commuter delay. Synthetic; flagged.
VALUE_OF_QUIET = 1.8


def _synthetic_residential_by_index(substrate: Substrate) -> np.ndarray:
    """Deterministic synthetic residential weight (0..1) when no real permit
    geocode is supplied. Higher on interior (non-sink) nodes — a stand-in for
    'people live here', flagged as synthetic until the permits feed is fused."""
    w = np.where(substrate.is_sink, 0.1, 1.0).astype(float)
    # Mild deterministic spatial variation so it isn't a flat field.
    w *= 0.5 + 0.5 * (np.cos(substrate.lat * 311.0) ** 2)
    peak = float(w.max())
    return w / peak if peak > 0 else w


class NoiseLivabilityLens(Lens):
    name = "noise_livability"

    def __init__(
        self, node_residential: dict[str, float] | None = None, *, weight: float = 1.0
    ) -> None:
        self.node_residential = dict(node_residential) if node_residential else None
        self.weight = weight
        self._res: np.ndarray | None = None

    def configure(self, substrate: Substrate) -> None:
        if self.node_residential:
            self._res = np.array(
                [float(self.node_residential.get(nid, 0.0)) for nid in substrate.ids],
                dtype=float,
            )
        else:
            self._res = _synthetic_residential_by_index(substrate)

    def couple(self, state: State, t: float) -> None:
        state.fields["residential"] = self._res
        queue = np.maximum(0.0, state.fields["load"] - state.substrate.capacity)
        dt = float(state.params.get("dt", 1.0))
        state.params["_noise_exposure_step"] = float(np.sum(self._res * queue) * dt)

    def observe(self, state: State, t: float) -> dict[str, float]:
        return {
            "noise_exposure": state.params.get("_noise_exposure_step", 0.0),
            "residential_peak": float(np.max(self._res)) if self._res is not None else 0.0,
        }

    def cost(self, result: SimResult) -> float:
        # J term: crush person-minutes weighted by residential exposure, priced.
        return self.weight * VALUE_OF_QUIET * float(sum(result.series("noise_exposure")))
