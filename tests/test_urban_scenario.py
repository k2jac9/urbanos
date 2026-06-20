"""P0 end-to-end: the downtown egress scenario behaves like the pitch.

- the crowd funnels through Union (the modelled bottleneck);
- a staggered release lowers both peak platform density and the delay dollars,
  while conserving the crowd (same people, spread over a wider window).
No data, no model, no network — deterministic.
"""
from __future__ import annotations

from urbanos.kernel.adapters import downtown_scenario
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.lenses import EconomicLens, EventSurge


def _run(release_minutes: float):
    sc = downtown_scenario()
    lenses = [
        EventSurge(events=sc.events),
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


def test_event_surge_never_seeds_people_into_sinks() -> None:
    """The egress wave is seeded by spatial proximity, which used to inject people
    DIRECTLY into nearby sinks — an exit pin would then carry a slug of load that
    never drained: the drawn graph did not equal the simulated routing. With the
    fix, sink nodes carry zero standing LOAD every step (the crowd only ever
    reaches them via real edges, where it is absorbed into ``arrived``)."""
    sc, res = _run(0.0)
    sub = sc.substrate
    sink_idx = [i for i in range(sub.n) if sub.is_sink[i]]
    assert sink_idx, "scenario must have exit sinks"
    for fr in res.frames:
        for i in sink_idx:
            assert fr["load"][i] == 0.0  # no standing load ever sits on a sink
