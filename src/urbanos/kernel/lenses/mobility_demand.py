"""MobilityDemand lens — Bike Share trip-origin demand as an advisory display overlay.

Fit C of the data-driven roadmap (``docs/research/tpf-and-data-driven-lenses.md`` §6,
"MobilityDemand lens — Bike Share OD as a real demand field / display overlay"; ADR-0030).
A Bike Share trip *origin* is a local "demand to leave" event; counting trip starts per
station per 15-min bin gives a real micromobility demand field. This lens lifts that field
onto the substrate (``adapters.bikeshare_demand_by_node`` — real data, synthetic fallback
offline) and writes it as its OWN advisory overlay alongside the kernel's crowd, so the map
can show *where people want to leave from* next to *where the crush actually piles up*.

Honesty stance (roadmap §7 — none regressed; mirrors CongestionNowcast/TransitLoad)
-----------------------------------------------------------------------------------
- **Display-only, additive, no headline movement.** This lens is **read-only on the crowd
  fields** (``load``/``congestion``/``risk``): it only writes its own ``bike_demand``
  overlay and reports advisory metrics. It declares **no levers** and contributes **zero
  cost**, and it lives in ``scenarios.extra_display_lenses`` — which is deliberately
  excluded from the optimizer's objective ``J`` — so it CANNOT move the chosen intervention
  or any headline dollar figure (the additivity contract test pins this).
- **Real demand under the demo, synthetic fallback in CI/dev.** A committed downtown slice
  (``demo_data/bikeshare__downtown.csv`` — real Q1-2026 evening trip origins, located via the
  GBFS station feed; see ``scripts/fetch_bikeshare.py``) backs the demo, which loads it with
  ``DATA_DIR=demo_data``. Without that slice on the loader's path (CI/dev) the adapter falls
  back to a deterministic synthetic series, so tests stay offline and the lens always runs.
- **Provenance honesty.** :data:`PROVENANCE` is the *fallback* label (``"synthetic/advisory"``),
  accurate in CI/dev where the synthetic series is used; under the demo the same
  ``{node: {minute: count}}`` shape carries the real measured origins. The value is not
  surfaced at runtime, so it is documentation, not a claim attached to any number.
- **Offline-safe.** Constructed bare (no series) the lens is an inert no-op; the adapter
  supplies a deterministic synthetic series when no real slice is present, so CI/dev never
  need real data or network.
"""
from __future__ import annotations

import math

import numpy as np

from ..kernel.operators import Lens
from ..kernel.state import State, Substrate

# Provenance marker — the FALLBACK label, accurate in CI/dev where the synthetic series is
# used. Under the demo (DATA_DIR=demo_data) the same shape carries the real committed
# Bike Share origins (demo_data/bikeshare__downtown.csv). The value is not surfaced at
# runtime; either way the lens is clearly ADVISORY — display-only, never priced, never a
# headline number.
PROVENANCE = "synthetic/advisory"


class MobilityDemandLens(Lens):
    """Advisory display lens: Bike Share trip-origin demand lifted onto the substrate.

    Construct with a ``{node_id: {minute: count}}`` demand series (the same shape
    ``CongestionNowcastLens``/``TransitLoadLens`` consume — see
    ``adapters.bikeshare_demand_by_node``). Constructed bare it is inert (no series →
    writes nothing, reports nothing, never an error), so it is always safe to include in a
    stack. Declares no levers and contributes no cost — it is display-only and excluded
    from the optimizer's objective ``J``.
    """

    name = "mobility_demand"

    def __init__(
        self, node_demand: dict[str, dict[float, float]] | None = None, *, weight: float = 1.0
    ) -> None:
        self.node_demand = dict(node_demand) if node_demand else None
        self.weight = weight
        self._bins: list[float] = []                 # sorted demand bin minutes
        self._demand: dict[float, np.ndarray] = {}    # {bin: (N,) validated per-node demand}

    # -- configuration ------------------------------------------------------
    def configure(self, substrate: Substrate) -> None:
        """Bake the per-node series into per-bin per-node demand arrays. Only NON-SINK
        nodes carry demand (a sink is an exit/home line, not an origin where someone
        decides to leave — mirrors the TransitLoad/EventSurge "never a sink" rule). Values
        are validated here (negative / NaN / inf dropped) so ``couple``/``observe`` can
        never emit a non-finite overlay. Inert when constructed bare."""
        self._bins = []
        self._demand = {}
        if not self.node_demand:
            return
        bins: set[float] = set()
        for series in self.node_demand.values():
            bins.update(float(m) for m in series)
        self._bins = sorted(bins)
        for b in self._bins:
            demand = np.zeros(substrate.n, dtype=float)
            for i, nid in enumerate(substrate.ids):
                if substrate.is_sink[i]:
                    continue  # an exit line is never a demand origin
                c = float(self.node_demand.get(nid, {}).get(b, 0.0))
                if math.isfinite(c) and c > 0.0:
                    demand[i] = c
            # Defensive: keep the baked array finite even if a degenerate value slipped
            # past the per-cell guard (so the overlay can never carry NaN/inf).
            np.nan_to_num(demand, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
            self._demand[b] = demand

    # -- per-step overlay ---------------------------------------------------
    def couple(self, state: State, t: float) -> None:
        """Write ONLY this lens's advisory ``bike_demand`` overlay for the demand bin
        nearest sim-time ``t`` (read-only on ``load``/``congestion``/``risk`` — it never
        mutates a crowd field, so it cannot perturb the kernel or any other lens). Inert
        (no write) when constructed bare."""
        demand = self._demand_at(t)
        if demand is None:
            return
        state.fields["bike_demand"] = demand

    # -- reporting ----------------------------------------------------------
    def observe(self, state: State, t: float) -> dict[str, float]:
        """Advisory, display-only metrics (no dollars, no lever influence):

        - ``bike_demand_peak``: the highest single-node trip-origin demand this step.
        - ``micromobility_relief``: a transparency scalar in ``[0, 1]`` — the cosine
          overlap between *where the crowd is crushing* (``load``) and *where bike-share
          demand is high*. A high value means the egress crush coincides with strong
          demand-to-leave, i.e. a micromobility relief OPPORTUNITY (people who would
          gladly ride out if a bike were there). It is purely informational — it prices
          nothing and steers nothing."""
        demand = self._demand_at(t)
        if demand is None:
            return {}
        out: dict[str, float] = {"bike_demand_peak": float(demand.max())}
        load = np.asarray(state.fields.get("load"), dtype=float)
        if load.shape == demand.shape:
            nl = float(np.linalg.norm(load))
            nd = float(np.linalg.norm(demand))
            if nl > 0.0 and nd > 0.0:
                out["micromobility_relief"] = float(
                    np.clip(np.dot(load, demand) / (nl * nd), 0.0, 1.0)
                )
            else:
                out["micromobility_relief"] = 0.0
        return out

    def cost(self, result: object) -> float:
        """No J term — MobilityDemand is a display-only advisory overlay, never a priced
        lever, so it can never move a headline dollar figure."""
        return 0.0

    # -- helpers ------------------------------------------------------------
    def _demand_at(self, t: float) -> np.ndarray | None:
        """The baked per-node demand ``(N,)`` for the demand bin nearest sim-time ``t``.
        None when inert (no baked demand) — both ``couple`` and ``observe`` go through here
        so they agree exactly on which bin is active."""
        if not self._demand or not self._bins:
            return None
        arr = np.asarray(self._bins, dtype=float)
        bin_minute = float(arr[int(np.argmin(np.abs(arr - float(t))))])
        return self._demand.get(bin_minute)
