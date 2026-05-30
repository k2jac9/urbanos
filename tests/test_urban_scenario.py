"""P0 end-to-end: the downtown egress scenario behaves like the pitch.

- the crowd funnels through Union (the modelled bottleneck);
- a staggered release lowers both peak platform density and the delay dollars,
  while conserving the crowd (same people, spread over a wider window).
No data, no model, no network — deterministic.
"""
from __future__ import annotations

from urban_os.adapters import downtown_scenario
from urban_os.kernel import Simulation
from urban_os.lenses import EconomicLens, EventSurge


def _run(release_minutes: float):
    sc = downtown_scenario()
    lenses = [
        EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
        EconomicLens(),
    ]
    sim = Simulation(
        sc.substrate,
        lenses,
        params={"release_minutes": release_minutes},
        dt=sc.dt,
    )
    return sc, sim.run(sc.horizon)


def test_union_is_the_bottleneck() -> None:
    _, res = _run(0.0)
    peak = res.peak_congestion()
    assert peak["node"] == "union", f"expected Union, got {peak}"
    assert peak["congestion"] > 1.0  # over capacity — a real crush forms


def test_staggered_release_reduces_peak_and_cost() -> None:
    _, base = _run(0.0)
    _, staggered = _run(12.0)
    assert staggered.peak_congestion()["congestion"] < base.peak_congestion()["congestion"]
    base_cost = sum(base.series("delay_cost"))
    stag_cost = sum(staggered.series("delay_cost"))
    assert stag_cost < base_cost
    assert base_cost > 0.0


def test_crowd_conserved_regardless_of_lever() -> None:
    sc, base = _run(0.0)
    _, staggered = _run(12.0)
    # Everyone who entered the system eventually arrives at a sink; the final
    # cumulative arrivals match the crowd (within the Gaussian's tail truncation).
    for res in (base, staggered):
        arrived = res.frames[-1]["arrived"].sum()
        assert arrived > 0.9 * sc.crowd_size
