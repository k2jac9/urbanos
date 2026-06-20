# ADR-0037 — Footfall lens (ambient TMC pedestrian volume)

**Status:** Accepted · **Date:** 2026-06-20 · **Relates:** the data-driven roadmap
(`docs/research/tpf-and-data-driven-lenses.md` §6, the "real source/demand lenses" Fit C track),
ADR-0030 (MobilityDemand display lens — the structural template), ADR-0036 (RoadRisk display
lens — the most recent Fit C sibling), ADR-0029 (TransitLoad — the TMC count source this reuses)

## Context

The shell's intelligence lenses cover the crowd crush, transit, civic activity, EMS access,
emissions, micromobility demand, transit supply, and historical road risk — but nothing captures
**how busy each place already is on foot**: its ambient pedestrian presence. The City's Traffic
Management Centre (TMC) 15-min counts already carry a **pedestrian** mode, and a committed
downtown slice is read today by `observed_counts_by_node(mode="ped")`. Lifting that ped count onto
the egress substrate answers a genuinely new question — *does the staggered-release lever pile the
crowd into areas that were already busy with pedestrians?* — a footfall axis distinct from the
crush (load) itself, from Bike Share "demand to leave", and from the fixed KSI danger field.

## Decision

Add **`FootfallLens`** — a Fit C, display-only advisory lens, an exact clone of the MobilityDemand
pattern (ADR-0030): a **time series** of per-node pedestrian volume on the 15-min grid.

- **Data.** Reuses the already-committed TMC pedestrian slice — **no new fetch**. A thin adapter
  wrapper `adapters.footfall_by_node(substrate)` returns
  `observed_counts_by_node(substrate, mode="ped", ...)`, i.e. the same `{node_id: {minute: count}}`
  shape the other temporal lenses consume, with the existing deterministic synthetic fallback when
  no slice is present — so CI/dev never need real data.
- **Lens.** `FootfallLens` bakes the per-bin per-node footfall at non-sink nodes only (validated:
  negative / NaN / inf dropped), writes it as its own `footfall` overlay in `couple()` (read-only on
  the crowd fields), and reports in `observe()`: `footfall_peak` and **`crush_footfall_overlap`** —
  a scale-free cosine in `[0, 1]` of how much the egress crush (`load`) coincides with already-busy
  pedestrian areas (the same bounded cosine, with the zero-norm guard, that MobilityDemand uses for
  `micromobility_relief`). **No levers, zero cost.** Lives in `scenarios.extra_display_lenses`
  (excluded from the optimizer's `J`).
- **Surfaces.** `/overlays` gains a normalised `footfall` per-node field; `/lenses` gains a
  `footfall` advisory report (peak/mean overlap). The shell adds a **"Footfall"** map-heat button
  (Context group, after Road risk) and a "Pedestrian footfall" advisory card on the optimizer
  result, styled like the other learned/advisory cards (labelled *footfall · advisory*).

Because the source is the same committed TMC ped slice as the existing pedestrian path, footfall
concentrates on the busy downtown corridors, and the do-nothing crush reads a high overlap — the
egress does pile into already-busy pedestrian areas.

## Honesty / invariants (unchanged)

Display-only and additive: read-only on the crowd fields, no lever, no `J` term, excluded from the
objective — proven by `tests/test_footfall.py` (additivity contract: `load`/`delay_cost`/
`safety_cost` byte-identical with vs without the lens). The golden numbers (do-nothing
**J $323,222** → best **$105,050**), the 100%-offline map, and the hallucination guard are
unchanged. Real TMC ped counts under the demo (`DATA_DIR=demo_data`), deterministic synthetic
series in CI/dev. `PROVENANCE = "synthetic/advisory"` (the fallback label, not surfaced at
runtime). Suite: **+13 footfall tests** (incl. the adapter wrapper check), all green.
