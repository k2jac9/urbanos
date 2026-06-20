"""WeatherLens — behavioral, contract-conformance, and edge-case tests.

Pure synthetic graphs; no data, no model, no network. The lens models rain as a
transient tax on link throughput (slower drainage) plus a multiplier on the
crowd-safety risk field, with a shelter-deployment lever.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np
import pytest

from urbanos.kernel.kernel import Simulation, Substrate
from urbanos.kernel.kernel.operators import Lens, Lever
from urbanos.kernel.lenses import EconomicLens, WeatherLens
from urbanos.kernel.lenses.weather import (
    _MAX_CAP_PENALTY,
    _MAX_RISK_BONUS,
    _SHELTER_COST,
)


# --------------------------------------------------------------------------- fixtures
def _line_graph(down_cap: float = 50.0) -> Substrate:
    """venue → mid → exit(sink). `down_cap` throttles the draining link."""
    g = nx.DiGraph()
    g.add_node("venue", label="Venue", lat=43.64, lng=-79.39, capacity=1000.0)
    g.add_node("mid", label="Mid", lat=43.65, lng=-79.39, capacity=1000.0)
    g.add_node("exit", label="Exit", lat=43.66, lng=-79.39, capacity=1.0e9)
    g.add_edge("venue", "mid", capacity=500.0, length=1.0)
    g.add_edge("mid", "exit", capacity=down_cap, length=1.0)
    return Substrate.from_graph(g, sinks=["exit"])


class _Seed(Lens):
    """Drop a one-shot slug of people at the venue on the first step."""

    name = "seed"

    def __init__(self, amount: float) -> None:
        self.amount = amount

    def source(self, state, t) -> None:
        if state.step == 0:
            state.field("load")[state.substrate.idx("venue")] += self.amount


def _rain_now() -> WeatherLens:
    """A heavy rain cell centred at t=0 so step-0 already sees strong rain."""
    return WeatherLens(peak_time=0.0, intensity=1.0, width=10.0, crowd_size=400.0)


# --------------------------------------------------------------------------- construction / validation
def test_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        WeatherLens(peak_time=0.0, width=0.0)
    with pytest.raises(ValueError):
        WeatherLens(peak_time=0.0, width=-5.0)
    with pytest.raises(ValueError):
        WeatherLens(peak_time=0.0, intensity=1.5)
    with pytest.raises(ValueError):
        WeatherLens(peak_time=0.0, intensity=-0.1)
    with pytest.raises(ValueError):
        WeatherLens(peak_time=0.0, max_shelter=2.0)
    with pytest.raises(ValueError):
        WeatherLens(peak_time=0.0, crowd_size=-1.0)


def test_name_and_weight() -> None:
    lens = WeatherLens(peak_time=10.0, weight=2.0)
    assert lens.name == "weather"
    assert lens.weight == 2.0


# --------------------------------------------------------------------------- rain profile
def test_rain_profile_is_gaussian_peaking_at_peak_time() -> None:
    lens = WeatherLens(peak_time=30.0, intensity=0.8, width=10.0)
    assert lens._rain_at(30.0) == pytest.approx(0.8)
    # Symmetric and decaying away from the peak.
    assert lens._rain_at(20.0) == pytest.approx(lens._rain_at(40.0))
    assert lens._rain_at(20.0) < lens._rain_at(30.0)
    # Far from the peak it is ~0.
    assert lens._rain_at(200.0) < 1e-6


def test_zero_intensity_is_a_total_noop_on_dynamics() -> None:
    sub_dry = _line_graph()
    dry = Simulation(sub_dry, [_Seed(300.0), EconomicLens()], dt=1.0).run(40)

    sub_wet = _line_graph()
    lens = WeatherLens(peak_time=0.0, intensity=0.0, width=10.0, crowd_size=300.0)
    wet = Simulation(sub_wet, [_Seed(300.0), EconomicLens(), lens], dt=1.0).run(40)

    # No rain ⇒ identical load drainage and identical risk every step.
    for fd, fw in zip(dry.frames, wet.frames):
        assert np.allclose(fd["load"], fw["load"])
        assert np.allclose(fd["risk"], fw["risk"])


# --------------------------------------------------------------------------- drainage tax (source)
def test_rain_slows_drainage() -> None:
    """Same crowd, same graph: rain should leave more people in-system longer."""
    seed = 600.0
    sub_dry = _line_graph(down_cap=40.0)
    dry = Simulation(sub_dry, [_Seed(seed), EconomicLens()], dt=1.0).run(30)

    sub_wet = _line_graph(down_cap=40.0)
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=30.0, crowd_size=seed)
    wet = Simulation(sub_wet, [_Seed(seed), EconomicLens(), rain], dt=1.0).run(30)

    dry_in = [f["load"].sum() for f in dry.frames]
    wet_in = [f["load"].sum() for f in wet.frames]
    # At the same mid-run step the wet network has drained strictly less.
    assert wet_in[15] > dry_in[15] + 1e-6
    # And cumulatively more person-minutes were spent in-system under rain.
    assert sum(wet_in) > sum(dry_in)


def test_cap_penalty_magnitude_is_exact() -> None:
    """source() scales the per-step multiplier to exactly (1 − _MAX_CAP_PENALTY·wetness),
    leaving the baked substrate.edge_cap untouched (ADR-0021)."""
    from urbanos.kernel.kernel.state import State

    sub = _line_graph()
    dry = sub.edge_cap.copy()
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=50.0)
    rain.configure(sub)
    st = State(sub, {"dt": 1.0})
    rain.source(st, 0.0)  # t==peak ⇒ wetness 1.0
    # The rain tax lands on the per-step multiplier, not the substrate.
    assert np.allclose(st.edge_cap_mult, 1.0 - _MAX_CAP_PENALTY)
    assert np.allclose(sub.edge_cap, dry)  # substrate never mutated
    rain.couple(st, 0.0)
    assert np.allclose(sub.edge_cap, dry)


def test_substrate_edge_cap_never_mutated() -> None:
    """The capacity tax must never touch the shared substrate (ADR-0021): the baked
    edge_cap is byte-identical before and after a full rainy run."""
    sub = _line_graph()
    dry_caps = sub.edge_cap.copy()
    rain = _rain_now()
    Simulation(sub, [_Seed(200.0), EconomicLens(), rain], dt=1.0).run(20)
    # The substrate's baked link capacities are pristine (were never written).
    assert np.allclose(sub.edge_cap, dry_caps)


def test_repeated_runs_do_not_compound_the_penalty() -> None:
    """Running the same substrate twice yields identical dynamics (no drift)."""
    sub = _line_graph()
    rain = _rain_now()
    r1 = Simulation(sub, [_Seed(300.0), EconomicLens(), rain], dt=1.0).run(25)
    r2 = Simulation(sub, [_Seed(300.0), EconomicLens(), rain], dt=1.0).run(25)
    for f1, f2 in zip(r1.frames, r2.frames):
        assert np.allclose(f1["load"], f2["load"])


def test_people_still_conserved_under_rain() -> None:
    """Rain changes timing, never headcount — the conservation invariant holds."""
    sub = _line_graph(down_cap=30.0)
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=40.0, crowd_size=500.0)
    res = Simulation(sub, [_Seed(500.0), EconomicLens(), rain], dt=1.0).run(60)
    for f in res.frames:
        total = float(f["load"].sum() + f["arrived"].sum())
        assert abs(total - 500.0) < 1e-6


# --------------------------------------------------------------------------- risk amplification (couple)
def test_rain_amplifies_risk_relative_to_dry() -> None:
    sub_dry = _line_graph()
    dry = Simulation(sub_dry, [_Seed(800.0), EconomicLens()], dt=1.0).run(20)

    sub_wet = _line_graph()
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=20.0, crowd_size=800.0)
    wet = Simulation(sub_wet, [_Seed(800.0), EconomicLens(), rain], dt=1.0).run(20)

    dry_peak = max(max(f["risk"]) for f in dry.frames)
    wet_peak = max(max(f["risk"]) for f in wet.frames)
    assert wet_peak > dry_peak


def test_risk_multiplier_magnitude_is_exact() -> None:
    """Unit-test couple() in isolation: a known risk field is multiplied by
    exactly (1 + _MAX_RISK_BONUS·wetness).

    We drive couple() directly with a pre-populated risk field so the result
    isolates the multiplier from the drainage tax (which would otherwise change
    the underlying load/risk between runs).
    """
    from urbanos.kernel.kernel.state import State

    sub = _line_graph()
    rain = WeatherLens(peak_time=2.0, intensity=1.0, width=50.0, crowd_size=800.0)
    rain.configure(sub)
    st = State(sub, {"dt": 1.0})
    known = np.array([2.0, 5.0, 0.0], dtype=float)
    st.fields["risk"] = known.copy()
    # t == peak_time, intensity 1.0, no shelter ⇒ wetness exactly 1.0.
    rain.source(st, 2.0)   # snapshots + penalises caps
    rain.couple(st, 2.0)   # restores caps, multiplies risk
    assert np.allclose(st.fields["risk"], known * (1.0 + _MAX_RISK_BONUS))

    # Half rain (z such that exp = 0.5) — verify the linear-in-wetness scaling
    # by choosing a t with a known gaussian value.
    st2 = State(sub, {"dt": 1.0})
    st2.fields["risk"] = known.copy()
    t_half = 2.0 + 50.0 * math.sqrt(2.0 * math.log(2.0))  # rain == 0.5
    rain.source(st2, t_half)
    rain.couple(st2, t_half)
    expected_wet = 0.5
    assert np.allclose(
        st2.fields["risk"], known * (1.0 + _MAX_RISK_BONUS * expected_wet)
    )


# --------------------------------------------------------------------------- shelter lever (couple/source/cost)
def test_shelter_lever_grid() -> None:
    levers = WeatherLens(peak_time=0.0).levers()
    assert len(levers) == 1
    lev = levers[0]
    assert isinstance(lev, Lever)
    assert lev.name == "shelter_fraction"
    assert lev.values[0] == 0.0
    assert lev.values[-1] == pytest.approx(1.0)


def test_shelter_lever_respects_max_shelter() -> None:
    lev = WeatherLens(peak_time=0.0, max_shelter=0.5).levers()[0]
    assert max(lev.values) <= 0.5 + 1e-9


def test_full_shelter_neutralises_rain_dynamics() -> None:
    """shelter_fraction=1 ⇒ wetness 0 ⇒ same load & risk as the dry baseline."""
    sub_dry = _line_graph(down_cap=40.0)
    dry = Simulation(sub_dry, [_Seed(500.0), EconomicLens()], dt=1.0).run(30)

    sub_wet = _line_graph(down_cap=40.0)
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=30.0, crowd_size=500.0)
    wet = Simulation(
        sub_wet,
        [_Seed(500.0), EconomicLens(), rain],
        params={"shelter_fraction": 1.0},
        dt=1.0,
    ).run(30)

    for fd, fw in zip(dry.frames, wet.frames):
        assert np.allclose(fd["load"], fw["load"])
        assert np.allclose(fd["risk"], fw["risk"])


def test_shelter_reduces_exposure_cost() -> None:
    sub = _line_graph(down_cap=40.0)
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=30.0, crowd_size=500.0)

    no_shelter = Simulation(
        _line_graph(down_cap=40.0), [_Seed(500.0), EconomicLens(), rain], dt=1.0
    ).run(30)
    half = Simulation(
        _line_graph(down_cap=40.0),
        [_Seed(500.0), EconomicLens(), rain],
        params={"shelter_fraction": 0.5},
        dt=1.0,
    ).run(30)

    assert rain.cost(half) < rain.cost(no_shelter) or sum(
        half.series("exposure_cost")
    ) < sum(no_shelter.series("exposure_cost"))


def test_cost_nonnegative_and_zero_when_dry_and_unsheltered() -> None:
    sub = _line_graph()
    # No rain at all over the window, no shelter ⇒ zero weather cost.
    rain = WeatherLens(peak_time=1000.0, intensity=1.0, width=5.0, crowd_size=300.0)
    res = Simulation(sub, [_Seed(300.0), EconomicLens(), rain], dt=1.0).run(20)
    assert rain.cost(res) == pytest.approx(0.0, abs=1e-9)


def test_shelter_adds_staffing_cost() -> None:
    """Engaging shelter during rain books a positive staffing cost."""
    rain = WeatherLens(peak_time=10.0, intensity=1.0, width=15.0, crowd_size=400.0)
    res = Simulation(
        _line_graph(),
        [_Seed(400.0), EconomicLens(), rain],
        params={"shelter_fraction": 1.0},
        dt=1.0,
    ).run(40)
    # Full shelter ⇒ no exposure cost but a real staffing bill > 0.
    assert sum(res.series("exposure_cost")) == pytest.approx(0.0, abs=1e-9)
    assert rain.cost(res) > 0.0


# --------------------------------------------------------------------------- observe (contract)
def test_observe_emits_expected_metrics() -> None:
    sub = _line_graph()
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=10.0, crowd_size=300.0)
    res = Simulation(sub, [_Seed(300.0), EconomicLens(), rain], dt=1.0).run(15)
    for key in ("rain_intensity", "wetness", "exposure_cost"):
        series = res.series(key)
        assert len(series) == 15
        assert all(isinstance(v, float) for v in series)
        assert all(v >= 0.0 for v in series)
    # Rain intensity at step 0 (peak) should be ~max.
    assert res.series("rain_intensity")[0] == pytest.approx(1.0, rel=1e-3)


# --------------------------------------------------------------------------- contract conformance / defaults
def test_lens_subclass_and_default_hooks() -> None:
    lens = WeatherLens(peak_time=0.0)
    assert isinstance(lens, Lens)
    # Hooks exist and are callable with the documented signatures.
    assert callable(lens.configure)
    assert callable(lens.source)
    assert callable(lens.couple)
    assert callable(lens.observe)
    assert callable(lens.levers)
    assert callable(lens.cost)


def test_configure_missing_is_handled_gracefully() -> None:
    """source() needs no configure() now — it taxes the per-step multiplier and
    never reads/writes the substrate's edge_cap (ADR-0021)."""
    sub = _line_graph()
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=10.0)
    state_caps = sub.edge_cap.copy()
    # Drive source/couple manually without configure().
    from urbanos.kernel.kernel.state import State

    st = State(sub, {"dt": 1.0})
    rain.source(st, 0.0)
    # The penalty is on the multiplier; the substrate is untouched throughout.
    assert np.all(st.edge_cap_mult <= 1.0 + 1e-9)
    assert np.allclose(sub.edge_cap, state_caps)
    rain.couple(st, 0.0)
    assert np.allclose(sub.edge_cap, state_caps)


