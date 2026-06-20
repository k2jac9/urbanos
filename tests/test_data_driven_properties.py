"""Property + edge tests for the two data-driven modules (advisory-only).

These are the *property/edge* companions to ``test_congestion_nowcast.py`` (Phase 1,
``CongestionNowcastLens``) and ``test_learned_dynamics.py`` (Phase 2,
``learned_dynamics.evaluate``). The existing files pin the headline contracts and
findings; this file hardens the boundaries those modules must hold no matter what is
fed in:

* **Determinism** — same inputs run twice give byte-identical outputs.
* **Degenerate inputs** — empty series, single node, single/too-few observed bins,
  all-zero profiles, mismatched/unknown node ids — never crash, clean no-op.
* **NaN/inf resistance** — pathological-but-finite magnitudes keep every output
  finite and the cosine in ``[0, 1]``.
* **Advisory invariants** — neither module exposes a lever or feeds a cost; the
  learned diagnostic is off without the flag/``force`` and never mutates its input;
  the nowcast lens is read-only on the kernel crowd fields.
* **Cosine bounds** — the shared ``_cosine`` primitive is in ``[0, 1]`` and 0.0 when
  either profile is all-zero.
* **Offline-safe** — driven by the adapter's synthetic fallback series: no network,
  no committed slice.

All offline + hermetic: env is touched only via ``monkeypatch`` (auto-restored).
"""
from __future__ import annotations

import warnings

import networkx as nx
import numpy as np

from urbanos.kernel import learned_dynamics as ld
from urbanos.kernel.adapters.toronto import (
    _synthetic_counts_by_node,
    downtown_scenario,
    downtown_substrate,
    observed_counts_by_node,
)
from urbanos.kernel.kernel import Simulation
from urbanos.kernel.kernel.state import Substrate
from urbanos.kernel.lenses import EconomicLens, EventSurge
from urbanos.kernel.lenses.congestion_nowcast import CongestionNowcastLens
from urbanos.kernel.lenses.congestion_nowcast import _cosine as nc_cosine


# --- shared helpers (mirror the existing test files' construction) ----------
def _run(sc, lens=None, release=0.0):
    """Build the standard kernel stack (optionally + one extra lens) and run it,
    exactly as the existing data-driven tests do — a valid finished ``SimResult``."""
    stack = [EventSurge(events=sc.events), EconomicLens()]
    if lens is not None:
        stack.append(lens)
    return Simulation(
        sc.substrate, stack, params={"release_minutes": release}, dt=sc.dt
    ).run(sc.horizon)


def _obs(sc):
    """Real-shaped synthetic observed series straight from the adapter fallback
    (no committed data, no network)."""
    return observed_counts_by_node(sc.substrate, provider=lambda: [])


# ===========================================================================
# Cosine primitive — bounds, all-zero, NaN/inf resistance (both modules share
# the same primitive shape; pin both).
# ===========================================================================
def test_cosine_bounded_in_unit_interval_both_modules():
    """For a sweep of non-negative profiles, both ``_cosine`` primitives stay in
    ``[0, 1]`` and never return NaN/inf (the metric is a *trust* score, so an
    out-of-range or non-finite value would be a silent lie)."""
    rng = np.random.default_rng(7)
    for fn in (nc_cosine, ld._cosine):
        for _ in range(50):
            n = int(rng.integers(2, 12))
            a = np.abs(rng.normal(size=n)) * float(rng.integers(1, 1000))
            b = np.abs(rng.normal(size=n)) * float(rng.integers(1, 1000))
            v = fn(a, b)
            assert np.isfinite(v)
            assert 0.0 <= v <= 1.0


def test_cosine_zero_profile_is_zero_both_modules():
    """Either profile all-zero => exactly 0.0 (not NaN from a 0/0), in both modules."""
    a = np.array([1.0, 2.0, 3.0])
    for fn in (nc_cosine, ld._cosine):
        assert fn(np.zeros(3), a) == 0.0
        assert fn(a, np.zeros(3)) == 0.0
        assert fn(np.zeros(3), np.zeros(3)) == 0.0


