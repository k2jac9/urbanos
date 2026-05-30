"""Edge-case hardening for the Urban-OS kernel.

Tiny hand-built graphs exercise the degenerate inputs the API can hand the
kernel: no sinks, unreachable nodes, single nodes, zero-capacity nodes, extreme
lever values, zero crowds, off-unit dt, frame sub-sampling and bad node ids.
The bar is: never crash, never NaN/inf, never silently corrupt (people stay
conserved and non-negative). Pure synthetic — no data, no model, no network.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from urban_os.adapters.toronto import downtown_scenario
from urban_os.kernel import Simulation, Substrate
from urban_os.kernel.operators import Lens
from urban_os.lenses import EconomicLens, EventSurge


class _Seed(Lens):
    """Drop a one-shot slug of people at given node id(s) on the first step."""

    name = "seed"

    def __init__(self, drops: dict[str, float]) -> None:
        self.drops = drops

    def source(self, state, t) -> None:
        if state.step == 0:
            for nid, amt in self.drops.items():
                state.field("load")[state.substrate.idx(nid)] += amt


def _finite(frame) -> bool:
    return all(
        np.isfinite(frame[k]).all() for k in ("load", "congestion", "risk", "arrived")
    )


def _two_node(cap_a: float = 100.0, sinks: list[str] | None = None) -> Substrate:
    g = nx.DiGraph()
    g.add_node("a", label="A", lat=43.60, lng=-79.40, capacity=cap_a)
    g.add_node("b", label="B", lat=43.70, lng=-79.40, capacity=1.0e9)
    g.add_edge("a", "b", capacity=50.0, length=1.0)
    return Substrate.from_graph(g, sinks=sinks if sinks is not None else ["b"])


# ---------------------------------------------------------------- no sinks


def test_no_sinks_keeps_people_in_system() -> None:
    """Nothing can drain: load is parked, never goes negative, never NaN."""
    sub = _two_node(sinks=[])
    assert np.isinf(sub.dist_to_sink).all()  # nobody can reach an exit
    sim = Simulation(sub, [_Seed({"a": 80.0})], dt=1.0)
    res = sim.run(10)
    last = res.frames[-1]
    assert _finite(last)
    assert (last["load"] >= 0).all()
    assert last["arrived"].sum() == 0.0  # no sink → nothing absorbed
    # People are conserved (just stuck in-system).
    assert abs(last["load"].sum() + last["arrived"].sum() - 80.0) < 1e-9


# -------------------------------------------------------- unreachable node


def test_unreachable_node_is_inf_and_never_drains() -> None:
    """A node with no path to any sink: dist=+inf, load parks there, the rest
    of the graph still drains normally and totals stay conserved."""
    g = nx.DiGraph()
    g.add_node("iso", label="Iso", lat=43.60, lng=-79.40, capacity=100.0)
    g.add_node("a", label="A", lat=43.61, lng=-79.40, capacity=100.0)
    g.add_node("exit", label="E", lat=43.70, lng=-79.40, capacity=1.0e9)
    g.add_edge("a", "exit", capacity=50.0, length=1.0)
    sub = Substrate.from_graph(g, sinks=["exit"])
    assert np.isinf(sub.dist_to_sink[sub.idx("iso")])
    assert np.isfinite(sub.dist_to_sink[sub.idx("a")])

    sim = Simulation(sub, [_Seed({"iso": 30.0, "a": 30.0})], dt=1.0)
    res = sim.run(15)
    last = res.frames[-1]
    assert _finite(last)
    assert last["load"][sub.idx("iso")] == pytest.approx(30.0)  # stuck forever
    assert last["load"][sub.idx("a")] < 1e-6                    # fully drained
    assert abs(last["load"].sum() + last["arrived"].sum() - 60.0) < 1e-9


# ------------------------------------------------------------ single node


def test_single_node_that_is_a_sink() -> None:
    """One node, no edges, and it's the sink. dist=0, no transport, no crash."""
    g = nx.DiGraph()
    g.add_node("x", label="X", lat=43.6, lng=-79.4, capacity=100.0)
    sub = Substrate.from_graph(g, sinks=["x"])
    assert sub.n == 1 and sub.n_edges == 0
    assert sub.dist_to_sink[0] == 0.0
    sim = Simulation(sub, [_Seed({"x": 50.0})], dt=1.0)
    res = sim.run(5)
    last = res.frames[-1]
    assert _finite(last)
    # No inbound edge, so directly-seeded load can never be absorbed — it stays
    # as load. The point is only: no crash, conserved, non-negative.
    assert (last["load"] >= 0).all()
    assert abs(last["load"].sum() + last["arrived"].sum() - 50.0) < 1e-9


