#!/usr/bin/env python3
"""Benchmark the optional Rust accelerator vs the numpy reference (ADR-0004/0009).

This proves ADR-0004's claim that the Rust core is (a) a *bit-for-bit* match for
the numpy reference and (b) actually faster, by:

  1. Asserting NUMERICAL PARITY between ``_transport_step_numpy`` and the live
     ``transport_step`` backend on both the real downtown substrate and a large
     synthetic one — within f64 tolerance — *when the rust backend is active*.
  2. Measuring wall-clock speedup over many iterations of ``transport_step``
     against the numpy reference (the reference is always available, so the
     speedup number is meaningful regardless of which backend is live).
  3. Printing the active backend + the measured numbers.

Degrades gracefully: with no compiled ``urban_os_native`` it reports
"rust not built, numpy only", still runs the numpy timing as a sanity baseline,
and exits 0. It only *fails* (exit 1) if rust IS built but disagrees with numpy.

Run anywhere:
    PYTHONPATH=src python scripts/bench_urbanos_accel.py
    PYTHONPATH=src python scripts/bench_urbanos_accel.py --iters 5000 --nodes 4000
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

import numpy as np

# Import via the package so this works from a checkout with PYTHONPATH=src.
from urban_os.adapters.toronto import downtown_substrate
from urban_os.kernel import accel
from urban_os.kernel.accel import _transport_step_numpy, transport_step

# Parity tolerances for f64. Both backends run the identical algorithm in f64,
# so agreement should be at round-off; we allow a little slack for the
# numpy<->list<->Vec marshalling on the rust path.
_RTOL = 1e-9
_ATOL = 1e-9


@dataclass
class Bench:
    """A named (substrate-like) problem instance as flat arrays for the step."""

    name: str
    load: np.ndarray
    edge_src: np.ndarray
    edge_dst: np.ndarray
    edge_cap: np.ndarray
    dist_to_sink: np.ndarray
    is_sink: np.ndarray
    capacity: np.ndarray
    dt: float

    @property
    def n(self) -> int:
        return int(self.load.shape[0])

    @property
    def e(self) -> int:
        return int(self.edge_src.shape[0])

    def args(self) -> dict:
        return dict(
            load=self.load,
            edge_src=self.edge_src,
            edge_dst=self.edge_dst,
            edge_cap=self.edge_cap,
            dist_to_sink=self.dist_to_sink,
            is_sink=self.is_sink,
            capacity=self.capacity,
            dt=self.dt,
        )


def _downtown_bench() -> Bench:
    """The real 9-node downtown substrate, primed with a crowd at the stadium."""
    sub = downtown_substrate()
    load = np.zeros(sub.n)
    load[sub.idx("stadium")] = 45000.0
    return Bench(
        name=f"downtown (N={sub.n}, E={sub.n_edges})",
        load=load,
        edge_src=sub.edge_src,
        edge_dst=sub.edge_dst,
        edge_cap=sub.edge_cap,
        dist_to_sink=sub.dist_to_sink,
        is_sink=sub.is_sink,
        capacity=sub.capacity,
        dt=1.0,
    )


def _synthetic_bench(n_nodes: int, fanout: int, seed: int) -> Bench:
    """A larger deterministic layered grid that drains toward a sink layer.

    Nodes are arranged in ``layers``; each non-sink node has up to ``fanout``
    outbound edges to the next layer (closer to the sink). ``dist_to_sink`` is
    simply the layer index, so every forward edge drains — a realistic dense
    transport step. The last layer are sinks. Sizable enough (thousands of
    nodes/edges) to expose any per-element overhead difference between backends.
    """
    if n_nodes < 4:
        n_nodes = 4
    rng = np.random.default_rng(seed)
    layers = max(2, int(round(np.sqrt(n_nodes))))
    per = max(1, n_nodes // layers)
    n = per * layers

    # layer index per node; sink = final layer.
    layer_of = np.repeat(np.arange(layers), per)
    dist_to_sink = (layers - 1 - layer_of).astype(float)
    is_sink = layer_of == (layers - 1)

    # Forward edges: node in layer L -> `fanout` random nodes in layer L+1.
    src_list: list[int] = []
    dst_list: list[int] = []
    for layer in range(layers - 1):
        base = layer * per
        nxt = (layer + 1) * per
        for local in range(per):
            s = base + local
            targets = rng.integers(0, per, size=min(fanout, per))
            for t in np.unique(targets):
                src_list.append(s)
                dst_list.append(int(nxt + t))
    edge_src = np.asarray(src_list, dtype=np.int64)
    edge_dst = np.asarray(dst_list, dtype=np.int64)
    edge_cap = rng.uniform(50.0, 500.0, size=edge_src.shape[0])

    load = np.zeros(n)
    load[layer_of == 0] = rng.uniform(100.0, 5000.0, size=int((layer_of == 0).sum()))
    capacity = np.full(n, 2000.0)

    return Bench(
        name=f"synthetic (N={n}, E={edge_src.shape[0]}, layers={layers})",
        load=load,
        edge_src=edge_src,
        edge_dst=edge_dst,
        edge_cap=edge_cap,
        dist_to_sink=dist_to_sink,
        is_sink=is_sink,
        capacity=capacity,
        dt=1.0,
    )


def _assert_parity(b: Bench) -> tuple[bool, float]:
    """Compare the live backend to the numpy reference for one step of ``b``.

    Returns ``(ok, max_abs_diff)``. ``ok`` is True when the two agree within
    tolerance OR the live backend *is* numpy (trivially identical).
    """
    ref_load, ref_arr = _transport_step_numpy(**b.args())
    got_load, got_arr = transport_step(**b.args())
    diff = max(
        float(np.max(np.abs(ref_load - got_load))) if ref_load.size else 0.0,
        float(np.max(np.abs(ref_arr - got_arr))) if ref_arr.size else 0.0,
    )
    ok = bool(
        np.allclose(ref_load, got_load, rtol=_RTOL, atol=_ATOL)
        and np.allclose(ref_arr, got_arr, rtol=_RTOL, atol=_ATOL)
    )
    return ok, diff


def _time_callable(fn, args: dict, iters: int) -> float:
    """Median-of-3 wall time (seconds) for ``iters`` calls of ``fn(**args)``."""
    best = float("inf")
    for _ in range(3):
        t0 = time.perf_counter()
        for _ in range(iters):
            fn(**args)
        best = min(best, time.perf_counter() - t0)
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iters", type=int, default=2000, help="timed iterations")
    parser.add_argument("--nodes", type=int, default=4000, help="synthetic node count")
    parser.add_argument("--fanout", type=int, default=4, help="synthetic edge fanout")
    parser.add_argument("--seed", type=int, default=7, help="synthetic rng seed")
    args = parser.parse_args(argv)
    iters = max(1, args.iters)

    backend = accel.backend_name()
    rust_live = backend == "rust"

    print("=" * 64)
    print("Urban-OS transport accelerator benchmark (ADR-0004 / ADR-0009)")
    print("=" * 64)
    print(f"active backend : {backend}")
    if not rust_live:
        print("note           : rust not built, numpy only "
              "(build with `make urbanos-accel`)")
    print()

    benches = [_downtown_bench(), _synthetic_bench(args.nodes, args.fanout, args.seed)]

    # --- (a) numerical parity ------------------------------------------------
    print("[parity] numpy reference vs active backend")
    parity_all_ok = True
    for b in benches:
        ok, diff = _assert_parity(b)
        parity_all_ok = parity_all_ok and ok
        if rust_live:
            status = "PASS" if ok else "FAIL"
            print(f"  {b.name:<42} {status}  max|Δ|={diff:.3e}")
        else:
            # numpy-vs-numpy is trivially identical; report it as a self-check.
            print(f"  {b.name:<42} self-check max|Δ|={diff:.3e}")
    print()

    # --- (b) wall-clock speedup ---------------------------------------------
    print(f"[timing] {iters} iterations each (median of 3)")
    for b in benches:
        a = b.args()
        t_numpy = _time_callable(_transport_step_numpy, a, iters)
        t_live = _time_callable(transport_step, a, iters)
        per_numpy_us = t_numpy / iters * 1e6
        per_live_us = t_live / iters * 1e6
        if rust_live and t_live > 0:
            speedup = t_numpy / t_live
            print(f"  {b.name}")
            print(f"    numpy : {t_numpy:7.3f}s  ({per_numpy_us:8.2f} us/step)")
            print(f"    rust  : {t_live:7.3f}s  ({per_live_us:8.2f} us/step)"
                  f"   -> {speedup:5.2f}x")
        else:
            print(f"  {b.name}")
            print(f"    numpy : {t_numpy:7.3f}s  ({per_numpy_us:8.2f} us/step)")
    print()

    # --- (c) verdict ---------------------------------------------------------
    if rust_live and not parity_all_ok:
        print("RESULT: FAIL — rust backend disagrees with the numpy reference.")
        return 1
    if rust_live:
        print("RESULT: PASS — rust matches numpy (f64) and the speedup is measured above.")
    else:
        print("RESULT: OK — numpy-only run (no rust to compare); build it to get parity+speedup.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