def test_cosine_negative_dot_clamped_to_zero_both_modules():
    """A negative dot product (anti-aligned vectors) clamps to 0.0 rather than going
    negative — the score is defined on non-negative crowd/count profiles, so a
    negative cosine is not physical and must not leak through."""
    a = np.array([1.0, 0.0])
    anti = np.array([-1.0, 0.0])
    for fn in (nc_cosine, ld._cosine):
        assert fn(a, anti) == 0.0


def test_cosine_large_but_finite_magnitudes_stay_finite_and_bounded():
    """Pathological-but-finite magnitudes (no float64 overflow) keep the cosine finite
    and in ``[0, 1]`` with no numpy RuntimeWarning — guards the realistic 'huge counts'
    case without asserting behaviour past the float64 overflow cliff."""
    cases = [
        (np.array([1e12, 5e11, 2e11]), np.array([3e11, 1e12, 7e11])),
        (np.array([1e9, 0.0, 0.0]), np.array([0.0, 1e9, 0.0])),   # orthogonal
        (np.array([1e6, 1e6, 1e6]), np.array([1e6, 1e6, 1e6])),   # identical
        (np.array([1e10, 1.0, 0.0]), np.array([1.0, 1e10, 0.0])),
    ]
    for fn in (nc_cosine, ld._cosine):
        for a, b in cases:
            with warnings.catch_warnings():
                warnings.simplefilter("error", RuntimeWarning)
                v = fn(a, b)
            assert np.isfinite(v)
            assert 0.0 <= v <= 1.0


def test_cosine_identical_is_one_and_orthogonal_is_zero_at_scale():
    """Scale-free contract holds at non-unit magnitudes: a profile scaled by any
    positive factor is still a perfect (1.0) shape match; orthogonal stays 0.0."""
    a = np.array([1.0, 2.0, 3.0, 4.0])
    for fn in (nc_cosine, ld._cosine):
        assert np.isclose(fn(a, a * 1234.5), 1.0)
        assert fn(np.array([1.0, 0.0, 0.0]), np.array([0.0, 5.0, 7.0])) == 0.0


# ===========================================================================
# CongestionNowcastLens — determinism, degenerate inputs, advisory invariants.
# ===========================================================================
def test_nowcast_full_run_deterministic_summary_and_series():
    """Two independent lenses on identical inputs produce byte-identical calibration
    summaries AND the same per-bin ``calibration_fit`` series — determinism end to end,
    not just on the scalar summary the existing test checks."""
    sc = downtown_scenario()
    obs = _obs(sc)
    a, b = CongestionNowcastLens(obs), CongestionNowcastLens(obs)
    ra = _run(sc, a)
    rb = _run(sc, b)
    assert a.calibration_summary() == b.calibration_summary()
    assert ra.series("calibration_fit") == rb.series("calibration_fit")


def test_nowcast_summary_bounds_hold_per_bin():
    """Every recorded per-bin fit (not just the mean/min summary) is finite and in
    ``[0, 1]`` — the score cannot silently emit a junk bin."""
    sc = downtown_scenario()
    res = _run(sc, CongestionNowcastLens(_obs(sc)))
    fits = res.series("calibration_fit")
    assert fits  # at least one bin compared
    for v in fits:
        assert np.isfinite(v)
        assert 0.0 <= v <= 1.0


def test_nowcast_empty_series_is_clean_noop():
    """No observed series => inert: no metric series, an empty-marked summary, and no
    error — safe to leave in any stack."""
    sc = downtown_scenario()
    lens = CongestionNowcastLens()
    res = _run(sc, lens)
    assert lens.calibration_summary() == {"mean_fit": 0.0, "min_fit": 0.0, "n_bins": 0}
    assert res.series("calibration_fit") == []
    assert lens.cost(res) == 0.0
    assert lens.levers() == []


def test_nowcast_all_zero_profiles_scores_zero_not_crash():
    """An all-zero observed series across real bins must not crash and must not produce
    a *misleading positive* fit: the lens still aligns to the kernel's (non-zero) sim
    peak and compares bins, but cosine against an all-zero observed profile is 0.0, so
    every fit — and the mean/min summary — is exactly 0.0."""
    sc = downtown_scenario()
    zero_series = {nid: {0.0: 0.0, 15.0: 0.0, 30.0: 0.0} for nid in sc.substrate.ids}
    lens = CongestionNowcastLens(zero_series)
    res = _run(sc, lens)
    summ = lens.calibration_summary()
    assert summ["mean_fit"] == 0.0 and summ["min_fit"] == 0.0
    assert set(res.series("calibration_fit")) <= {0.0}  # only honest zeros, no junk


