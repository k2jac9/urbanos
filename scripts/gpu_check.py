"""Prove which compute backend each RAPIDS seam actually used (run on the box).

    URBANOS_GPU_GRAPH=1 URBANOS_GPU_DF=1 PYTHONPATH=src python scripts/gpu_check.py
    # or simply:  make gpu-check

Exercises the two genuinely-wired GPU seams and reports the backend that RAN — so a
judge / teammate can verify the GPU path is invoked, not just claimed. Exits 0
regardless (CPU fallback is a valid, honest outcome off the box); the VALUE is the
printed backend. On the GB10 with requirements-gpu.txt installed and the env vars
set, expect ``cugraph`` and ``cudf-polars``; anywhere else, ``networkx`` / ``polars``
/ ``pandas``.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def main() -> int:
    print("=== RAPIDS GPU seam check ===")
    print(f"env: URBANOS_GPU_GRAPH={os.environ.get('URBANOS_GPU_GRAPH', '')!r} "
          f"URBANOS_GPU_DF={os.environ.get('URBANOS_GPU_DF', '')!r}")
    print("installed: " + ", ".join(
        f"{m}={_have(m)}" for m in
        ("nx_cugraph", "cudf", "cudf_polars", "polars", "cuopt", "cuml")
    ))

    # 1) nx-cugraph seam — building the scenario bakes the substrate shortest paths.
    from urban_os.adapters import downtown_scenario
    from urban_os.kernel import state as kstate

    sc = downtown_scenario()
    print(f"\n[graph]  substrate={sc.substrate.n} nodes  ->  GRAPH_BACKEND="
          f"{kstate.GRAPH_BACKEND}")

    # 2) cuDF/Polars seam — read a CSV through the ingest path.
    from civic_analyst.ingest import loader

    csv = next(Path("demo_data").glob("*.csv"), None) or next(Path("fixtures").glob("*.csv"), None)
    if csv is not None:
        cols, rows = loader._read_csv_rows(csv)
        print(f"[ingest] read {csv.name}: {len(rows)} rows, {len(cols)} cols  ->  "
              f"DF_BACKEND={loader.DF_BACKEND}")
    else:
        print("[ingest] no CSV found under demo_data/ or fixtures/ — skipped")

    # 3) cuOpt seam — optimal evacuation max-flow on the substrate.
    from urban_os import flow
    demands = {vid: crowd for vid, crowd, _ in sc.events}
    fr = flow.optimal_evacuation_flow(sc.substrate, demands, horizon=sc.horizon)
    print(f"[flow]   max_throughput={fr['max_throughput']} / demand={fr['demand']}  ->  "
          f"FLOW_BACKEND={flow.FLOW_BACKEND}")

    # 4) cuML seam — spatial risk-hotspot clustering of the civic addresses.
    from civic_analyst import cluster
    try:
        from civic_analyst import mcp_server as civ
        civ.load()
        addrs = [a for a in civ.top_risk(limit=2000) if a.get("lat") is not None]
    except Exception:
        addrs = []
    hotspots = cluster.risk_hotspots(addrs, k=4) if addrs else []
    print(f"[cluster] {len(addrs)} addresses -> {len(hotspots)} hotspots  ->  "
          f"CLUSTER_BACKEND={cluster.CLUSTER_BACKEND}")

    # 5) PhysicsNeMo/Modulus surrogate seam (ADR-0027) — interface + exact-kernel ref.
    from urban_os import surrogate
    sur = surrogate.JSurrogate.load(["release_min"])  # any lever name; None unless trained
    print(f"[surrogate] enabled={surrogate.surrogate_enabled()} loaded={sur is not None}  ->  "
          f"SURROGATE_BACKEND={'physicsnemo' if sur is not None else 'none'} "
          f"(exact kernel decides regardless)")

    backends = {
        "graph": kstate.GRAPH_BACKEND, "ingest": loader.DF_BACKEND,
        "flow": flow.FLOW_BACKEND, "cluster": cluster.CLUSTER_BACKEND,
    }
    gpu = {k: v for k, v in backends.items()
           if v in ("cugraph", "cudf-polars", "cuopt", "cuml")}
    print(f"\nGPU paths active: {gpu or 'none'}")
    print("RESULT:", "GPU path active ✅" if gpu else
          "CPU fallback (honest) — install requirements-gpu.txt + set env on the box")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
