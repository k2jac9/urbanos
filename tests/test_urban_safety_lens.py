"""SafetyLens — the civic risk app made literal as a kernel lens.

Verifies the cross-domain behaviour (a crush through a high-civic-risk node costs
public-safety dollars; the staggered release cuts it), the J-term contract,
additivity, the zero-risk degenerate case, determinism, and that the Toronto
adapter's civic→node fusion produces a well-formed overlay.
"""
import numpy as np

from urbanos.kernel.adapters import civic_safety_by_node, downtown_scenario
from urbanos.kernel.adapters.toronto import downtown_substrate
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.lenses import EconomicLens, EventSurge, SafetyLens

# Union is the engineered bottleneck — give its district the civic safety risk.
NODE_RISK = {"union": 1.0, "king": 0.4, "queen": 0.4}


def _stack(sc, node_risk):
    ls = [EventSurge(events=sc.events), EconomicLens()]
    if node_risk is not None:
        ls.append(SafetyLens(node_risk))
    return ls


def _run(sc, release, node_risk=NODE_RISK):
    return Simulation(sc.substrate, _stack(sc, node_risk),
                      params={"release_minutes": release}, dt=sc.dt).run(sc.horizon)


def test_crush_creates_public_safety_exposure():
    sc = downtown_scenario()
    exposure = sum(_run(sc, 0.0).series("civic_exposure"))
    assert exposure > 0.0  # a crush through the high-civic-risk district


def test_release_cuts_safety_exposure():
    sc = downtown_scenario()
    assert sum(_run(sc, 14.0).series("civic_exposure")) < sum(_run(sc, 0.0).series("civic_exposure"))


def test_zero_risk_is_zero_cost():
    """No civic risk → the lens contributes nothing (degenerate, harmless)."""
    sc = downtown_scenario()
    bf = SafetyLens({nid: 0.0 for nid in sc.substrate.ids})
    res = Simulation(sc.substrate,
                     [EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
                      EconomicLens(), bf], params={"release_minutes": 0.0}, dt=sc.dt).run(sc.horizon)
    assert bf.cost(res) == 0.0


def test_cost_scales_with_value_constant():
    sc = downtown_scenario()
    sl = SafetyLens(NODE_RISK)
    res = _run(sc, 0.0)
    from urbanos.kernel.lenses.safety import VALUE_OF_CIVIC_SAFETY
    assert np.isclose(sl.cost(res), VALUE_OF_CIVIC_SAFETY * sum(res.series("civic_exposure")))


def test_additive_does_not_perturb_other_lenses():
    sc = downtown_scenario()
    without = _run(sc, 0.0, node_risk=None)
    withsl = _run(sc, 0.0, node_risk=NODE_RISK)
    assert np.isclose(sum(without.series("delay_cost")), sum(withsl.series("delay_cost")))
    assert np.isclose(sum(without.series("safety_cost")), sum(withsl.series("safety_cost")))


def test_deterministic():
    sc = downtown_scenario()
    assert sum(_run(sc, 0.0).series("civic_exposure")) == sum(_run(sc, 0.0).series("civic_exposure"))


def test_civic_fusion_overlay_well_formed():
    """The adapter's address-risk → node-field fusion (real civic data or the
    deterministic fallback) yields one bounded value per substrate node."""
    sub = downtown_substrate()
    overlay = civic_safety_by_node(sub)
    assert set(overlay) == set(sub.ids)
    assert all(0.0 <= v <= 1.0 and np.isfinite(v) for v in overlay.values())