def test_nowcast_mismatched_node_ids_does_not_crash():
    """Observed keys that don't match any substrate node => those nodes contribute 0;
    the lens still runs cleanly (boundary robustness, not a KeyError). Every lifted
    observed profile is all-zero, so the recorded fits are honest zeros."""
    sc = downtown_scenario()
    bogus = {f"NOT_A_NODE_{i}": {0.0: 1.0, 15.0: 2.0, 30.0: 3.0} for i in range(4)}
    lens = CongestionNowcastLens(bogus)
    res = _run(sc, lens)  # must not raise
    assert lens.calibration_summary()["mean_fit"] == 0.0
    assert set(res.series("calibration_fit")) <= {0.0}


def test_nowcast_single_observed_bin_does_not_crash():
    """A single observed bin (degenerate temporal series) runs without error; with one
    bin the lens may align and score it, but every output stays bounded and finite."""
    sc = downtown_scenario()
    one_bin = {nid: {0.0: float(i + 1)} for i, nid in enumerate(sc.substrate.ids)}
    lens = CongestionNowcastLens(one_bin)
    res = _run(sc, lens)  # must not raise
    summ = lens.calibration_summary()
    assert summ["n_bins"] >= 0
    for v in res.series("calibration_fit"):
        assert np.isfinite(v) and 0.0 <= v <= 1.0


def test_nowcast_single_node_substrate_does_not_crash():
    """A one-node substrate (no edges) is a valid degenerate kernel: the lens lifts a
    one-element profile and runs without error."""
    g = nx.DiGraph()
    g.add_node("only", label="Only", lat=43.0, lng=-79.0, capacity=100.0)
    sub = Substrate.from_graph(g, sinks=["only"])
    series = {"only": {0.0: 1.0, 15.0: 2.0, 30.0: 1.0}}
    lens = CongestionNowcastLens(series)
    # A bare kernel (no event lens) is enough to exercise configure/couple/observe.
    res = Simulation(sub, [lens], dt=1.0).run(40)
    assert lens.cost(res) == 0.0 and lens.levers() == []
    for v in res.series("calibration_fit"):
        assert np.isfinite(v) and 0.0 <= v <= 1.0


def test_nowcast_read_only_on_risk_and_congestion_fields():
    """Beyond the existing 'load + priced terms unchanged' check, pin that the lens
    perturbs neither ``risk`` nor ``congestion`` either — it is read-only on ALL the
    kernel crowd fields, writing only its own advisory ``observed_load`` overlay."""
    sc = downtown_scenario()
    base = _run(sc, None)
    withl = _run(sc, CongestionNowcastLens(_obs(sc)))
    assert np.allclose(base.frames[-1]["risk"], withl.frames[-1]["risk"])
    assert np.allclose(base.frames[-1]["congestion"], withl.frames[-1]["congestion"])


def test_nowcast_offline_with_synthetic_fallback_series():
    """Driven directly by the adapter's synthetic fallback (the offline path), the lens
    aligns and scores at least one bin with bounded fits — no network, no committed
    slice required."""
    sub = downtown_substrate()
    series = _synthetic_counts_by_node(sub)
    sc = downtown_scenario()
    lens = CongestionNowcastLens(series)
    res = _run(sc, lens)
    assert lens.calibration_summary()["n_bins"] >= 1
    for v in res.series("calibration_fit"):
        assert 0.0 <= v <= 1.0


# ===========================================================================
# learned_dynamics.evaluate — determinism, degenerate inputs, advisory invariants.
# ===========================================================================
def test_learned_force_runs_without_env_flag(monkeypatch):
    """``force=True`` runs the math regardless of the env flag being unset (the test
    path). Hermetic: the flag is removed via monkeypatch and restored automatically."""
    monkeypatch.delenv("URBANOS_LEARNED_DYNAMICS", raising=False)
    assert ld.learned_dynamics_enabled() is False
    sc = downtown_scenario()
    res = _run(sc)
    rep = ld.evaluate(_obs(sc), res, force=True)
    assert rep.available is True


