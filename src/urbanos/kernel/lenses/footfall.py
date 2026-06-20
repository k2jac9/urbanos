"""Footfall lens — ambient pedestrian volume per node as an advisory display overlay.

Fit C of the data-driven roadmap (``docs/research/tpf-and-data-driven-lenses.md`` §6,
"real source/demand lenses" track; ADR-0037). A Toronto Traffic Management Centre (TMC)
*pedestrian* count is a real, geocoded measurement of *how many people are on foot near a
place at a given time* — the city's ambient footfall. Counting those pedestrian records per
substrate node per 15-min bin gives a real footfall field. This lens lifts that field onto
the substrate (``adapters.footfall_by_node`` — a thin wrapper over the committed TMC ped
slice, real data with a synthetic fallback offline) and writes it as its OWN advisory overlay
alongside the kernel's crowd, so the map can show *where pedestrians already are* next to
*where the egress crush actually piles up* — and report how much the crush coincides with
already-busy pedestrian areas.

Honesty stance (roadmap §7 — none regressed; mirrors MobilityDemand/RoadRisk)
-----------------------------------------------------------------------------
- **Display-only, additive, no headline movement.** This lens is **read-only on the crowd
  fields** (``load``/``congestion``/``risk``): it only writes its own ``footfall`` overlay
  and reports advisory metrics. It declares **no levers** and contributes **zero cost**, and
  it lives in ``scenarios.extra_display_lenses`` — which is deliberately excluded from the
  optimizer's objective ``J`` — so it CANNOT move the chosen intervention or any headline
  dollar figure (the additivity contract test pins this).
- **Real footfall under the demo, synthetic fallback in CI/dev.** The committed downtown TMC
  slice (the same one ``observed_counts_by_node(mode="ped")`` reads) backs the demo, which
  loads it with ``DATA_DIR=demo_data``. Without that slice on the loader's path (CI/dev) the
  adapter falls back to a deterministic synthetic series, so tests stay offline and the lens
  always runs.
- **Provenance honesty.** :data:`PROVENANCE` is the *fallback* label (``"synthetic/advisory"``),
  accurate in CI/dev where the synthetic series is used; under the demo the same
  ``{node: {minute: count}}`` shape carries the real measured pedestrian counts. The value is
  not surfaced at runtime, so it is documentation, not a claim attached to any number.
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
# used. Under the demo (DATA_DIR=demo_data) the same shape carries the real committed TMC
# pedestrian counts. The value is not surfaced at runtime; either way the lens is clearly
# ADVISORY — display-only, never priced, never a headline number.
PROVENANCE = "synthetic/advisory"


class FootfallLens(Lens):
    """Advisory display lens: ambient TMC pedestrian volume lifted onto the substrate.

    Construct with a ``{node_id: {minute: count}}`` footfall series (the same shape
    ``MobilityDemandLens``/``CongestionNowcastLens`` consume — see
    ``adapters.footfall_by_node``). Constructed bare it is inert (no series → writes
    nothing, reports nothing, never an error), so it is always safe to include in a stack.
    Declares no levers and contributes no cost — it is display-only and excluded from the
    optimizer's objective ``J``.
    """

    name = "footfall"

    def __init__(
        self, node_footfall: dict[str, dict[float, float]] | None = None, *, weight: float = 1.0
    ) -> None:
        self.node_footfall = dict(node_footfall) if node_footfall else None
        self.weight = weight
        self._bins: list[float] = []                  # sorted footfall bin minutes
        self._footfall: dict[float, np.ndarray] = {}  # {bin: (N,) validated per-node footfall}

    # -- configuration ------------------------------------------------------
    def configure(self, substrate: Substrate) -> None:
        """Bake the per-node series into per-bin per-node footfall arrays. Only NON-SINK
        nodes carry footfall (a sink is an abstract exit/home line, not a real pedestrian
        location — mirrors the MobilityDemand/TransitLoad "never a sink" rule). Values are
        validated here (negative / NaN / inf dropped) so ``couple``/``observe`` can never
        emit a non-finite overlay. Inert when constructed bare."""
        self._bins = []
        self._footfall = {}
        if not self.node_footfall:
            return
        bins: set[float] = set()
        for series in self.node_footfall.values():
            bins.update(float(m) for m in series)
        self._bins = sorted(bins)
        for b in self._bins:
            footfall = np.zeros(substrate.n, dtype=float)
            for i, nid in enumerate(substrate.ids):
                if substrate.is_sink[i]:
                    continue  # an exit line is never a pedestrian location
                c = float(self.node_footfall.get(nid, {}).get(b, 0.0))
                if math.isfinite(c) and c > 0.0:
                    footfall[i] = c
            # Defensive: keep the baked array finite even if a degenerate value slipped
            # past the per-cell guard (so the overlay can never carry NaN/inf).
            np.nan_to_num(footfall, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
            self._footfall[b] = footfall

    # -- per-step overlay ---------------------------------------------------
    def couple(self, state: State, t: float) -> None:
        """Write ONLY this lens's advisory ``footfall`` overlay for the footfall bin nearest
        sim-time ``t`` (read-only on ``load``/``congestion``/``risk`` — it never mutates a
        crowd field, so it cannot perturb the kernel or any other lens). Inert (no write)
        when constructed bare."""
        footfall = self._footfall_at(t)
        if footfall is None:
            return
        state.fields["footfall"] = footfall

    # -- reporting ----------------------------------------------------------
    def observe(self, state: State, t: float) -> dict[str, float]:
        """Advisory, display-only metrics (no dollars, no lever influence):

        - ``footfall_peak``: the highest single-node pedestrian volume this step.
        - ``crush_footfall_overlap``: a transparency scalar in ``[0, 1]`` — the cosine
          overlap between *where the crowd is crushing* (``load``) and *where ambient
          footfall is high*. A high value means the egress crush coincides with already-busy
          pedestrian areas, i.e. the crowd is piling into places that were already on foot.
          It is purely informational — it prices nothing and steers nothing."""
        footfall = self._footfall_at(t)
        if footfall is None:
            return {}
        out: dict[str, float] = {"footfall_peak": float(footfall.max())}
        load = np.asarray(state.fields.get("load"), dtype=float)
        if load.shape == footfall.shape:
            nl = float(np.linalg.norm(load))
            nf = float(np.linalg.norm(footfall))
            if nl > 0.0 and nf > 0.0:
                out["crush_footfall_overlap"] = float(
                    np.clip(np.dot(load, footfall) / (nl * nf), 0.0, 1.0)
                )
            else:
                out["crush_footfall_overlap"] = 0.0
        return out

    def cost(self, result: object) -> float:
        """No J term — Footfall is a display-only advisory overlay, never a priced lever, so
        it can never move a headline dollar figure."""
        return 0.0

    # -- helpers ------------------------------------------------------------
    def _footfall_at(self, t: float) -> np.ndarray | None:
        """The baked per-node footfall ``(N,)`` for the footfall bin nearest sim-time ``t``.
        None when inert (no baked footfall) — both ``couple`` and ``observe`` go through here
        so they agree exactly on which bin is active."""
        if not self._footfall or not self._bins:
            return None
        arr = np.asarray(self._bins, dtype=float)
        bin_minute = float(arr[int(np.argmin(np.abs(arr - float(t))))])
        return self._footfall.get(bin_minute)