def test_single_node_not_a_sink() -> None:
    """One node, no edges, not a sink. dist=+inf, load parks, no crash."""
    g = nx.DiGraph()
    g.add_node("x", label="X", lat=43.6, lng=-79.4, capacity=100.0)
    sub = Substrate.from_graph(g, sinks=[])
    assert np.isinf(sub.dist_to_sink[0])
    sim = Simulation(sub, [_Seed({"x": 50.0})], dt=1.0)
    last = sim.run(5).frames[-1]
    assert _finite(last)
    assert last["load"][0] == pytest.approx(50.0)


# ------------------------------------------------------- zero-capacity node


def test_zero_capacity_node_does_not_nan_the_run() -> None:
    """capacity 0 → congestion = load/0 must be a safe 0, never NaN/inf."""
    g = nx.DiGraph()
    g.add_node("a", label="A", lat=43.60, lng=-79.40, capacity=0.0)
    g.add_node("exit", label="E", lat=43.70, lng=-79.40, capacity=1.0e9)
    g.add_edge("a", "exit", capacity=50.0, length=1.0)
    sub = Substrate.from_graph(g, sinks=["exit"])
    sim = Simulation(sub, [_Seed({"a": 200.0})], dt=1.0)
    res = sim.run(10)
    for f in res.frames:
        assert _finite(f)
        # Safe-divide convention: zero capacity yields zero congestion (not inf).
        assert f["congestion"][sub.idx("a")] == 0.0
        assert (f["risk"] >= 0).all()


# ----------------------------------------------- release lever at/over max


@pytest.mark.parametrize("release", [20.0, 40.0, 100.0])
def test_release_minutes_at_and_beyond_max_does_not_crash(release: float) -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    sim = Simulation(
        sc.substrate,
        [es, EconomicLens()],
        params={"release_minutes": release},
        dt=sc.dt,
    )
    res = sim.run(sc.horizon)
    for f in res.frames:
        assert _finite(f)
        assert (f["load"] >= 0).all()


def test_huge_release_flattens_more_than_small_release() -> None:
    """Going well past the lever max keeps the monotone direction (a bigger
    release never gives a higher peak at Union)."""
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

    assert union_peak(100.0) <= union_peak(20.0) + 1e-6


# ------------------------------------------------------------ crowd_size 0


def test_crowd_size_zero_is_a_quiet_valid_run() -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, 0.0, event_end=sc.event_end)
    sim = Simulation(sc.substrate, [es, EconomicLens()], dt=sc.dt)
    res = sim.run(sc.horizon)
    for f in res.frames:
        assert _finite(f)
        assert f["load"].max() == 0.0
        assert f["risk"].max() == 0.0
    assert max(res.series("peak_congestion")) == 0.0
    assert sum(res.series("delay_cost")) == 0.0


# ----------------------------------------------------------------- dt != 1


@pytest.mark.parametrize("dt", [0.5, 2.0])
def test_non_unit_dt_conserves_people(dt: float) -> None:
    sc = downtown_scenario()
    steps = int(round(sc.horizon / dt))
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    sim = Simulation(sc.substrate, [es, EconomicLens()], dt=dt)
    res = sim.run(steps)
    last = res.frames[-1]
    assert _finite(last)
    # Over a horizon that captures the whole pulse, arrivals ≈ crowd_size.
    total = last["load"].sum() + last["arrived"].sum()
    assert total == pytest.approx(sc.crowd_size, rel=1e-3)


# --------------------------------------------- frame_every / record_frames


def test_frame_every_subsamples_frames() -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    sim = Simulation(sc.substrate, [es, EconomicLens()], dt=sc.dt)
    res = sim.run(20, record_frames=True, frame_every=5)
    assert [f["t"] for f in res.frames] == [0.0, 5.0, 10.0, 15.0]
    # Metrics are still collected every step regardless of frame sub-sampling.
    assert len(res.series("peak_congestion")) == 20


def test_record_frames_false_yields_no_frames_but_keeps_metrics() -> None:
    sc = downtown_scenario()
    es = EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end)
    sim = Simulation(sc.substrate, [es, EconomicLens()], dt=sc.dt)
    res = sim.run(20, record_frames=False)
    assert res.frames == []
    assert len(res.series("peak_congestion")) == 20


# --------------------------------------------------------- bad node id


def test_idx_unknown_node_raises_keyerror() -> None:
    sub = downtown_scenario().substrate
    with pytest.raises(KeyError):
        sub.idx("does_not_exist")


def test_eventsurge_unknown_venue_raises_keyerror_at_configure() -> None:
    """A lens pointed at a non-existent venue should fail cleanly on configure,
    not corrupt a run."""
    sc = downtown_scenario()
    es = EventSurge("no_such_venue", 1000.0, event_end=10.0)
    sim = Simulation(sc.substrate, [es, EconomicLens()], dt=sc.dt)
    with pytest.raises(KeyError):
        sim.run(5)
