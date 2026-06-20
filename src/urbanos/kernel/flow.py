"""Optimal evacuation flow (ADR-0025): a genuine cuOpt use — a max-flow LP on the
capacitated substrate.

This is a NEW analysis, deliberately NOT the lever optimizer (cuOpt can't evaluate a
black-box simulation). The substrate is a capacitated directed graph (ADR-0002), so
"what is the maximum crowd the network can drain to the exits over the egress window?"
is a textbook **max-flow** problem — an LP that cuOpt's GPU solver handles. It yields
the *theoretical optimal evacuation capacity* that bounds what any release policy can
achieve: the staggered-release sim shows what actually happens; this shows the ceiling.

cuOpt LP solves it on the GPU when ``URBANOS_GPU_FLOW=1`` and ``cuopt`` is installed;
``networkx.maximum_flow`` is the exact CPU reference. Identical optimum either way
(parity-tested); the GPU win is at city scale, not the 17-node demo.
"""
from __future__ import annotations

import os

import networkx as nx

# Which solver produced the last flow: "cuopt" (RAPIDS GPU LP) or "networkx" (CPU).
FLOW_BACKEND: str = "networkx"

_SRC = "__evac_src__"
_SNK = "__evac_snk__"


def _gpu_flow_enabled() -> bool:
    """Opt-in: ``URBANOS_GPU_FLOW=1`` on a box with RAPIDS ``cuopt`` installed."""
    return os.environ.get("URBANOS_GPU_FLOW", "").strip().lower() in {"1", "true", "yes"}


def _build_flow_graph(substrate, demands: dict, *, horizon: int):
    """Super-source → venues (cap = crowd); substrate edges (cap = edge_cap·horizon,
    the total persons a link can pass over the window); sinks → super-sink (cap = ∞).
    Integer capacities (networkx max-flow needs them). Returns (G, total_demand)."""
    g = nx.DiGraph()
    for e in range(substrate.n_edges):
        u = substrate.ids[int(substrate.edge_src[e])]
        v = substrate.ids[int(substrate.edge_dst[e])]
        cap = int(round(float(substrate.edge_cap[e]) * horizon))
        if cap <= 0:
            continue
        if g.has_edge(u, v):
            g[u][v]["capacity"] += cap          # parallel links combine
        else:
            g.add_edge(u, v, capacity=cap)
    total = 0
    for vid, crowd in demands.items():
        c = int(round(float(crowd)))
        if c > 0:
            g.add_edge(_SRC, vid, capacity=c)
            total += c
    big = total + 1
    for i in range(substrate.n):
        if bool(substrate.is_sink[i]):
            g.add_edge(substrate.ids[i], _SNK, capacity=big)
    return g, total


def _result(max_flow: float, total: float, horizon: int) -> dict:
    cleared = max_flow >= total - 1e-9
    return {
        "max_throughput": int(round(max_flow)),      # persons the network can clear
        "demand": int(round(total)),                 # total crowd to evacuate
        "cleared": bool(cleared),                    # can the network drain everyone?
        "utilization": round(float(total) / max_flow, 3) if max_flow > 0 else 0.0,
        "horizon_min": int(horizon),
        "backend": FLOW_BACKEND,
    }


def _cuopt_max_flow(g: nx.DiGraph, src: str, snk: str) -> float:
    """Max-flow value via cuOpt's GPU LP solver (circulation formulation: maximise the
    return-arc flow subject to per-node conservation ``A·f = 0`` and per-edge capacity
    ``0 ≤ f ≤ cap``). Verified against the real cuopt 26.04 LP API on the GB10; raises
    on a non-optimal status or any error so the caller falls back to networkx."""
    import numpy as np
    import scipy.sparse as sp  # cuopt ships scipy; imported only on the GPU path
    from cuopt.linear_programming import data_model, solver  # type: ignore

    # Return-arc capacity = total capacity leaving the source (bounds the max flow,
    # and keeps coefficients well-scaled vs. a huge sentinel).
    src_cap = float(sum(d["capacity"] for _, _, d in g.out_edges(src, data=True)))
    edges = list(g.edges(data=True)) + [(snk, src, {"capacity": src_cap})]
    ret = len(edges) - 1
    nodes = list(g.nodes())
    nidx = {n: i for i, n in enumerate(nodes)}

    # Conservation A·f = 0 at every node: edge (u,v) is -1 at u (outflow), +1 at v.
    rows, cols, vals = [], [], []
    for j, (u, v, _d) in enumerate(edges):
        rows += [nidx[u], nidx[v]]
        cols += [j, j]
        vals += [-1.0, 1.0]
    A = sp.csr_matrix((vals, (rows, cols)), shape=(len(nodes), len(edges)))

    n_vars = len(edges)
    upper = np.array([float(e[2]["capacity"]) for e in edges], dtype=float)
    obj = np.zeros(n_vars)
    obj[ret] = 1.0                                   # maximise the return-arc flow

    dm = data_model.DataModel()
    dm.set_csr_constraint_matrix(A.data, A.indices, A.indptr)
    zeros = np.zeros(len(nodes))
    dm.set_constraint_lower_bounds(zeros)            # equalities: lower == upper == 0
    dm.set_constraint_upper_bounds(zeros)
    dm.set_variable_lower_bounds(np.zeros(n_vars))
    dm.set_variable_upper_bounds(upper)
    dm.set_objective_coefficients(obj)
    dm.set_maximize(True)
    sol = solver.Solve(dm)
    if int(sol.get_termination_status()) != 1:       # 1 == Optimal
        raise RuntimeError(f"cuopt LP not optimal: {sol.get_termination_reason()}")
    return float(sol.get_primal_objective())


def optimal_evacuation_flow(substrate, demands: dict, *, horizon: int) -> dict:
    """Max persons the capacitated substrate can drain to its exits over ``horizon``.

    cuOpt LP on GPU when enabled+installed; else exact networkx max-flow. ``demands``
    maps venue node-id → crowd (e.g. ``{vid: crowd for vid, crowd, _ in sc.events}``).
    """
    global FLOW_BACKEND
    g, total = _build_flow_graph(substrate, demands, horizon=horizon)
    if g.number_of_edges() == 0 or total == 0:
        FLOW_BACKEND = "networkx"
        return _result(0.0, total, horizon)
    if _gpu_flow_enabled():
        try:
            val = _cuopt_max_flow(g, _SRC, _SNK)
            FLOW_BACKEND = "cuopt"
            return _result(val, total, horizon)
        except Exception:  # cuopt missing / API / runtime → exact CPU max-flow
            pass
    FLOW_BACKEND = "networkx"
    val, _ = nx.maximum_flow(g, _SRC, _SNK)
    return _result(val, total, horizon)
