"""Property / invariant tests for the Urban-OS kernel.

These lock in the contracts the API and optimizer rely on across parameter
sweeps: conservation of people, determinism under seeds, non-negativity and
finiteness of every field, a soft monotonicity of the staggered-release
intervention, and basic optimizer sanity. Pure synthetic + the downtown
adapter — no data, no model, no network.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from urbanos.kernel.adapters.toronto import downtown_scenario
from urbanos.kernel.kernel import Simulation, Substrate
from urbanos.kernel.kernel.operators import Lens
from urbanos.kernel.lenses import EconomicLens, EventSurge
from urbanos.kernel.optimize import optimize


class _Seed(Lens):
    """One-shot slug at a node on step 0 — a closed system with no ongoing
    source, so the conserved total is exactly the injected amount."""

    name = "seed"

    def __init__(self, node: str, amount: float) -> None:
        self.node = node
        self.amount = amount

    def source(self, state, t) -> None:
        if state.step == 0:
            state.field("load")[state.substrate.idx(self.node)] += self.amount


def _line_graph() -> Substrate:
    g = nx.DiGraph()
    g.add_node("venue", label="Venue", lat=43.64, lng=-79.39, capacity=100.0)
    g.add_node("mid", label="Mid", lat=43.65, lng=-79.39, capacity=100.0)
    g.add_node("exit", label="Exit", lat=43.66, lng=-79.39, capacity=1.0e9)
    g.add_edge("venue", "mid", capacity=50.0, length=1.0)
    g.add_edge("mid", "exit", capacity=50.0, length=1.0)
    return Substrate.from_graph(g, sinks=["exit"])


def _all_finite_nonneg(frame) -> None:
    for k in ("load", "congestion", "risk", "arrived"):
        arr = frame[k]
        assert np.isfinite(arr).all(), f"{k} not finite at t={frame['t']}"
        assert (arr >= 0).all(), f"{k} went negative at t={frame['t']}"


# --------------------------------------------------------------- conservation


def test_per_step_conservation_exact_noise_zero() -> None:
    """With a one-shot source and noise=0, load.sum()+arrived.sum() equals the
    injected total at *every* recorded frame, to machine precision."""
    sub = _line_graph()
    sim = Simulation(sub, [_Seed("venue", 80.0)], dt=1.0, noise=0.0)
    res = sim.run(40)
    for f in res.frames:
        total = float(f["load"].sum() + f["arrived"].sum())
        assert total == pytest.approx(80.0, abs=1e-9)


@pytest.mark.parametrize("seed", [0, 1, 42])
@pytest.mark.parametrize("noise", [0.5, 2.0])
def test_per_step_conservation_exact_with_noise(seed: int, noise: float) -> None:
    """ADR-0021: conservation now holds UNDER noise too, not just on the noise==0
    path. The jitter is zero-sum and rescaled after the non-negativity clip, so
    load.sum()+arrived.sum() stays equal to the injected total at every frame."""
    sub = _line_graph()
    sim = Simulation(sub, [_Seed("venue", 80.0)], dt=1.0, noise=noise, seed=seed)
    res = sim.run(40)
    for f in res.frames:
        total = float(f["load"].sum() + f["arrived"].sum())
        assert total == pytest.approx(80.0, abs=1e-6)


@pytest.mark.parametrize("dt", [0.5, 1.0, 2.0])
def test_per_step_conservation_exact_various_dt(dt: float) -> None:
    sub = _line_graph()
    sim = Simulation(sub, [_Seed("venue", 123.0)], dt=dt, noise=0.0)
    res = sim.run(int(round(80 / dt)))
    for f in res.frames:
        assert f["load"].sum() + f["arrived"].sum() == pytest.approx(123.0, abs=1e-9)


def test_eventsurge_arrivals_approach_crowd_size_over_long_horizon() -> None:
    """The EventSurge integrates a normalized Gaussian; over a horizon that
    captures ≥99% of the pulse, load+arrived ≈ crowd_size."""
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    sim = Simulation(sc.substrate, [es, EconomicLens()], dt=sc.dt, noise=0.0)
    res = sim.run(sc.horizon)
    last = res.frames[-1]
    total = float(last["load"].sum() + last["arrived"].sum())
    assert total == pytest.approx(sc.crowd_size, rel=1e-3)


@pytest.mark.parametrize("seed", [0, 1, 42, 7])
@pytest.mark.parametrize("noise", [0.0, 0.5, 2.0])
def test_fields_finite_and_nonneg_across_seed_noise_sweep(seed: int, noise: float) -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    sim = Simulation(
        sc.substrate, [es, EconomicLens()], dt=sc.dt, noise=noise, seed=seed
    )
    res = sim.run(sc.horizon)
    for f in res.frames:
        _all_finite_nonneg(f)


@pytest.mark.parametrize("noise", [0.5, 2.0])
def test_noise_keeps_totals_in_a_sane_band(noise: float) -> None:
    """Noise perturbs load (so exact conservation is not expected), but it must
    not blow up or drain the system — totals stay within a loose band."""
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    sim = Simulation(sc.substrate, [es, EconomicLens()], dt=sc.dt, noise=noise, seed=3)
    last = sim.run(sc.horizon).frames[-1]
    total = float(last["load"].sum() + last["arrived"].sum())
    assert 0.8 * sc.crowd_size <= total <= 1.2 * sc.crowd_size


# ---------------------------------------------------------------- determinism


def test_same_seed_same_params_identical_frames() -> None:
    sc = downtown_scenario()

    def run():
        es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
        return Simulation(
            sc.substrate, [es, EconomicLens()], dt=sc.dt, noise=1.0, seed=11
        ).run(sc.horizon)

    a, b = run(), run()
    assert len(a.frames) == len(b.frames)
    for fa, fb in zip(a.frames, b.frames):
        for k in ("load", "congestion", "risk", "arrived"):
            assert np.array_equal(fa[k], fb[k])


def test_different_seed_with_noise_differs() -> None:
    sc = downtown_scenario()

    def run(seed: int):
        es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
        return Simulation(
            sc.substrate, [es, EconomicLens()], dt=sc.dt, noise=1.0, seed=seed
        ).run(sc.horizon)

    a, b = run(1), run(2)
    assert any(
        not np.array_equal(fa["load"], fb["load"]) for fa, fb in zip(a.frames, b.frames)
    )


def test_noise_zero_is_seed_independent() -> None:
    sc = downtown_scenario()

    def run(seed: int):
        es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
        return Simulation(
            sc.substrate, [es, EconomicLens()], dt=sc.dt, noise=0.0, seed=seed
        ).run(sc.horizon)

    a, b = run(1), run(123456)
    for fa, fb in zip(a.frames, b.frames):
        assert np.array_equal(fa["load"], fb["load"])


# ----------------------------------------------- monotone intervention (soft)


@pytest.mark.parametrize(
    "lo,hi",
    [(0.0, 2.0), (2.0, 4.0), (4.0, 8.0), (8.0, 12.0), (12.0, 16.0), (16.0, 20.0)],
)
def test_more_release_never_raises_union_peak(lo: float, hi: float) -> None:
    """Higher staggered release should never increase peak congestion at Union
    (tiny numerical slack allowed)."""
    sc = downtown_scenario()
    ui = sc.substrate.idx("union")

    def union_peak(release: float) -> float:
        es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
        sim = Simulation(
            sc.substrate, [es, EconomicLens()],
            params={"release_minutes": release}, dt=sc.dt,
        )
        res = sim.run(sc.horizon)
        return max(f["congestion"][ui] for f in res.frames)

    assert union_peak(hi) <= union_peak(lo) + 1e-6


def test_fields_nonneg_across_release_sweep() -> None:
    sc = downtown_scenario()
    for release in np.arange(0.0, 21.0, 2.0):
        es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
        sim = Simulation(
            sc.substrate, [es, EconomicLens()],
            params={"release_minutes": float(release)}, dt=sc.dt,
        )
        for f in sim.run(sc.horizon).frames:
            _all_finite_nonneg(f)


# ------------------------------------------------------------ optimizer sanity


def test_optimizer_baseline_is_do_nothing() -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    opt = optimize(sc.substrate, [es, EconomicLens()], sc.horizon, dt=sc.dt)
    # Every lever's baseline is its first (do-nothing) grid value.
    for lv in opt.levers:
        assert opt.baseline_params[lv.name] == lv.values[0]


def test_optimizer_best_is_no_worse_than_baseline() -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    opt = optimize(sc.substrate, [es, EconomicLens()], sc.horizon, dt=sc.dt)
    assert opt.best_J <= opt.baseline_J
    assert opt.savings >= 0.0


def test_optimizer_all_trial_J_finite() -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    opt = optimize(sc.substrate, [es, EconomicLens()], sc.horizon, dt=sc.dt)
    for tr in opt.trials:
        assert np.isfinite(tr["J"])


def test_optimizer_trial_count_equals_grid_size() -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    opt = optimize(sc.substrate, [es, EconomicLens()], sc.horizon, dt=sc.dt)
    grid_size = 1
    for lv in opt.levers:
        grid_size *= len(lv.values)
    assert len(opt.trials) == grid_size
