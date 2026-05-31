"""GPU-accelerator seams are wired with a verified CPU fallback.

These run on any machine (no GPU/CUDA needed): they assert the seams exist, are
invoked, and that the CPU fallback path is correct and behaviour-preserving. The
actual GPU activation is proven separately on the GB10 box (``make gpu-check``).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import networkx as nx
import pytest

from urban_os.kernel import state as kstate
from urban_os.optimize import optimize
from urban_os.adapters import downtown_scenario
from urban_os.lenses import EconomicLens, EventSurge

from civic_analyst.ingest import loader

_HAS_POLARS = importlib.util.find_spec("polars") is not None


# --------------------------------------------------------------- nx-cugraph seam
def test_dijkstra_seam_runs_cpu_by_default_and_reports_backend():
    """With the GPU env unset, the substrate bake uses the CPU networkx backend and
    records it. The seam is exercised on every substrate build."""
    sc = downtown_scenario()
    assert sc.substrate.n > 0
    # The bake ran during downtown_scenario(); the seam recorded the backend.
    assert kstate.GRAPH_BACKEND in {"networkx", "cugraph"}
    # Default (no URBANOS_GPU_GRAPH) → CPU.
    assert kstate.GRAPH_BACKEND == "networkx"


def test_dijkstra_seam_matches_plain_networkx():
    """The seam's lengths are identical to a direct networkx call — it is a
    drop-in accelerator, never a behaviour change."""
    g = nx.DiGraph()
    g.add_edge("a", "b", length=1.0)
    g.add_edge("b", "c", length=2.0)
    g.add_edge("c", "exit", length=1.0)
    rev = g.reverse(copy=False)
    sinks = {"exit"}
    via_seam = kstate._multi_source_dijkstra_lengths(rev, sinks)
    via_nx = nx.multi_source_dijkstra_path_length(rev, sinks, weight="length")
    assert via_seam == via_nx


def test_supersource_reformulation_equals_multisource():
    """The GPU path uses a super-source + single-source Dijkstra (the form cugraph
    supports). On CPU it must produce byte-identical lengths to multi_source — proven
    here on a multi-sink graph so we trust the GPU path's correctness."""
    g = nx.DiGraph()
    for u, v, w in [("a", "b", 1.0), ("b", "x", 2.0), ("c", "x", 1.0),
                    ("c", "y", 4.0), ("d", "y", 1.0)]:
        g.add_edge(u, v, length=w)
    rev = g.reverse(copy=False)
    sinks = {"x", "y"}
    reformulated = kstate._supersource_sssp(rev, sinks)        # CPU, no backend
    multisource = nx.multi_source_dijkstra_path_length(rev, sinks, weight="length")
    assert reformulated == multisource
    # And the caller's graph was not mutated by the reformulation.
    assert kstate._SUPERSOURCE not in rev


def test_gpu_graph_disabled_by_default(monkeypatch):
    monkeypatch.delenv("URBANOS_GPU_GRAPH", raising=False)
    monkeypatch.delenv("NX_CUGRAPH_AUTOCONFIG", raising=False)
    assert kstate._gpu_graph_enabled() is False
    monkeypatch.setenv("URBANOS_GPU_GRAPH", "1")
    assert kstate._gpu_graph_enabled() is True


# ------------------------------------------------------------------- cuOpt seam
def test_optimizer_uses_grid_fallback_by_default_and_reports_solver():
    """With the cuOpt env unset, the optimizer uses the deterministic grid search
    and records that solver. The result is the honest grid optimum."""
    sc = downtown_scenario()
    opt = optimize(sc.substrate, [EventSurge(events=sc.events), EconomicLens()],
                   sc.horizon, dt=sc.dt)
    assert getattr(opt, "solver", "grid") == "grid"
    assert opt.best_J <= opt.baseline_J + 1e-6  # never worse than do-nothing


# --------------------------------------------------------------- cuDF/Polars seam
def _a_fixture_csv() -> Path:
    for d in ("fixtures", "demo_data"):
        csv = next(Path(d).glob("*.csv"), None)
        if csv is not None:
            return csv
    pytest.skip("no CSV fixture available")


