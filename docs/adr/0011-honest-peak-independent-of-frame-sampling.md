# ADR-0011 — The headline peak congestion is computed over every step, independent of frame sampling

## Status
Accepted.

## Context
`/simulate` subsamples its per-step field `frames` by a `frame_every` query
parameter to cap the JSON payload size for the map. `SimResult.peak_congestion()`
— which feeds the "specific station, specific timing" insight and the
before/after panel — originally scanned **only the recorded (subsampled) frames**.

That made the headline safety number an artifact of a *display* knob: a coarse
`frame_every` could skip the true peak step and under-report congestion. The
two-lens demo passed an `frame_every`-independence contract test only by luck
(the peak happened to fall on a retained step). Wiring in the third lens
(`WeatherLens`, ADR-0007) shifted the congestion trajectory so the true peak
landed on a non-retained step, and the test `test_simulate_frame_every_subsamples_monotonically`
correctly failed: `frame_every=1 → 2.484` vs `frame_every=4 → 2.454`.

## Decision
Track the peak congestion at **full resolution inside `Simulation.run()`** — a
running max over every step's congestion field — and carry it on `SimResult.peak`.
`peak_congestion()` returns that precomputed peak when present, and falls back to
scanning `frames` for `SimResult`s built directly (e.g. in unit tests), so the
change is backward compatible.

The peak number is therefore invariant to `frame_every`: the payload can be
subsampled for the map without ever changing the reported safety figure.

## Consequences
- The reported peak is now honest and reproducible regardless of the display
  sampling rate; the cited insight cannot be softened by a coarser payload.
- One extra `argmax` per step (cheap; the numpy transport step dominates).
- `SimResult` gains an optional `peak` field; directly-constructed results keep
  working via the frame-scan fallback.
- Discovered while wiring `WeatherLens` into the demo stack; the lens was the
  trigger, not the cause — this was a latent kernel correctness bug.
