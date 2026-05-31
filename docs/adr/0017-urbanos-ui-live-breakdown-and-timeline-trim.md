# ADR-0017 — Urban-OS dashboard: live J-breakdown, optimizer-card invalidation, timeline trim

## Status
Accepted. Presentation-only fixes on top of the verified model (no physics, no
metrics, no peak readouts changed). Builds on
[ADR-0015](0015-shelter-as-real-lever-and-cost-transparency.md) /
[ADR-0016](0016-shelter-interior-optimum-coverage-premium.md) (the cost
transparency + interior optimum those ADRs established are what these fixes
*surface* honestly in the UI).

## Context
A third audit pass over the Urban-OS dashboard flagged three real
**presentation** defects. The simulation kernel, optimizer, cost decomposition
and hallucination-guarded narrator were all re-verified as sound — these are
display-layer staleness bugs only.

- **BUG-A — stale, hard-looking J-breakdown.** `/simulate` already returns a real
  per-lever `cost_breakdown` (delay/hold/exposure/staffing/safety/total), but the
  UI never consumed `SIM.cost_breakdown`. The "objective J breakdown" table was
  rendered *only* inside the `/optimize` click handler from `d.cost_breakdown`, so
  it looked hard-coded and went stale the moment a lever moved.
- **BUG-B — optimizer card contradicts the live map.** After "Find best
  intervention" wrote the recommendation card, a later *manual* lever change left
  that card untouched, so it described an intervention that was no longer on the
  map.
- **BUG-C — dead timeline tail.** The crowd fully drains by ~t=68 but the sim
  horizon is 120, so ~43% of the slider (t≈68→118) was all-zero padding — the
  playback spent nearly half its run on an empty map.
- **CLARITY — ambiguous peak timing.** The insight said "about N minutes after
  full-time"; two auditors misread that relative figure as an absolute clock time.

## Decision
**BUG-A (UI).** Factor the breakdown-row rendering into one `breakdownRowsHTML()`
helper (same labels + whole-`$k` rounding) used by both cards. `loadSim()` now
renders `SIM.cost_breakdown` into a new live "Why — objective J breakdown (live)"
table on every fetch, so it tracks the levers. The breakdown visibly changes when
a lever moves.

**BUG-B (UI).** On a successful `/optimize`, remember the pick in `BEST_PARAMS`
`{release_minutes, shelter_fraction}` and render a hidden "superseded — re-run to
refresh" note inside the card. `loadSim()` calls `refreshOptStale()`, which dims
the card (`.stale`) and shows the note whenever the levers are off `BEST_PARAMS`;
setting the levers back to the exact pick un-dims it. A fresh optimize run clears
the stale state. The optimize flow itself is untouched (it reflects its own pick,
so it lands un-stale).

**BUG-C (server, `api.simulate()`).** After the run, drop trailing frames whose
total node load is `< 1.0` person, keeping a 2-frame "drained" coda. Guarded so
the **peak frame is always retained** (`t <= peak.t` frames are never dropped) and
so a degenerate all-quiet run keeps its frames. This trims only the returned
`frames` list — `times`, the metrics series, the physics, and the peak/peak-
congestion readouts (computed over *every* step via `result.peak`) are unchanged.
The slider max is `frames.length - 1`, so it follows automatically. Result: the
default run goes from 120 → ~70 displayed frames spanning t≈0→69.

**CLARITY (narrate.py).** Add `peak_t_abs` (the real `peak.t`, a whitelisted
figure) to the insight figures and phrase the timing as "about N minutes after
full-time (t=<abs> min)". The hallucination guard is intact: `peak_t_abs` is a
genuine simulation figure, so it joins the whitelist; no number outside the
figures can appear.

## Consequences
- The live J-breakdown and the optimizer card now agree with the map at all
  times; neither can silently go stale.
- Playback spans the active egress window instead of idling on an empty map.
- `figures` gained one key (`peak_t_abs`); the pinned contract test was updated to
  match. All other endpoint shapes are unchanged.
- Tests: `/simulate` frame-trim coverage (tail trimmed, peak frame retained, full
  metrics series length unchanged) and a `cost_breakdown` present/non-constant
  check were added; the full suite stays green (311 passed, 1 skipped).

## Note on the audit
The third audit's three findings above are confirmed and fixed. Its **other six
findings were refuted** — they were misattributions to the model (kernel /
optimizer / cost decomposition / narrator), which was re-verified sound. Only the
presentation layer needed changes.
