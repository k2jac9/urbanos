"""TransitLoad lens — REAL/measured background ridership injected as a source.

Fit C of the data-driven roadmap (``docs/research/tpf-and-data-driven-lenses.md``
§6, "TransitLoad lens — ``source()`` injects measured TTC boardings at relay
nodes"; ADR-0029). Where ``CongestionNowcastLens`` (Phase 1) *reads* the same
observed-count series to score the kernel against ground truth, this lens *writes*
it: it adds the measured boardings/throughput as honest background ridership — the
people who enter the transit system on top of the event-egress wave.

This is a **real/measured source term, NOT a learned/approximate one.** It does not
fit, predict, or interpolate anything; it simply meters the observed Toronto TMC
15-min counts (``adapters.observed_counts_by_node`` — real data, synthetic fallback
offline) onto the substrate as inflow, the same way ``EventSurge`` meters a venue
crowd. The exact kernel still moves and prices every person; this only makes the
demand side more *real*.

Honesty stance (roadmap §7, ADR-0029 — none regressed)
------------------------------------------------------
- **No new J term, no lever.** ``cost`` is always ``0.0`` and ``levers`` is empty,
  so this lens can never move a headline dollar figure or change the optimizer's
  chosen intervention — it is a realism source, not a priced or controllable lever.
- **Opt-in, off by default.** Gated by ``URBANOS_TRANSIT_LOAD`` (mirrors
  ``learned_dynamics_enabled``); not even constructed in the default stack, so the
  golden numbers are byte-identical with the flag off.
- **Real/measured provenance.** The injected mass is metered observed data, stamped
  ``provenance="real/measured"`` (distinct from learned/approximate fields), so it
  is never mistaken for a fitted quantity.
- **Offline-safe.** Constructed bare (no series) it is an inert no-op; the adapter
  supplies a deterministic synthetic series when no real slice is present.
"""
from __future__ import annotations

import math
import os

import numpy as np

from ..kernel.operators import Lens
from ..kernel.state import State, Substrate

# Provenance marker stamped on this lens's measured output, distinct from the
# learned_dynamics "learned/approximate" label — this is real metered data, not a fit.
PROVENANCE = "real/measured"

# A 15-min observed bin is a measured *count over that interval*. We meter it into the
# sim's per-step inflow honestly: ``count / 15`` people-per-minute, times ``dt`` minutes
# per step, gives the people that entered during this step. ``BIN_MINUTES`` is the width
# of an observed bin; the per-step inflow is ``count / BIN_MINUTES * dt``.
BIN_MINUTES = 15.0

# Default scale for the metered boardings. 1.0 means "inject the observed counts as-is"
# (the honest, untuned default — the counts are real people). A demo can dial this down
# if the absolute survey units dwarf the event crowd, but it is documented and fixed
# here rather than fished against any headline number.
_DEFAULT_SCALE = 1.0


def transit_load_enabled() -> bool:
    """Opt-in: set ``URBANOS_TRANSIT_LOAD=1`` (mirrors ``learned_dynamics_enabled`` /
    ``URBANOS_SURROGATE``). Off by default → the lens is not even constructed in the
    default stack and the golden numbers are untouched."""
    return os.environ.get("URBANOS_TRANSIT_LOAD", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


class TransitLoadLens(Lens):
    """Inject measured background ridership as a real ``source`` term.

    Construct with a ``{node_id: {minute: count}}`` series (the same shape
    ``CongestionNowcastLens`` consumes — see ``adapters.observed_counts_by_node``).
    Constructed bare it is inert (no series → injects nothing, never an error), so it
    is always safe to include in a stack. Declares no levers and contributes no cost.
    """

    name = "transit_load"

    def __init__(
        self,
        node_counts: dict[str, dict[float, float]] | None = None,
        *,
        scale: float = _DEFAULT_SCALE,
        weight: float = 1.0,
    ) -> None:
        # Validate at the boundary: a non-finite/negative scale would inject garbage.
        s = float(scale)
        if not math.isfinite(s) or s < 0.0:
            raise ValueError(f"TransitLoadLens scale must be finite and >= 0, got {scale!r}")
        self.node_counts = dict(node_counts) if node_counts else None
        self.scale = s
        self.weight = weight
        self._bins: list[float] = []                # sorted observed bin minutes
        self._counts: dict[float, np.ndarray] = {}   # {bin: (N,) validated per-node count}

    # -- configuration ------------------------------------------------------
    def configure(self, substrate: Substrate) -> None:
        """Bake the per-node series into per-bin per-node count arrays. Only NON-SINK
        nodes are seeded: like ``EventSurge``, we never inject load directly onto a sink
        (a sink absorbs via real edges; a slug placed on it would never route through the
        graph). Counts are validated here (negatives / NaN / inf dropped); the per-step
        inflow conversion happens in ``source`` where the live ``dt`` is known. Inert
        when constructed bare."""
        self._bins = []
        self._counts = {}
        if not self.node_counts:
            return
        # Collect the union of observed bin minutes across all nodes.
        bins: set[float] = set()
        for series in self.node_counts.values():
            bins.update(float(m) for m in series)
        self._bins = sorted(bins)
        for b in self._bins:
            counts = np.zeros(substrate.n, dtype=float)
            for i, nid in enumerate(substrate.ids):
                if substrate.is_sink[i]:
                    continue  # never seed a sink (EventSurge's reasoning)
                c = float(self.node_counts.get(nid, {}).get(b, 0.0))
                if math.isfinite(c) and c > 0.0:
                    counts[i] = c
            # Defensive: keep the baked array finite even if a degenerate value slipped
            # past the per-cell guard (so source() can never propagate NaN/inf to load).
            np.nan_to_num(counts, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
            self._counts[b] = counts

    # -- per-step source ----------------------------------------------------
    def source(self, state: State, t: float) -> None:
        """Inject the measured boardings for the nearest observed bin to sim-time ``t``
        as real background ridership load (people entering on top of the event egress).

        A 15-min observed bin is a measured count over that interval; the per-step inflow
        is ``count / BIN_MINUTES * dt * scale`` (people/min × min/step × scale) — read at
        the live ``dt`` so the per-step mass is correct at any step size. People-conserving
        in intent: each step adds exactly the metered count for its bin, never more."""
        people = self._inflow_at(t, state)
        if people is None:
            return
        load = state.field("load")
        load[:] += people

    # -- reporting ----------------------------------------------------------
    def observe(self, state: State, t: float) -> dict[str, float]:
        """Report the total measured boardings injected this step (transparency)."""
        people = self._inflow_at(t, state)
        if people is None:
            return {}
        return {"transit_boardings": float(people.sum())}

    def cost(self, result: object) -> float:
        """No new J term — TransitLoad is a realism source, not a priced lever, so it
        can never move a headline dollar figure."""
        return 0.0

    # -- helpers ------------------------------------------------------------
    def _inflow_at(self, t: float, state: State) -> np.ndarray | None:
        """The per-step inflow ``(N,)`` for the observed bin nearest sim-time ``t``:
        ``count / BIN_MINUTES * dt * scale``. None when inert (no baked counts) — both
        ``source`` and ``observe`` go through here so they agree exactly."""
        if not self._counts or not self._bins:
            return None
        arr = np.asarray(self._bins, dtype=float)
        bin_minute = float(arr[int(np.argmin(np.abs(arr - float(t))))])
        counts = self._counts.get(bin_minute)
        if counts is None:
            return None
        dt = float(state.params.get("dt", 1.0))
        return counts / BIN_MINUTES * dt * self.scale
