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

    @property
    def steps(self) -> int:
        return len(self.times)

    def series(self, name: str) -> list[float]:
        return self.metrics.get(name, [])

    def peak_congestion(self) -> dict:
        """The node and time of maximum congestion across the whole run — the raw
        material for the 'specific station, specific timing' insight."""
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

        for step in range(steps):
            t = step * self.dt
            state.t = t
            state.step = step

            # 1. sources — lenses inject forcing.
            for lens in self.lenses:
                lens.source(state, t)

            # 2. integrate — move load on the graph, then optional noise.
            Operators.transport(state, dt=self.dt)
            if self.noise > 0:
                load = state.fields["load"]
                load += rng.normal(0.0, self.noise, size=load.shape) * np.sqrt(load + 1.0)
                np.clip(load, 0.0, None, out=load)

            # 3. couple — kernel maintains congestion; lenses derive the rest.
            state.fields["congestion"] = _safe_div(state.fields["load"], sub.capacity)
            for lens in self.lenses:
                lens.couple(state, t)

            # 4. observe — collect scalar metrics from every lens.
            times.append(t)
            for lens in self.lenses:
                for k, v in lens.observe(state, t).items():
                    metrics.setdefault(k, []).append(float(v))

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
        )
