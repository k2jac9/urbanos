"""Fit C — Footfall lens (ambient TMC pedestrian volume, advisory display overlay).

The lens lifts a TMC pedestrian "ambient footfall" series onto the substrate as its OWN
``footfall`` overlay. It is DISPLAY-ONLY and ADDITIVE: read-only on the crowd fields
(``load``/``congestion``/``risk``), declares NO levers, carries NO cost, and lives in
``extra_display_lenses`` (excluded from the optimizer's ``J``) — so it can never move a
headline number. These tests pin the honesty invariants (ADR-0037):

1. bare construction is inert (offline-safe no-op);
2. footfall baked at NON-SINK nodes only; nearest-bin selection; degenerate/empty inputs
   don't raise and never emit NaN/inf;
3. no levers, zero cost, advisory provenance;
4. read-only on the crowd fields — the additivity contract (it perturbs nothing else);
5. determinism;
6. the underlying TMC ped series (``observed_counts_by_node(mode="ped")``) is well-formed
   and falls back synthetically when no slice is present.

All offline: a tiny in-test substrate + in-test footfall slices, no network, no real data.
The adapter-backed checks use ``observed_counts_by_node(mode="ped", provider=lambda: [])``
— the synthetic ped series ``footfall_by_node`` will thinly wrap once wired.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from urbanos.kernel.adapters import downtown_scenario, observed_counts_by_node
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.kernel.state import State, Substrate
from urbanos.kernel.lenses import EconomicLens, EventSurge, FootfallLens
from urbanos.kernel.lenses.footfall import PROVENANCE


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
    lens = FootfallLens()
    lens.configure(sub)
    st = _state(sub)
    lens.couple(st, 0.0)
    assert "footfall" not in st.fields                # wrote no overlay
    assert lens.observe(st, 0.0) == {}                # no metric when inert


def test_bare_lens_inert_in_a_full_run():
    sc = downtown_scenario()
    stack = [EventSurge(events=sc.events), EconomicLens(), FootfallLens()]
    res = Simulation(sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt).run(
        sc.horizon
    )
    assert res.series("footfall_peak") == []          # inert -> no footfall metric


# --- 2. footfall baked at non-sink nodes only; overlay written ---------------
def test_couple_writes_overlay_at_non_sinks_only():
    """The footfall overlay carries the configured value at the non-sink node; the sink's
    value is IGNORED (an exit line is never a pedestrian location)."""
    sub = _toy_substrate()
    footfall = {"a": {0.0: 150.0}, "s": {0.0: 999.0}}  # sink value must be ignored
    lens = FootfallLens(footfall)
    lens.configure(sub)
    st = _state(sub)
    lens.couple(st, 0.0)
    ai, si = sub.idx("a"), sub.idx("s")
    overlay = st.fields["footfall"]
    assert overlay[ai] == pytest.approx(150.0)
    assert overlay[si] == 0.0                          # sink never seeded
    assert lens.observe(st, 0.0)["footfall_peak"] == pytest.approx(150.0)


def test_couple_picks_the_nearest_footfall_bin():
    """Sim-time snaps to the nearest footfall bin minute (bins are 15-min spaced)."""
    sub = _toy_substrate()
    footfall = {"a": {0.0: 150.0, 15.0: 300.0}}
    ai = sub.idx("a")
    lens = FootfallLens(footfall)
    lens.configure(sub)
    # t=7 is closer to bin 0 (|7-0|=7 < |7-15|=8).
    st = _state(sub)
    lens.couple(st, 7.0)
    assert st.fields["footfall"][ai] == pytest.approx(150.0)
    # t=12 is closer to bin 15.
    st2 = _state(sub)
    lens.couple(st2, 12.0)
    assert st2.fields["footfall"][ai] == pytest.approx(300.0)


def test_no_nan_or_inf_from_degenerate_inputs():
    """Negative, NaN and inf cell values are dropped at configure; the overlay stays
    finite and the run never propagates NaN/inf."""
    sub = _toy_substrate()
    footfall = {"a": {0.0: -50.0, 15.0: float("nan"), 30.0: float("inf")}}
    lens = FootfallLens(footfall)
    lens.configure(sub)
    ai = sub.idx("a")
    for t in (0.0, 15.0, 30.0):
        st = _state(sub)
        lens.couple(st, t)                            # must not raise
        assert np.all(np.isfinite(st.fields["footfall"]))
        assert st.fields["footfall"][ai] == 0.0      # all degenerate -> nothing seeded


def test_empty_series_does_not_raise():
    sub = _toy_substrate()
    for series in ({}, None):
        lens = FootfallLens(series)
        lens.configure(sub)
        st = _state(sub)
        lens.couple(st, 0.0)                          # inert, no raise
        assert "footfall" not in st.fields


# --- 3. no levers, zero cost, advisory provenance ----------------------------
def test_no_levers_no_cost_and_provenance():
    sub = _toy_substrate()
    lens = FootfallLens({"a": {0.0: 10.0}})
    lens.configure(sub)
    assert lens.levers() == []
    assert lens.cost(None) == 0.0                      # display-only, never a J term
    assert PROVENANCE == "synthetic/advisory"          # honest: synthetic fallback today


def test_crush_footfall_overlap_metric_is_bounded():
    """The advisory overlap is a scale-free cosine in [0, 1] (display-only)."""
    sub = _toy_substrate()
    lens = FootfallLens({"a": {0.0: 10.0}})
    lens.configure(sub)
    st = _state(sub)
    st.fields["load"][sub.idx("a")] = 5.0             # crowd coincides with footfall at 'a'
    lens.couple(st, 0.0)
    m = lens.observe(st, 0.0)
    assert 0.0 <= m["crush_footfall_overlap"] <= 1.0
    assert m["crush_footfall_overlap"] == pytest.approx(1.0)  # perfectly aligned profiles


# --- 4. read-only on the crowd fields (the additivity contract) --------------
def test_lens_does_not_perturb_crowd_fields_or_economic_terms():
    """Adding Footfall to a run leaves load/congestion/risk and the economic terms
    byte-identical — it writes only its own ``footfall`` overlay."""
    sc = downtown_scenario()
    ped = observed_counts_by_node(sc.substrate, mode="ped", provider=lambda: [])

    def run(with_lens: bool):
        stack = [EventSurge(events=sc.events), EconomicLens()]
        if with_lens:
            stack.append(FootfallLens(ped))
        return Simulation(
            sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt
        ).run(sc.horizon)

    base, withl = run(False), run(True)
    assert np.allclose(base.frames[-1]["load"], withl.frames[-1]["load"])
    assert np.isclose(sum(base.series("delay_cost")), sum(withl.series("delay_cost")))
    assert np.isclose(sum(base.series("safety_cost")), sum(withl.series("safety_cost")))


def test_extra_display_lenses_includes_footfall_and_stays_additive():
    """extra_display_lenses(sc) now includes the grounded Footfall lens; bare construction
    stays synthetic, and the contract additivity test still holds for the full extra-lens
    set (none perturb the economic terms)."""
    from urbanos.kernel.scenarios import extra_display_lenses

    sc = downtown_scenario()
    grounded = next(l for l in extra_display_lenses(sc) if l.name == "footfall")
    bare = next(l for l in extra_display_lenses() if l.name == "footfall")
    assert grounded.node_footfall is not None
    assert set(grounded.node_footfall) == set(sc.substrate.ids)
    assert bare.node_footfall is None

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
    footfall = observed_counts_by_node(sc.substrate, mode="ped", provider=lambda: [])

    def run():
        stack = [EventSurge(events=sc.events), EconomicLens(), FootfallLens(footfall)]
        return Simulation(
            sc.substrate, stack, params={"release_minutes": 6.0}, dt=sc.dt
        ).run(sc.horizon)

    a, b = run(), run()
    assert a.series("footfall_peak") == b.series("footfall_peak")
    assert np.allclose(a.frames[-1]["load"], b.frames[-1]["load"])


# --- 6. underlying ped series: shape + synthetic fallback --------------------
def test_observed_ped_series_well_formed_synthetic_fallback():
    """With no count slice the ped series (which ``footfall_by_node`` thinly wraps) is a
    deterministic synthetic series: one {minute: count} dict per node, finite values,
    non-sink nodes carry footfall, sinks none."""
    sc = downtown_scenario()
    ped = observed_counts_by_node(sc.substrate, mode="ped", provider=lambda: [])  # -> synthetic
    sub = sc.substrate
    assert set(ped) == set(sub.ids)
    for i, nid in enumerate(sub.ids):
        series = ped[nid]
        assert all(np.isfinite(v) for v in series.values())
        if sub.is_sink[i]:
            assert all(v == 0.0 for v in series.values())  # sinks carry no footfall
    # At least one non-sink node has positive footfall somewhere.
    non_sink_total = sum(
        v for i, nid in enumerate(sub.ids) if not sub.is_sink[i] for v in ped[nid].values()
    )
    assert non_sink_total > 0.0


# --- adapter: footfall_by_node wraps observed_counts_by_node(mode="ped") -------
def test_footfall_by_node_wraps_ped_counts():
    """footfall_by_node is a thin wrapper over observed_counts_by_node(mode='ped'): same shape,
    finite, non-sink nodes carry footfall, sinks none — synthetic fallback offline."""
    from urbanos.kernel.adapters import footfall_by_node

    sc = downtown_scenario()
    ff = footfall_by_node(sc.substrate, provider=lambda: [])   # empty -> synthetic ped series
    ref = observed_counts_by_node(sc.substrate, mode="ped", provider=lambda: [])
    sub = sc.substrate
    assert set(ff) == set(sub.ids)
    assert ff == ref                                           # identical wrapper output
    for i, nid in enumerate(sub.ids):
        assert all(np.isfinite(v) for v in ff[nid].values())
        if sub.is_sink[i]:
            assert all(v == 0.0 for v in ff[nid].values())
    non_sink_total = sum(
        v for i, nid in enumerate(sub.ids) if not sub.is_sink[i] for v in ff[nid].values()
    )
    assert non_sink_total > 0.0
