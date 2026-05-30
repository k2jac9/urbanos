# ADR-0010 — Harden the urban_os narrator's hallucination guard

- **Status:** accepted
- **Date:** 2026-05-30
- **Supersedes (the guard internals of):** ADR-0005

## Context

ADR-0005 established the invariant: the killer-insight sentence (`build_insight`
in `urban_os/narrate.py`) must only contain numbers the simulation actually
produced. A local model phrases the figures; any output that invents a number or
omits the station falls back to a correct-by-construction template. This mirrors
`civic_analyst.agents.verify` (compute deterministically, let the model only
phrase, reject untraceable numbers).

Workstream E is a "test and harden everything" mandate on that guard. Auditing
the ADR-0005 implementation surfaced three concrete holes:

1. **Decimal/integer confusion.** The original whitelist extracted *digit runs*
   (`re.findall(r"\d+", ...)`), so a figure of `2.5x` whitelisted `{2, 5}`. A
   model could then emit any sentence built from the digits 2 and 5, and
   `2.5` was indistinguishable from the unrelated integer `25` at the token
   level. ADR-0005 itself flagged this as a known simplification.
2. **Degenerate-run crash.** `peak_congestion()` returns `label=None` when a run
   has no frames or never congests (e.g. zero crowd, or an empty substrate). The
   old code interpolated that `None` into the sentence (printing the literal
   `"None"`) and ran `f["station"] in out`, which raises `TypeError` when
   `station is None`. A demo on a degenerate scenario could crash the narrator.
3. **One-sided invariant.** The guard verified the *LLM* path but never asserted
   the *fallback* sentence was itself grounded, and never clamped figures
   (`reduction_pct` could in principle print negative or >100%; `savings_k`
   negative) — so a future change to `_figures` could silently emit an
   ungrounded headline through the "safe" path.

## Decision

Rewrite the guard internals in `narrate.py` around a single, value-correct
numeric model, while keeping the public surface (`build_insight`, `Insight`)
unchanged so callers and the existing `tests/test_urban_narrate.py` are
untouched.

- **Numbers are tokens, not digit runs.** `_nums()` matches `\d+(?:\.\d+)?` and
  canonicalizes via `_canon` (`2.0` → `"2"`, `07` → `"7"`, `2.50` → `"2.5"`).
  The whitelist (`_whitelist`) is the canonical form of each figure *value* — the
  single source of truth. The deterministic sentence is built from those same
  values, so it is grounded by construction, and the LLM line is held to the
  identical set. `2.5` no longer whitelists `25`.
- **Guard invariant, stated once, used everywhere.** `is_grounded(text, figures)`
  (and the internal `_unverified`) is the predicate "every number in `text`
  comes from `figures`, years excepted." `build_insight` applies it to the LLM
  output *and* defensively to the fallback (rebuilding a still-grounded, less
  specific sentence in the should-never-happen case the template regresses).
- **Year exemption mirrors civic_analyst.** Integers in `1900..2100` are treated
  as descriptive context, not fabricated figures — exactly as
  `verify._allowed_numbers`/`verify_claims` do for the risk narrative.
- **Degenerate runs are first-class.** `station=None` renders as
  `"no single station"` (never `"None"`); `f["station"] in out` is replaced by a
  membership test on that safe phrase. `reduction_pct` is clamped to `[0, 100]`,
  `savings_k` to `>= 0`, and `minutes_after` to `>= 0`, so pathological inputs
  (zero crowd, empty substrate, baseline==best, event_end after the peak) can
  never print a negative/impossible figure or crash.

`optimize.py` is unchanged (read-only dependency); all behaviour lives in
`narrate.py`.

## How it mirrors the civic_analyst hallucination guard

| civic_analyst (`agents/verify.py`)              | urban_os (`narrate.py`)                         |
|-------------------------------------------------|-------------------------------------------------|
| Compute findings deterministically; LLM phrases | Compute figures deterministically; LLM phrases  |
| `_allowed_numbers` from findings/evidence       | `_whitelist` from `insight.figures` values      |
| `_ints(claim) - allowed`, year-range exempt     | `_unverified(text, allowed)`, year-range exempt |
| Untraceable number → reject claim               | Untraceable number → reject sentence → fallback |
| Source tag must be a valid evidence id          | Station name must appear verbatim in the line   |
| Deterministic narrative on any failure          | Deterministic template on any failure / offline |

Same principle (let the model phrase, never invent; trace every number to
evidence; degrade to a correct-by-construction line), right-sized to numeric
display figures instead of tagged claims.

## Consequences

- **Stronger guarantee.** Every numeric token in `insight.text` provably traces
  to `insight.figures` (years excepted) on both the LLM and fallback paths,
  verified by property-style tests over a crowd-size sweep and by the explicit
  decimal-vs-integer test that the old `_ints` approach failed.
- **Crash-free + offline-safe + deterministic** across degenerate scenarios
  (zero crowd → `station=None`, empty single-sink substrate, baseline==best),
  all covered by new tests in `tests/test_urban_narrate_hardening.py`.
- **No public-API or prompt change**; the demo invariant "narrator cites only
  evidence passed in" is preserved and tightened, not loosened. Existing
  `test_urban_narrate.py` and `test_narrator_quality.py` still pass unedited.
- **Minor behavioural change:** decimals are now matched by value, so a model
  that re-renders `2.5` as `2.50` is still accepted (canonicalization), while a
  bare `25` is correctly rejected — a net tightening with no false negatives on
  faithful phrasings.
- `is_grounded` is now exported as a reusable predicate for callers/tests that
  want to assert groundedness of an arbitrary sentence against a figure set.
