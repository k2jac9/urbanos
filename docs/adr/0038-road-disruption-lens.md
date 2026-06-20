# ADR-0038 — RoadDisruption lens (active road closures / restrictions)

**Status:** Accepted · **Date:** 2026-06-20 · **Relates:** the data-driven roadmap
(`docs/research/tpf-and-data-driven-lenses.md` §6, the "real source/demand lenses" Fit C track),
ADR-0036 (RoadRisk lens — the static-field template this clones, the *historical-danger* pair),
ADR-0030 (MobilityDemand display lens — the original Fit C pattern), ADR-0032 (transit-supply
overlay)

## Context

The shell's intelligence lenses cover the crowd crush, transit, civic activity, EMS access,
emissions, micromobility demand, transit supply, and — with ADR-0036 — where the road is
**historically** dangerous (Vision Zero / KSI collisions). But nothing captures where the road is
**currently constrained**: the lane closures, full closures and construction restrictions in
force *right now*. The City publishes the *Road Restrictions* feed: real, geocoded, road-class-
bearing restriction records. Overlaying that on the egress substrate answers a genuinely new
question — *does the staggered-release lever funnel the crowd through actively closed or
restricted streets?* — distinct from the historical-danger axis (RoadRisk) and from the civic
Safety index (food inspections + permits). RoadRisk says *where the road has been dangerous*;
RoadDisruption says *where the road is closed today*. They pair naturally as two road-axis
overlays.

## Decision

Add **`RoadDisruptionLens`** — a Fit C, display-only advisory lens, built on the exact RoadRisk
pattern (ADR-0036): a **static** per-node field rather than a time series.

- **Data.** `scripts/fetch_road_restrictions.py` streams the Road Restrictions feed, keeps the
  downtown bbox, weights each record by road class (Major-Arterial 3 / Minor 2 / Local 1), and
  writes a small committed slice `demo_data/road_restrictions__downtown.csv` (629 real active
  downtown restrictions; columns `lat,lng,severity,road_class`). Offline-safe (network failure →
  exit 0); the raw feed is never committed.
- **Adapter.** `adapters.road_disruption_by_node(substrate)` loads that slice via
  `timeseries.load_station_values(key="road_restrictions", value_col="severity")` — the same
  mechanism `road_risk_by_node` uses — and fuses the points onto the substrate by a Gaussian
  proximity-weighted **sum** (disruption is cumulative — more severe nearby restrictions ⇒ more
  constrained), returning raw `{node_id: density}`. Synthetic deterministic fallback when no
  slice is present, so CI/dev never need real data.
- **Lens.** `RoadDisruptionLens` bakes a **normalised 0..1** disruption field at non-sink nodes
  only, writes it as its own `road_disruption` overlay in `couple()` (read-only on the crowd
  fields), and reports in `observe()`: `road_disruption_peak` and **`crush_disruption_exposure`**
  — a scale-free cosine in `[0, 1]` of how much the crush (`load`) overlaps the fixed disruption
  field (lower is safer). The baked field is stored on `self._risk` (the same attribute name
  RoadRisk uses) so the overlay helper reads it identically. **No levers, zero cost.** Lives in
  `scenarios.extra_display_lenses` (excluded from the optimizer's `J`).
- **Surfaces.** `/overlays` gains a normalised `road_disruption` per-node field; `/lenses` gains
  a `road_disruption` advisory report (peak/mean exposure). The shell adds a **"Road disruption"**
  map-heat button (Context group, after Road risk) and a "Road disruption" advisory card on the
  optimizer result, styled like the other learned/advisory cards (labelled *advisory*).

On the demo substrate the disruption concentrates on the currently-restricted downtown corridors,
so the do-nothing crush reads a non-trivial peak exposure — i.e. the egress does funnel the crowd
through actively constrained places.

## Honesty / invariants (unchanged)

Display-only and additive: read-only on the crowd fields, no lever, no `J` term, excluded from
the objective — proven by `tests/test_road_disruption.py` (additivity contract: `load`/
`delay_cost`/`safety_cost` byte-identical with vs without the lens). The golden numbers
(do-nothing **J $323,222** → best **$105,050**), the 100%-offline map, and the hallucination
guard are unchanged. Real restrictions under the demo (`DATA_DIR=demo_data`), deterministic
synthetic field in CI/dev. Suite: **+13 road-disruption tests** (incl. adapter proximity-fusion +
synthetic-fallback), all green.
