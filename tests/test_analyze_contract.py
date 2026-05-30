"""Public-API contract + invariant regression lane.

Pins the shape of /health, /addresses, /analyze and the cross-dataset *fusion*
and *grounded-citation* invariants against the committed real downtown slice in
`demo_data/`. These tests are **offline-safe**: they never reach a real model, so
the narrator falls back to deterministic claims — therefore everything asserted
here is STRUCTURE and INVARIANTS, never exact model prose.

Run them with the LLM unreachable, e.g.:
    PYTHONPATH=src LLM_BASE_URL="http://127.0.0.1:9" \
        python -m pytest -q tests/test_analyze_contract.py

If `demo_data/` is absent the demo-slice cases skip gracefully so CI without the
slice still passes.
"""
from __future__ import annotations

import numbers
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civic_analyst.config import settings

# The committed real downtown slice. We do NOT mutate settings.data_dir at import
# time (that races with other modules' import-time assignments by collection order);
# the `client` fixture pins it to this slice only around its own lifespan and then
# restores it, and the app's lifespan reloads the graph cleanly, so this lane is
# fully order-independent.
_DEMO = Path(__file__).resolve().parent.parent / "demo_data"
_HAS_DEMO = _DEMO.is_dir() and any(_DEMO.glob("*.csv"))

from civic_analyst.api.server import app  # noqa: E402

HERO = "500 Bloor St W"  # the 3-dataset fusion pin (permits + failed inspection + licence)

_demo_required = pytest.mark.skipif(
    not _HAS_DEMO, reason="demo_data/ slice not present; skipping real-slice contract cases"
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    # The app/graph are module-global singletons shared with other test modules,
    # and settings.data_dir is mutated at import time by whichever module imports
    # the app last. Pin it to the demo slice right before lifespan runs (which
    # reloads the graph), then restore — so this lane is order-independent and
    # doesn't leak demo data into the synthetic-fixture tests.
    prev = settings.data_dir
    if _HAS_DEMO:
        settings.data_dir = _DEMO
    try:
        with TestClient(app) as c:
            yield c
    finally:
        settings.data_dir = prev


def _is_unit_interval(x: object) -> bool:
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and 0.0 <= float(x) <= 1.0


# --------------------------------------------------------------------------- #
# /health — load summary contract                                             #
# --------------------------------------------------------------------------- #
def test_health_contract(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "graph_nodes" in body
    assert "loaded" in body
    assert isinstance(body["graph_nodes"], int)
    assert isinstance(body["loaded"], dict)


# --------------------------------------------------------------------------- #
# /addresses — pin list contract                                              #
# --------------------------------------------------------------------------- #
@_demo_required
def test_addresses_contract(client: TestClient) -> None:
    addrs = client.get("/addresses").json()
    assert isinstance(addrs, list)
    assert addrs, "demo slice should yield geocoded addresses"
    for a in addrs:
        assert {"label", "lat", "lng", "risk_score"} <= a.keys()
        assert isinstance(a["label"], str) and a["label"]
        assert isinstance(a["lat"], numbers.Real) and not isinstance(a["lat"], bool)
        assert isinstance(a["lng"], numbers.Real) and not isinstance(a["lng"], bool)
        assert _is_unit_interval(a["risk_score"]), a["risk_score"]


# --------------------------------------------------------------------------- #
# /analyze — full report contract + fusion + grounded-citation invariants     #
# --------------------------------------------------------------------------- #
def _analyze(client: TestClient, address: str) -> dict:
    return client.get("/analyze", params={"address": address}).json()


@_demo_required
def test_analyze_response_keys(client: TestClient) -> None:
    body = _analyze(client, HERO)
    expected = {
        "address",
        "found",
        "matched_address",
        "risk_score",
        "risk_band",
        "narrative",
        "findings",
        "evidence",
        "evidence_total",
        "claims",
    }
    assert expected <= body.keys(), expected - body.keys()


@_demo_required
def test_analyze_hero_found_and_high_band(client: TestClient) -> None:
    body = _analyze(client, HERO)
    assert body["found"] is True
    assert body["risk_band"] == "high"
    assert _is_unit_interval(body["risk_score"])


@_demo_required
def test_analyze_evidence_item_shape(client: TestClient) -> None:
    body = _analyze(client, HERO)
    evidence = body["evidence"]
    assert isinstance(evidence, list) and evidence
    for e in evidence:
        assert {"tag", "dataset", "kind"} <= e.keys(), e


@_demo_required
def test_analyze_fusion_three_datasets_with_licence(client: TestClient) -> None:
    """Fusion invariant: the hero pin's evidence spans 3 distinct datasets and
    includes a licence row — the cross-dataset linking the demo is built on."""
    body = _analyze(client, HERO)
    evidence = body["evidence"]
    datasets = {e["dataset"] for e in evidence}
    assert len(datasets) >= 3, f"expected >=3 distinct datasets, got {datasets}"
    kinds = {e["kind"] for e in evidence}
    assert "licence" in kinds, f"expected a licence row, got kinds {kinds}"


@_demo_required
def test_analyze_evidence_total_at_least_shown(client: TestClient) -> None:
    body = _analyze(client, HERO)
    assert isinstance(body["evidence_total"], int)
    assert body["evidence_total"] >= len(body["evidence"])


@_demo_required
def test_analyze_no_dangling_citations(client: TestClient) -> None:
    """Grounded-citation invariant: every claim's source is None or an object
    whose tag is a real evidence tag — no fabricated / dangling citations."""
    body = _analyze(client, HERO)
    evidence_tags = {e["tag"] for e in body["evidence"]}
    claims = body["claims"]
    assert isinstance(claims, list) and claims
    for c in claims:
        assert "text" in c and "source" in c, c
        src = c["source"]
        if src is None:
            continue
        assert isinstance(src, dict), src
        assert "tag" in src, src
        assert src["tag"] in evidence_tags, f"dangling citation {src['tag']!r} not in {evidence_tags}"


@_demo_required
def test_analyze_is_deterministic(client: TestClient) -> None:
    """Same address twice → identical risk_score and risk_band (LLM-free path)."""
    a = _analyze(client, HERO)
    b = _analyze(client, HERO)
    assert a["risk_score"] == b["risk_score"]
    assert a["risk_band"] == b["risk_band"]


# --------------------------------------------------------------------------- #
# Bogus address — graceful not-found, never a 500                             #
# --------------------------------------------------------------------------- #
def test_analyze_bogus_address_not_found(client: TestClient) -> None:
    resp = client.get("/analyze", params={"address": "999 Nowhere Fake St"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["found"] is False
