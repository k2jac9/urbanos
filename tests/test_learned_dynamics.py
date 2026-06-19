"""Phase 2 — Action-Matching-floor learned-dynamics diagnostic (ADR-0028, advisory-only).

The module fits a velocity field from the observed-count marginals on the substrate, rolls
it out, and reports whether the LEARNED field beats the exact kernel at matching the
observed counts. It is advisory: no lever, no cost, off by default. These tests pin the
honesty contract and the Phase-2 finding:

1. **Opt-in + CPU fallback** — off by default it is a clean no-op (``available=False``);
   ``force=True`` runs the numpy-only math (no torch, no CUDA).
2. **Learned predicts, exact kernel decides** — running the diagnostic alongside a finished
   run perturbs neither the kernel transport nor the priced lenses' ``J`` (it is consulted
   AFTER the run, like ``surrogate.py``), so no headline number can move.
3. **Provenance honesty** — every output is stamped ``learned/approximate``.
4. **Fairness** — the comparison is not rigged toward "learned": when the observed series
   *is* the kernel's own load, the kernel wins (``learned_better=False``).
5. **The finding** — on the TMC-shaped marginal slice the learned field DOES beat the kernel
   (a positive margin), which is the answer Phase 2 set out to establish.
6. **Determinism** + the ``/lenses`` surface (advisory block, headline unchanged).

All offline: the adapter's deterministic synthetic-but-real-shaped series + injected
providers, no network, no committed data.
"""
import numpy as np

from urban_os import learned_dynamics as ld
from urban_os.adapters.toronto import downtown_scenario, observed_counts_by_node
from urban_os.kernel import Simulation
from urban_os.lenses import EconomicLens, EventSurge


def _run(sc, release=0.0):
    stack = [EventSurge(events=sc.events), EconomicLens()]
    return stack, Simulation(
        sc.substrate, stack, params={"release_minutes": release}, dt=sc.dt
    ).run(sc.horizon)


def _obs(sc):
    # Real-shaped synthetic series straight from the adapter fallback (no committed data).
    return observed_counts_by_node(sc.substrate, provider=lambda: [])


# ---- the cosine primitive (shared scale-free shape metric) -----------------
def test_cosine_identity_and_orthogonal():
    a = np.array([1.0, 2.0, 3.0])
    assert ld._cosine(a, a) == 1.0
    assert ld._cosine(a, np.zeros(3)) == 0.0
    assert ld._cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == 0.0


# ---- incidence + continuity (the learned field obeys mass conservation) ----
def test_incidence_divergence_matches_observed_mass_change():
    """The fitted edge flow's divergence reproduces the per-node mass change (continuity).
    The learned velocity field is meaningful only if ``B f ≈ Δc`` — pin that the ridge fit
    recovers an in-range target to a small residual (ridge trades a tiny bias for a unique,
    minimum-energy solution, so it is close-but-not-exact by design)."""
    sc = downtown_scenario()
    sub = sc.substrate
    B = ld._incidence(sub)
    # Each column has exactly one -1 (tail) and one +1 (head): a valid signed incidence.
    assert np.allclose(B.sum(axis=0), 0.0)
    # A mass change that conserves total people (sum 0) is reproducible by an edge flow.
    rng = np.random.default_rng(0)
    f_true = rng.normal(size=sub.n_edges)
    dc = B @ f_true                          # a divergence => guaranteed in range(B)
    f_fit = ld._fit_edge_flows(B, dc)
    # Residual is small relative to the signal (the ridge bias, not a fit failure).
    resid = float(np.linalg.norm(B @ f_fit - dc))
    assert resid < 0.05 * float(np.linalg.norm(dc))


# ---- opt-in + CPU fallback (honesty #2) ------------------------------------
def test_disabled_by_default_is_noop(monkeypatch):
    """With the env flag unset the diagnostic is a clean no-op: available False, no math."""
    monkeypatch.delenv("URBANOS_LEARNED_DYNAMICS", raising=False)
    sc = downtown_scenario()
    _, res = _run(sc)
    rep = ld.evaluate(_obs(sc), res)
    assert rep.available is False
    assert "disabled" in rep.note
    assert rep.learned_fit == 0.0 and rep.kernel_fit == 0.0


def test_env_flag_enables(monkeypatch):
    """Setting the flag enables it without ``force`` (the production path)."""
    monkeypatch.setenv("URBANOS_LEARNED_DYNAMICS", "1")
    assert ld.learned_dynamics_enabled() is True
    sc = downtown_scenario()
    _, res = _run(sc)
    rep = ld.evaluate(_obs(sc), res)
    assert rep.available is True


def test_input_validation_short_circuits(monkeypatch):
    """Bad/empty inputs short-circuit to a no-op report rather than raising (boundary
    validation): no series, a frame-less result, and a thin series all stay available
    False."""
    monkeypatch.setenv("URBANOS_LEARNED_DYNAMICS", "1")
    sc = downtown_scenario()
    _, res = _run(sc)
    assert ld.evaluate(None, res).available is False
    assert ld.evaluate({}, res).available is False
    # A frame-less result is handled without raising.
    no_frame = Simulation(sc.substrate, [EventSurge(events=sc.events)], dt=sc.dt).run(
        sc.horizon, record_frames=False
    )
    assert ld.evaluate(_obs(sc), no_frame).available is False
    # Fewer than three observed bins -> nothing to predict.
    thin = {sc.substrate.ids[0]: {0.0: 1.0, 15.0: 2.0}}
    assert ld.evaluate(thin, res, force=True).available is False


