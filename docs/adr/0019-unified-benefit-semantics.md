# ADR-0019 — Unified, self-labelled benefit semantics

**Status:** Accepted · **Date:** 2026-05-31 · **Supersedes/relates:** ADR-0003 (honest optimum), ADR-0015/0016 (shelter cost), ADR-0006 (api contract)

## Context

Two independent audits (a source-level architecture review and a black-box UX
audit) converged on the **same highest-leverage finding**: Urban-OS surfaces
*three* differently-derived "benefit" numbers, unlabelled, so the same optimized
intervention appears with three different headline dollar figures (the UX audit's
**F-4**; also its F-1 and F-3 about what "combined" includes):

1. `combined_benefit` on **/lenses** = `base_J − cur_J` over the four-lens stack —
   the conservative, no-double-count single-objective number.
2. `cross_domain_benefit` on **/lenses** = `transit_savings + safety_reduction +
   business_recovered` — an **additive** cross-domain framing (larger; domains can
   overlap).
3. `combined_benefit` on **/optimize** = `opt.savings + per-lens deltas` — *another*
   additive number, computed by a **separate code path** from (2), so the two could
   silently drift; and the narrator reports `opt.savings` as the "net intervention
   benefit" (a fourth surfaced figure).

The key defects: (a) the additive headline was derived twice with no shared helper
(it could diverge between `/lenses` and `/optimize`), and (b) every number was shown
without saying *what it means*, so users couldn't reconcile them.

## Decision

1. **One shared helper.** `_cross_domain_components(sc, *, release, shelter, safety,
   business)` is the single source of truth for the additive `cross_domain_benefit`.
   Both `/lenses` and `/optimize` call it, so they report the **identical** number at
   the same levers — pinned by `test_benefit_semantics_lenses_and_optimize_agree`.

2. **Two clearly-named concepts, each self-labelled.** Every response now carries a
   `benefit_definitions` block (the single source of truth for wording):
   - **`j_avoided`** — reduction in the single combined objective J the optimizer
     minimises. Conservative, double-count-free; this is the honest headline and
     equals the narrator's "net intervention benefit" (`opt.savings`).
   - **`cross_domain_benefit`** — additive sum of per-domain dollar improvements
     (transit + public safety + local business). Explicitly labelled *additive*:
     larger than `j_avoided` because domains are summed independently and may overlap.

3. **Backwards compatibility.** The legacy `combined_benefit` key is retained as a
   **deprecated alias** (on `/optimize` it equals `cross_domain_benefit`; on `/lenses`
   it remains the four-lens J reduction) so the current UI keeps working; the UI will
   migrate to the explicit keys (tracked under the Urban-OS UI fix task) and the alias
   can then be dropped.

## Consequences

- The audit's F-4 is resolved at the source: there is now **one** additive headline,
  computed once, consistent across endpoints, and **every** surfaced number is
  self-describing via `benefit_definitions`. F-1/F-3 (what "combined" includes) become
  answerable directly from the JSON.
- `j_avoided ≤ cross_domain_benefit` is an asserted invariant (conservative ≤ additive).
- Slightly more sims per request (the helper runs its own baseline/current pairs), but
  on the 17-node demo substrate this is negligible and correctness/consistency wins.
- The duplicate `_cross_domain` derivation is gone; future lens additions flow through
  one helper, so the two surfaces cannot drift again.

## Alternatives considered

- *Collapse to a single number.* Rejected: `j_avoided` and `cross_domain_benefit`
  answer genuinely different questions (single-objective vs. cross-domain framing);
  hiding one would be less honest, not more. Labelling both is the honest fix the
  audits actually recommended.
- *Rename `combined_benefit` outright.* Rejected for now — it would break the live UI
  mid-demo; the deprecated-alias path lets the UI migrate without a flag day.
