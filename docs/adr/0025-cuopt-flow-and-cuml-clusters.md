# ADR-0025 — cuOpt evacuation-flow LP + cuML risk-hotspot clustering

**Status:** Accepted · **Date:** 2026-05-31 · **Relates:** ADR-0024 (RAPIDS seams), ADR-0002 (capacitated substrate), ADR-0014 (two-index risk)

## Context

ADR-0024 wired `nx-cugraph` and cuDF (via Polars) but left cuOpt and cuML *unwired*
because neither fits the existing code: cuOpt can't evaluate our black-box
simulation-in-the-loop lever search, and no clustering step shipped. Rather than fake
them, we add **new, domain-genuine computations** that those libraries are actually
built for — keeping the honest "wired + CPU fallback + box-proven" pattern.

## Decision

1. **cuOpt — optimal evacuation flow (`urban_os/flow.py`, `GET /flow`).** The substrate
   is a capacitated directed graph (ADR-0002), so "max crowd the network can drain to
   its exits over the egress window" is a **max-flow LP** — cuOpt's wheelhouse. It is a
   *new analysis*: the theoretical **ceiling** any release policy can reach (the
   staggered-release sim shows what a real policy achieves against it). Solved by
   **cuOpt's GPU LP** (circulation formulation, `URBANOS_GPU_FLOW=1`); **networkx
   `maximum_flow`** is the exact CPU reference. It is explicitly **not** the lever
   optimizer (`optimize.py` stays grid-search; cuOpt can't score the sim).

2. **cuML — spatial risk hotspots (`civic_analyst/cluster.py`, `GET /clusters`).**
   Cluster the scored addresses by `(lat, lng)` into K geographic risk zones (hottest
   first) — a Safety-lens enrichment. **cuML GPU KMeans** when
   `URBANOS_GPU_CLUSTER=1` + installed; a small **deterministic numpy KMeans** is the
   offline/CI fallback (seeded, reproducible — no sklearn dependency).

Both follow the ADR-0024 template: opt-in env flag, graceful CPU fallback (the live
demo is never blocked), backend recorded (`flow.FLOW_BACKEND`, `cluster.CLUSTER_BACKEND`),
and reported by `make gpu-check`. GPU wheels (`cuopt-cu12`, `cuml-cu12`) live in
`requirements-gpu.txt` (box-only).

## Honesty notes

- These are **new computations**, documented as such — cuOpt optimizes the *evacuation
  flow*, not the lever search; cuML adds a *new* clustering analysis. No retrofit claim.
- On the demo-size graph/address set neither gives a speedup; the value is the
  capability + the city-scale story (same framing as ADR-0009/0024).

## Verification (GB10)

cuOpt LP confirmed against the real `cuopt 26.04` API on the box (tiny max-flow →
`Status: Optimal`, correct value). `tests/test_gpu_seams.py` covers the CPU paths
(deterministic clustering, sane evacuation bound, env gating); `make gpu-check` reports
`FLOW_BACKEND` / `CLUSTER_BACKEND` alongside the graph/ingest backends. Full suite:
**413 passed** on both the Polars and forced-pandas paths.
