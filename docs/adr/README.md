# Architecture Decision Records

Short records of the non-obvious choices behind Urban-OS. Newest decisions
supersede older ones only when explicitly marked.

- [ADR-0001](0001-urban-os-kernel-on-civic-analyst.md) — Build the Urban-OS dynamics kernel on the civic_analyst repo
- [ADR-0002](0002-transport-is-capacitated-drainage.md) — Transport is pure capacitated drainage; speed–density lives in the delay coupling
- [ADR-0003](0003-delay-model-and-honest-optimum.md) — Linear over-capacity delay + discounted hold cost for an honest optimum
- [ADR-0004](0004-rust-core-as-optional-accelerator.md) — Rust core is an optional drop-in accelerator, numpy is the always-present fallback
- [ADR-0005](0005-reuse-hallucination-guard-for-insight.md) — Reuse civic_analyst's hallucination guard for the killer insight
- [ADR-0006](0006-urban-os-api-contract-and-validation.md) — Harden the API surface + pin it with a contract/regression test lane
- [ADR-0007](0007-third-lens-weather.md) — WeatherLens: rain as a capacity tax + risk multiplier (third domain lens)
- [ADR-0008](0008-urban-os-ui.md) — Offline congestion/risk heatmap over the vendored MapLibre/PMTiles map
- [ADR-0009](0009-rust-accelerator-benchmark.md) — Measured Rust↔numpy parity + speedup; boundary-marshalling caveat
- [ADR-0010](0010-narrator-hallucination-guard.md) — Narrator guard: every figure in the insight traces to the evidence
- [ADR-0011](0011-honest-peak-independent-of-frame-sampling.md) — Peak congestion is computed over every step, independent of frame_every subsampling
- [ADR-0012](0012-map-qa-screenshot-harness.md) — Map QA via a Playwright CDP harness (one-shot headless can't render WebGL2+PMTiles)
- [ADR-0013](0013-dedup-inspections-and-severity-honesty.md) — De-dup inspections by (estId, date) visit + severity honesty (Conditional Pass ≠ adverse; convictions surface as severe)
- [ADR-0014](0014-two-index-safety-activity.md) — Two-index model: independent Safety vs Activity scores (never summed), severity-weighted safety to keep the LOW band alive
- [ADR-0015](0015-shelter-as-real-lever-and-cost-transparency.md) — Urban-OS: price crush-safety into J so shelter is a real lever, surface the J-decomposition, fix sink-injection (map==engine)
- [ADR-0016](0016-shelter-interior-optimum-coverage-premium.md) — Convex coverage premium + fine grid → shelter is a genuine *interior* optimum (release 16 + 50% shelter), not a corner
- [ADR-0017](0017-urbanos-ui-live-breakdown-and-timeline-trim.md) — Urban-OS UI: live J-breakdown that tracks levers, optimizer-card invalidation, trim the dead timeline tail (3rd audit's other findings refuted)
- [ADR-0018](0018-fifa-convergence-crunch-substrate.md) — FIFA-window convergence crunch: multi-venue EventSurge (4 concurrent let-outs, 140,800 people) into the Union/Exhibition-GO corridor under one coordinated release lever; real exit lines replace abstract sinks
- [ADR-0024](0024-rapids-gpu-accelerator-seams.md) — RAPIDS GPU accelerator seams (nx-cugraph substrate dijkstra + cuDF-via-Polars ingest), opt-in with CPU fallback
- [ADR-0025](0025-cuopt-flow-and-cuml-clusters.md) — cuOpt evacuation max-flow `/flow` + cuML risk-hotspot `/clusters`, opt-in GPU with networkx/CPU fallback
- [ADR-0027](0027-tensorrt-llm-and-physicsnemo-surrogate-seams.md) — TensorRT-LLM narrator runtime (config not code) + PhysicsNeMo J-surrogate seam (interface-only), opt-in, exact kernel decides
- [ADR-0028](0028-learned-dynamics-action-matching-floor.md) — Learned-dynamics lens: the Action-Matching floor (least-squares velocity fit from TMC marginals), advisory-only, opt-in, exact kernel decides
