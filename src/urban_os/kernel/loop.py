"""The time loop: gather sources → integrate transport(+noise) → couple → observe.

This is the whole kernel control flow in one place. It is deterministic under a
seed and carries no domain knowledge — every city- or domain-specific behaviour
arrives as a lens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .operators import Lens, Operators, _safe_div
from .state import State, Substrate


@dataclass
class SimResult:
    """Everything a finished run produced: per-step metric series, optional field
    frames for the map, and the params/levers that produced them."""

    substrate: Substrate
    params: dict
    dt: float
    times: list[float]
    metrics: dict[str, list[float]]      # metric name -> per-step series
    frames: list[dict] = field(default_factory=list)  # {t, load, congestion, risk}
    # True peak congestion computed over EVERY step during run() — independent of
    # the ``frame_every`` display subsampling. None for directly-built SimResults
    # (peak_congestion then falls back to scanning the recorded frames).
    peak: dict | None = None

    @property
    def steps(self) -> int:
        return len(self.times)

    def series(self, name: str) -> list[float]:
        return self.metrics.get(name, [])

    def peak_congestion(self) -> dict:
        """The node and time of maximum congestion across the whole run — the raw
        material for the 'specific station, specific timing' insight.

        Uses the peak tracked over ALL steps when available (so the headline
        number does not change with ``frame_every``); otherwise scans the
        recorded frames as a backward-compatible fallback.
        """
        if self.peak is not None:
            return dict(self.peak)
        best = {"node": None, "label": None, "congestion": 0.0, "t": 0.0}
        for frame in self.frames:
            cong = frame["congestion"]
            i = int(np.argmax(cong))
            if cong[i] > best["congestion"]:
                best = {
                    "node": self.substrate.ids[i],
                    "label": self.substrate.labels[i],
                    "congestion": float(cong[i]),
                    "t": float(frame["t"]),
                }
        return best


class Simulation:
    """Run lenses over a substrate for N steps.

    ``dt`` is the minutes per step; ``noise`` adds seeded stochastic jitter to
    load each step (0 = fully deterministic, used by tests). ``beta`` is exposed
    to lenses via ``state.params['beta']`` (the speed–density exponent some
    couplings use); the kernel's transport itself is pure capacitated drainage.
    """

    def __init__(
        self,
        substrate: Substrate,
        lenses: list[Lens],
        *,
        params: dict | None = None,
        beta: float = 1.8,
        dt: float = 1.0,
        noise: float = 0.0,
        seed: int = 42,
    ) -> None:
        self.substrate = substrate
        self.lenses = lenses
        self.params = dict(params or {})
        self.beta = beta
        self.dt = dt
        self.noise = noise
        self.seed = seed

    def run(self, steps: int, *, record_frames: bool = True, frame_every: int = 1) -> SimResult:
        frame_every = max(1, frame_every)  # guard internal callers; HTTP enforces ge=1
        sub = self.substrate
        state = State(sub, self.params)
        state.params["dt"] = self.dt  # lenses read dt to integrate rates over a step
        state.params["beta"] = self.beta
        for lens in self.lenses:
            lens.configure(sub)
        rng = np.random.default_rng(self.seed)

        times: list[float] = []
        metrics: dict[str, list[float]] = {}
        frames: list[dict] = []
        # True peak congestion over EVERY step (not just recorded frames).
        peak_best = {"node": None, "label": None, "congestion": 0.0, "t": 0.0}

        for step in range(steps):
            t = step * self.dt
            state.t = t
            state.step = step

            # Reset the per-step transport capacity multiplier; lenses that tax
            # throughput (e.g. rain) multiply into it during source() (ADR-0021).
            state.edge_cap_mult[:] = 1.0

            # 1. sources — lenses inject forcing.
            for lens in self.lenses:
                lens.source(state, t)

            # 2. integrate — move load on the graph, then optional noise.
            Operators.transport(state, dt=self.dt)
            if self.noise > 0:
                # Conservative jitter (ADR-0021): the perturbation is made zero-sum
                # (subtract its mean) so it REDISTRIBUTES load rather than creating or
                # destroying people, and after the non-negativity clip we rescale to
                # restore the exact pre-noise total. People-conservation (ADR-0002)
                # therefore holds under noise, not only on the noise==0 path.
                load = state.fields["load"]
                total_before = float(load.sum())
                eps = rng.normal(0.0, self.noise, size=load.shape) * np.sqrt(load + 1.0)
                eps -= eps.mean()                       # zero-sum: never injects mass
                load += eps
                np.clip(load, 0.0, None, out=load)      # keep load physical (≥ 0)
                total_after = float(load.sum())
                if total_after > 0.0:                   # correct the clip's tiny leak
                    load *= total_before / total_after

            # 3. couple — kernel maintains congestion; lenses derive the rest.
            state.fields["congestion"] = _safe_div(state.fields["load"], sub.capacity)
            for lens in self.lenses:
                lens.couple(state, t)

            # 4. observe — collect scalar metrics from every lens.
            times.append(t)
            for lens in self.lenses:
                for k, v in lens.observe(state, t).items():
                    metrics.setdefault(k, []).append(float(v))

            # Track the honest peak congestion at full resolution, so the headline
            # number is invariant to the frame_every payload-subsampling knob.
            cong = state.fields["congestion"]
            ci = int(np.argmax(cong))
            cval = float(cong[ci])
            if cval > peak_best["congestion"]:
                peak_best = {
                    "node": sub.ids[ci],
                    "label": sub.labels[ci],
                    "congestion": cval,
                    "t": t,
                }

            if record_frames and step % frame_every == 0:
                frames.append(
                    {
                        "t": t,
                        "load": state.fields["load"].copy(),
                        "congestion": state.fields["congestion"].copy(),
                        "risk": state.fields["risk"].copy(),
                        "arrived": state.fields["arrived"].copy(),
                    }
                )

        return SimResult(
            substrate=sub,
            params=dict(state.params),
            dt=self.dt,
            times=times,
            metrics=metrics,
            frames=frames,
            peak=peak_best,
        )
