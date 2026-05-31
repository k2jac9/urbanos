# ADR-0020 — Civic narrator guard parity (decimal-safe numbers + record-kind matching)

**Status:** Accepted · **Date:** 2026-05-31 · **Relates:** ADR-0010 (urban_os narrator guard), ADR-0005 (reuse the guard)

## Context

The architecture audit found that `civic_analyst`'s hallucination guard
(`agents/verify.py::verify_claims`) **enforced less than its own system prompt
advertised** — the single highest-severity correctness finding for the
"grounded citations" pitch:

1. **No record-kind matching.** The prompt states "the cited tag's record type must
   match what the claim is about (cite a permit row for a permit claim, an inspection
   row for an inspection claim)." But `verify_claims` only checked that the cited tag
   *exists*. A claim like *"A failed health inspection means closure is imminent"*
   citing a **permit** row passed the guard — an ungrounded, mis-sourced claim
   reaching the user.
2. **Digit-run number extraction.** `_ints` used `re.findall(r"\d+")`, splitting
   `2.5` into `{2, 5}`. A claim "risk rose 2.5x" was accepted whenever `2` and `5`
   appeared anywhere in the evidence. This is exactly the flaw ADR-0010 fixed in
   `urban_os/narrate.py` — but the fix was never back-ported to civic.

## Decision

Bring the civic guard to parity with the hardened urban_os guard:

- **Decimal-safe numeric model.** Replace `_ints` with `_nums`/`_canon` (mirroring
  `narrate.py`): a number is `\d+(?:\.\d+)?`, canonicalised so `2.0`≡`2` and
  `2.50`≡`2.5` compare on value, and decimals are never split. Years (1900–2100)
  remain exempt as descriptive context.
- **Record-kind matching.** `verify_claims` now accepts the `tag_map` (not just the
  tag set). It infers a claim's topic from its wording (`_claim_kind`) and, when that
  topic is **unambiguous**, requires the cited tag's `kind` to match. Ambiguous or
  topic-less claims skip the check — we reject mis-citations, not merely loose
  phrasing.
- **Back-compatible signature.** `verify_claims(claims, address, findings, tags)`
  accepts either a `tag_map` dict (enables kind-matching) or a bare set of valid tags
  (legacy: existence + numbers only). The production path (`subagents.py`) now passes
  the `tag_map`; existing callers/tests that pass a set keep working.

## Consequences

- The guard now enforces what the prompt promises: a permit claim citing an
  inspection row is rejected; a `2.5x` that isn't a real figure is rejected. The
  "narrator cites only datasets passed in evidence" invariant holds at the
  *substantiation* level, not just *tag-exists*.
- Civic and urban_os now share the same numeric-grounding model (ADR-0010), so a
  future change can be reasoned about once.
- Slightly stricter guard ⇒ a marginally higher fall-back-to-deterministic rate for
  a sloppy small model. Acceptable: the fallback is correct-by-construction, and a
  grounded template beats an ungrounded LLM sentence.

## Tests

`tests/test_verify.py` adds: decimal smuggling rejected (`2.5` not accepted from
`{2,5}`), year-like numbers still exempt, kind-mismatch caught with `tag_map`,
kind-match passes, and kind-matching skipped for the bare tag set (back-compat).

## Not done here (tracked separately)

The all-or-nothing fallback (one bad claim discards the whole LLM response) is a
separate quality improvement and is intentionally out of scope for this correctness
ADR.
