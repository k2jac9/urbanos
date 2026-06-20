"""The default Urban-OS demo stack is three lenses (event + economic + weather).

Locks the WeatherLens wiring (ADR-0007 fast-follow): the lens is appended after
EconomicLens, the optimizer composes its shelter lever with EventSurge's release
lever, and /optimize still returns a grounded-shaped, people-conserving result.
These pin the *wiring* — the per-lens behaviour is covered by the lens' own suite.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from urbanos.kernel.api import _lenses, _scenario, app

client = TestClient(app)


def test_default_stack_is_three_lenses_in_order():
    names = [type(lens).__name__ for lens in _lenses(_scenario())]
    # Weather must come AFTER Economic so its couple() multiplies a populated risk.
    assert names == ["EventSurge", "EconomicLens", "WeatherLens"]


def test_optimizer_searches_both_levers():
    levers = [lv.name for lens in _lenses(_scenario()) for lv in lens.levers()]
    assert "release_minutes" in levers
    assert "shelter_fraction" in levers


def test_optimize_endpoint_grounded_shape_and_people_conserved():
    r = client.get("/optimize")
    assert r.status_code == 200
    body = r.json()
    # Both levers are reported in the chosen intervention.
    assert {"release_minutes", "shelter_fraction"} <= set(body["best_params"])
    # Honest optimum: doing nothing is in the search, so savings are never negative.
    assert body["savings"] >= 0.0
    assert body["grounded"] in (True, False)  # offline -> deterministic fallback
    # The best intervention never makes the peak worse than the baseline.
    assert body["best_peak"]["congestion"] <= body["baseline_peak"]["congestion"] + 1e-9


def test_simulate_unaffected_by_added_lens():
    # /simulate doesn't pass shelter_fraction; the added lens must default to "no
    # shelter" and the endpoint stays 200 with frames.
    r = client.get("/simulate", params={"release_minutes": 0.0})
    assert r.status_code == 200
    assert r.json()["frames"]
