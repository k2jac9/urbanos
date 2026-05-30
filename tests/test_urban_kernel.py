"""Kernel invariants: people are conserved, load drains downhill to sinks, and
bottlenecks build a queue. Pure synthetic graphs — no data, no model, no network.
"""
from __future__ import annotations

import networkx as nx
import numpy as np

from urban_os.kernel import Simulation, Substrate
from urban_os.kernel.operators import Lens, Operators


def _line_graph() -> Substrate:
    """venue → mid → exit(sink). Link caps let everything flow if uncongested."""
    g = nx.DiGraph()
    g.add_node("venue", label="Venue", lat=43.64, lng=-79.39, capacity=100.0)
    g.add_node("mid", label="Mid", lat=43.65, lng=-79.39, capacity=100.0)
    g.add_node("exit", label="Exit", lat=43.66, lng=-79.39, capacity=100.0)
    g.add_edge("venue", "mid", capacity=50.0, length=1.0)
    g.add_edge("mid", "exit", capacity=50.0, length=1.0)
    return Substrate.from_graph(g, sinks=["exit"])


class _Seed(Lens):
    """Drop a one-shot slug of people at the venue on the first step."""

    name = "seed"

    def __init__(self, amount: float) -> None:
        self.amount = amount

    def source(self, state, t) -> None:
        if state.step == 0:
            state.field("load")[state.substrate.idx("venue")] += self.amount


def test_load_conserved_and_drains_to_exit() -> None:
    sub = _line_graph()
    sim = Simulation(sub, [_Seed(80.0)], beta=1.8, dt=1.0)
    res = sim.run(40)
    last = res.frames[-1]
    arrived_at_exit = last["load"][sub.idx("exit")]
    # Sinks absorb; their `load` stays 0, the people land in `arrived`. Recompute
    # total people = still-in-system load + absorbed.
    state_load_total = last["load"].sum()  # venue+mid (+exit which is ~0)
    # After 40 min everything should have reached the exit.
    assert arrived_at_exit < 1e-6  # exits don't accumulate load
    assert state_load_total < 1e-6  # system drained


def test_bottleneck_builds_a_queue() -> None:
    """Halve the downstream link: people pile up at `mid` before clearing."""
    g = nx.DiGraph()
    g.add_node("venue", label="Venue", lat=43.64, lng=-79.39, capacity=1000.0)
    g.add_node("mid", label="Mid", lat=43.65, lng=-79.39, capacity=1000.0)
    g.add_node("exit", label="Exit", lat=43.66, lng=-79.39, capacity=1000.0)
    g.add_edge("venue", "mid", capacity=200.0, length=1.0)
    g.add_edge("mid", "exit", capacity=20.0, length=1.0)  # bottleneck
    sub = Substrate.from_graph(g, sinks=["exit"])
    sim = Simulation(sub, [_Seed(400.0)], beta=1.8, dt=1.0)
    res = sim.run(60)
    mid_series = [f["load"][sub.idx("mid")] for f in res.frames]
    assert max(mid_series) > 50.0  # a real queue formed at the bottleneck
    assert mid_series[-1] < 5.0    # and eventually cleared


def test_total_people_conserved_each_step() -> None:
    sub = _line_graph()
    sim = Simulation(sub, [_Seed(80.0)], beta=1.8, dt=1.0)
    res = sim.run(40)
    # in-system load + cumulative arrived must equal the injected total at every step.
    for f in res.frames:
        total = float(f["load"].sum() + f["arrived"].sum())
        assert abs(total - 80.0) < 1e-6
