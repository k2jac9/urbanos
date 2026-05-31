"""Contract / regression lane for the Urban-OS FastAPI surface.

Companion to ``tests/test_urban_api.py`` (which exercises happy-path behaviour).
This lane *pins the contract*: the exact response SHAPES/keys of every endpoint
and the cross-cutting invariants the UI and the other workstreams rely on:

- **No numpy leakage** — every numeric field in every payload is a *native*
  Python ``int``/``float``/``bool`` (numpy scalars subclass these but are a
  latent boundary bug; we reject them structurally, not just via ``json.dumps``).
- **People conservation** — the ``in_system`` series of ``/simulate`` rises from
  a near-empty start to a peak and drains back down (a conserved crowd that
  enters and then exits through the sinks), and per-frame node loads are finite
  and non-negative.
- **Grounded, cited insight** — ``/optimize`` returns ``grounded`` as a bool and
  every integer cited in the insight sentence is a real figure value (the
  hallucination-guard whitelist). A stubbed LLM pins the ``grounded is True``
  branch end-to-end.
- **Peak structure** — the reported peak matches the max congestion actually
  present in the frames, names a real node, and the optimizer never makes the
  peak worse than the do-nothing baseline.
- **Offline static mount** — ``/static`` serves the vendored MapLibre/PMTiles
  assets from this origin (no CDN), and the page references them.

These tests must stay fast: the default short-horizon downtown scenario is used
throughout, ``/optimize`` is hit once, and the LLM is never contacted over the
network (offline → deterministic fallback, or an injected stub).
"""
from __future__ import annotations

