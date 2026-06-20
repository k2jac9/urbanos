"""BusinessFlow lens — the Sports/Business-Flow plugin.

Verifies the cross-domain behaviour (a crush destroys trade; the staggered
release recovers it), the J-term contract, additivity (it must not change the
other lenses), and determinism.
"""
import numpy as np

from urbanos.kernel.adapters import downtown_scenario
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.lenses import BusinessFlow, EconomicLens, EventSurge


def _stack(sc, business):
    ls = [EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end), EconomicLens()]
    if business:
        ls.append(BusinessFlow(sc.venue_id))
    return ls


def _run(sc, release, business=True):
    return Simulation(sc.substrate, _stack(sc, business),
                      params={"release_minutes": release}, dt=sc.dt).run(sc.horizon)


def test_crush_destroys_trade():
    sc = downtown_scenario()
    lost = sum(_run(sc, 0.0).series("business_lost"))
    assert lost > 0.0  # a do-nothing crush wipes out local trade


def test_release_recovers_business():
    """The staggered release that eases the platform crush also recovers trade."""
    sc = downtown_scenario()
    lost_nothing = sum(_run(sc, 0.0).series("business_lost"))
    lost_release = sum(_run(sc, 14.0).series("business_lost"))
    assert lost_release < lost_nothing


def test_cost_equals_lost_series():
    sc = downtown_scenario()
    bf = BusinessFlow(sc.venue_id)
    res = Simulation(sc.substrate,
                     [EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
                      EconomicLens(), bf],
                     params={"release_minutes": 0.0}, dt=sc.dt).run(sc.horizon)
    assert np.isclose(bf.cost(res), sum(res.series("business_lost")))


def test_additive_does_not_perturb_other_lenses():
    """Adding BusinessFlow must not change EconomicLens's delay/safety costs
    (it is read-only on load/congestion/risk)."""
    sc = downtown_scenario()
    without = _run(sc, 0.0, business=False)
    with_biz = _run(sc, 0.0, business=True)
    assert np.isclose(sum(without.series("delay_cost")), sum(with_biz.series("delay_cost")))
    assert np.isclose(sum(without.series("safety_cost")), sum(with_biz.series("safety_cost")))


def test_captured_and_lost_nonnegative():
    sc = downtown_scenario()
    res = _run(sc, 0.0)
    assert min(res.series("business_captured")) >= 0.0
    assert min(res.series("business_lost")) >= 0.0


def test_deterministic():
    sc = downtown_scenario()
    a = sum(_run(sc, 0.0).series("business_lost"))
    b = sum(_run(sc, 0.0).series("business_lost"))
    assert a == b
