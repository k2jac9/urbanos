"""Offline + clarity/a11y gate for the civic map page (``/`` → map.html).

Mirrors tests/test_urban_ui_offline.py for the civic surface: the public map must
stay 100% offline (no CDN/tile hosts, vendored assets only) and keep its a11y +
ADR-0026 clarity affordances (skip link, legend, dataset-provenance chips, motion
honouring the OS preference).
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from civic_analyst.api.server import app

client = TestClient(app)

_FORBIDDEN = (
    "unpkg.com", "jsdelivr.net", "cdnjs", "esm.sh", "googleapis.com", "gstatic.com",
    "tile.openstreetmap.org", "a.tile.", "b.tile.", "basemaps.cartocdn",
    "api.mapbox.com", "demotiles.maplibre.org", "raw.githubusercontent.com", "://cdn.",
)


@pytest.fixture(scope="module")
def page() -> str:
    r = client.get("/")
    assert r.status_code == 200
    return r.text


def test_is_the_civic_map_page(page: str) -> None:
    assert "Toronto Civic Risk Analyst" in page and "<html" in page.lower()


def test_no_known_cdn_or_tile_hosts(page: str) -> None:
    hits = [s for s in _FORBIDDEN if s in page.lower()]
    assert not hits, f"civic map references forbidden external host(s): {hits}"


def test_no_external_http_urls(page: str) -> None:
    scrubbed = page.replace("${location.origin}", "")
    urls = re.findall(r"https?://[A-Za-z0-9.\-]+", scrubbed)
    allowed = {"https://www.openstreetmap.org", "http://www.openstreetmap.org"}
    bad = [u for u in urls if u not in allowed]
    assert not bad, f"civic map must not reference external URLs, found: {bad}"


def test_references_vendored_offline_assets(page: str) -> None:
    for asset in ("/static/vendor/maplibre-gl.js", "/static/vendor/tokens.css",
                  "/static/toronto.pmtiles"):
        assert asset in page, f"civic map missing offline asset {asset}"


@pytest.mark.parametrize(
    "marker",
    [
        "<h1>Toronto Civic Risk Analyst",   # page heading
        'class="skip"',                     # a11y: skip link
        'id="legend"',                      # clarity: risk legend (shape + colour)
        'class="provchips"',                # ADR-0026: dataset provenance chips
        "prefers-reduced-motion",           # a11y: motion honours OS preference
    ],
)
def test_clarity_and_a11y_present(page: str, marker: str) -> None:
    assert marker in page, f"civic map missing clarity/a11y element: {marker}"
