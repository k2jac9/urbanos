"""Contract tests for the four new domain lenses (EMS-access, emissions,
noise/livability, fare-revenue).

Each mirrors the SafetyLens contract: a crush creates the new exposure, the
staggered-release lever cuts it, the J term scales with its value constant, the
lens is additive (it must not perturb the existing economic terms), and runs are
deterministic.
"""
import numpy as np

from urbanos.kernel.adapters.toronto import downtown_scenario
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.lenses import EconomicLens, EventSurge
from urbanos.kernel.lenses.ems_access import EmsAccessLens, VALUE_OF_EMS_DELAY
from urbanos.kernel.lenses.emissions import EmissionsLens, SOCIAL_COST_PER_KG
from urbanos.kernel.lenses.noise_livability import NoiseLivabilityLens, VALUE_OF_QUIET
from urbanos.kernel.lenses.fare_revenue import FareRevenueLens, FARE, ABANDON_FRACTION


def _run(sc, lens, release):
    stack = [EventSurge(events=sc.events), EconomicLens()]
    if lens is not None:
        stack.append(lens)
    return Simulation(sc.substrate, stack,
                      params={"release_minutes": release}, dt=sc.dt).run(sc.horizon)


# ---- EMS-access -----------------------------------------------------------
def test_ems_crush_creates_exposure_release_cuts_it():
    sc = downtown_scenario()
    crush = sum(_run(sc, EmsAccessLens(), 0.0).series("ems_exposure"))
    eased = sum(_run(sc, EmsAccessLens(), 14.0).series("ems_exposure"))
    assert crush > 0.0 and eased < crush


def test_ems_cost_scales_with_constant():
    sc = downtown_scenario()
    lens = EmsAccessLens()
    res = _run(sc, lens, 0.0)
    assert np.isclose(lens.cost(res), VALUE_OF_EMS_DELAY * sum(res.series("ems_exposure")))


# ---- Emissions ------------------------------------------------------------
def test_emissions_crush_creates_kg_release_cuts_it():
    sc = downtown_scenario()
    crush = sum(_run(sc, EmissionsLens(), 0.0).series("emissions_kg"))
    eased = sum(_run(sc, EmissionsLens(), 14.0).series("emissions_kg"))
    assert crush > 0.0 and eased < crush


def test_emissions_cost_scales_with_constant():
    sc = downtown_scenario()
    lens = EmissionsLens()
    res = _run(sc, lens, 0.0)
    assert np.isclose(lens.cost(res), SOCIAL_COST_PER_KG * sum(res.series("emissions_kg")))


# ---- Noise / livability ---------------------------------------------------
def test_noise_crush_creates_exposure_release_cuts_it():
    sc = downtown_scenario()
    crush = sum(_run(sc, NoiseLivabilityLens(), 0.0).series("noise_exposure"))
    eased = sum(_run(sc, NoiseLivabilityLens(), 14.0).series("noise_exposure"))
    assert crush > 0.0 and eased < crush


def test_noise_zero_residential_is_zero_cost():
    sc = downtown_scenario()
    lens = NoiseLivabilityLens({nid: 0.0 for nid in sc.substrate.ids})
    res = _run(sc, lens, 0.0)
    assert lens.cost(res) == 0.0


# ---- Fare-revenue ---------------------------------------------------------
def test_fare_peak_backlog_release_recovers_revenue():
    sc = downtown_scenario()
    crush = FareRevenueLens().cost(_run(sc, FareRevenueLens(), 0.0))
    eased = FareRevenueLens().cost(_run(sc, FareRevenueLens(), 14.0))
    assert crush > 0.0 and eased < crush


def test_fare_cost_scales_with_constants():
    sc = downtown_scenario()
    lens = FareRevenueLens()
    res = _run(sc, lens, 0.0)
    peak = max(res.series("fare_in_system"))
    assert np.isclose(lens.cost(res), FARE * ABANDON_FRACTION * peak)


