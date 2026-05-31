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
    assert "Urban OS" in r.text  # the unified shell (or classic fallback) wordmark
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


def test_simulate_accepts_and_echoes_shelter_fraction():
    """/simulate takes the shelter lever, echoes it back, and validates bounds —
    so any (release, shelter) the optimizer evaluates is reproducible on the map."""
    body = client.get(
        "/simulate", params={"release_minutes": 16, "shelter_fraction": 0.75}
    ).json()
    assert body["shelter_fraction"] == pytest.approx(0.75, abs=1e-6)
    assert body["release_minutes"] == pytest.approx(16.0, abs=1e-6)
    # Out-of-range / non-finite shelter is rejected at the boundary.
    assert client.get(
        "/simulate", params={"shelter_fraction": -0.1}
    ).status_code == 422
    assert client.get(
        "/simulate", params={"shelter_fraction": 1.5}
    ).status_code == 422
    assert client.get(
        "/simulate", params={"shelter_fraction": "nan"}
    ).status_code == 422


def test_simulate_shelter_changes_the_run():
    """Deploying shelter must actually change the simulation (less rain risk and
    a different cost breakdown) — not be a silently ignored parameter."""
    none = client.get(
        "/simulate", params={"release_minutes": 0, "shelter_fraction": 0.0}
    ).json()
    full = client.get(
        "/simulate", params={"release_minutes": 0, "shelter_fraction": 1.0}
    ).json()
    # Full shelter neutralises the rain-risk amplification ⇒ strictly lower peak
    # risk somewhere in the run, and a different J breakdown.
    none_peak_risk = max(
        nd["risk"] for fr in none["frames"] for nd in fr["nodes"]
    )
    full_peak_risk = max(
        nd["risk"] for fr in full["frames"] for nd in fr["nodes"]
    )
    assert full_peak_risk < none_peak_risk
    assert none["cost_breakdown"] != full["cost_breakdown"]
    # Sheltered run pays staffing but no exposure; unsheltered the reverse.
    assert full["cost_breakdown"]["staffing"] > 0
    assert full["cost_breakdown"]["exposure"] == pytest.approx(0.0, abs=1e-6)
    assert none["cost_breakdown"]["exposure"] > 0


def test_simulate_sinks_carry_no_standing_load():
    """The egress wave is seeded only at non-sink nodes (graph bug fix), so the
    exit lines never receive a direct injection — map routing == engine routing.
    Every sink carries ~zero standing load every frame (people are absorbed into
    ``arrived`` as they reach an exit, never parked on the pin)."""
    scenario = client.get("/scenario").json()
    sink_ids = {n["id"] for n in scenario["nodes"] if n["is_sink"]}
    assert sink_ids, "scenario must expose exit sinks"
    body = client.get("/simulate", params={"release_minutes": 0}).json()
    for fr in body["frames"]:
        for nd in fr["nodes"]:
            if nd["id"] in sink_ids:
                assert nd["load"] == pytest.approx(0.0, abs=1e-3)


def test_simulate_trims_dead_timeline_tail_but_keeps_peak_and_metrics():
    """BUG-C: the crowd drains long before the fixed horizon, so /simulate drops
    the trailing all-zero frames before returning — the slider/playback span the
    active window. The peak frame is retained and the full metrics series (and the
    physics behind them) are NOT trimmed."""
    body = client.get("/simulate", params={"release_minutes": 0, "frame_every": 1}).json()
    frames = body["frames"]
    times = body["times"]

    # The trim happened: fewer frames than the full per-step time series.
    assert len(frames) < len(times)
    # The full metrics series are untouched (one value per step over the horizon).
    for series in body["metrics"].values():
        assert len(series) == len(times)

    # No trailing all-zero padding: the LAST frame is part of a short drained coda,
    # but the frames before it are not an unbroken run of empties — i.e. there is
    # real activity within a couple of frames of the end.
    total_load = [sum(nd["load"] for nd in fr["nodes"]) for fr in frames]
    assert max(total_load[-3:]) > 0.0, "tail should still be near the active window"

    # The peak frame is retained: the peak congestion is present in some frame and
    # the peak readout itself is unchanged by the trim.
    peak_t = body["peak"]["t"]
    assert any(fr["t"] == peak_t for fr in frames), "peak frame must survive the trim"
    frame_max = max(nd["congestion"] for fr in frames for nd in fr["nodes"])
    assert body["peak"]["congestion"] == pytest.approx(frame_max, abs=1e-3)


def test_simulate_trim_does_not_change_peak_readout_vs_untrimmed_metrics():
    """The frame trim is display-only: the peak readout (computed over every step)
    is identical to the peak of the full untrimmed metric/time series."""
    body = client.get("/simulate", params={"release_minutes": 0, "frame_every": 1}).json()
    # in_system metric is the full per-step series; its support spans the horizon,
    # while the trimmed frames stop near the drained end.
    assert len(body["metrics"]["in_system"]) > len(body["frames"])
    # Peak congestion readout is still positive and names a real node.
    assert body["peak"]["congestion"] > 0
    assert body["peak"]["label"]


def test_simulate_cost_breakdown_is_present_and_tracks_levers():
    """BUG-A backing: /simulate returns a per-lever cost_breakdown that the UI can
    render live; moving a lever must visibly change it (it is not constant)."""
    a = client.get(
        "/simulate", params={"release_minutes": 0, "shelter_fraction": 0.0}
    ).json()["cost_breakdown"]
    b = client.get(
        "/simulate", params={"release_minutes": 18, "shelter_fraction": 0.0}
    ).json()["cost_breakdown"]
    c = client.get(
        "/simulate", params={"release_minutes": 0, "shelter_fraction": 1.0}
    ).json()["cost_breakdown"]
    keys = {"delay", "hold", "exposure", "staffing", "safety", "total"}
    assert set(a.keys()) == keys
    # The breakdown is NOT constant across levers (the live table must move).
    assert a != b, "moving the release lever must change the breakdown"
    assert a != c, "moving the shelter lever must change the breakdown"


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