def test_learned_disabled_without_force_is_noop(monkeypatch):
    """Env unset AND no ``force`` => clean no-op (available False), and the no-op report
    carries the advisory provenance + a 'disabled' note, never raising."""
    monkeypatch.delenv("URBANOS_LEARNED_DYNAMICS", raising=False)
    sc = downtown_scenario()
    res = _run(sc)
    rep = ld.evaluate(_obs(sc), res)  # no force
    assert rep.available is False
    assert rep.provenance == "learned/approximate"
    assert "disabled" in rep.note
    assert rep.margin == 0.0 and rep.learned_better is False


def test_learned_deterministic_report_is_byte_identical():
    """Same inputs, two ``force`` evaluations => identical dataclass report (every
    field, not only ``as_dict``) — the least-squares fit + rollout is deterministic."""
    sc = downtown_scenario()
    res = _run(sc)
    obs = _obs(sc)
    r1 = ld.evaluate(obs, res, force=True)
    r2 = ld.evaluate(obs, res, force=True)
    assert r1 == r2  # frozen-ish dataclass equality over all fields


def test_learned_outputs_finite_and_bounded():
    """The reported fits are finite and in ``[0, 1]``; the margin is finite and equals
    learned_fit - kernel_fit exactly (no rounding drift in the raw report)."""
    sc = downtown_scenario()
    res = _run(sc)
    rep = ld.evaluate(_obs(sc), res, force=True)
    assert np.isfinite(rep.learned_fit) and 0.0 <= rep.learned_fit <= 1.0
    assert np.isfinite(rep.kernel_fit) and 0.0 <= rep.kernel_fit <= 1.0
    assert np.isfinite(rep.margin)
    assert np.isclose(rep.margin, rep.learned_fit - rep.kernel_fit)


def test_learned_empty_and_none_series_are_noop():
    """A ``None`` or empty observed series short-circuits to a no-op report (boundary
    validation), never raising."""
    sc = downtown_scenario()
    res = _run(sc)
    assert ld.evaluate(None, res, force=True).available is False
    assert ld.evaluate({}, res, force=True).available is False


def test_learned_too_few_bins_is_noop():
    """Fewer than three observed bins => 'too few observed bins' no-op (nothing to fit
    a transition + hold out)."""
    sc = downtown_scenario()
    res = _run(sc)
    one = {sc.substrate.ids[0]: {0.0: 1.0}}
    two = {sc.substrate.ids[0]: {0.0: 1.0, 15.0: 2.0}}
    assert ld.evaluate(one, res, force=True).available is False
    rep_two = ld.evaluate(two, res, force=True)
    assert rep_two.available is False
    assert "too few" in rep_two.note


def test_learned_all_zero_profiles_is_noop_not_crash():
    """All-zero observed profiles over >=3 bins => no scorable held-out bin (every
    eval profile sums to 0), a clean no-op with finite zero fits — not a 0/0 NaN."""
    sc = downtown_scenario()
    res = _run(sc)
    zeros = {nid: {0.0: 0.0, 15.0: 0.0, 30.0: 0.0, 45.0: 0.0} for nid in sc.substrate.ids}
    rep = ld.evaluate(zeros, res, force=True)
    assert rep.available is False
    assert rep.learned_fit == 0.0 and rep.kernel_fit == 0.0
    assert np.isfinite(rep.margin)


def test_learned_mismatched_node_ids_is_noop_not_crash():
    """Observed series whose keys match no substrate node => all-zero lifted profiles =>
    no scorable bin, handled without raising."""
    sc = downtown_scenario()
    res = _run(sc)
    bogus = {f"GHOST_{i}": {0.0: 1.0, 15.0: 2.0, 30.0: 3.0, 45.0: 4.0} for i in range(5)}
    rep = ld.evaluate(bogus, res, force=True)
    assert rep.available is False
    assert rep.learned_fit == 0.0 and rep.kernel_fit == 0.0


def test_learned_frameless_result_is_noop():
    """A result with no recorded frames (``record_frames=False``) => 'no frames' no-op:
    the kernel comparison has nothing to read, so the diagnostic declines cleanly."""
    sc = downtown_scenario()
    no_frame = Simulation(
        sc.substrate, [EventSurge(events=sc.events)], dt=sc.dt
    ).run(sc.horizon, record_frames=False)
    rep = ld.evaluate(_obs(sc), no_frame, force=True)
    assert rep.available is False
    assert "no frames" in rep.note


