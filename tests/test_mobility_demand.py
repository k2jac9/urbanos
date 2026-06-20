"""Fit C — MobilityDemand lens (Bike Share trip-origin demand, advisory display overlay).

The lens lifts a Bike Share "demand to leave" series onto the substrate as its OWN
``bike_demand`` overlay. It is DISPLAY-ONLY and ADDITIVE: read-only on the crowd fields
(``load``/``congestion``/``risk``), declares NO levers, carries NO cost, and lives in
``extra_display_lenses`` (excluded from the optimizer's ``J``) — so it can never move a
headline number. These tests pin the honesty invariants (ADR-0030):

1. bare construction is inert (offline-safe no-op);
2. demand baked at NON-SINK nodes only; nearest-bin selection; degenerate/empty inputs
   don't raise and never emit NaN/inf;
3. no levers, zero cost, advisory provenance;
4. read-only on the crowd fields — the additivity contract (it perturbs nothing else);
5. determinism;
6. the adapter ``bikeshare_demand_by_node`` returns the right shape and falls back
   synthetically when no slice is present.

All offline: a tiny in-test substrate + in-test demand slices, no network, no real data.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from urbanos.kernel.adapters import bikeshare_demand_by_node, downtown_scenario
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.kernel.state import State, Substrate
from urbanos.kernel.lenses import EconomicLens, EventSurge, MobilityDemandLens
from urbanos.kernel.lenses.mobility_demand import PROVENANCE


# --- a tiny deterministic substrate -----------------------------------------
def _toy_substrate() -> Substrate:
    """One transit node 'a' draining to a sink 's' — small enough to assert exact shape."""
    g = nx.DiGraph()
    g.add_node("a", lat=43.60, lng=-79.40, capacity=100.0)
    g.add_node("s", lat=43.50, lng=-79.50, capacity=1.0e9)
    g.add_edge("a", "s", capacity=1000.0, length=1.0)
    return Substrate.from_graph(g, sinks=["s"])


def _state(sub: Substrate, dt: float = 1.0) -> State:
    st = State(sub, {"release_minutes": 0.0})
    st.params["dt"] = dt
    return st


# --- 1. bare lens is inert ---------------------------------------------------
def test_bare_lens_is_inert():
    """Constructed with no series the lens writes no overlay and reports no metric — a
    clean offline-safe no-op, never an error."""
    sub = _toy_substrate()
    lens = MobilityDemandLens()
    lens.configure(sub)
    st = _state(sub)
    lens.couple(st, 0.0)
    assert "bike_demand" not in st.fields           # wrote no overlay
    assert lens.observe(st, 0.0) == {}              # no metric when inert


def test_bare_lens_inert_in_a_full_run():
    sc = downtown_scenario()
    stack = [EventSurge(events=sc.events), EconomicLens(), MobilityDemandLens()]
    res = Simulation(sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt).run(
        sc.horizon
    )
    assert res.series("bike_demand_peak") == []     # inert -> no demand metric


# --- 2. demand baked at non-sink nodes only; overlay written -----------------
def test_couple_writes_overlay_at_non_sinks_only():
    """The demand overlay carries the configured value at the non-sink node; the sink's
    value is IGNORED (an exit line is never a demand origin)."""
    sub = _toy_substrate()
    demand = {"a": {0.0: 150.0}, "s": {0.0: 999.0}}  # sink value must be ignored
    lens = MobilityDemandLens(demand)
    lens.configure(sub)
    st = _state(sub)
    lens.couple(st, 0.0)
    ai, si = sub.idx("a"), sub.idx("s")
    overlay = st.fields["bike_demand"]
    assert overlay[ai] == pytest.approx(150.0)
    assert overlay[si] == 0.0                        # sink never seeded
    assert lens.observe(st, 0.0)["bike_demand_peak"] == pytest.approx(150.0)


def test_couple_picks_the_nearest_demand_bin():
    """Sim-time snaps to the nearest demand bin minute (bins are 15-min spaced)."""
    sub = _toy_substrate()
    demand = {"a": {0.0: 150.0, 15.0: 300.0}}
    ai = sub.idx("a")
    lens = MobilityDemandLens(demand)
    lens.configure(sub)
    # t=7 is closer to bin 0 (|7-0|=7 < |7-15|=8).
    st = _state(sub)
    lens.couple(st, 7.0)
    assert st.fields["bike_demand"][ai] == pytest.approx(150.0)
    # t=12 is closer to bin 15.
    st2 = _state(sub)
    lens.couple(st2, 12.0)
    assert st2.fields["bike_demand"][ai] == pytest.approx(300.0)


def test_no_nan_or_inf_from_degenerate_inputs():
    """Negative, NaN and inf cell values are dropped at configure; the overlay stays
    finite and the run never propagates NaN/inf."""
    sub = _toy_substrate()
    demand = {"a": {0.0: -50.0, 15.0: float("nan"), 30.0: float("inf")}}
    lens = MobilityDemandLens(demand)
    lens.configure(sub)
    ai = sub.idx("a")
    for t in (0.0, 15.0, 30.0):
        st = _state(sub)
        lens.couple(st, t)                          # must not raise
        assert np.all(np.isfinite(st.fields["bike_demand"]))
        assert st.fields["bike_demand"][ai] == 0.0  # all degenerate -> nothing seeded


def test_empty_series_does_not_raise():
    sub = _toy_substrate()
    for series in ({}, None):
        lens = MobilityDemandLens(series)
        lens.configure(sub)
        st = _state(sub)
        lens.couple(st, 0.0)                         # inert, no raise
        assert "bike_demand" not in st.fields


# --- 3. no levers, zero cost, advisory provenance ----------------------------
def test_no_levers_no_cost_and_provenance():
    sub = _toy_substrate()
    lens = MobilityDemandLens({"a": {0.0: 10.0}})
    lens.configure(sub)
    assert lens.levers() == []
    assert lens.cost(None) == 0.0                    # display-only, never a J term
    assert PROVENANCE == "synthetic/advisory"        # honest: synthetic fallback today


def test_micromobility_relief_metric_is_bounded():
    """The advisory relief overlap is a scale-free cosine in [0, 1] (display-only)."""
    sub = _toy_substrate()
    lens = MobilityDemandLens({"a": {0.0: 10.0}})
    lens.configure(sub)
    st = _state(sub)
    st.fields["load"][sub.idx("a")] = 5.0           # crowd coincides with demand at 'a'
    lens.couple(st, 0.0)
    m = lens.observe(st, 0.0)
    assert 0.0 <= m["micromobility_relief"] <= 1.0
    assert m["micromobility_relief"] == pytest.approx(1.0)  # perfectly aligned profiles


# --- 4. read-only on the crowd fields (the additivity contract) --------------
def test_lens_does_not_perturb_crowd_fields_or_economic_terms():
    """Adding MobilityDemand to a run leaves load/congestion/risk and the economic terms
    byte-identical — it writes only its own ``bike_demand`` overlay."""
    sc = downtown_scenario()

    def run(with_lens: bool):
        stack = [EventSurge(events=sc.events), EconomicLens()]
        if with_lens:
            stack.append(MobilityDemandLens(bikeshare_demand_by_node(sc.substrate)))
        return Simulation(
            sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt
        ).run(sc.horizon)

    base, withl = run(False), run(True)
    assert np.allclose(base.frames[-1]["load"], withl.frames[-1]["load"])
    assert np.isclose(sum(base.series("delay_cost")), sum(withl.series("delay_cost")))
    assert np.isclose(sum(base.series("safety_cost")), sum(withl.series("safety_cost")))


def test_extra_display_lenses_includes_mobility_and_stays_additive():
    """extra_display_lenses(sc) now includes the grounded MobilityDemand lens; bare
    construction stays synthetic, and the contract additivity test still holds for the
    full extra-lens set (none perturb the economic terms)."""
    from urbanos.kernel.scenarios import extra_display_lenses

    sc = downtown_scenario()
    grounded = next(l for l in extra_display_lenses(sc) if l.name == "mobility_demand")
    bare = next(l for l in extra_display_lenses() if l.name == "mobility_demand")
    assert grounded.node_demand is not None
    assert set(grounded.node_demand) == set(sc.substrate.ids)
    assert bare.node_demand is None

    base = Simulation(
        sc.substrate, [EventSurge(events=sc.events), EconomicLens()],
        params={"release_minutes": 0.0}, dt=sc.dt,
    ).run(sc.horizon)
    stack = [EventSurge(events=sc.events), EconomicLens(), *extra_display_lenses(sc)]
    withl = Simulation(
        sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt
    ).run(sc.horizon)
    assert np.isclose(sum(base.series("delay_cost")), sum(withl.series("delay_cost")))
    assert np.isclose(sum(base.series("safety_cost")), sum(withl.series("safety_cost")))
    assert np.allclose(base.frames[-1]["load"], withl.frames[-1]["load"])


# --- 5. determinism ----------------------------------------------------------
def test_deterministic():
    sc = downtown_scenario()
    demand = bikeshare_demand_by_node(sc.substrate, provider=lambda: [])

    def run():
        stack = [EventSurge(events=sc.events), EconomicLens(), MobilityDemandLens(demand)]
        return Simulation(
            sc.substrate, stack, params={"release_minutes": 6.0}, dt=sc.dt
        ).run(sc.horizon)

    a, b = run(), run()
    assert a.series("bike_demand_peak") == b.series("bike_demand_peak")
    assert np.allclose(a.frames[-1]["load"], b.frames[-1]["load"])


# --- 6. adapter: shape + synthetic fallback ----------------------------------
def test_bikeshare_demand_by_node_well_formed_synthetic_fallback():
    """With no Bike Share slice the adapter returns a deterministic synthetic series: one
    {minute: count} dict per node, finite values, non-sink nodes carry demand, sinks none."""
    sc = downtown_scenario()
    demand = bikeshare_demand_by_node(sc.substrate, provider=lambda: [])  # empty -> synthetic
    sub = sc.substrate
    assert set(demand) == set(sub.ids)
    for i, nid in enumerate(sub.ids):
        series = demand[nid]
        assert all(np.isfinite(v) for v in series.values())
        if sub.is_sink[i]:
            assert all(v == 0.0 for v in series.values())  # sinks carry no demand
    # At least one non-sink node has positive demand somewhere.
    non_sink_total = sum(
        v for i, nid in enumerate(sub.ids) if not sub.is_sink[i] for v in demand[nid].values()
    )
    assert non_sink_total > 0.0


def test_bikeshare_demand_by_node_default_provider_is_offline_safe():
    """The DEFAULT provider path (no committed slice today) also yields a well-formed
    series via the synthetic fallback — proving the real-data wiring degrades cleanly."""
    from urbanos.kernel.adapters.toronto import reset_bikeshare_demand_cache

    reset_bikeshare_demand_cache()
    sc = downtown_scenario()
    demand = bikeshare_demand_by_node(sc.substrate)  # default provider -> load_counts(bikeshare)
    assert set(demand) == set(sc.substrate.ids)
    assert all(np.isfinite(v) for s in demand.values() for v in s.values())
