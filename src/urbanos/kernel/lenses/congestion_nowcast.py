"""CongestionNowcast lens — calibrate the kernel against *observed* Toronto counts.

Phase 1 of the data-driven roadmap (``docs/research/tpf-and-data-driven-lenses.md``
§8.2): a **calibration metric, no learned field yet**. Where ``SafetyLens`` lifts a
*static* address scalar onto the substrate, this lens lifts the **time-varying**
observed-throughput series (the real Toronto TMC 15-min counts, fused per node by
``adapters.observed_counts_by_node``) and, at each step, asks the honest question the
deterministic kernel could never answer before: *how well does the kernel's predicted
crowd profile match what was actually measured on the street?*

It is the safest possible first data-driven step (roadmap §6 "Fit B", §7 honesty #1 —
"learned predicts, exact kernel decides"): the lens is **read-only** on the crowd
fields, declares **no levers**, and contributes **zero cost** — it cannot move the
optimizer's chosen intervention or any headline number. It only reports a *trust*
signal: a scale-free agreement score between the kernel's node-load profile and the
observed-count profile at matching times.

Why a *shape* metric, not a raw error
-------------------------------------
Observed TMC counts are absolute people in survey units; the kernel's ``load`` is the
simulated crowd of a hypothetical FIFA-day convergence — the two share no common
absolute scale, so a raw ``|load - count|`` would be meaningless (and easy to fish).
The defensible, scale-free question is whether the kernel puts the crowd in the *same
relative places* the data does: cosine similarity between the two node-profiles (1.0 =
identical shape, 0.0 = orthogonal). We report it alongside the exact kernel, never in
place of it.

Time alignment
--------------
Observed bins are on a rebased relative axis (first bin = minute 0; see
``_observed_counts_by_node``). We map the sim clock onto that axis by an offset so the
kernel's *peak* window lines up with the observed peak window, then compare at each
observed bin against the nearest sim step. Alignment lives here (the lens), kept out of
the data layer so the ingest stays honest about what it does and does not assert.

Offline-safe: with no real slice the adapter returns a deterministic synthetic series,
so the lens (and its test) run with no network and no committed data.
"""
from __future__ import annotations

import numpy as np

from ..kernel.operators import Lens
from ..kernel.state import State, Substrate


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two non-negative profiles, 0.0 when either is all-zero.

    Bounded to ``[0, 1]`` (both inputs are non-negative count/load profiles, so a
    negative cosine is not physically meaningful here and is clamped to 0)."""
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(np.clip(np.dot(a, b) / (na * nb), 0.0, 1.0))


class CongestionNowcastLens(Lens):
    """Advisory calibration lens: kernel-vs-observed node-profile agreement.

    Construct with a ``{node_id: {minute: count}}`` series (the temporal twin of the
    civic overlays — see ``adapters.observed_counts_by_node``). Constructed bare it is
    inert (no observed series → it reports an empty calibration, never an error), so it
    is always safe to include in a stack.
    """

    name = "congestion_nowcast"

    def __init__(
        self, node_counts: dict[str, dict[float, float]] | None = None, *, weight: float = 1.0
    ) -> None:
        self.node_counts = dict(node_counts) if node_counts else None
        self.weight = weight
        self._obs: dict[float, np.ndarray] | None = None   # {obs_minute: (N,) profile}
        self._offset: float | None = None                  # sim_t = obs_minute + offset
        self._scores: list[float] = []

    # -- configuration ------------------------------------------------------
    def configure(self, substrate: Substrate) -> None:
        self._scores = []
        self._offset = None
        if not self.node_counts:
            self._obs = None
            return
        # Bake the per-node series into a per-bin profile array over the substrate.
        bins: set[float] = set()
        for series in self.node_counts.values():
            bins.update(float(m) for m in series)
        self._obs = {}
        for b in sorted(bins):
            prof = np.array(
                [float(self.node_counts.get(nid, {}).get(b, 0.0)) for nid in substrate.ids],
                dtype=float,
            )
            self._obs[b] = prof
        # Align the observed time axis to the sim clock so the two PEAK windows
        # coincide: offset = (sim peak bin) - (observed peak bin). The observed peak
        # bin is the one with the largest total throughput; the sim peak window is
        # discovered lazily on the first step the kernel's load is non-trivial.
        if self._obs:
            self._obs_peak_bin = max(self._obs, key=lambda b: float(self._obs[b].sum()))
        self._sim_peak_t = 0.0
        self._sim_peak_load = 0.0

    # -- per-step calibration ----------------------------------------------
    def couple(self, state: State, t: float) -> None:
        """Track where/when the kernel piles up load, and (once aligned) score the
        kernel's current profile against the observed profile at the matching bin.

        Read-only on the crowd fields — it writes only its own advisory display field
        ``observed_load`` (the aligned observed profile for the map) and never mutates
        ``load``/``congestion``/``risk``."""
        if not self._obs:
            return
        load = state.fields["load"]
        total = float(load.sum())
        # Discover the sim peak window, then lock the time offset once the surge has
        # actually arrived (so we align peak-to-peak, not the empty pre-event ramp).
        if total > self._sim_peak_load:
            self._sim_peak_load = total
            self._sim_peak_t = t
        if self._offset is None and self._sim_peak_load > 0.0:
            self._offset = self._sim_peak_t - self._obs_peak_bin

        if self._offset is None:
            return
        obs_minute = t - self._offset
        prof = self._obs.get(obs_minute)
        if prof is None:                       # only compare on observed bins
            return
        score = _cosine(np.asarray(load, dtype=float), prof)
        self._scores.append(score)
        # Advisory overlay for the map (labelled observed/approximate by the caller).
        state.fields["observed_load"] = prof

    # -- reporting ----------------------------------------------------------
    def observe(self, state: State, t: float) -> dict[str, float]:
        if not self._obs or self._offset is None:
            return {}
        obs_minute = t - self._offset
        if obs_minute not in self._obs:
            return {}
        # The latest per-bin agreement (the series ``calibration_fit``), so the UI can
        # plot trust over time and the optimizer-independent summary is just its mean.
        return {"calibration_fit": self._scores[-1] if self._scores else 0.0}

    def calibration_summary(self) -> dict[str, float]:
        """Run-level calibration report: mean shape-agreement over the observed bins,
        the worst bin, and how many bins were compared. Empty agreement (no data /
        never aligned) reports ``n_bins`` 0 so callers can show "not calibrated"
        rather than a misleading 0.0 fit."""
        if not self._scores:
            return {"mean_fit": 0.0, "min_fit": 0.0, "n_bins": 0}
        arr = np.array(self._scores, dtype=float)
        return {
            "mean_fit": float(arr.mean()),
            "min_fit": float(arr.min()),
            "n_bins": int(arr.size),
        }