# ---- Additivity contract (the important one) ------------------------------
def test_new_lenses_do_not_perturb_economic_terms():
    sc = downtown_scenario()
    base = _run(sc, None, 0.0)
    for lens in (EmsAccessLens(), EmissionsLens(), NoiseLivabilityLens(), FareRevenueLens()):
        withl = _run(sc, lens, 0.0)
        assert np.isclose(sum(base.series("delay_cost")), sum(withl.series("delay_cost")))
        assert np.isclose(sum(base.series("safety_cost")), sum(withl.series("safety_cost")))


def test_deterministic():
    sc = downtown_scenario()
    a = sum(_run(sc, EmsAccessLens(), 0.0).series("ems_exposure"))
    b = sum(_run(sc, EmsAccessLens(), 0.0).series("ems_exposure"))
    assert a == b


# ---- /lenses endpoint surface + headline regression ------------------------
def test_lenses_endpoint_exposes_extra_lenses_without_moving_headline():
    """/lenses must surface all four supplementary lenses AND leave the calibrated
    headline (combined_cost / cross_domain_benefit) byte-for-byte unchanged — the
    extras ride along in the sims but are excluded from J."""
    from fastapi.testclient import TestClient

    from urbanos.kernel.api import app
    from urbanos.kernel.kernel import Simulation
    from urbanos.kernel.services import four_lens_J, four_lens_stack

    client = TestClient(app)
    r = client.get("/lenses", params={"release_minutes": 8.0, "shelter_fraction": 0.5})
    assert r.status_code == 200
    body = r.json()

    extra = body["extra_lenses"]
    assert set(extra) == {"ems_access", "emissions", "noise_livability", "fare_revenue"}
    for name, e in extra.items():
        assert {"label", "baseline_cost", "optimized_cost", "saved", "metric"} <= set(e)
        # The intervention should not make any additive harm term worse.
        assert e["saved"] >= 0.0 or name == "fare_revenue"

    # Regression: headline combined_cost == four-lens-only J (extras excluded).
    sc = downtown_scenario()
    stack = four_lens_stack(sc)
    res = Simulation(sc.substrate, stack,
                     params={"release_minutes": 8.0, "shelter_fraction": 0.5},
                     dt=sc.dt).run(sc.horizon)
    assert body["combined_cost"] == round(four_lens_J(stack, res), 2)


# ---- noise lens real-data grounding (Activity overlay) --------------------
def test_civic_activity_overlay_well_formed():
    """The adapter's Activity-index → node-field fusion yields one bounded value per
    node (mirrors the civic-safety fusion contract)."""
    from urbanos.kernel.adapters import civic_activity_by_node
    from urbanos.kernel.adapters.toronto import downtown_substrate

    sub = downtown_substrate()
    overlay = civic_activity_by_node(sub)
    assert set(overlay) == set(sub.ids)
    assert all(np.isfinite(v) for v in overlay.values())


def test_extra_display_lenses_grounds_noise_from_real_data():
    """extra_display_lenses(sc) grounds NoiseLivabilityLens in the real Activity
    overlay; bare construction stays synthetic."""
    from urbanos.kernel.scenarios import extra_display_lenses

    sc = downtown_scenario()
    grounded = next(l for l in extra_display_lenses(sc) if l.name == "noise_livability")
    bare = next(l for l in extra_display_lenses() if l.name == "noise_livability")
    assert grounded.node_residential is not None
    assert set(grounded.node_residential) == set(sc.substrate.ids)
    assert bare.node_residential is None


# ---- /overlays endpoint (map heat layers) ---------------------------------
def test_overlays_endpoint_returns_normalized_node_fields():
    from fastapi.testclient import TestClient

    from urbanos.kernel.api import app

    client = TestClient(app)
    r = client.get("/overlays")
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    assert len(nodes) > 0
    for o in nodes:
        assert {
            "id", "lat", "lng", "ems_access", "residential", "emissions", "bike_demand"
        } <= set(o)
        for k in ("ems_access", "residential", "emissions", "bike_demand"):
            assert 0.0 <= o[k] <= 1.0
    # normalised 0..1 → each field peaks at exactly 1.0 on its hottest node. (The
    # MobilityDemand overlay runs on a synthetic fallback in tests, so it too has a
    # nonzero peak; it returns all-zeros gracefully only when the lens is inert.)
    for k in ("ems_access", "residential", "emissions", "bike_demand"):
        assert max(o[k] for o in nodes) == 1.0
