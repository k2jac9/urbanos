"""Offline-safety regression test for the Urban-OS map UI.

The demo MUST stay 100% on-device: the page may reference ONLY same-origin
``/static`` assets (vendored MapLibre + PMTiles) and same-origin API endpoints.
A single stray ``https://cdn...`` script tag would silently break the offline
demo on the GX10 (no network) — so we assert it can never sneak in.

These tests fetch ``/`` through a FastAPI ``TestClient`` (exercising the real
route, not just the file on disk) and assert:
  1. No external/CDN/tile-server URLs appear anywhere in the HTML.
  2. The vendored offline assets are referenced by their ``/static`` paths.
  3. The key interactive UI hooks exist (time slider, heatmap layer + toggle,
     release lever, before/after optimize panel) so a refactor that drops one
     fails loudly.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from urban_os.api import app

client = TestClient(app)


@pytest.fixture(scope="module")
def page() -> str:
    """The served map page (via the real route, not a raw file read)."""
    r = client.get("/")
    assert r.status_code == 200
    return r.text


def test_index_serves_and_is_the_urban_os_page(page: str) -> None:
    assert "Urban-OS" in page
    assert "<html" in page.lower()


# ---- 1. Offline invariant: no external / CDN / tile-server URLs ------------

# Hosts/patterns that would each break the offline demo if present.
_FORBIDDEN_SUBSTRINGS = (
    "unpkg.com",
    "jsdelivr.net",
    "cdnjs",
    "cdn.jsdelivr",
    "cdn.skypack",
    "esm.sh",
    "googleapis.com",
    "gstatic.com",
    "tile.openstreetmap.org",
    "tiles.openstreetmap.org",
    "a.tile.",
    "b.tile.",
    "tile.osm",
    "basemaps.cartocdn",
    "api.mapbox.com",
    "demotiles.maplibre.org",
    "raw.githubusercontent.com",
    "://cdn.",
)


def test_no_known_cdn_or_tile_hosts(page: str) -> None:
    low = page.lower()
    hits = [s for s in _FORBIDDEN_SUBSTRINGS if s in low]
    assert not hits, f"offline UI references forbidden external host(s): {hits}"


def test_no_external_http_urls(page: str) -> None:
    """No absolute http(s):// URL may point off-origin.

    The only acceptable absolute-looking strings are non-fetched references such
    as the OSM attribution credit; an actual external *resource* URL has a host
    after the scheme. We allow ``://${location.origin}`` (a runtime same-origin
    template) and bare scheme mentions, and reject any concrete external host.
    """
    # Strip the one legitimate runtime same-origin template before scanning.
    scrubbed = page.replace("${location.origin}", "")
    # Any http(s):// immediately followed by a host character is suspect.
    urls = re.findall(r"https?://[A-Za-z0-9.\-]+", scrubbed)
    # OpenStreetMap.org may legitimately appear ONLY as an attribution credit
    # string (not a fetched tile/script). Allow that exact attribution host but
    # nothing else.
    allowed_hosts = {"https://www.openstreetmap.org", "http://www.openstreetmap.org"}
    bad = [u for u in urls if u not in allowed_hosts]
    assert not bad, f"offline UI must not reference external URLs, found: {bad}"


def test_no_protocol_relative_urls(page: str) -> None:
    """``//host/...`` (protocol-relative) would also reach the network."""
    # Allow JS comments (`// ...`) and same-origin paths (`/static`), reject `//host`.
    assert not re.search(r'(?:src|href)\s*=\s*["\']//', page), (
        "protocol-relative resource URL found (would hit the network)"
    )


# ---- 2. Vendored offline assets are referenced by /static path ------------


@pytest.mark.parametrize(
    "asset",
    [
        "/static/vendor/maplibre-gl.js",
        "/static/vendor/maplibre-gl.css",
        "/static/vendor/pmtiles.js",
        "/static/toronto.pmtiles",
    ],
)
def test_references_vendored_offline_asset(page: str, asset: str) -> None:
    assert asset in page, f"expected the page to load the offline asset {asset}"


@pytest.mark.parametrize(
    "asset",
    [
        "/static/vendor/maplibre-gl.js",
        "/static/vendor/maplibre-gl.css",
        "/static/vendor/pmtiles.js",
    ],
)
def test_vendored_asset_is_actually_served(asset: str) -> None:
    """The referenced asset must really be mounted at the same origin."""
    assert client.get(asset).status_code == 200


def test_pmtiles_basemap_supports_range_requests() -> None:
    """PMTiles is read with HTTP Range requests; the mount must honour them."""
    r = client.get("/static/toronto.pmtiles", headers={"Range": "bytes=0-15"})
    assert r.status_code in (200, 206)


def test_pmtiles_referenced_as_same_origin_runtime_url(page: str) -> None:
    """The pmtiles:// URL is built from location.origin at runtime (same-origin)."""
    assert "pmtiles://" in page
    assert "${location.origin}/static/toronto.pmtiles" in page


# ---- 3. Key interactive UI hooks are present ------------------------------


@pytest.mark.parametrize(
    "element_id",
    [
        'id="time"',          # time-slider scrubbing /simulate frames
        'id="release"',       # release-minutes lever (re-calls /simulate)
        'id="play"',          # play/pause the time scrub
        'id="heatmap-toggle"',  # heatmap on/off control (HTML button)
        'id="opt-btn"',       # "find best intervention" → /optimize
        'id="opt-out"',       # before/after optimize output panel
    ],
)
def test_ui_hook_present(page: str, element_id: str) -> None:
    assert element_id in page, f"missing required UI hook: {element_id}"


def test_heatmap_layer_is_wired(page: str) -> None:
    """A real MapLibre heatmap layer (not just colored circles) must exist."""
    assert "'heatmap'" in page or '"heatmap"' in page
    assert "type: 'heatmap'" in page or 'type: "heatmap"' in page
    assert "heatmap-weight" in page  # weighted by congestion/risk


def test_calls_the_three_same_origin_endpoints(page: str) -> None:
    """The UI consumes /scenario, /simulate and /optimize (same-origin paths)."""
    assert "fetch('/scenario')" in page or 'fetch("/scenario")' in page
    assert "/simulate?release_minutes=" in page
    assert "fetch('/optimize')" in page or 'fetch("/optimize")' in page


def test_release_lever_recalls_simulate(page: str) -> None:
    """The release lever must trigger a /simulate re-fetch (the lever's job)."""
    assert "loadSim(" in page
    assert "release" in page


def test_before_after_panel_uses_optimize_fields(page: str) -> None:
    """The before/after panel renders the optimizer's cited insight + savings."""
    assert "baseline_peak" in page
    assert "best_peak" in page
    assert "savings" in page
    assert "insight" in page
