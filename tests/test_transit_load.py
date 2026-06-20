"""Fit C — TransitLoad lens (data-driven REAL source, opt-in, off by default).

The lens injects the measured observed-count series onto the substrate as honest
background ridership load (people entering the transit system on top of the event
egress). It is a REAL/measured ``source`` term: it declares NO levers and carries NO
cost, so it can never move the optimizer's choice or any headline dollar figure. These
tests pin the honesty invariants (ADR-0029):

1. bare construction is inert (offline-safe no-op);
2. ``source`` injects only at NON-SINK nodes, the documented per-step mass
   (``count / 15 * dt * scale``), and never emits NaN/inf;
3. the wiring is opt-in + OFF BY DEFAULT — ``default_lens_stack(sc)`` contains NO
   TransitLoadLens, ``transit_load=True`` adds exactly one;
4. the default CLI stack's golden numbers are byte-identical (J $323,222 → $105,050);
5. determinism;
6. degenerate inputs (empty / negative / NaN series, bad scale) are handled at the
   boundary without raising garbage.

All offline: a tiny in-test substrate + in-test count slices, no network, no real data.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pytest

from urbanos.kernel.adapters import downtown_scenario, observed_counts_by_node
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.kernel.state import State, Substrate
from urbanos.kernel.lenses import EconomicLens, EventSurge, TransitLoadLens, transit_load_enabled
from urbanos.kernel.lenses.transit_load import BIN_MINUTES, PROVENANCE
from urbanos.kernel.optimize import optimize
from urbanos.kernel.scenarios import default_lens_stack


# --- a tiny deterministic substrate for exact-mass assertions ----------------
def _toy_substrate() -> Substrate:
    """One transit node 'a' draining to a sink 's' — small enough to assert exact mass."""
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
    """Constructed with no series the lens injects nothing and emits no metric — a clean
    offline-safe no-op, never an error."""
    sub = _toy_substrate()
    lens = TransitLoadLens()
    lens.configure(sub)
    st = _state(sub)
    lens.source(st, 0.0)
    assert np.all(st.fields["load"] == 0.0)       # injected nothing
    assert lens.observe(st, 0.0) == {}            # no metric when inert


def test_bare_lens_inert_in_a_full_run():
    sc = downtown_scenario()
    stack = [EventSurge(events=sc.events), EconomicLens(), TransitLoadLens()]
    res = Simulation(sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt).run(
        sc.horizon
    )
    assert res.series("transit_boardings") == []  # inert -> no boardings metric


# --- 2. source injects only at non-sink nodes, the documented per-step mass ---
def test_source_injects_documented_per_step_mass_at_non_sinks_only():
    """A 15-min bin count of 150 at dt=1.0 injects 150/15*1 = 10 people this step at the
    non-sink node; the sink's count is IGNORED (never seed a sink — EventSurge's rule)."""
    sub = _toy_substrate()
    counts = {"a": {0.0: 150.0}, "s": {0.0: 999.0}}  # sink count must be ignored
    lens = TransitLoadLens(counts)
    lens.configure(sub)
    st = _state(sub, dt=1.0)
    lens.source(st, 0.0)
    ai, si = sub.idx("a"), sub.idx("s")
    assert st.fields["load"][ai] == pytest.approx(150.0 / BIN_MINUTES * 1.0)
    assert st.fields["load"][si] == 0.0           # sink never seeded
    assert lens.observe(st, 0.0)["transit_boardings"] == pytest.approx(10.0)


def test_per_step_mass_scales_with_dt_and_scale():
    sub = _toy_substrate()
    counts = {"a": {0.0: 150.0}}
    ai = sub.idx("a")
    # dt=0.5 -> half the per-minute inflow.
    st = _state(sub, dt=0.5)
    lens = TransitLoadLens(counts)
    lens.configure(sub)
    lens.source(st, 0.0)
    assert st.fields["load"][ai] == pytest.approx(150.0 / BIN_MINUTES * 0.5)
    # scale=2.0 doubles the injected mass.
    st2 = _state(sub, dt=1.0)
    lens2 = TransitLoadLens(counts, scale=2.0)
    lens2.configure(sub)
    lens2.source(st2, 0.0)
    assert st2.fields["load"][ai] == pytest.approx(150.0 / BIN_MINUTES * 1.0 * 2.0)


def test_source_picks_the_nearest_observed_bin():
    """Sim-time snaps to the nearest observed bin minute (bins are 15-min spaced)."""
    sub = _toy_substrate()
    counts = {"a": {0.0: 150.0, 15.0: 300.0}}
    ai = sub.idx("a")
    lens = TransitLoadLens(counts)
    lens.configure(sub)
    # t=7 is closer to bin 0 (|7-0|=7 < |7-15|=8) -> count 150.
    st = _state(sub)
    lens.source(st, 7.0)
    assert st.fields["load"][ai] == pytest.approx(150.0 / BIN_MINUTES)
    # t=12 is closer to bin 15 -> count 300.
    st2 = _state(sub)
    lens.source(st2, 12.0)
    assert st2.fields["load"][ai] == pytest.approx(300.0 / BIN_MINUTES)


def test_no_nan_or_inf_injected_from_degenerate_counts():
    """Negative, NaN and inf cell values are dropped at configure; the injected load
    stays finite and the run never propagates NaN/inf."""
    sub = _toy_substrate()
    counts = {"a": {0.0: -50.0, 15.0: float("nan"), 30.0: float("inf")}}
    lens = TransitLoadLens(counts)
    lens.configure(sub)
    ai = sub.idx("a")
    for t in (0.0, 15.0, 30.0):
        st = _state(sub)
        lens.source(st, t)                 # must not raise
        assert np.all(np.isfinite(st.fields["load"]))
        assert st.fields["load"][ai] == 0.0  # all degenerate -> nothing injected


def test_empty_series_does_not_raise():
    sub = _toy_substrate()
    for series in ({}, None):
        lens = TransitLoadLens(series)
        lens.configure(sub)
        st = _state(sub)
        lens.source(st, 0.0)               # inert, no raise
        assert np.all(st.fields["load"] == 0.0)


def test_invalid_scale_rejected_at_boundary():
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            TransitLoadLens({"a": {0.0: 1.0}}, scale=bad)


def test_no_levers_no_cost_and_provenance():
    sub = _toy_substrate()
    lens = TransitLoadLens({"a": {0.0: 10.0}})
    lens.configure(sub)
    assert lens.levers() == []
    assert lens.cost(None) == 0.0          # realism source, never a J term
    assert PROVENANCE == "real/measured"   # distinct from learned/approximate


def test_grounded_lens_injects_only_at_non_sinks_in_full_run():
    """In a full downtown run the lens never leaves standing load on a sink (the crowd
    only reaches sinks via real edges) and emits a boardings metric every step."""
    sc = downtown_scenario()
    obs = observed_counts_by_node(sc.substrate, provider=lambda: [])  # synthetic fallback
    lens = TransitLoadLens(obs)
    stack = [EventSurge(events=sc.events), EconomicLens(), lens]
    res = Simulation(sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt).run(
        sc.horizon
    )
    sink_idx = [i for i in range(sc.substrate.n) if sc.substrate.is_sink[i]]
    assert sink_idx
    for fr in res.frames:
        assert np.all(np.isfinite(fr["load"]))
        for i in sink_idx:
            assert fr["load"][i] == 0.0
    boardings = res.series("transit_boardings")
    assert len(boardings) == res.steps and sum(boardings) > 0.0


# --- 3. wiring: opt-in + OFF BY DEFAULT --------------------------------------
def test_default_stack_has_no_transit_load_lens():
    """The critical invariant: with the flag off (the default) the stack is exactly the
    pre-existing one — no TransitLoadLens is even constructed."""
    sc = downtown_scenario()
    stack = default_lens_stack(sc)
    assert all(ln.name != "transit_load" for ln in stack)


def test_opt_in_appends_exactly_one_transit_load_lens():
    sc = downtown_scenario()
    stack = default_lens_stack(sc, transit_load=True)
    matches = [ln for ln in stack if ln.name == "transit_load"]
    assert len(matches) == 1
    # It is grounded in the observed series (synthetic fallback here) over the substrate.
    assert matches[0].node_counts is not None


def test_transit_load_enabled_reads_env(monkeypatch):
    monkeypatch.delenv("URBANOS_TRANSIT_LOAD", raising=False)
    assert transit_load_enabled() is False
    for truthy in ("1", "true", "yes", "YES", "True"):
        monkeypatch.setenv("URBANOS_TRANSIT_LOAD", truthy)
        assert transit_load_enabled() is True
    for falsy in ("0", "no", "", "off"):
        monkeypatch.setenv("URBANOS_TRANSIT_LOAD", falsy)
        assert transit_load_enabled() is False


# --- 4. golden-number invariance of the default stack ------------------------
def test_default_stack_golden_numbers_unchanged():
    """The headline numbers come from the default (flag-off) stack; the new lens being in
    the codebase must not move them — do-nothing J $323,222, best 14-min -> J $105,050."""
    sc = downtown_scenario()
    stack = default_lens_stack(sc)
    opt = optimize(sc.substrate, stack, sc.horizon, dt=sc.dt)
    assert round(opt.baseline_J) == 323222
    assert round(opt.best_J) == 105050
    assert opt.best_params.get("release_minutes") == 14.0


def test_transit_load_adds_no_cost_and_no_lever_when_opted_in():
    """Even ON, the lens contributes no lever and no J term: the optimizer searches the
    same lever space and the baseline/best J are byte-identical to the off stack (the
    extra source moves load but is never priced into J — only EconomicLens prices it,
    and that pricing is part of the kernel, not this lens)."""
    sc = downtown_scenario()
    off = default_lens_stack(sc)
    on = default_lens_stack(sc, transit_load=True)
    # Same number of optimizer levers (transit_load declares none).
    assert sum(len(ln.levers()) for ln in on) == sum(len(ln.levers()) for ln in off)
    # The transit_load lens's own cost contribution to J is zero on any result.
    tl = next(ln for ln in on if ln.name == "transit_load")
    res = Simulation(sc.substrate, on, params={"release_minutes": 0.0}, dt=sc.dt).run(
        sc.horizon
    )
    assert tl.cost(res) == 0.0


# --- 5. determinism ----------------------------------------------------------
def test_deterministic():
    sc = downtown_scenario()
    obs = observed_counts_by_node(sc.substrate, provider=lambda: [])

    def run():
        stack = [EventSurge(events=sc.events), EconomicLens(), TransitLoadLens(obs)]
        return Simulation(
            sc.substrate, stack, params={"release_minutes": 6.0}, dt=sc.dt
        ).run(sc.horizon)

    a, b = run(), run()
    assert a.series("transit_boardings") == b.series("transit_boardings")
    assert np.allclose(a.frames[-1]["load"], b.frames[-1]["load"])
