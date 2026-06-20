"""TTC subway boardings source for TransitLoad (ADR-0031) — real magnitude, modelled shape.

Covers the adapter (proximity-distribution of real per-station boardings + the modelled
intraday shape, synthetic fallback), the committed real slice, and the scenarios wiring
(opt-in source choice; golden numbers untouched when off). Offline: injected providers +
the committed slice, no network.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from urbanos.risk.ingest import timeseries
from urbanos.kernel.adapters import toronto
from urbanos.kernel.adapters.toronto import (
    TTC_BOARDINGS_PROVENANCE,
    downtown_substrate,
    ttc_boardings_by_node,
)
from urbanos.kernel.lenses import TransitLoadLens
from urbanos.kernel.scenarios import default_lens_stack

# A tiny injected slice: real-shaped {location, lat, lng, value} at two downtown stations.
_UNION = {"location": "UNION", "lat": 43.6452, "lng": -79.3806, "value": 128655.0}
_OSGOODE = {"location": "OSGOODE", "lat": 43.6505, "lng": -79.3866, "value": 23669.0}


def _provider(recs):
    return lambda: list(recs)


def test_ttc_boardings_real_magnitude_lands_on_right_node():
    sub = downtown_substrate()
    series = ttc_boardings_by_node(sub, provider=_provider([_UNION, _OSGOODE]))
    assert set(series) == set(sub.ids)
    # 15-min grid over the sim window; non-negative; sinks carry nothing.
    assert all(min(s) == 0.0 and max(s) == 120.0 for s in series.values() if s)
    assert all(v >= 0 for s in series.values() for v in s.values())
    assert all(v == 0 for v in series["sink_line1"].values())
    # The big station (Union, 128k) drives far more boardings at its node than the small
    # one (Osgoode, 24k) at its node — real magnitude preserved through the fusion.
    assert sum(series["union"].values()) > sum(series["osgoode"].values()) > 0


def test_ttc_boardings_modelled_share_and_finite():
    sub = downtown_substrate()
    series = ttc_boardings_by_node(sub, provider=_provider([_UNION]))
    union_total = sum(series["union"].values())
    # The window total is the real node magnitude scaled by the documented PM share — a
    # fraction of the daily boardings, never more than the daily total reaches a node.
    assert 0 < union_total < 128655.0
    assert all(np.isfinite(v) for s in series.values() for v in s.values())
    assert TTC_BOARDINGS_PROVENANCE == "real-magnitude/modelled-shape"


def test_ttc_boardings_synthetic_fallback_when_empty():
    sub = downtown_substrate()
    series = ttc_boardings_by_node(sub, provider=lambda: [])  # empty -> synthetic
    assert set(series) == set(sub.ids)
    assert any(v > 0 for v in series["union"].values())
    assert all(v == 0 for v in series["sink_line1"].values())


def test_ttc_boardings_determinism():
    sub = downtown_substrate()
    p = _provider([_UNION, _OSGOODE])
    assert ttc_boardings_by_node(sub, provider=p) == ttc_boardings_by_node(sub, provider=p)


def test_committed_ttc_slice_is_real_downtown_boardings():
    """Guard the committed real slice: demo_data/ttc_boardings__downtown.csv parses to
    downtown subway stations with positive boardings (real TTC station usage)."""
    demo = Path(__file__).resolve().parent.parent / "demo_data"
    recs = timeseries.load_station_values(demo, key="ttc_boardings", value_col="boardings")
    assert recs, "expected a committed ttc_boardings__downtown.csv slice"
    assert all(43.62 <= r["lat"] <= 43.69 and -79.43 <= r["lng"] <= -79.34 for r in recs)
    assert all(r["value"] > 0 for r in recs)
    assert any(r["location"] == "UNION" for r in recs)


def test_scenarios_transit_source_choice():
    sc = toronto.downtown_scenario()
    # Off by default → no TransitLoad lens at all (golden numbers untouched).
    assert not any(isinstance(ln, TransitLoadLens) for ln in default_lens_stack(sc))
    # tmc (default) and ttc both add exactly one TransitLoad lens when opted in.
    tmc = [ln for ln in default_lens_stack(sc, transit_load=True) if isinstance(ln, TransitLoadLens)]
    ttc = [ln for ln in default_lens_stack(sc, transit_load=True, transit_source="ttc")
           if isinstance(ln, TransitLoadLens)]
    assert len(tmc) == 1 and len(ttc) == 1
