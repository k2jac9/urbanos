"""RoadDisruption lens — active road closures/restrictions as an advisory display overlay.

Fit C of the data-driven roadmap (``docs/research/tpf-and-data-driven-lenses.md`` §6, the
"real source/demand lenses" track; ADR-0038). A Road Restriction is a real, geocoded record of
*where the network is currently constrained* (a lane closure, a full closure, a construction
restriction). Counting severity-weighted restriction records near each substrate node gives a
static **road-disruption density** — a different axis of intelligence from the crowd crush, from
the civic Safety index (food inspections), and from the historical RoadRisk danger field (KSI
collisions). Where RoadRisk asks *where the road is historically dangerous*, RoadDisruption asks
*where the road is constrained right now*. This lens lifts that field onto the substrate
(``adapters.road_disruption_by_node`` — real data, synthetic fallback offline) and writes it as
its OWN advisory overlay, so the map can show *where the network is closed* next to *where the
crush actually piles up* — and report how much the egress funnels the crowd through actively
restricted places.

Honesty stance (roadmap §7 — none regressed; mirrors RoadRisk/MobilityDemand/TransitLoad)
-----------------------------------------------------------------------------------------
- **Display-only, additive, no headline movement.** Read-only on the crowd fields
  (``load``/``congestion``/``risk``): it only writes its own ``road_disruption`` overlay and
  reports advisory metrics. It declares **no levers** and contributes **zero cost**, and it lives
  in ``scenarios.extra_display_lenses`` (excluded from the optimizer's objective ``J``), so it
  CANNOT move the chosen intervention or any headline dollar figure (the additivity contract
  test pins this).
- **Real disruptions under the demo, synthetic fallback in CI/dev.** A committed downtown slice
  (``demo_data/road_restrictions__downtown.csv`` — 629 real active downtown restrictions,
  ``scripts/fetch_road_restrictions.py``) backs the demo (``DATA_DIR=demo_data``). Without that
  slice on the loader's path (CI/dev) the adapter falls back to a deterministic synthetic field,
  so tests stay offline and the lens always runs.
- **Static field.** Unlike the time-varying demand lenses, the disruption field is a fixed
  property of the network for a given run: the same per-node density every step. ``observe``
  still reports each step so the exposure metric reflects how the *crush* (which does evolve)
  overlaps the fixed disruption field.
- **Offline-safe.** Constructed bare (no field) the lens is an inert no-op.

Internal note: like ``RoadRiskLens`` the baked normalised field is stored on ``self._risk`` (NOT
``self._disruption``), so the overlay helper ``services.road_disruption_overlay`` reads it the
same way (``getattr(lens, "_risk", None)``) — kept consistent with RoadRisk on purpose.
"""
from __future__ import annotations

import math

import numpy as np

from ..kernel.operators import Lens
from ..kernel.state import State, Substrate

# Provenance marker — the FALLBACK label, accurate in CI/dev where the synthetic field is used.
# Under the demo (DATA_DIR=demo_data) the same shape carries the real committed restriction
# density. Not surfaced at runtime; either way the lens is clearly ADVISORY — display-only,
# never priced.
PROVENANCE = "synthetic/advisory"


class RoadDisruptionLens(Lens):
    """Advisory display lens: severity-weighted road-restriction density lifted onto the substrate.

    Construct with a ``{node_id: density}`` map (see ``adapters.road_disruption_by_node``).
    Constructed bare it is inert (no field → writes nothing, reports nothing, never an error),
    so it is always safe to include in a stack. Declares no levers and contributes no cost — it
    is display-only and excluded from the optimizer's objective ``J``.
    """

    name = "road_disruption"

    def __init__(
        self, node_disruption: dict[str, float] | None = None, *, weight: float = 1.0
    ) -> None:
        self.node_disruption = dict(node_disruption) if node_disruption else None
        self.weight = weight
        self._risk: np.ndarray | None = None   # baked, NORMALISED (0..1) per-node density

    # -- configuration ------------------------------------------------------
    def configure(self, substrate: Substrate) -> None:
        """Bake the per-node density into a normalised ``(N,)`` array. Only NON-SINK nodes carry
        disruption (a sink is an abstract exit line, not a real road location). Values are
        validated (negative / NaN / inf dropped) and normalised by the peak so the overlay is a
        scale-free 0..1 disruption field. Inert when constructed bare."""
        self._risk = None
        if not self.node_disruption:
            return
        risk = np.zeros(substrate.n, dtype=float)
        for i, nid in enumerate(substrate.ids):
            if substrate.is_sink[i]:
                continue
            v = float(self.node_disruption.get(nid, 0.0))
            if math.isfinite(v) and v > 0.0:
                risk[i] = v
        np.nan_to_num(risk, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        peak = float(risk.max())
        if peak > 0.0:
            risk = risk / peak     # scale-free 0..1 (the relative disruption shape is the claim)
        self._risk = risk

    # -- per-step overlay ---------------------------------------------------
    def couple(self, state: State, t: float) -> None:
        """Write ONLY this lens's advisory ``road_disruption`` overlay (read-only on
        ``load``/``congestion``/``risk`` — it never mutates a crowd field, so it cannot perturb
        the kernel or any other lens). The field is static (same every step). Inert when bare."""
        if self._risk is None:
            return
        state.fields["road_disruption"] = self._risk

    # -- reporting ----------------------------------------------------------
    def observe(self, state: State, t: float) -> dict[str, float]:
        """Advisory, display-only metrics (no dollars, no lever influence):

        - ``road_disruption_peak``: the most-restricted node's normalised density (constant over
          the run).
        - ``crush_disruption_exposure``: a scale-free cosine in ``[0, 1]`` — how much *where the
          crowd is crushing* (``load``) overlaps *where the road is actively restricted*
          (``road_disruption``). A high value means the egress funnels the crowd through active
          closures — a routing concern the lever can ease by spreading the crowd. Purely
          informational: it prices nothing and steers nothing."""
        if self._risk is None:
            return {}
        out: dict[str, float] = {"road_disruption_peak": float(self._risk.max())}
        load = np.asarray(state.fields.get("load"), dtype=float)
        if load.shape == self._risk.shape:
            nl = float(np.linalg.norm(load))
            nr = float(np.linalg.norm(self._risk))
            if nl > 0.0 and nr > 0.0:
                out["crush_disruption_exposure"] = float(
                    np.clip(np.dot(load, self._risk) / (nl * nr), 0.0, 1.0)
                )
            else:
                out["crush_disruption_exposure"] = 0.0
        return out

    def cost(self, result: object) -> float:
        """No J term — RoadDisruption is a display-only advisory overlay, never a priced lever, so
        it can never move a headline dollar figure."""
        return 0.0
