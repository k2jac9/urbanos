# ADR-0028 — Learned-dynamics lens: the Action-Matching floor (data-driven transport calibration)

**Status:** Accepted · **Date:** 2026-06-19 · **Relates:** ADR-0027 (PhysicsNeMo surrogate seam — the honesty template), ADR-0024/0025 (opt-in GPU/learned seams), ADR-0002 (capacitated substrate), ADR-0014 (two-index risk) · **Research:** `docs/research/tpf-and-data-driven-lenses.md` §6/§7/§8.3

## Context

The data-driven roadmap (research note §8) is phased: Phase 0 ingested the TMC time-marginal counts; Phase 1 shipped `CongestionNowcastLens` (kernel-vs-observed *calibration*, no learned field). Phase 2 (§8.3) is the **"Action Matching floor"**: a minimal learned velocity field fit from those marginals, rolled out, and **compared against (a) the kernel and (b) the observed counts** — to establish, before any heavier TPF machinery is justified, whether a learned field beats the kernel at all.

Action Matching's canonical form trains a neural action `s(x,t)` (with `u = ∇s`) by SGD. This repo is **numpy-only — no torch, no autodiff** (`requirements.txt`). Per the roadmap's explicit descope clause, rather than fake a neural loop we ship the **deterministic least-squares floor that obeys the same continuity law** Action Matching's velocity satisfies. It answers the Phase-2 question with a closed-form fit instead of SGD; the boundary is stated in the module docstring.

## Decision

**`urban_os/learned_dynamics.py` — an advisory diagnostic, not a loop lens.** Like `surrogate.py`, it is consulted *alongside* a finished kernel run, never inside the time loop:

1. **The learned field.** A velocity field on the substrate is a per-edge flow `f`. Discrete continuity (the graph analogue of `∂ρ/∂t + ∇·(ρu) = 0`) ties a node's mass change between observed bins to the divergence of `f`: `B f = Δc`, with `B` the signed node–edge incidence. We solve it per bin by **ridge least squares** (`(BᵀB + λI) f = Bᵀ Δc`), which makes the rank-deficient system unique and selects the **minimum-energy** flow — so circulation the data does not demand is not invented (the §2 "no a-priori curl control" caveat).
2. **Rollout + comparison.** Fit on the leading `train_fraction` of bins, average to the typical learned velocity, roll forward from the last training marginal (clamped non-negative, mass-renormalised), and score the **held-out** tail: learned-rollout-vs-observed and kernel-load-vs-observed shape agreement (cosine — the same scale-free primitive Phase 1 uses; the series share no absolute scale). Report `learned_better` + `margin`.
3. **Surface.** `services.learned_dynamics_report` reuses the observed series the nowcast lens already carries (no extra plumbing, no extra sim) and `GET /lenses` returns a `learned_dynamics` block beside the Phase-1 `calibration` block.

## Honesty notes (the #1 credibility rule — roadmap §7, none regressed)

- **Learned predicts, exact kernel decides (§7.1).** Advisory/diagnostic only: **no lever, no `J` cost**, consulted after the run. It cannot move the optimizer, the chosen lever, or any headline `J` / priced-lens number — pinned by a test that toggles the flag and asserts every priced headline (`combined_cost`, `cross_domain_benefit`, the calibration fit) is byte-identical on/off.
- **Opt-in + CPU fallback (§7.2).** Off by default; gated behind **`URBANOS_LEARNED_DYNAMICS`** (mirrors `URBANOS_SURROGATE`). Absent the flag or with too-thin data → `available=False`, a clean no-op. numpy-only and deterministic — CI/dev never need a model or CUDA.
- **Provenance honesty (§7.3).** Every output is stamped `provenance="learned/approximate"`, distinct from kernel-exact fields.
- **Narrator boundary (§7.4).** Nothing here touches `narrate.py`; a learned number reaching the guarded narration would need its own evidence kind — deliberately out of scope.
- **No private deps (§7.5).** A from-scratch least-squares fit; never vendors `flanch`/`hdfx`/`hdfv`.

## Verification

`tests/test_learned_dynamics.py` (12 tests): incidence/continuity (`B f ≈ Δc`); off-by-default no-op + flag enables + boundary validation; the diagnostic perturbs neither kernel transport nor priced lenses; provenance label; **fairness** — when the observed series *is* the kernel's own load the kernel wins (`learned_better=False`); the Phase-2 **finding** — on the TMC-shaped marginal slice the learned field beats the kernel (positive margin); determinism; and the `/lenses` advisory block with the headline unchanged on/off. Full suite green.

**Finding (demo TMC-shaped slice):** the learned field **beats the kernel** — `learned_fit ≈ 0.99` vs `kernel_fit ≈ 0.05`. The honest reading: the kernel's strictly-downhill drainage (ADR-0002) structurally cannot reproduce the smooth build-up/circulation in the marginal data, which a continuity-fit field can. This is the signal the roadmap wanted before committing to Phase 3 (TPF / grey-box residual): a learned field *does* capture structure the kernel misses — but it remains advisory, because a black-box predictor must never decide the city's intervention.

## What's next (Phase 3, when justified)

If the learned field's edge in *rotational* structure proves out on real (non-synthetic) TMC, add the TPF CFM→regression core as a **residual on the kernel reference** (VGB-DM grey-box framing). Still advisory. Training/validating that residual is the documented stretch — not faked here.
