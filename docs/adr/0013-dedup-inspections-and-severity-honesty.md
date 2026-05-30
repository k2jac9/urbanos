# 0013 — De-dup inspections by visit + severity/prose honesty

Status: Accepted
Date: 2026-05-30

## Context

DineSafe is published **one CSV row per deficiency line-item**, not one row per
inspection. In the committed `demo_data/dinesafe__downtown.csv` slice this means
**250 raw rows represent only ~135 distinct establishment visits** — so a single
dated inspection of a busy premises showed up as N separate "inspections". Because
the risk score sums per-inspection weight, this **inflated risk**: a building with
one Conditional-Pass visit carrying 9 deficiencies scored as if it had 9 inspections.
The net effect was a useless triage signal — **~19 of the demo addresses landed in
HIGH** with almost nothing in MEDIUM/LOW.

**Choosing the de-dup key matters.** A naïve (normalized address, date) key
*over*-collapses: distinct establishments that share a building and are inspected the
same day fuse into one. The clearest example is **1 Blue Jays Way (Rogers Centre):
seven distinct `estId`s (seven food vendors) inspected on 2025-10-20** — an
address-keyed merge would report them as a single inspection. Across the slice **26 of
the address+date groups fuse more than one `estId`**, under-counting real inspections.
The correct grain is the **establishment**, identified by `estId`.

Two related honesty problems surfaced alongside the over-count:

1. **"Adverse" was applied to Conditional Pass.** The prose called every non-Pass
   inspection "adverse", but a Conditional Pass is a routine minor follow-up, not an
   enforcement event. The score already weighted it correctly (minor 0.8 vs severe
   2.0) — only the *words* were wrong.
2. **Real enforcement outcomes were invisible.** The dataset's `OutcomeDesc` column
   carries the genuine signal (one real `"Conviction - Fined"` record in the slice),
   but the pipeline only read `inspectionStatus` (Pass / Conditional Pass), so an
   actual court conviction was scored identically to a clean Conditional Pass.

## Decision

Three coherent changes, score formula and weights unchanged:

1. **De-dup inspections by visit (`ingest/loader.py`).** When loading
   inspection-kind records, collapse the deficiency line-items of a single visit into
   **one visit record** — keeping the **worst severity** across the group and exposing
   a `deficiency_count` attribute for display. The grouping key, in priority order:
   - **`(estId, inspectionDate)`** when an establishment-id column exists (DineSafe).
     This collapses one premises' own line-items while keeping **distinct
     establishments that share an address+date separate** (the Rogers-Centre case).
   - **`(normalized address, date)`** as a fallback when there is **no estId column**
     (e.g. the synthetic `fixtures/dinesafe__sample.csv`).
   - **per-row** (no collapse) when there is **no usable date column**, so other feeds
     and fixtures are unaffected.

   On the committed slice the 250 line-items resolve to **135 establishment visits**
   under the `(estId, date)` key — *not* the ~76 an address-keyed merge would have
   produced, which would have silently dropped 26 groups' worth of distinct vendors.

2. **Prose honesty (`agents/subagents.py`, `agents/verify.py`).** Reserve the word
   **"adverse" for SEVERE outcomes only** (fail / closed / conviction). A Conditional
   Pass is reported as a **"Conditional Pass inspection visit"** (with its
   deficiency count, e.g. *"1 Conditional Pass inspection visit (9 deficiencies)"*),
   not "adverse". `graded_score` is untouched.

3. **Additive conviction severity (`ingest/loader.py`).** `inspectionStatus` stays
   the **primary** outcome (Conditional Pass → minor). **Additively**, if a visit's
   `OutcomeDesc` contains a conviction/order/closure keyword
   (`conviction`, `closed`, `closure`, `order`, `suspend`, `fined`), the visit is
   escalated to **SEVERE**. This makes the single real `"Conviction - Fined"` record
   a genuine severe site. We do **not** switch the primary column to `OutcomeDesc`
   (that would erase the Conditional-Pass minor signal), and the logic is robust to
   fixtures with no `OutcomeDesc` column.

## Consequences

- **Triage is now usable.** On the committed demo slice the band distribution moves
  from **HIGH 19 / MED 6 / LOW 0 / NONE 2** to **HIGH 6 / MED 11 / LOW 8 / NONE 2** —
  a real risk gradient instead of a saturated HIGH bucket. The single real conviction
  is the only SEVERE inspection site.
- **The golden invariant holds.** `100 Queen St W → 0.826, high` is preserved: the
  pinned `fixtures/dinesafe__sample.csv` has **no estId column**, so it takes the
  `(address, date)` fallback; its two "Fail" rows were given **distinct dates**, so
  they remain **two visits → two severe → weight 5.0 → 0.826**.
- **No over-collapse.** A regression test asserts two distinct estIds at the same
  address+date stay as **two** inspection records, and on the real slice the number of
  address+date groups fusing more than one estId is **0** under the new key.
- **Grounded-citation behavior is intact** — claims still cite only real evidence
  tags; the narrator prompt is unchanged.
- The `demo_data` count guard moves from `dinesafe: 250` to `dinesafe: 135` to lock in
  the establishment-level de-dup.
