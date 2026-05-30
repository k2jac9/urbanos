# ADR-0005 — Reuse civic_analyst's hallucination guard for the killer insight

- **Status:** accepted
- **Date:** 2026-05-29

## Context

The demo's headline (Value & Impact, 20 pts) is one cited sentence: a specific
station, specific timing, specific lever, specific dollars. A local model phrases
it. But a model that invents a number or a station name turns the headline into a
liability — and the project invariant is explicit: "narrator cites only datasets
passed in evidence; don't loosen that prompt."

civic_analyst already solved the analogous problem for risk claims: compute every
figure deterministically, let the model only phrase them, and reject any output
whose numbers don't trace to the evidence — falling back to a
correct-by-construction sentence.

## Decision

`urban_os/narrate.py` reuses that machinery: the same `LocalLLM` client
(`interactive_llm`) and the same guard *pattern*. The optimizer/simulation
produce a small set of display figures (station, peak multiple, minutes after
full-time, release minutes, % reduction, $ saved). We **whitelist exactly those
integers**, prompt the model for one sentence, and accept it only if it names the
station and introduces no number outside the whitelist; otherwise we emit the
deterministic template. The narrator returns a `grounded` flag so the UI/CLI can
show whether the live model or the fallback produced the line.

## Consequences

- The headline is always grounded in the run — never a fabricated statistic —
  whether or not a model is reachable (verified by tests, including a
  hallucinated-number rejection test).
- We did not generalize civic_analyst's risk-specific verifier; we reimplemented a
  tiny integer-whitelist check tuned to numeric figures (the risk verifier is
  coupled to evidence tags/record kinds that don't apply here). Same principle,
  right-sized check.
- Decimal figures (e.g. "2.5x") are whitelisted by their digit runs; the figure
  set is kept integer-friendly (percentages, whole minutes, $k) to keep the guard
  simple and robust.