import json
import numbers
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from urban_os import api
from urban_os.api import app

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _assert_native(obj, path: str = "root") -> None:
    """Fail if any leaf is a numpy scalar (or a non-finite float).

    numpy scalars subclass Python ``int``/``float`` so a plain ``isinstance``
    check would pass; we test the concrete type against ``np.generic`` to catch
    the leak the project invariant forbids.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert isinstance(k, str), f"non-str key at {path}: {k!r}"
            _assert_native(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_native(v, f"{path}[{i}]")
    elif isinstance(obj, np.generic):  # numpy scalar leaked through
        raise AssertionError(f"numpy scalar leaked at {path}: {type(obj)!r}")
    elif isinstance(obj, float):
        assert np.isfinite(obj), f"non-finite float at {path}: {obj}"
    elif isinstance(obj, (str, bool, int, type(None))):
        pass
    else:
        raise AssertionError(f"unexpected leaf type at {path}: {type(obj)!r}")


def _ints(s: str) -> set[int]:
    return {int(x) for x in re.findall(r"\d+", s or "")}


def _get(path: str, **params):
    r = client.get(path, params=params or None)
    assert r.status_code == 200, (path, params, r.status_code, r.text[:200])
    body = r.json()
    json.dumps(body)          # legal JSON (no NaN/Infinity tokens)
    _assert_native(body)      # and strictly native python
    return body


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
def test_health_shape_is_pinned():
    body = _get("/health")
    assert set(body.keys()) == {"status", "nodes", "edges"}
    assert body["status"] == "ok"
    assert isinstance(body["nodes"], int) and not isinstance(body["nodes"], bool)
    assert isinstance(body["edges"], int)
    assert body["nodes"] > 0 and body["edges"] > 0


# --------------------------------------------------------------------------- #
# /scenario
# --------------------------------------------------------------------------- #
def test_scenario_shape_and_referential_integrity():
    body = _get("/scenario")
    assert set(body.keys()) == {"nodes", "edges", "meta"}

    node_keys = {"id", "label", "lat", "lng", "capacity", "is_sink", "group"}
    valid_groups = {"venue", "fanzone", "transit", "exit"}
    ids = set()
    for n in body["nodes"]:
        assert set(n.keys()) == node_keys
        assert isinstance(n["id"], str) and n["id"]
        assert isinstance(n["label"], str)
        assert isinstance(n["lat"], float) and isinstance(n["lng"], float)
        assert isinstance(n["capacity"], float)
        assert isinstance(n["is_sink"], bool)
        assert n["group"] in valid_groups
        ids.add(n["id"])
    assert len(ids) == len(body["nodes"]), "node ids must be unique"
    assert any(n["is_sink"] for n in body["nodes"]), "expected at least one sink"

    for e in body["edges"]:
        assert set(e.keys()) == {"src", "dst"}
        assert e["src"] in ids and e["dst"] in ids  # no dangling edge endpoints

    meta = body["meta"]
    assert set(meta.keys()) == {"venue_id", "crowd_size", "event_end", "horizon", "events"}
    assert meta["venue_id"] in ids                  # venue is a real node
    assert isinstance(meta["horizon"], int) and meta["horizon"] > 0
    assert meta["crowd_size"] > 0
    # The concurrent let-outs that make up the convergence crunch.
    assert isinstance(meta["events"], list) and meta["events"]
    event_keys = {"venue_id", "label", "crowd_size", "event_end"}
    for ev in meta["events"]:
        assert set(ev.keys()) == event_keys
        assert ev["venue_id"] in ids                # each event venue is a real node
        assert ev["crowd_size"] > 0
    # The primary venue is one of the concurrent events.
    assert meta["venue_id"] in {ev["venue_id"] for ev in meta["events"]}


# --------------------------------------------------------------------------- #
# /simulate — shape, conservation, peak structure, validation
# --------------------------------------------------------------------------- #
def test_simulate_shape_is_pinned():
    body = _get("/simulate", release_minutes=0)
    assert set(body.keys()) == {
        "times", "frames", "metrics", "peak", "release_minutes",
        "shelter_fraction", "cost_breakdown",
    }
    # The J cost-breakdown names every term and sums to total.
    cb = body["cost_breakdown"]
    assert set(cb.keys()) == {
        "delay", "hold", "exposure", "staffing", "safety", "total"
    }
    assert cb["total"] == pytest.approx(
        cb["delay"] + cb["hold"] + cb["exposure"] + cb["staffing"] + cb["safety"],
        abs=0.1,
    )
    assert body["frames"], "expected at least one frame"
    n_nodes = _get("/health")["nodes"]

    frame_keys = {"t", "nodes"}
    node_keys = {"id", "load", "congestion", "risk"}
    for fr in body["frames"]:
        assert set(fr.keys()) == frame_keys
        assert len(fr["nodes"]) == n_nodes  # every frame spans the whole substrate
        for nd in fr["nodes"]:
            assert set(nd.keys()) == node_keys
            assert nd["load"] >= 0.0
            assert nd["congestion"] >= 0.0
            assert nd["risk"] >= 0.0

    # ``times`` is the full per-step series; ``frames`` is subsampled by the
    # default ``frame_every`` (2) → fewer frames than steps, never more.
    assert len(body["frames"]) <= len(body["times"])
    assert len(body["times"]) > 0
    peak = body["peak"]
    assert set(peak.keys()) == {"node", "label", "congestion", "t"}


def test_simulate_peak_matches_frames_and_names_a_real_node():
    scenario = _get("/scenario")
    by_id = {n["id"]: n["label"] for n in scenario["nodes"]}

    body = _get("/simulate", release_minutes=0, frame_every=1)
    peak = body["peak"]
    # The reported peak congestion equals the max congestion actually in a frame
    # (to the response's rounding precision), and references a real node.
    frame_max = max(nd["congestion"] for fr in body["frames"] for nd in fr["nodes"])
    assert peak["congestion"] == pytest.approx(frame_max, abs=1e-3)
    assert peak["node"] in by_id
    assert peak["label"] == by_id[peak["node"]]
    assert peak["congestion"] > 0


def test_simulate_conserves_people_rise_then_drain():
    """``in_system`` (total load on the network) starts near-empty, peaks as the
    crowd is injected, and drains back down as people reach the sinks — the
    conservation signature of a finite crowd flowing through to exits."""
    body = _get("/simulate", release_minutes=0, frame_every=1)
    series = body["metrics"]["in_system"]
    assert len(series) == len(body["times"])
    assert all(v >= 0.0 for v in series)

    peak_idx = series.index(max(series))
    assert series[peak_idx] > series[0]      # rises into the peak
    assert series[-1] < series[peak_idx]     # then drains below the peak
    # Tail is much emptier than the peak — the crowd has largely cleared.
    assert series[-1] < 0.5 * series[peak_idx]


def test_simulate_total_population_never_exceeds_crowd_size():
    """No frame may hold more people than were ever injected (conservation upper
    bound): peak in-system load ≤ the scenario crowd_size (+ rounding slack)."""
    crowd = _get("/scenario")["meta"]["crowd_size"]
    body = _get("/simulate", release_minutes=0, frame_every=1)
    peak_in_system = max(body["metrics"]["in_system"])
    assert peak_in_system <= crowd + 1.0


def test_simulate_release_lever_lowers_peak():
    base = _get("/simulate", release_minutes=0)
    spread = _get("/simulate", release_minutes=18)
    assert spread["peak"]["congestion"] < base["peak"]["congestion"]


def test_simulate_frame_every_subsamples_monotonically():
    fine = _get("/simulate", release_minutes=0, frame_every=1)
    coarse = _get("/simulate", release_minutes=0, frame_every=4)
    assert len(coarse["frames"]) <= len(fine["frames"])
    assert coarse["frames"], "coarse subsampling must still yield frames"
    # Same physics: identical peak congestion regardless of frame sampling.
    assert coarse["peak"]["congestion"] == pytest.approx(
        fine["peak"]["congestion"], abs=1e-3
    )


@pytest.mark.parametrize(
    "params,field",
    [
        ({"release_minutes": -0.1}, "release_minutes"),
        ({"release_minutes": 20.1}, "release_minutes"),
        ({"release_minutes": 1e9}, "release_minutes"),
        ({"frame_every": 0}, "frame_every"),
        ({"frame_every": -3}, "frame_every"),
        ({"frame_every": 61}, "frame_every"),
        ({"release_minutes": "abc"}, "release_minutes"),
        ({"frame_every": "x"}, "frame_every"),
    ],
)
def test_simulate_rejects_out_of_range_or_malformed(params, field):
    r = client.get("/simulate", params=params)
    assert r.status_code == 422, (params, r.status_code)


def test_simulate_rejects_nan_release():
    # NaN passes neither ge nor le but can slip framework bound checks; the
    # endpoint guards it explicitly and returns 422.
    r = client.get("/simulate", params={"release_minutes": "nan"})
    assert r.status_code == 422


def test_benefit_semantics_lenses_and_optimize_agree():
    """ADR-0019: the additive ``cross_domain_benefit`` is computed by ONE shared
    helper, so /optimize and /lenses MUST report the identical number at the same
    levers. Pins the fix for the audit's F-4 (three differently-derived benefit
    numbers shown unlabelled)."""
    opt = _get("/optimize")
    bp = opt["best_params"]
    ln = _get(
        "/lenses",
        release_minutes=bp["release_minutes"],
        shelter_fraction=bp.get("shelter_fraction", 0.0),
    )
    # Same definition, same levers, one helper → equal (allow 2-dp rounding noise).
    assert abs(ln["cross_domain_benefit"] - opt["cross_domain_benefit"]) <= 0.01
    # The conservative single-objective number is never larger than the additive one.
    assert opt["j_avoided"] <= opt["cross_domain_benefit"] + 0.01
    # Both surfaces ship the definitions block so every number is self-labelled.
    for body in (opt, ln):
        assert "cross_domain_benefit" in body["benefit_definitions"]


def test_simulate_accepts_boundary_values():
    assert client.get("/simulate", params={"release_minutes": 0}).status_code == 200
    assert client.get("/simulate", params={"release_minutes": 20}).status_code == 200
    assert client.get("/simulate", params={"frame_every": 1}).status_code == 200
    assert client.get("/simulate", params={"frame_every": 60}).status_code == 200


def test_simulate_huge_frame_every_still_returns_a_frame():
    # frame_every is clamped to the horizon internally, so a max-bound value
    # still yields at least the opening frame (graceful, not empty).
    body = _get("/simulate", frame_every=60)
    assert len(body["frames"]) >= 1


# --------------------------------------------------------------------------- #
# /optimize — shape, savings, grounded+cited insight
# --------------------------------------------------------------------------- #
def test_optimize_shape_is_pinned():
    body = _get("/optimize")
    assert set(body.keys()) == {
        "insight", "grounded", "figures", "optimization",
        "baseline_peak", "best_peak", "best_params", "savings",
        "j_avoided",
        "cost_breakdown", "baseline_cost_breakdown",
        "cross_domain", "enabled", "cross_domain_benefit",
        "cross_domain_components", "combined_benefit", "benefit_definitions",
    }
    # Cross-domain extras: the same release scored across the user-selected Safety +
    # Business lenses. `cross_domain` carries only the enabled lenses (well-formed
    # if present); `cross_domain_benefit` = transit savings + the enabled contributions
    # (ADR-0019: computed by the shared helper, labelled in benefit_definitions).
    cd = body["cross_domain"]
    if cd:
        if "safety" in cd:
            assert cd["safety"]["best"] <= cd["safety"]["baseline"]
        if "business" in cd:
            assert cd["business"]["recovered"] >= 0
    assert set(body["enabled"]) == {"safety", "business"}
    # ADR-0019: j_avoided is the conservative single-objective number (= savings);
    # combined_benefit is retained as a deprecated alias of cross_domain_benefit.
    assert body["j_avoided"] == body["savings"]
    assert body["combined_benefit"] == body["cross_domain_benefit"]
    assert set(body["benefit_definitions"]) >= {
        "j_avoided", "cross_domain_benefit", "combined_benefit",
    }
    assert isinstance(body["combined_benefit"], (int, float))
    assert body["combined_benefit"] >= body["savings"]  # enabled lenses only add value
    assert isinstance(body["insight"], str) and body["insight"].strip()
    assert isinstance(body["grounded"], bool)
    assert isinstance(body["savings"], (int, float)) and body["savings"] > 0

    fig_keys = {
        "station", "base_mult", "best_mult", "minutes_after", "peak_t_abs",
        "reduction_pct", "release_min", "shelter_pct", "baseline_cost_k",
        "savings_k",
    }
    assert set(body["figures"].keys()) == fig_keys

    breakdown_keys = {"delay", "hold", "exposure", "staffing", "safety", "total"}
    for key in ("cost_breakdown", "baseline_cost_breakdown"):
        assert set(body[key].keys()) == breakdown_keys
        cb = body[key]
        assert cb["total"] == pytest.approx(
            cb["delay"] + cb["hold"] + cb["exposure"] + cb["staffing"] + cb["safety"],
            abs=0.5,
        )

    opt = body["optimization"]
    assert set(opt.keys()) == {"baseline", "best", "savings", "levers", "trials"}
    assert set(opt["baseline"].keys()) == {"params", "J", "breakdown"}
    assert set(opt["best"].keys()) == {"params", "J", "breakdown"}
    for lv in opt["levers"]:
        assert set(lv.keys()) == {"name", "label"}
    for tr in opt["trials"]:
        assert set(tr.keys()) == {"params", "J"}

    for pk in ("baseline_peak", "best_peak"):
        assert set(body[pk].keys()) == {"node", "label", "congestion", "t"}


def test_optimize_best_no_worse_than_baseline():
    body = _get("/optimize")
    assert body["best_peak"]["congestion"] <= body["baseline_peak"]["congestion"]
    assert body["optimization"]["best"]["J"] <= body["optimization"]["baseline"]["J"]
    # Reported savings equals baseline_J - best_J (within rounding).
    opt = body["optimization"]
    assert body["savings"] == pytest.approx(
        opt["baseline"]["J"] - opt["best"]["J"], abs=0.5
    )


def test_optimize_insight_only_cites_real_figures():
    """Hallucination-guard contract: every integer in the insight sentence is a
    figure the simulation actually produced (no fabricated statistic)."""
    body = _get("/optimize")
    figures = body["figures"]
    allowed: set[int] = set()
    for v in figures.values():
        if isinstance(v, numbers.Real) and not isinstance(v, bool):
            allowed |= _ints(str(v))
    cited = _ints(body["insight"])
    assert cited, "insight should cite at least one figure"
    assert cited <= allowed, f"insight cites non-figure numbers: {cited - allowed}"
    # The bottleneck station is always named verbatim.
    assert figures["station"] in body["insight"]


def test_optimize_trials_include_do_nothing_baseline():
    body = _get("/optimize")
    opt = body["optimization"]
    base_release = opt["baseline"]["params"].get("release_minutes")
    assert base_release == 0  # convention: index-0 lever value is "do nothing"
    trial_releases = [t["params"].get("release_minutes") for t in opt["trials"]]
    assert 0 in trial_releases


def test_optimize_grounded_path_with_stub_llm(monkeypatch):
    """Pin the ``grounded is True`` branch end-to-end with a deterministic stub
    LLM that echoes only real figures — proving the endpoint surfaces a verified
    sentence (not just the offline fallback) and the citation invariant holds."""
    from urban_os import narrate

    class _StubLLM:
        def chat(self, system, user, temperature=0.0):  # noqa: ARG002
            # Build a one-liner from the figures embedded in the user prompt so
            # it only ever cites whitelisted numbers and names the station.
            station = re.search(r"bottleneck station: (.+)", user).group(1).strip()
            return (
                f"{station} is the chokepoint and a staggered release helps."
            )

    # Force the endpoint's narrator to use the stub (no network, deterministic).
    monkeypatch.setattr(narrate, "interactive_llm", lambda: _StubLLM())

    body = _get("/optimize")
    assert body["grounded"] is True, body["insight"]
    assert body["figures"]["station"] in body["insight"]
    # Still only cites real figures.
    allowed: set[int] = set()
    for v in body["figures"].values():
        if isinstance(v, numbers.Real) and not isinstance(v, bool):
            allowed |= _ints(str(v))
    assert _ints(body["insight"]) <= allowed


def test_optimize_falls_back_when_llm_hallucinates(monkeypatch):
    """A model that injects a fabricated number must be rejected → the response
    falls back to the deterministic (grounded=False) sentence."""
    from urban_os import narrate

    class _LiarLLM:
        def chat(self, system, user, temperature=0.0):  # noqa: ARG002
            station = re.search(r"bottleneck station: (.+)", user).group(1).strip()
            return f"{station} overloads by 99999 percent — evacuate now."

    monkeypatch.setattr(narrate, "interactive_llm", lambda: _LiarLLM())
    body = _get("/optimize")
    assert body["grounded"] is False
    assert 99999 not in _ints(body["insight"])


# --------------------------------------------------------------------------- #
# Offline static surface
# --------------------------------------------------------------------------- #
def test_index_references_vendored_offline_assets():
    r = client.get("/")
    assert r.status_code == 200
    text = r.text
    assert "Urban OS" in text
    assert "maplibre-gl" in text            # vendored, not a CDN
    assert "http://" not in text.replace("http://localhost", "")  # no external http
    assert "cdn." not in text and "unpkg" not in text and "jsdelivr" not in text


def test_static_mount_serves_offline_assets():
    # The vendored MapLibre JS must load from THIS origin (offline invariant).
    for asset in ("vendor/maplibre-gl.js", "vendor/maplibre-gl.css"):
        r = client.get(f"/static/{asset}")
        assert r.status_code == 200, asset
        assert r.content, f"{asset} should be non-empty"


def test_favicon_is_served_offline():
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


# --------------------------------------------------------------------------- #
# Boundary helpers (unit-level guards backing the endpoints)
# --------------------------------------------------------------------------- #
def test_round_helper_coerces_numpy_and_clamps_non_finite():
    assert isinstance(api._r(np.float64(1.23456)), float)
    assert not isinstance(api._r(np.float64(1.0)), np.generic)
    assert api._r(float("nan")) == 0.0
    assert api._r(float("inf")) == 0.0
    assert api._r(np.float64(2.0) / np.float64(0.0) if False else 3.14159, 2) == 3.14


def test_native_helper_strips_numpy_recursively():
    blob = {
        "a": np.float64(1.5),
        "b": [np.int64(2), np.bool_(True), {"c": np.float32(3.5)}],
        "d": float("inf"),
        "e": "keep",
        "f": None,
    }
    out = api._native(blob)
    json.dumps(out)
    _assert_native(out)
    assert out["a"] == 1.5 and isinstance(out["a"], float)
    assert out["b"][0] == 2 and isinstance(out["b"][0], int)
    assert out["b"][1] is True
    assert out["b"][2]["c"] == pytest.approx(3.5)
    assert out["d"] == 0.0  # non-finite clamped
    assert out["e"] == "keep" and out["f"] is None