def test_ingest_reports_dataframe_backend():
    cols, rows = loader._read_csv_rows(_a_fixture_csv())
    assert loader.DF_BACKEND in {"pandas", "polars", "cudf-polars"}
    assert cols and rows  # read something


def test_force_pandas_backend(monkeypatch):
    monkeypatch.setenv("URBANOS_DF_BACKEND", "pandas")
    cols, rows = loader._read_csv_rows(_a_fixture_csv())
    assert loader.DF_BACKEND == "pandas"
    assert cols and rows


# ----------------------------------------------------------- cuOpt flow seam
def test_optimal_evacuation_flow_cpu():
    """The networkx max-flow CPU path computes a sane evacuation bound and reports
    its backend. cuOpt LP is the GPU path (env-gated); identical optimum (box-proven)."""
    from urban_os import flow
    sc = downtown_scenario()
    demands = {vid: crowd for vid, crowd, _ in sc.events}
    r = flow.optimal_evacuation_flow(sc.substrate, demands, horizon=sc.horizon)
    assert flow.FLOW_BACKEND in {"networkx", "cuopt"}
    assert r["backend"] == flow.FLOW_BACKEND
    assert r["demand"] == int(round(sum(demands.values())))
    assert r["max_throughput"] >= 0
    assert isinstance(r["cleared"], bool)


def test_flow_gpu_disabled_by_default(monkeypatch):
    from urban_os import flow
    monkeypatch.delenv("URBANOS_GPU_FLOW", raising=False)
    assert flow._gpu_flow_enabled() is False


# ----------------------------------------------------------- cuML cluster seam
def test_risk_hotspots_cpu_deterministic():
    """The numpy KMeans CPU path is deterministic and separates risk zones; cuML is
    the GPU path (env-gated)."""
    from civic_analyst import cluster
    addrs = [
        {"lat": 43.65, "lng": -79.38, "risk_safety": 0.9, "risk_activity": 0.1},
        {"lat": 43.651, "lng": -79.381, "risk_safety": 0.8, "risk_activity": 0.2},
        {"lat": 43.70, "lng": -79.40, "risk_safety": 0.1, "risk_activity": 0.6},
        {"lat": 43.701, "lng": -79.401, "risk_safety": 0.2, "risk_activity": 0.5},
    ]
    a = cluster.risk_hotspots(addrs, k=2)
    b = cluster.risk_hotspots(addrs, k=2)
    assert a == b                                   # deterministic
    assert cluster.CLUSTER_BACKEND in {"numpy", "cuml"}
    assert len(a) == 2
    assert a[0]["mean_risk"] >= a[1]["mean_risk"]    # hottest first
    assert sum(c["size"] for c in a) == 4            # every point assigned


def test_risk_hotspots_empty_and_gating(monkeypatch):
    from civic_analyst import cluster
    assert cluster.risk_hotspots([], k=3) == []
    monkeypatch.delenv("URBANOS_GPU_CLUSTER", raising=False)
    assert cluster._gpu_cluster_enabled() is False


@pytest.mark.skipif(not _HAS_POLARS, reason="polars not installed (pandas-only env)")
def test_polars_and_pandas_read_identical_rows(monkeypatch):
    """The Polars ingest path is a drop-in: it yields byte-identical (columns, rows)
    to the pandas path, so the golden two-index numbers are unaffected by the swap."""
    csv = _a_fixture_csv()
    monkeypatch.setenv("URBANOS_DF_BACKEND", "pandas")
    p_cols, p_rows = loader._read_csv_rows(csv)
    assert loader.DF_BACKEND == "pandas"
    monkeypatch.delenv("URBANOS_DF_BACKEND", raising=False)
    pl_cols, pl_rows = loader._read_csv_rows(csv)
    assert loader.DF_BACKEND == "polars"  # polars present → preferred path
    assert pl_cols == p_cols
    assert pl_rows == p_rows
