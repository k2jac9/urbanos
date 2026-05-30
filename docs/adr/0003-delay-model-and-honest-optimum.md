# ADR-0003 — Linear over-capacity delay + discounted hold cost for an honest optimum

- **Status:** accepted
- **Date:** 2026-05-29

## Context

The economic lens turns congestion into the dollar figure the demo lives or dies
on. Two earlier choices produced misleading numbers:

1. A BPR volume-delay term `t = t0·(1 + a·ρ^b)` with `b = 4` made delay explode
   near the crush (`ρ ≈ 4.7` → a 75× multiplier → ~$6.2M for one event). The
   number was indefensible and the result was effectively binary.
2. With staggered release **free**, the optimizer drove the lever to its maximum
   (delay → $0), because holding the crowd back imposed no modelled cost. The
   "optimum" was a degenerate corner solution.

## Decision

- **Delay = person-minutes spent beyond comfortable capacity.** Anyone held at a
  node past its reference occupancy (`load > capacity`) is queueing and pays
  `dt` minutes of delay, valued at $28/commuter-hour. Linear in queue length, so
  the dollar figure is auditable and robust.
- **Staggered release is not free.** Event Surge contributes a `J` term: holding
  the crowd `release` minutes makes the average attendee wait ~`release/2` extra
  minutes, counted at **20% of crush-delay value** (orderly concourse waiting is
  genuinely less costly — and far safer — than an over-capacity crush).

## Consequences

- Realistic figures: no-action ≈ $51.5k delay, Union at 2.48× capacity ~44 min
  after full-time. The objective `J` has a genuine **interior optimum at a
  ~12-minute release** (J ≈ $28.5k; peak density 2.48× → 1.17×, −53%), not a
  corner. This is the demo's headline result.
- The 20% hold discount and the $28/hr value-of-time are plausibility-calibrated,
  not ground-truth-validated, and are flagged as such in code and README.
- Risk field stays `risk = ρ^2.5` (super-linear crush risk) and drives the map's
  danger layer independently of the dollar model.
