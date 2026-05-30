"""Tests for the Urban-OS FastAPI surface.

Fast by design: every test uses the default downtown scenario (short horizon).
The /optimize test is the slow one (it runs the lever grid + may hit a local
LLM); it is called exactly once and asserts only structural facts about the
insight, never its exact text.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from urban_os.api import app

client = TestClient(app)


def _json_serializable(obj) -> None:
    """Round-trips through json — catches numpy types leaking into a response
    (numpy scalars are NOT json-serializable, a common boundary bug)."""
    json.dumps(obj)


def test_health_ok_and_counts_positive():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["nodes"] > 0
    assert body["edges"] > 0


def test_index_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "Urban-OS" in r.text
    assert "maplibre-gl" in r.text  # offline vendored asset, not a CDN


def test_scenario_nodes_have_coords_and_a_sink():
    r = client.get("/scenario")
    assert r.status_code == 200
    body = r.json()
    # No numpy leakage anywhere in the payload.
    _json_serializable(body)

    nodes = body["nodes"]
    edges = body["edges"]
    assert len(nodes) > 0
    assert len(edges) > 0

    for n in nodes:
        assert isinstance(n["lat"], float)
        assert isinstance(n["lng"], float)
        assert isinstance(n["is_sink"], bool)  # bool, not numpy.bool_
        assert isinstance(n["capacity"], float)

    assert any(n["is_sink"] for n in nodes), "expected at least one sink/exit"

    # Edges reference real node ids.
    ids = {n["id"] for n in nodes}
    for e in edges:
        assert e["src"] in ids and e["dst"] in ids

    meta = body["meta"]
    assert meta["venue_id"]
    assert meta["horizon"] > 0


def test_simulate_frames_match_substrate_and_congestion_rises_then_falls():
    n_nodes = client.get("/health").json()["nodes"]
    r = client.get("/simulate", params={"release_minutes": 0})
    assert r.status_code == 200
    body = r.json()
    _json_serializable(body)

    frames = body["frames"]
    assert len(frames) > 2
    for fr in frames:
        assert len(fr["nodes"]) == n_nodes  # every frame covers the whole substrate

    # Peak congestion over the run, and a rise-then-fall shape in the max series.
    max_cong = [max(nd["congestion"] for nd in fr["nodes"]) for fr in frames]
    peak_val = max(max_cong)
    peak_idx = max_cong.index(peak_val)
    assert peak_val > 0
    # rises into the peak
    assert max_cong[peak_idx] >= max_cong[0]
    # then drains back down below the peak by the end
    assert max_cong[-1] < peak_val

    assert body["peak"]["congestion"] > 0
    assert body["peak"]["label"]


def test_simulate_release_lowers_peak_congestion():
    base = client.get("/simulate", params={"release_minutes": 0}).json()
    staggered = client.get("/simulate", params={"release_minutes": 18}).json()
    assert staggered["peak"]["congestion"] < base["peak"]["congestion"]


def test_simulate_validates_release_bounds():
    assert client.get("/simulate", params={"release_minutes": -1}).status_code == 422
    assert client.get("/simulate", params={"release_minutes": 99}).status_code == 422


def test_optimize_returns_insight_and_positive_savings():
    r = client.get("/optimize")
    assert r.status_code == 200
    body = r.json()
    _json_serializable(body)

    assert isinstance(body["insight"], str)
    assert body["insight"].strip()  # non-empty (LLM or deterministic fallback)
    assert isinstance(body["grounded"], bool)

    figures = body["figures"]
    for key in ("station", "base_mult", "best_mult", "savings_k", "release_min"):
        assert key in figures

    assert body["savings"] > 0
    assert "baseline" in body["optimization"]
    assert "best" in body["optimization"]
    # Best peak should be no worse than baseline peak.
    assert body["best_peak"]["congestion"] <= body["baseline_peak"]["congestion"]
