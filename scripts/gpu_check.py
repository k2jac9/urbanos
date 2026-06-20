"""Prove which compute backend each RAPIDS seam actually used (run on the box).

    URBANOS_GPU_GRAPH=1 URBANOS_GPU_DF=1 PYTHONPATH=src python scripts/gpu_check.py
    # or simply:  make gpu-check

Exercises the genuinely-wired GPU seams and reports the backend that RAN — so a
judge / teammate can verify the GPU path is invoked, not just claimed. On the GB10
with requirements-gpu.txt installed and the env vars set, expect ``cugraph`` and
``cudf-polars`` (and ``cuopt`` / ``cuml`` for the flow / cluster seams); anywhere
else, ``networkx`` / ``polars`` / ``pandas`` / ``numpy``.

Exit-code contract (so ``make gpu-check-wsl`` can GATE on "GPU path reproducible"):

* No GPU env flags set (off-box / dev / CI default) → **exit 0**, "CPU fallback
  (honest)". CPU is a valid, honest outcome off the box; the VALUE is the printed
  backend.
* A GPU env flag IS set but its seam silently fell back to CPU → **exit 5**, naming
  the requested-but-degraded seam(s). A requested GPU path that quietly ran on CPU is
  a reproducibility failure, so we fail loudly rather than over-promise with exit 0.
* Every requested seam reported its GPU backend → **exit 0**, "GPU path active".

The gate keys off **requested** seams only (each ``URBANOS_GPU_*`` flag → its expected
GPU backend), so the off-box behaviour is unchanged. The pure decision lives in
``gate_exit_code`` for hermetic unit testing without a GPU.
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


# Each seam: env flag that REQUESTS the GPU path -> the backend string that proves it
# ran on the GPU. Mirrors the per-module gating helpers (state.py / loader.py /
# flow.py / cluster.py), which all parse {"1","true","yes"} after strip().lower().
_SEAM_ENV = {
    "graph": ("URBANOS_GPU_GRAPH", "cugraph"),
    "ingest": ("URBANOS_GPU_DF", "cudf-polars"),
    "flow": ("URBANOS_GPU_FLOW", "cuopt"),
    "cluster": ("URBANOS_GPU_CLUSTER", "cuml"),
}
_TRUTHY = {"1", "true", "yes"}


def _flag_set(env: dict[str, str], name: str) -> bool:
    """Match the per-module helpers' truthiness exactly: "1"/"true"/"yes" (any case),
    "" / "0" / unset are false."""
    return env.get(name, "").strip().lower() in _TRUTHY


def gate_exit_code(backends: dict[str, str], env: dict[str, str]) -> tuple[int, str]:
    """Decide the process exit code from the seam backends + the request env.

    Pure (no I/O, no ``os.environ``) so it is unit-testable without a GPU.

    * No GPU env flag set → ``(0, ...)``: CPU is the honest off-box outcome.
    * A flag set but its seam did NOT report its GPU backend → ``(5, ...)`` naming the
      requested-but-degraded seam(s): a quietly-CPU GPU request is a reproducibility
      failure.
    * Every requested seam reported its GPU backend → ``(0, ...)``.
    """
    requested = [s for s in _SEAM_ENV if _flag_set(env, _SEAM_ENV[s][0])]
    if not requested:
        return 0, ("RESULT: CPU fallback (honest) — no GPU env flags set; "
                   "install requirements-gpu.txt + set URBANOS_GPU_* on the box")
    degraded = [s for s in requested if backends.get(s) != _SEAM_ENV[s][1]]
    if degraded:
        detail = ", ".join(
            f"{s} (set {_SEAM_ENV[s][0]}, expected {_SEAM_ENV[s][1]}, "
            f"got {backends.get(s)!r})"
            for s in degraded
        )
        return 5, ("RESULT: GPU REQUESTED BUT FELL BACK TO CPU — " + detail +
                   ". The GPU path is not reproducible here; see scripts/gpu_check_wsl.sh.")
    ok = ", ".join(f"{s}->{_SEAM_ENV[s][1]}" for s in requested)
    return 0, f"RESULT: GPU path active ✅ — every requested seam on GPU: {ok}"


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

    code, message = gate_exit_code(backends, dict(os.environ))
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