def test_learned_train_fraction_extremes_are_clamped():
    """``train_fraction`` is clamped to ``[0.1, 0.9]`` and always leaves >=2 training
    bins and >=1 eval bin — degenerate 0.0 / 1.0 splits do not blow up the fit."""
    sc = downtown_scenario()
    res = _run(sc)
    obs = _obs(sc)
    for tf in (0.0, 1.0, -5.0, 99.0):
        rep = ld.evaluate(obs, res, train_fraction=tf, force=True)
        assert rep.available is True
        assert rep.n_train_bins >= 2
        assert rep.n_eval_bins >= 1


def test_learned_single_observed_bin_per_node_noop():
    """One bin per node (the thinnest possible temporal series) => too-few-bins no-op."""
    sc = downtown_scenario()
    res = _run(sc)
    thin = {nid: {0.0: float(i + 1)} for i, nid in enumerate(sc.substrate.ids)}
    assert ld.evaluate(thin, res, force=True).available is False


def test_learned_does_not_mutate_passed_result_under_force():
    """The diagnostic is read-only: running ``evaluate(..., force=True)`` leaves the
    passed ``SimResult`` byte-for-byte unchanged (priced series + final fields), so it
    can move no headline number even when forced on. (Companion to the existing
    delay/safety/load check — adds risk/congestion + the metrics dict identity.)"""
    sc = downtown_scenario()
    res = _run(sc)
    delay_before = list(res.series("delay_cost"))
    risk_before = res.frames[-1]["risk"].copy()
    cong_before = res.frames[-1]["congestion"].copy()
    load_before = res.frames[-1]["load"].copy()

    rep = ld.evaluate(_obs(sc), res, force=True)
    assert rep.available is True
    assert list(res.series("delay_cost")) == delay_before
    assert np.array_equal(res.frames[-1]["risk"], risk_before)
    assert np.array_equal(res.frames[-1]["congestion"], cong_before)
    assert np.array_equal(res.frames[-1]["load"], load_before)


def test_learned_exposes_no_lever_and_feeds_no_cost():
    """Honesty contract at the module level: ``learned_dynamics`` is a plain module of
    advisory functions — it has no ``Lens``-style lever/cost surface at all. The report
    it returns is purely descriptive (no ``cost``/``levers`` attribute), so nothing it
    produces can enter the optimizer's ``J``."""
    sc = downtown_scenario()
    res = _run(sc)
    rep = ld.evaluate(_obs(sc), res, force=True)
    assert not hasattr(rep, "cost")
    assert not hasattr(rep, "levers")
    assert not hasattr(ld, "Lens")
    # The advisory report only ever describes a comparison; it carries provenance.
    assert rep.provenance == "learned/approximate"


def test_learned_offline_with_synthetic_fallback_series():
    """Driven by the adapter's synthetic fallback (offline path), the forced diagnostic
    runs, scores a held-out tail, and reports bounded finite fits — no network, no
    committed slice."""
    sub = downtown_substrate()
    series = _synthetic_counts_by_node(sub)
    sc = downtown_scenario()
    res = _run(sc)
    rep = ld.evaluate(series, res, force=True)
    assert rep.available is True
    assert rep.n_eval_bins >= 1 and rep.n_train_bins >= 2
    assert 0.0 <= rep.learned_fit <= 1.0 and 0.0 <= rep.kernel_fit <= 1.0


def test_learned_report_as_dict_is_json_safe_and_native():
    """``as_dict`` emits only native Python scalars (no numpy types leak into the API
    block) and round-trips through ``json.dumps`` — the advisory block stays JSON-safe
    for the ``/lenses`` surface."""
    import json

    sc = downtown_scenario()
    res = _run(sc)
    d = ld.evaluate(_obs(sc), res, force=True).as_dict()
    assert json.loads(json.dumps(d)) == d
    for k in ("learned_fit", "kernel_fit", "margin"):
        assert isinstance(d[k], float)
    assert isinstance(d["available"], bool)
    assert isinstance(d["learned_better"], bool)
    assert isinstance(d["n_eval_bins"], int) and isinstance(d["n_train_bins"], int)
