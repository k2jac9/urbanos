# ADR-0001 — Build the Urban-OS dynamics kernel on the civic_analyst repo

- **Status:** accepted
- **Date:** 2026-05-29
- **Context:** Spark Hack Toronto, flagship Urban Operations track. Deadline 2026-05-31 11:00.

## Context

The repo already ships a verified, CI-green demo: `civic_analyst`, a *static*
address-level risk app (a `networkx` graph of `address → {permit, inspection,
licence}`, a saturating risk score, and a local-LLM narrator with a
hallucination guard). The flagship track rewards "systems engineering" — a
local pipeline that ingests raw data, processes it on the DGX Spark, and
produces a valuable result. A static lookup scores poorly there; a temporal
**simulation kernel** scores well.

The two apps are different in kind: civic_analyst has no time, flow, transit, or
optimization. Urban-OS needs all four. But ~40% of Urban-OS already exists here:
the CKAN ingest, the FastAPI + offline MapLibre/PMTiles map shell, and — most
valuably — the narrator + hallucination guard, which is exactly the "killer
insight" generator.

## Decision

Build Urban-OS as a new `src/urban_os/` package: a small, deterministic
Python/numpy **kernel** (State = named fields over a road/transit graph; four
operators `source`/`transport`/`couple`/`observe`; a time loop; an optimizer
minimizing `J = Σ wₚ·Jₚ`) with **city adapters** and **domain lenses** as the
two plugin axes. Reuse civic_analyst directly for ingest, the map shell, and the
cited-insight narrator. Keep `civic_analyst` intact: it becomes the
Safety/Public-Services *lens* running on the kernel, which itself demonstrates
the adapter×lens architecture.

## Consequences

- `main` stays green as the fallback demo throughout; work lands on
  `feat/urban-os-kernel` via PR.
- We own a simulation kernel (net-new) — the bulk of the effort — but inherit a
  working data-in / insight-out shell.
- P0 (Event Surge → congestion → $ insight) must run end-to-end before any
  breadth (cuOpt, more lenses) is added. "One flawless demo > five half-features."
