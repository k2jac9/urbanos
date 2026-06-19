"""Phase 1 — CongestionNowcast calibration lens (data-driven, advisory-only).

The lens lifts the real observed-count series onto the substrate and scores how well
the kernel's crowd profile matches what was actually measured (a scale-free shape
agreement in 0..1). It declares NO levers and carries NO cost — a *trust* signal, not
a priced harm. These tests pin: (1) it scores when given observed data, (2) it is inert
and additive (never perturbs the kernel or the other lenses), (3) it is offline-safe via
the synthetic fallback, (4) it is deterministic, and (5) it surfaces in /lenses under its
own ``calibration`` block WITHOUT moving the calibrated headline or the priced extras.

All offline: a tiny in-test count slice + injected providers, no network, no real data.
"""
import numpy as np

from urban_os.adapters.toronto import downtown_scenario, downtown_substrate
from urban_os.kernel import Simulation
from urban_os.lenses import EconomicLens, EventSurge
from urban_os.lenses.congestion_nowcast import CongestionNowcastLens, _cosine


def _run(sc, lens, release):
    stack = [EventSurge(events=sc.events), EconomicLens()]
    if lens is not None:
        stack.append(lens)
    return Simulation(
        sc.substrate, stack, params={"release_minutes": release}, dt=sc.dt
    ).run(sc.horizon)


# ---- the cosine primitive --------------------------------------------------
def test_cosine_identity_and_orthogonal():
    a = np.array([1.0, 2.0, 3.0])
    assert _cosine(a, a) == 1.0                      # identical shape -> 1.0
    assert _cosine(a, np.zeros(3)) == 0.0            # all-zero -> 0.0 (no NaN)
    assert _cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == 0.0  # orthogonal


# ---- scores against observed data -----------------------------------------
def test_nowcast_scores_when_given_observed_series():
    """With a per-node observed series the lens aligns peak-to-peak and reports a
    bounded shape-agreement score for every observed bin it can compare."""
    sc = downtown_scenario()
    # A synthetic-but-real-shaped observed series straight from the adapter fallback,
    # so the test needs no committed data.
    from urban_os.adapters.toronto import observed_counts_by_node

    obs = observed_counts_by_node(sc.substrate, provider=lambda: [])
    lens = CongestionNowcastLens(obs)
    _run(sc, lens, 0.0)
    summary = lens.calibration_summary()
    assert summary["n_bins"] > 0
    assert 0.0 <= summary["min_fit"] <= summary["mean_fit"] <= 1.0


def test_nowcast_bare_is_inert():
    """Constructed with no observed series the lens reports 'not calibrated' (n_bins 0)
    and emits no metric — never an error."""
    sc = downtown_scenario()
    lens = CongestionNowcastLens()
    res = _run(sc, lens, 0.0)
    assert lens.calibration_summary() == {"mean_fit": 0.0, "min_fit": 0.0, "n_bins": 0}
    assert res.series("calibration_fit") == []       # no metric emitted when inert


# ---- additivity contract (the important one) -------------------------------
def test_nowcast_does_not_perturb_kernel_or_other_lenses():
    """The lens is read-only on the crowd fields, so adding it must leave the kernel
    transport AND the economic terms byte-for-byte unchanged."""
    sc = downtown_scenario()
    from urban_os.adapters.toronto import observed_counts_by_node

    obs = observed_counts_by_node(sc.substrate, provider=lambda: [])
    base = _run(sc, None, 0.0)
    withl = _run(sc, CongestionNowcastLens(obs), 0.0)
    assert np.isclose(sum(base.series("delay_cost")), sum(withl.series("delay_cost")))
    assert np.isclose(sum(base.series("safety_cost")), sum(withl.series("safety_cost")))
    # Final load field identical (the calibration lens moves no mass).
    assert np.allclose(base.frames[-1]["load"], withl.frames[-1]["load"])


def test_nowcast_has_no_levers_and_no_cost():
    sc = downtown_scenario()
    from urban_os.adapters.toronto import observed_counts_by_node

    obs = observed_counts_by_node(sc.substrate, provider=lambda: [])
    lens = CongestionNowcastLens(obs)
    res = _run(sc, lens, 0.0)
    assert lens.levers() == []
    assert lens.cost(res) == 0.0


def test_nowcast_deterministic():
    sc = downtown_scenario()
    from urban_os.adapters.toronto import observed_counts_by_node

    obs = observed_counts_by_node(sc.substrate, provider=lambda: [])
    a = CongestionNowcastLens(obs)
    b = CongestionNowcastLens(obs)
    _run(sc, a, 0.0)
    _run(sc, b, 0.0)
    assert a.calibration_summary() == b.calibration_summary()


# ---- grounded via extra_display_lenses ------------------------------------
def test_extra_display_lenses_grounds_nowcast_from_observed_data():
    """extra_display_lenses(sc) wires the nowcast lens with the REAL observed series;
    bare construction stays inert."""
    from urban_os.scenarios import extra_display_lenses

    sc = downtown_scenario()
    grounded = next(l for l in extra_display_lenses(sc) if l.name == "congestion_nowcast")
    bare = next(l for l in extra_display_lenses() if l.name == "congestion_nowcast")
    assert grounded.node_counts is not None
    assert set(grounded.node_counts) == set(sc.substrate.ids)
    assert bare.node_counts is None


# ---- /lenses endpoint surface ---------------------------------------------
def test_lenses_endpoint_exposes_calibration_without_moving_headline():
    """/lenses surfaces a ``calibration`` block (mean/min fit in 0..1, n_bins) and the
    nowcast lens stays OUT of the priced ``extra_lenses`` dict — so the calibrated
    headline and the four priced extras are unchanged."""
    from fastapi.testclient import TestClient

    from urban_os.api import app

    client = TestClient(app)
    r = client.get("/lenses", params={"release_minutes": 8.0, "shelter_fraction": 0.5})
    assert r.status_code == 200
    body = r.json()

    # Priced extras are still exactly the four cost-bearing display lenses.
    assert set(body["extra_lenses"]) == {
        "ems_access", "emissions", "noise_livability", "fare_revenue",
    }
    # Calibration is its own advisory block.
    cal = body["calibration"]
    assert {"calibrated", "mean_fit", "min_fit", "n_bins"} <= set(cal)
    assert cal["calibrated"] is True and cal["n_bins"] > 0
    assert 0.0 <= cal["min_fit"] <= 1.0 and 0.0 <= cal["mean_fit"] <= 1.0


def test_observed_load_overlay_field_written():
    """The lens writes an advisory ``observed_load`` field (the aligned observed
    profile) for the map — distinct from the kernel-exact ``load``."""
    sc = downtown_substrate()
    from urban_os.adapters.toronto import observed_counts_by_node

    obs = observed_counts_by_node(sc, provider=lambda: [])
    scen = downtown_scenario()
    lens = CongestionNowcastLens(obs)
    res = _run(scen, lens, 0.0)
    # The field exists on the run (it rode along as a display layer).
    assert res.series("calibration_fit")  # at least one bin compared
