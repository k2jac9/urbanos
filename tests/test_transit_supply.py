"""Transit-supply overlay (ADR-0032) — real GTFS scheduled evening departures per node.

Covers the adapter (proximity fusion + synthetic fallback), the committed real slice, and the
/overlays surfacing. Offline: injected providers + the committed slice, no network.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from urbanos.risk.ingest import timeseries
from urbanos.kernel.adapters.toronto import (
    TRANSIT_SUPPLY_PROVENANCE,
    downtown_substrate,
    transit_supply_by_node,
)
from urbanos.kernel.api import app

_NEAR_UNION = {"location": "stop_a", "lat": 43.6452, "lng": -79.3806, "value": 300.0}
_NEAR_ST_PATRICK = {"location": "stop_b", "lat": 43.6549, "lng": -79.3884, "value": 40.0}


def _prov(recs):
    return lambda: list(recs)


def test_transit_supply_per_node_real_magnitude():
    sub = downtown_substrate()
    out = transit_supply_by_node(sub, provider=_prov([_NEAR_UNION, _NEAR_ST_PATRICK]))
    assert set(out) == set(sub.ids)
    assert all(v >= 0 and np.isfinite(v) for v in out.values())
    # The high-supply stop near Union drives Union's supply above St Patrick's.
    assert out["union"] > out["st_patrick"] > 0
    assert TRANSIT_SUPPLY_PROVENANCE == "real/measured"


def test_transit_supply_synthetic_fallback_when_empty():
    sub = downtown_substrate()
    out = transit_supply_by_node(sub, provider=lambda: [])  # empty -> synthetic
    assert set(out) == set(sub.ids) and any(v > 0 for v in out.values())


def test_transit_supply_determinism():
    sub = downtown_substrate()
    p = _prov([_NEAR_UNION, _NEAR_ST_PATRICK])
    assert transit_supply_by_node(sub, provider=p) == transit_supply_by_node(sub, provider=p)


def test_committed_transit_supply_slice_is_real_downtown():
    """Guard the committed real slice: demo_data/transit_supply__downtown.csv parses to
    downtown stops with positive scheduled-departure counts (real GTFS supply)."""
    demo = Path(__file__).resolve().parent.parent / "demo_data"
    recs = timeseries.load_station_values(demo, key="transit_supply", value_col="departures")
    assert recs, "expected a committed transit_supply__downtown.csv slice"
    assert all(43.62 <= r["lat"] <= 43.69 and -79.43 <= r["lng"] <= -79.34 for r in recs)
    assert all(r["value"] > 0 for r in recs)


def test_overlays_endpoint_includes_transit_supply():
    nodes = TestClient(app).get("/overlays").json()["nodes"]
    assert nodes and all(
        "transit_supply" in n and 0.0 <= n["transit_supply"] <= 1.0 for n in nodes
    )
    # normalised 0..1 → peaks at exactly 1.0 (synthetic fallback active in tests).
    assert max(n["transit_supply"] for n in nodes) == 1.0