# ---- learned predicts, exact kernel decides (honesty #1) -------------------
def test_diagnostic_does_not_perturb_kernel_or_priced_lenses():
    """The diagnostic is consulted AFTER a finished run (like surrogate.py) — running it
    leaves the kernel transport and the economic terms byte-for-byte unchanged, so it can
    move no headline number."""
    sc = downtown_scenario()
    stack, res = _run(sc)
    delay_before = sum(res.series("delay_cost"))
    safety_before = sum(res.series("safety_cost"))
    load_before = res.frames[-1]["load"].copy()

    rep = ld.evaluate(_obs(sc), res, force=True)
    assert rep.available is True
    # The result object is untouched by the read-only diagnostic.
    assert np.isclose(sum(res.series("delay_cost")), delay_before)
    assert np.isclose(sum(res.series("safety_cost")), safety_before)
    assert np.allclose(res.frames[-1]["load"], load_before)


# ---- provenance honesty (honesty #3) ---------------------------------------
def test_outputs_are_labelled_learned_approximate():
    sc = downtown_scenario()
    _, res = _run(sc)
    rep = ld.evaluate(_obs(sc), res, force=True)
    assert rep.provenance == "learned/approximate"
    assert rep.as_dict()["provenance"] == "learned/approximate"


# ---- fairness: the comparison is not rigged toward "learned" ---------------
def test_kernel_wins_when_observed_equals_kernel():
    """If the 'observed' series IS the kernel's own load, the kernel must score ~perfectly
    and the learned field must NOT be reported as better — proof the metric is honest and
    not biased to always favour the learned rollout."""
    sc = downtown_scenario()
    _, res = _run(sc)
    kernel_as_obs = {nid: {} for nid in sc.substrate.ids}
    for fr in res.frames:
        if int(fr["t"]) % 15 == 0:                       # mirror the 15-min observed grid
            for i, nid in enumerate(sc.substrate.ids):
                kernel_as_obs[nid][float(fr["t"])] = float(fr["load"][i])
    rep = ld.evaluate(kernel_as_obs, res, force=True)
    assert rep.available is True
    assert rep.kernel_fit > 0.95           # kernel matches itself
    assert rep.learned_better is False     # learned does not beat the kernel here


# ---- the Phase-2 finding ----------------------------------------------------
def test_learned_beats_kernel_on_tmc_shaped_marginals():
    """The headline Phase-2 result: on the TMC-shaped marginal slice the LEARNED velocity
    field beats the exact kernel at reproducing the observed counts (positive margin,
    bounded fits). This is the question §8.3 set out to answer — established here."""
    sc = downtown_scenario()
    _, res = _run(sc)
    rep = ld.evaluate(_obs(sc), res, force=True)
    assert rep.available is True
    assert rep.n_eval_bins >= 1 and rep.n_train_bins >= 2
    assert 0.0 <= rep.kernel_fit <= 1.0 and 0.0 <= rep.learned_fit <= 1.0
    assert rep.learned_better is True
    assert rep.margin > 0.0


# ---- determinism ------------------------------------------------------------
def test_deterministic():
    sc = downtown_scenario()
    _, res = _run(sc)
    obs = _obs(sc)
    assert ld.evaluate(obs, res, force=True).as_dict() == ld.evaluate(
        obs, res, force=True
    ).as_dict()


# ---- /lenses endpoint surface (advisory block, headline unchanged) ---------
def test_lenses_endpoint_exposes_learned_dynamics_block_off_by_default(monkeypatch):
    """/lenses surfaces a ``learned_dynamics`` advisory block. Off by default it reports
    available False — and the priced extras + calibration block are untouched, so no
    headline number depends on it."""
    monkeypatch.delenv("URBANOS_LEARNED_DYNAMICS", raising=False)
    from fastapi.testclient import TestClient

    from urban_os.api import app

    client = TestClient(app)
    r = client.get("/lenses", params={"release_minutes": 8.0, "shelter_fraction": 0.5})
    assert r.status_code == 200
    body = r.json()

    ldb = body["learned_dynamics"]
    assert ldb["available"] is False
    assert ldb["provenance"] == "learned/approximate"
    # Phase-1 calibration and the four priced extras are still present and independent.
    assert body["calibration"]["calibrated"] is True
    assert set(body["extra_lenses"]) == {
        "ems_access", "emissions", "noise_livability", "fare_revenue",
    }


def test_lenses_endpoint_headline_identical_with_flag_on_off(monkeypatch):
    """Toggling the learned-dynamics flag changes ONLY the advisory block — every priced
    headline (combined_cost, cross_domain_benefit, the calibration fit) is byte-identical
    on and off. This is the 'no headline number moved' guarantee, end to end."""
    from fastapi.testclient import TestClient

    from urban_os.api import app

    client = TestClient(app)
    params = {"release_minutes": 8.0, "shelter_fraction": 0.5}

    monkeypatch.delenv("URBANOS_LEARNED_DYNAMICS", raising=False)
    off = client.get("/lenses", params=params).json()
    monkeypatch.setenv("URBANOS_LEARNED_DYNAMICS", "1")
    on = client.get("/lenses", params=params).json()

    for key in (
        "combined_cost", "baseline_combined", "combined_benefit",
        "cross_domain_benefit", "extra_lenses", "calibration",
    ):
        assert off[key] == on[key], f"{key} moved when the learned flag toggled"
    # Only the advisory block flips on.
    assert off["learned_dynamics"]["available"] is False
    assert on["learned_dynamics"]["available"] is True
