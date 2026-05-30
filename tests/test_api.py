"""End-to-end API tests against the synthetic fixtures."""
from pathlib import Path

from fastapi.testclient import TestClient

from civic_analyst.config import settings
from civic_analyst.graph.builder import normalize_address

# Point the loader at the fixtures regardless of import order; lifespan reads this.
settings.data_dir = Path(__file__).resolve().parent.parent / "fixtures"

from civic_analyst.api.server import app  # noqa: E402


def _score(addrs: list[dict], address: str) -> float:
    key = normalize_address(address)
    return next(a["risk_score"] for a in addrs if normalize_address(a["label"]) == key)


def test_endpoints_with_fixtures():
    with TestClient(app) as client:
        health = client.get("/health").json()
        # Existing keys must stay intact (the map + other tests rely on them).
        assert health["status"] == "ok"
        assert health["graph_nodes"] > 0
        assert health["loaded"] == {"permits": 4, "dinesafe": 4, "311": 2, "licences": 3}
        # New keys: model names + whether a real digest is already cached.
        assert health["interactive_model"] == settings.llm_model
        assert health["batch_model"] == settings.llm_batch_model
        assert isinstance(health["digest_cached"], bool)

        addrs = client.get("/addresses").json()
        # Only DineSafe carries coords → 3 distinct geocoded addresses (labels are
        # whichever dataset created the node first, so compare normalized).
        labels = {normalize_address(a["label"]) for a in addrs}
        assert labels == {normalize_address(x) for x in ("100 Queen St W", "200 Bay St", "55 John St")}
        assert all(a["lat"] and a["lng"] for a in addrs)
        assert _score(addrs, "100 Queen St W") == 0.826
        assert _score(addrs, "55 John St") == 0.0

        analyze = client.get("/analyze", params={"address": "100 Queen St W"}).json()
        assert analyze["risk_score"] == 0.826
        assert analyze["found"] is True and analyze["risk_band"] == "high"

        # Not-found is distinct from clean (#2): a real query echoes; junk does not.
        missing = client.get("/analyze", params={"address": "999 Nowhere Rd"}).json()
        assert missing["found"] is False and missing["matched_address"] is None
        assert missing["risk_score"] == 0.0

        # Map page serves and uses vendored, offline MapLibre + PMTiles (no CDN).
        page = client.get("/").text
        assert "Toronto Civic Risk Analyst" in page
        assert "/static/vendor/maplibre-gl.js" in page
        assert "/static/vendor/pmtiles.js" in page
        assert "/static/toronto.pmtiles" in page
        assert "unpkg.com" not in page
        assert client.get("/static/vendor/maplibre-gl.js").status_code == 200
        assert client.get("/static/vendor/pmtiles.js").status_code == 200
        # The PMTiles file must serve with HTTP range support (pmtiles.js needs it).
        ranged = client.get("/static/toronto.pmtiles", headers={"Range": "bytes=0-15"})
        assert ranged.status_code == 206
        assert len(ranged.content) == 16


def test_digest_ranks_hottest_first():
    with TestClient(app) as client:
        digest = client.get("/digest").json()
        assert normalize_address(digest["ranked"][0]["label"]) == normalize_address("100 Queen St W")
        assert "digest" in digest
