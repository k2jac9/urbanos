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
        assert health["loaded"] == {"permits": 4, "dinesafe": 4, "311": 2, "licences": 3}

        addrs = client.get("/addresses").json()
        # Only DineSafe carries coords → 3 distinct geocoded addresses (labels are
        # whichever dataset created the node first, so compare normalized).
        labels = {normalize_address(a["label"]) for a in addrs}
        assert labels == {normalize_address(x) for x in ("100 Queen St W", "200 Bay St", "55 John St")}
        assert all(a["lat"] and a["lng"] for a in addrs)
        assert _score(addrs, "100 Queen St W") == 1.0
        assert _score(addrs, "55 John St") == 0.0

        analyze = client.get("/analyze", params={"address": "100 Queen St W"}).json()
        assert analyze["risk_score"] == 1.0

        # Map page serves.
        assert "Toronto Civic Risk Analyst" in client.get("/").text


def test_digest_ranks_hottest_first():
    with TestClient(app) as client:
        digest = client.get("/digest").json()
        assert normalize_address(digest["ranked"][0]["label"]) == normalize_address("100 Queen St W")
        assert "digest" in digest
