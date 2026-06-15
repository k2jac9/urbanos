"""Phase 0 — time-marginal count ingest + per-node observed-series fusion.

Covers civic_analyst.ingest.timeseries.load_counts (parse / bbox / hygiene) and the
urban_os adapter's observed_counts_by_node (proximity fusion + synthetic fallback).
All offline: a tiny in-test slice + injected providers, no network, no committed data.
"""
from __future__ import annotations

from civic_analyst.ingest import timeseries
from urban_os.adapters.toronto import downtown_substrate, observed_counts_by_node

# A tiny normalized slice (same schema as demo_data/tmc__downtown.csv). Includes a
# Vancouver row (out of the Toronto bbox) and a blank-time row that must be dropped.
_SLICE = """location,lat,lng,date,time_start,mode,volume
Union Stn,43.6452,-79.3806,2026-06-01,2026-06-01T07:30:00,ped,100
Union Stn,43.6452,-79.3806,2026-06-01,2026-06-01T07:45:00,ped,140
Union Stn,43.6452,-79.3806,2026-06-01,2026-06-01T08:00:00,ped,90
Far Away,49.2827,-123.1207,2026-06-01,2026-06-01T07:30:00,ped,9999
King St,43.6489,-79.3777,2026-06-01,2026-06-01T07:30:00,bike,12
Bad Row,43.6500,-79.3800,2026-06-01,,ped,55
"""


def _slice_dir(tmp_path):
    (tmp_path / "tmc__downtown.csv").write_text(_SLICE, encoding="utf-8")
    return tmp_path


def test_load_counts_parses_filters_and_normalizes(tmp_path):
    recs = timeseries.load_counts(_slice_dir(tmp_path))
    locs = {r["location"] for r in recs}
    # Out-of-Toronto (Vancouver) and the blank-time row are dropped.
    assert "Far Away" not in locs
    assert all(r["lat"] < 44 and r["lng"] < -79 for r in recs)
    # ISO timestamps parsed to minutes-from-midnight (07:30 -> 450).
    union = sorted(r["minute"] for r in recs if r["location"] == "Union Stn")
    assert union == [450.0, 465.0, 480.0]
    assert {r["mode"] for r in recs} == {"ped", "bike"}


def test_load_counts_absent_dir_is_empty(tmp_path):
    assert timeseries.load_counts(tmp_path / "does_not_exist") == []


def test_observed_counts_by_node_wellformed(tmp_path):
    dd = _slice_dir(tmp_path)
    sub = downtown_substrate()
    prov = lambda: timeseries.load_counts(dd)  # noqa: E731 — terse injected provider
    series = observed_counts_by_node(sub, mode="ped", provider=prov)
    # One series per substrate node; non-negative; time-axis rebased so first bin is 0.
    assert set(series) == set(sub.ids)
    assert all(v >= 0 for s in series.values() for v in s.values())
    assert all(min(s) == 0.0 for s in series.values() if s)
    # ped-only filter keeps the three Union bins (the bike row is excluded).
    assert sorted(series["union"]) == [0.0, 15.0, 30.0]
    # Deterministic.
    assert series == observed_counts_by_node(sub, mode="ped", provider=prov)


def test_observed_counts_synthetic_fallback_when_empty():
    sub = downtown_substrate()
    series = observed_counts_by_node(sub, provider=lambda: [])  # empty -> synthetic
    assert set(series) == set(sub.ids)
    assert all(v >= 0 for s in series.values() for v in s.values())
    # A non-sink relay carries real throughput; a sink's series is all-zero.
    assert any(v > 0 for v in series["union"].values())
    assert all(v == 0 for v in series["sink_line1"].values())
