"""Contract / regression lane for the urbanos.risk FastAPI surface.

Companion to ``tests/test_api.py`` (happy-path) and ``test_analyze_contract.py``
(fusion/grounded invariants on the real slice). This lane is the public-API
*hardening* contract added alongside ADR-0006's urbanos.kernel work: urbanos.risk is
the surface on the public Tailscale Funnel, so it pins both the response SHAPES
of every endpoint AND the no-stack-trace posture.

It pins:
- the exact / minimum key sets of /analyze, /addresses, /digest, /health;
- **no stack-trace leak** — an internal failure becomes a clean generic 500 with
  no traceback or internals in the body (app-level handler + per-endpoint wrap);
- **explicit, restrictive CORS** — no wildcard ``Access-Control-Allow-Origin``;
- **warm /digest is cheap** — a second hit serves the cached digest without
  re-running the batch model, and the output is unchanged.

Runs against the committed synthetic fixtures (same as ``test_api.py``) so it is
deterministic and fully offline — the narrator falls back to deterministic claims
and the digest to its offline fallback; we assert STRUCTURE, never model prose.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from urbanos.risk.config import settings

# Point the loader at the synthetic fixtures (mirrors test_api.py); the app's
# lifespan reads settings.data_dir when it (re)loads the graph.
settings.data_dir = Path(__file__).resolve().parent.parent / "fixtures"

from urbanos.risk.api import server  # noqa: E402
from urbanos.risk.api.server import app  # noqa: E402


# --------------------------------------------------------------------------- #
# /health — shape
# --------------------------------------------------------------------------- #
def test_health_shape_is_pinned() -> None:
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert set(body.keys()) == {
        "status", "graph_nodes", "loaded", "interactive_model",
        "batch_model", "digest_cached",
    }
    assert body["status"] == "ok"
    assert isinstance(body["graph_nodes"], int) and not isinstance(body["graph_nodes"], bool)
    assert isinstance(body["loaded"], dict)
    assert isinstance(body["interactive_model"], str)
    assert isinstance(body["batch_model"], str)
    assert isinstance(body["digest_cached"], bool)


# --------------------------------------------------------------------------- #
# /addresses — shape
# --------------------------------------------------------------------------- #
def test_addresses_shape_is_pinned() -> None:
    with TestClient(app) as client:
        addrs = client.get("/addresses").json()
    assert isinstance(addrs, list) and addrs
    row_keys = {
        "label", "lat", "lng",
        "risk_safety", "band_safety", "risk_activity", "band_activity",
    }
    for a in addrs:
        assert set(a.keys()) == row_keys
        assert "risk_score" not in a  # no blended public score (ADR 0014)
        assert isinstance(a["label"], str) and a["label"]
        assert isinstance(a["lat"], float) and isinstance(a["lng"], float)
        assert isinstance(a["risk_safety"], float) and 0.0 <= a["risk_safety"] <= 1.0
        assert isinstance(a["risk_activity"], float) and 0.0 <= a["risk_activity"] <= 1.0
        assert a["band_safety"] in {"none", "low", "medium", "high"}
        assert a["band_activity"] in {"none", "low", "medium", "high"}


# --------------------------------------------------------------------------- #
# /analyze — shape (found + not-found are both 200, never a 500)
# --------------------------------------------------------------------------- #
def test_analyze_shape_is_pinned() -> None:
    with TestClient(app) as client:
        r = client.get("/analyze", params={"address": "100 Queen St W"})
        assert r.status_code == 200
        body = r.json()
    expected = {
        "address", "found", "matched_address",
        "risk_safety", "band_safety", "risk_activity", "band_activity",
        "narrative", "findings", "evidence", "evidence_total", "claims",
    }
    assert set(body.keys()) == expected
    assert "risk_score" not in body and "risk_band" not in body
    assert body["found"] is True
    assert isinstance(body["risk_safety"], float) and isinstance(body["risk_activity"], float)
    assert isinstance(body["findings"], list)
    assert isinstance(body["evidence"], list)
    assert isinstance(body["evidence_total"], int)
    assert isinstance(body["claims"], list)


def test_analyze_bogus_address_is_found_false_not_an_error() -> None:
    with TestClient(app) as client:
        r = client.get("/analyze", params={"address": "999 Nowhere Fake St"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is False and body["matched_address"] is None


def test_analyze_rejects_too_short_input() -> None:
    # Declarative Query bound is the first gate (length < 3 → 422, not a 500).
    with TestClient(app) as client:
        r = client.get("/analyze", params={"address": "x"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# /digest — shape + warm-cache cheapness
# --------------------------------------------------------------------------- #
def test_digest_shape_is_pinned() -> None:
    with TestClient(app) as client:
        body = client.get("/digest").json()
    assert set(body.keys()) == {"digest", "ranked"}
    assert isinstance(body["digest"], str) and body["digest"].strip()
    assert isinstance(body["ranked"], list) and body["ranked"]
    # Ranked hottest-first by the worse of the two axes (ADR 0014).
    worst = [server._worst_axis(r) for r in body["ranked"]]
    assert worst == sorted(worst, reverse=True)


def test_digest_warm_cache_serves_same_output_without_rerunning_model(monkeypatch) -> None:
    """Once a real digest is memoized, the public path serves it from the warm cache
    without re-invoking the batch model — and the output is byte-for-byte unchanged."""
    import urbanos.risk.agents.digest as digest

    with digest._lock:
        digest._cache.clear()

    calls = {"n": 0}

    class _CountingLLM:
        def chat(self, system, user, temperature=0.2):  # noqa: ARG002
            calls["n"] += 1
            return "DETERMINISTIC BRIEFING"

    # Force a real (cacheable) batch result on the cold path.
    monkeypatch.setattr(digest, "batch_llm", lambda: _CountingLLM())

    with TestClient(app) as client:
        first = client.get("/digest").json()
        assert calls["n"] == 1  # cold path ran the (stub) batch model once
        second = client.get("/digest").json()
        assert calls["n"] == 1  # warm path did NOT re-run it

    assert first["digest"] == "DETERMINISTIC BRIEFING"
    assert second["digest"] == first["digest"]  # warm output unchanged
    assert second["ranked"] == first["ranked"]


# --------------------------------------------------------------------------- #
# No stack-trace leak — internal failures become a clean generic 500
# --------------------------------------------------------------------------- #
def test_analyze_internal_error_is_clean_500_no_traceback(monkeypatch) -> None:
    def _boom(address):  # noqa: ARG001
        raise RuntimeError("secret internal detail: db at /var/lib/pg")

    monkeypatch.setattr(server._supervisor, "analyze", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/analyze", params={"address": "100 Queen St W"})
    assert r.status_code == 500
    body = r.text
    assert "Traceback" not in body and "RuntimeError" not in body
    assert "secret internal detail" not in body and "/var/lib/pg" not in body
    assert r.json()["detail"] == "analysis failed"


def test_digest_internal_error_is_clean_500_no_traceback(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("secret ranking failure")

    monkeypatch.setattr(server, "_ranked_addresses", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/digest")
    assert r.status_code == 500
    assert "Traceback" not in r.text and "secret ranking failure" not in r.text
    assert r.json()["detail"] == "digest failed"


def test_index_unreadable_asset_is_clean_500(monkeypatch) -> None:
    def _boom(*a, **k):  # noqa: ARG001
        raise OSError("disk gone")

    monkeypatch.setattr(Path, "read_text", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/")
    assert r.status_code == 500
    assert "Traceback" not in r.text and "disk gone" not in r.text
    assert r.json()["detail"] == "map UI asset unavailable"


def test_app_level_handler_catches_unexpected_errors(monkeypatch) -> None:
    """An endpoint that raises a bare (non-HTTP) exception is still rendered as a
    generic 500 by the app-level handler — no traceback in the body."""
    def _boom():
        raise ValueError("leaky internals 12345")

    # /health has no per-endpoint wrap, so this exercises the app-level catch-all.
    monkeypatch.setattr(server, "_ranked_addresses", _boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/health")
    assert r.status_code == 500
    assert "Traceback" not in r.text and "leaky internals 12345" not in r.text
    assert r.json() == {"detail": "internal server error"}


# --------------------------------------------------------------------------- #
# CORS — explicit, restrictive (no wildcard)
# --------------------------------------------------------------------------- #
def test_cors_is_not_wildcard() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/health", headers={"Origin": "https://evil.example.com"}
        )
    assert r.status_code == 200
    # A cross-origin request from a disallowed origin gets NO permissive ACAO
    # header (and certainly not "*") — same-origin only.
    acao = r.headers.get("access-control-allow-origin")
    assert acao != "*"
    assert acao != "https://evil.example.com"


def test_legal_json_no_nan_tokens() -> None:
    with TestClient(app) as client:
        for path, params in (("/health", None), ("/addresses", None), ("/digest", None)):
            body = client.get(path, params=params).json()
            json.dumps(body)  # legal JSON: no NaN/Infinity tokens
