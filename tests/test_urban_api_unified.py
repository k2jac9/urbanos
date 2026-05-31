"""Tests for the unified Urban-OS shell surface.

The urban_os app (:8001) is becoming the single origin for the forthcoming
"Urban OS" shell: it mounts the civic address-risk app at /civic and adds the
new shell routes (/os, /classic). These tests assert that integration is real
and PURELY ADDITIVE — the existing /, /health, /scenario, /simulate, /optimize
behaviour is covered by test_urban_api.py and must stay untouched.

CRITICAL: civic's data graph is loaded by its own ``lifespan``, which does NOT
fire for a mounted sub-app under this Starlette version. The urban_os app
reproduces that load in its OWN lifespan, so /civic/addresses must return real
data when the app is driven through a ``with TestClient(...)`` block (which
enters the lifespan). We point the civic loader at the committed synthetic
fixtures (same as the civic API tests) so the data is deterministic and offline.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

# Point civic's loader at the deterministic fixtures BEFORE importing the app —
# the urban_os lifespan reads settings.data_dir to load civic's graph.
from civic_analyst.config import settings as _civic_settings

_civic_settings.data_dir = Path(__file__).resolve().parent.parent / "fixtures"

from urban_os.api import app  # noqa: E402

_ADDRESS_KEYS = {
    "label",
    "lat",
    "lng",
    "risk_safety",
    "band_safety",
    "risk_activity",
    "band_activity",
}


def test_civic_mounted_and_addresses_load_under_parent_lifespan():
    """The CRITICAL gotcha: /civic/addresses must return a non-empty list of
    address dicts — proving the parent app loaded civic's graph (the sub-app's own
    lifespan does not run when mounted)."""
    with TestClient(app) as client:
        r = client.get("/civic/addresses")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert data, "/civic/addresses must be non-empty (civic graph loaded)"
        for row in data:
            assert _ADDRESS_KEYS <= set(row.keys())
            assert isinstance(row["lat"], (int, float))
            assert isinstance(row["lng"], (int, float))


def test_civic_analyze_is_grounded_for_a_real_address():
    """/civic/analyze on a real label from /civic/addresses returns a grounded,
    found analysis dict (the full agentic read, same-origin)."""
    with TestClient(app) as client:
        addrs = client.get("/civic/addresses").json()
        assert addrs
        label = addrs[0]["label"]
        r = client.get("/civic/analyze", params={"address": label})
        assert r.status_code == 200
        body = r.json()
        assert body["found"] is True
        assert body["matched_address"]
        # Two-index read (ADR 0014): both axes present, no blended score leaks.
        assert "risk_safety" in body and "risk_activity" in body
        assert "risk_score" not in body and "risk_band" not in body


def test_civic_health_reachable_same_origin():
    """/civic/health is reachable through the mount and reports a loaded graph."""
    with TestClient(app) as client:
        r = client.get("/civic/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["graph_nodes"] > 0


def test_civic_index_served_same_origin():
    """/civic/ serves the civic map page (same-origin, no redirect off-host)."""
    with TestClient(app) as client:
        r = client.get("/civic/")
        assert r.status_code == 200
        assert "Toronto Civic Risk Analyst" in r.text


def test_root_serves_the_unified_shell():
    """/ now serves the unified "Urban OS" shell (one canvas + a lens dock)."""
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "Urban OS" in r.text
        assert "os-boot.js" in r.text          # the shell's boot module
        assert 'data-lens="city"' in r.text    # the lens dock is present
        assert "maplibre-gl" in r.text          # offline vendored asset, not a CDN


def test_classic_route_serves_the_current_urban_os_page():
    """/classic still serves the classic single-view urban_os.html (the proven
    page), distinct from the new shell at /."""
    with TestClient(app) as client:
        classic = client.get("/classic")
        assert classic.status_code == 200
        assert "Urban-OS" in classic.text       # classic page wordmark
        assert classic.text != client.get("/").text  # shell and classic differ


def test_lenses_endpoint_runs_full_stack_and_benefit_peaks_at_optimum():
    """GET /lenses runs the full four-lens stack at the exact levers and reports
    cross-domain costs. The combined_benefit at the known-good optimum
    (release 16, shelter 0.8) is positive and strictly larger than at release 0
    (where one lever does nothing), and bad params 422."""
    with TestClient(app) as client:
        r = client.get(
            "/lenses", params={"release_minutes": 16, "shelter_fraction": 0.8}
        )
        assert r.status_code == 200
        body = r.json()
        # Shape: transit / safety / business blocks + combined J fields.
        assert body["transit"]["peak_label"]
        assert isinstance(body["transit"]["peak_congestion"], (int, float))
        assert isinstance(body["transit"]["delay_cost"], (int, float))
        assert isinstance(body["safety"]["cost"], (int, float))
        assert "lost" in body["business"] and "recovered_vs_baseline" in body["business"]
        for k in ("combined_cost", "baseline_combined", "combined_benefit"):
            assert isinstance(body[k], (int, float))

        opt_benefit = body["combined_benefit"]
        assert opt_benefit > 0, "optimum must yield a positive combined benefit"
        # The additive cross-domain benefit (the shell's counter; matches /optimize)
        # is present, positive, and larger than the conservative single-objective one.
        assert isinstance(body["cross_domain_benefit"], (int, float))
        assert body["cross_domain_benefit"] > opt_benefit > 0

        # At release 0 (no intervention) the benefit collapses toward zero.
        zero = client.get(
            "/lenses", params={"release_minutes": 0, "shelter_fraction": 0.0}
        ).json()
        assert opt_benefit > zero["combined_benefit"]

        # Bounds + non-finite rejection (validated like /simulate).
        assert client.get(
            "/lenses", params={"release_minutes": -1}
        ).status_code == 422
        assert client.get(
            "/lenses", params={"release_minutes": 99}
        ).status_code == 422
        assert client.get(
            "/lenses", params={"shelter_fraction": 1.5}
        ).status_code == 422
        assert client.get(
            "/lenses", params={"shelter_fraction": "nan"}
        ).status_code == 422


def test_os_route_exists_and_404s_gracefully_until_built():
    """/os points at static/os.html; until that file exists it 404s (not 500)."""
    os_html = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "urban_os"
        / "static"
        / "os.html"
    )
    with TestClient(app) as client:
        r = client.get("/os")
        if os_html.is_file():
            assert r.status_code == 200
            assert "<html" in r.text.lower()
        else:
            assert r.status_code == 404
