# ADR-0026 — Public-UI clarity & explanatory context (design approach)

**Status:** Accepted (executing in phases) · **Date:** 2026-05-31
**Relates:** ADR-0008/0017 (urban_os UI), ADR-0019 (benefit semantics), ADR-0024/0025 (GPU honesty), PR #75 (UI a11y/honesty)
**Surfaces:** civic `map.html` (public `:443`, 621 ln) · urban_os `os.html` (public `:8443`, 771 ln)

## Context

The two public demos are visually strong and already carry real context (lens
titles, `psub` intros, `hint` captions, a band legend in `map.html`, benefit
tooltips, "✓ verify" framing — most added in PR #75). But a **cold judge** is still
dropped straight into a dense map + panel: the *orientation* ("what am I looking at,
what do I do, what does the colour mean") is implicit. The ask is **a little more
context so it's instantly understandable** — not a redesign. This ADR researches the
right principles, audits what we have, and commits to a careful, minimal approach.

## Principles we're designing against

Distilled to what actually decides our changes (not a checklist to bolt on):

- **Apple HIG — Clarity · Deference · Depth.** The *map and the data are the content*;
  chrome must defer to them. Add meaning, not decoration. Reveal complexity on demand
  (Depth), don't front-load it.
- **Rams — "As little design as possible / less, but better."** Every addition must
  earn its pixels. Prefer one well-placed orientation line over a paragraph.
- **Rams — Understandable.** The product should explain its own structure: a legend so
  colour encodings are self-evident; provenance so the grounding is obvious.
- **Rams — Honest** (the spine of everything we just shipped). Copy must never overstate:
  benefit numbers stay labelled (ADR-0019), synthetic dollars read as *illustrative*,
  GPU reads as "on the box," not "faster here" (ADR-0024/0025). Design must *preserve*
  the honesty we engineered, never paper over it.
- **Visual principles — Hierarchy, Contrast, Proximity, White space, Repetition/Unity.**
  A clear first-read order (what → action → result); group related controls; let
  negative space carry hierarchy; one shared visual language across both surfaces.

## Current-state audit (grounded)

| Principle | Where we're good | Gap to close |
|---|---|---|
| Clarity / Understandable | lens titles, `psub` intros, "✓ verify", map.html band legend | no **first-load orientation** ("what is this + the one thing to do"); congestion-× scale & per-lens colour encodings not always legend-backed |
| Deference / less-but-better | map-first layout; panels are compact | panels mix *intro + controls + results* in one block → the eye has no clear entry point |
| Hierarchy | `num` emphasis, headings (real `<h1/h2/h3>` after #75) | the **one action** per lens (drag the lever / pick a pin) isn't the visual focal point |
| Honest | benefit labels + tooltips (ADR-0019); "ranked by most-elevated index" | dollar figures should visibly read *illustrative/calibrated*; new GPU analyses unframed |
| Repetition / Unity | each surface internally consistent | civic `map.html` and urban `os.html` use **different visual languages** (type scale, chips, colour) |
| Useful (new value) | — | the new **`/flow`** (cuOpt optimal-evacuation ceiling) and **`/clusters`** (cuML hotspots) aren't surfaced |

Strengths to **preserve, not regress**: 100% offline invariant (no CDN/tiles — test-gated),
WCAG contrast + focus rings + semantic headings + skip links (PR #75), the grounded
"✓ verify," and every honest number.

## Decision (the approach)

Adopt a **minimal, progressive-disclosure, deference-first** approach — *add meaning,
not chrome* — applied identically to both surfaces (Unity). Concretely, in priority order:

1. **Orientation line (Clarity, Hierarchy).** One sentence at the top of each surface:
   what this is + the single action. e.g. urban: *"Toronto on FIFA day — drag one lever
   and watch every lens move."* civic: *"Any Toronto address, risk-scored on two grounded
   indices — pick a pin."* Plus a dismissible **"How it works"** disclosure (Depth) — the
   substrate/lens/kernel one-liner, hidden by default.
2. **Legend (Understandable).** A compact, always-visible key for the colour encodings:
   Safety/Activity bands (the `0.34 / 0.67` cutoffs, ADR-0014) and the congestion-× scale.
3. **Provenance chip (Honest, Understandable).** "3 fused City of Toronto open datasets:
   DineSafe · permits · licences" near the data, reinforcing grounding.
4. **Hierarchy pass (Deference, White space).** Within each lens panel, separate
   *intro → action → result* with spacing/weight so the lever / pin-pick is the focal
   point; let white space do the work rather than more text.
5. **Honesty labels (Honest).** Mark synthetic dollar figures *illustrative (calibrated)*
   via a tooltip/footnote; keep ADR-0019 benefit labels.
6. **Surface the new analyses (Useful, Depth) — optional, last.** A compact, opt-in line:
   *"Optimal evacuation: clears 140,800 (cuOpt) · 4 risk hotspots (cuML)"* — only if it
   aids comprehension, never as clutter.
7. **Shared visual vocabulary (Repetition/Unity).** Reuse the existing CSS design-token
   system across both pages (band colours, type scale, chip style) so they read as one
   product.

## Scope, risks, and the careful plan

- **Phased, reversible, behaviour-preserving.** Each phase is a small PR, redeployed to
  the box with the `*.service.bak` rollback in hand; **no** numbers/endpoints change.
  - **Phase 1** (highest value / lowest risk): orientation line + "How it works"
    disclosure + legend + provenance chip + hierarchy pass. Copy + CSS only.
  - **Phase 2**: surface `/flow` + `/clusters` (Depth).
  - **Phase 3**: unify the two surfaces' visual language.
- **Invariants that gate every change** (must stay green): the offline test
  (`test_urban_ui_offline.py` — no external URLs), a11y (`<h1>`, `#time` label, skip
  link), and the honest numbers. Both HTML files already exceed the 500-line guideline;
  additions must be concise (and Phase 3 may extract shared CSS/JS to a vendored
  same-origin asset rather than inline growth).
- **Out of scope:** a framework/build step (breaks the offline single-file invariant),
  and any copy that overstates capability.

## Next step

This document is the *approach*. On approval we execute **Phase 1 only**, verify the
invariants + redeploy, then review before Phase 2 — "move ahead carefully."