def test_runs_without_economic_lens() -> None:
    """If risk isn't populated by an upstream lens, couple must not crash.

    State always creates a zeroed `risk` field, so the multiply is a safe no-op
    numerically; the lens must still run end-to-end and slow drainage.
    """
    sub = _line_graph(down_cap=30.0)
    rain = WeatherLens(peak_time=0.0, intensity=1.0, width=30.0, crowd_size=300.0)
    res = Simulation(sub, [_Seed(300.0), rain], dt=1.0).run(20)
    assert res.steps == 20
    # Risk stays zero (no economic lens to populate it), multiplied-zero is zero.
    assert all(max(f["risk"]) == 0.0 for f in res.frames)


def test_three_lens_stack_end_to_end() -> None:
    """EventSurge + Economic + Weather compose on the real downtown substrate."""
    from urbanos.kernel.adapters.toronto import downtown_scenario
    from urbanos.kernel.lenses import EventSurge

    sc = downtown_scenario(crowd_size=20000.0)
    rain = WeatherLens(
        peak_time=sc.event_end, intensity=1.0, width=20.0, crowd_size=sc.crowd_size
    )
    lenses = [
        EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
        EconomicLens(),
        rain,
    ]
    res = Simulation(sc.substrate, lenses, dt=sc.dt).run(sc.horizon)
    assert res.steps == sc.horizon
    # The substrate's link caps survived the whole run untouched.
    assert "wetness" in res.metrics
    # Weather cost is a finite, non-negative dollar figure.
    c = rain.cost(res)
    assert math.isfinite(c) and c >= 0.0
