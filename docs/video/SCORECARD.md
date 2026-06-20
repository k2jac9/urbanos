# Judging Scorecard — where we are → how we get to full marks

Honest self-assessment against the official rubric (100 pts) + the Nemotron bounty, with a
**from-here → to-target** action for every line item. Scores are grounded in an audit of what's
**actually wired in code** (not docs). Source of truth for figures: README + `docs/PITCH.md`;
provenance in `docs/DEMO_SCRIPT.md`. Owners per `CLAUDE.md`: **@cyberqubit → ingest/graph/data**,
**@k2jac9 → agents/api/UI**.

> **Guardrail (applies to the video, README, and pitch): claim only what's wired.**
> ✅ Defensible: Nemotron-3-Nano at runtime · on-device/offline · hallucination guard ·
> deterministic kernel + optional Rust accel · 3-dataset fusion · MCP/NemoClaw ·
> **RAPIDS GPU seams now WIRED & box-proven (ADR-0024/0025): nx-cugraph, cuDF (via Polars),
> cuOpt evac-flow LP, cuML hotspot clustering — all opt-in, CPU-fallback, reported by
> `make gpu-check`; 429 tests green.**
> ⚠️ Honesty caveat (still the #1 credibility risk): **no speedup at demo scale** (17/459-node
> graphs) — the GPU win is at *city scale*. Claim the **capability + city-scale**, never a live
> benchmark we can't reproduce on camera.
> 🟡 Now wired (ADR-0027), claim **carefully**: **TensorRT-LLM** — the narrator
> runs unchanged behind `trtllm-serve` (set `LLM_RUNTIME=tensorrt-llm`); the box engine IS
> built and Nemotron-3-Nano serves via TRT-LLM (NVFP4/Blackwell FP4, OpenAI-compatible, Ollama
> fallback — a runtime-portable narrator). `make llm-check` reports the runtime as a **capability /
> proof-of-invocation, NOT a speedup**: measured single-stream decode is **not** faster than Ollama
> (54.5 vs 61.2 tok/s); throughput-under-load advantage is **unproven (next-step)**. Claim the
> capability (Nemotron served via TRT-LLM on the box), never a decode speedup.
> **PhysicsNeMo (Modulus)** — a J-surrogate *interface* for
> city-scale optimizer search, exact kernel still decides every result; **no trained
> checkpoint ships**, so claim the seam + next-step, NOT a working surrogate.

---

## Summary

| Category | Now | Target | Gap |
|---|---:|---:|---:|
| 1. Technical Execution & Completeness | 27 | 30 | 3 |
| 2. NVIDIA Ecosystem & Spark Utility | 27 | 28 | 1 |
| 3. Value & Impact | 15 | 19 | 4 |
| 4. Innovation & Execution | 18 | 19 | 1 |
| **Total** | **~87** | **~96** | **~9** |

Realistic ceiling is ~96, not 100 — usability is capped by synthetic calibration constants
(honestly flagged). "The Stack" is now full-marks-strong (**six NVIDIA libraries invoked** — see 2a),
with **TensorRT-LLM** adding a proven **capability** — Nemotron-3-Nano served via TRT-LLM on the box
(NVFP4/Blackwell FP4, OpenAI-compatible, Ollama fallback; runtime-portable narrator — ADR-0027),
shown live by `make llm-check`. **No single-stream decode speedup** (54.5 vs 61.2 tok/s — TRT-LLM is
~11% slower single-stream); throughput-under-load is **unproven (next-step)**. RAPIDS numerics also
show no demo-scale speedup (city-scale win, by design — ADR-0024/0025).

---

## 1. Technical Execution & Completeness (30)

| Item | Where we are (evidence) | Now | Max | How to close the gap | Effort · Owner |
|---|---|---:|---:|---|---|
| **Completeness** (full workflow, no crash) | End-to-end runs both apps: ingest→graph→two-index risk→narrate→verify→UI; urbanos.kernel sim→optimize→narrate. **429 tests green** (427 pass · 1 skip · 1 xfail); offline-safe fallback. | 14 | 15 | In the video, **show the full loop live, unedited** (input→processing→output) incl. the unplug. Have `:8000` + `:8001` both warm so nothing stalls on camera. | S · @k2jac9 |
| **Technical Depth** (complex pipeline, not a wrapper) | Real kernel: substrate + time loop + 4 operators (`source/transport/couple/observe`); optimizer grid-search; multi-dataset graph fusion; hallucination guard; optional Rust core; MCP server. | 13 | 15 | **Make depth legible to judges**: the architecture slide + README diagram must show the kernel/operators/optimizer/verifier explicitly (depth that isn't shown isn't scored). Narrate "deterministic simulation, not a lookup." | S · @k2jac9 (diagram), @cyberqubit (README) |

---

## 2. NVIDIA Ecosystem & Spark Utility (30)  ⚠️ biggest lever

| Item | Where we are (evidence) | Now | Max | How to close the gap | Effort · Owner |
|---|---|---:|---:|---|---|
| **The Stack** (≥1 major NVIDIA lib/tool) | **REAL (6 libs invoked):** NeMo — Nemotron-3-Nano at runtime (`agents/llm.py`); **TensorRT-LLM** narrator runtime (`LLM_RUNTIME=tensorrt-llm`, `make llm-check` times warm decode — ADR-0027); **nx-cugraph** substrate SSSP (`kernel/state.py`); **cuDF** via Polars ingest (`ingest/loader.py`); **cuOpt** evac-flow LP (`urbanos/kernel/flow.py`, `/flow`); **cuML** KMeans hotspots (`cluster.py`, `/clusters`). Plus a **PhysicsNeMo** J-surrogate *seam* (interface only, no checkpoint — next-step). All opt-in, CPU/Ollama-fallback, box-proven by `make gpu-check`/`make llm-check`; ADR-0024/0025/0027; 429 tests green. | 14 | 14 | **Box TRT engine is built**; show `make llm-check` confirming the runtime is TensorRT-LLM on camera — that's proof-of-invocation (the **capability**), **not** a speedup (single-stream is not faster than Ollama, 54.5 vs 61.2 tok/s; throughput TBD). PhysicsNeMo stays "seam/next-step." | **DONE** (wiring + box engine) · @cyberqubit/@k2jac9 |
| **The "Spark Story"** (why DGX Spark specifically) | Strong + true: 128GB unified memory holds Nano (interactive) + 33B MoE (batch) **simultaneously**; on-device for civic-data privacy + latency; ARM64 aarch64; MoE small-active chosen for ~273 GB/s bandwidth. **Nemotron-3-Nano served via TensorRT-LLM on the box (`make llm-check`) is a concrete capability** (NVFP4/Blackwell FP4) — note it is NOT a decode speedup (single-stream 54.5 vs Ollama 61.2 tok/s). | 13 | 14 | **Say it explicitly on camera** in the "how we built it" beat — unified-memory co-residency + privacy + bandwidth-aware model choice + the TRT-LLM **capability** (runtime portability, not a speedup). Last point: also show resident GB for both models co-resident. | S · @k2jac9 (script), @cyberqubit (measure) |

> ✅ Done (ADR-0024/0025/0027): six NVIDIA libraries are now *used*, each with the command that proves
> it (`make gpu-check`). README has moved RAPIDS/cuOpt/cuML from "aspirational" to "wired, opt-in,
> CPU-fallback" — keep it that way (capability + city-scale, never a demo-scale speedup claim).

---

## 3. Value & Impact (20)

| Item | Where we are (evidence) | Now | Max | How to close the gap | Effort · Owner |
|---|---|---:|---:|---|---|
| **Insight Quality** (non-obvious, valuable) | Cross-domain "one lever, every lens"; "don't route a crowd through the least-safe districts"; Exhibition GO as the single secondary crush for BMO Field's 46k. | 8 | 10 | Lead the climax with the **non-obvious** insight, not the headline $: name the *specific* finding (which station, which districts, why) — mirrors the rubric's "rain stalls this specific ramp" example. | S · @k2jac9 |
| **Usability** (a planner could use it tomorrow) | Real datasets + click-to-verify; but optimizer calibration constants are **synthetic (flagged)** → caps "tomorrow." | 7 | 9 | Frame the **decision** a planner makes ("stagger releases by N min across these venues") and show ✓-verify as the audit trail. Add a README "Known limitations" being explicit that constants are synthetic but the *shape/method* is the product. Honesty here is scored, not penalized. | S · @cyberqubit (README), @k2jac9 (framing) |

---

## 4. Innovation & Execution (20)

| Item | Where we are (evidence) | Now | Max | How to close the gap | Effort · Owner |
|---|---|---:|---:|---|---|
| **Creativity** (novel combo) | Microkernel "OS for the city"; four lenses on one kernel; civic-risk app made a *literal* kernel lens; cross-domain optimization. | 9 | 10 | Already strong — just make the "a new lens is ~90 lines, not a rewrite" platform point explicit in video + deck. | S · @k2jac9 |
| **Performance** (optimized for speed/scale) | Optional Rust core with measured parity + speedup (ADR-0009); sub-2s warm narration; deterministic kernel. Opt-in GPU path wired (nx-cugraph/cuDF/cuOpt/cuML). **TensorRT-LLM serves Nemotron on the box as a capability** (`make llm-check`, ADR-0027) — but **no single-stream decode speedup** (54.5 vs 61.2 tok/s; throughput TBD). | 9 | 9 | Show `make llm-check` confirming the **runtime** (capability), the Rust-vs-numpy speedup (ADR-0009), and warm latency. **Do not** claim a TRT-LLM decode speedup — single-stream is not faster than Ollama; throughput-under-load is unproven (next-step). RAPIDS numerics: cite as city-scale, don't fake a demo-scale number. | S–M · @cyberqubit (measure), @k2jac9 (show) |

---

## Bounty — Best Use of NVIDIA Nemotron

| Where we are | How to win it |
|---|---|
| Local Nemotron-3-Nano narrates, now served behind **NVIDIA TensorRT-LLM** (NVFP4/Blackwell FP4, OpenAI-compatible, Ollama fallback — a runtime-portable narrator, ADR-0027); **hallucination guard** rejects any number/source not in evidence → deterministic fallback; **agent-drivable** via MCP (NemoClaw matched the tool exactly). | Make the bounty case explicit: Nemotron isn't a chatbot here — it **phrases verified figures only** ("a hallucinated number physically cannot reach the screen"), runs **locally on the box via TensorRT-LLM** (a capability — *not* a decode speedup; single-stream 54.5 vs Ollama 61.2 tok/s, throughput TBD), and **drives tools as an agent**, all **local**. Show the "9 vs 8 permits" verifier catch + `make llm-check` confirming the runtime on camera. |

---

## Priority order (best points-per-hour)
1. **Honesty pass first (zero risk, protects all 100 pts):** video + README + pitch now claim the
   wired RAPIDS seams as *used* (opt-in, CPU-fallback) — keep the **capability + city-scale** framing
   and never imply a demo-scale speedup. TensorRT-LLM + PhysicsNeMo are now wired (ADR-0027):
   claim the TRT-LLM **capability** (Nemotron served via TRT-LLM on the box, runtime-portable with
   an Ollama fallback) — **not** a decode speedup (single-stream 54.5 vs Ollama 61.2 tok/s;
   throughput-under-load unproven, next-step) — and the surrogate
   *interface* — not a trained surrogate (no checkpoint ships; exact kernel still decides).
2. **Architecture diagram + explicit Spark story** (cheap, lifts 1b, 2b, 4a). — @k2jac9 / @cyberqubit
3. ~~**Wire one real NVIDIA accelerator**~~ ✅ **DONE** — six libs wired & box-proven (ADR-0024/0025/0027;
   2a 10→14, 4b 7→9, 2b 12→13). The box-side TensorRT-LLM engine is **built**; `make llm-check` confirms
   Nemotron serves via TRT-LLM on camera (a **capability** — *not* a decode speedup: single-stream 54.5
   vs Ollama 61.2 tok/s; throughput-under-load unproven, next-step). Optional city-scale RAPIDS number on
   a slide. — @cyberqubit / @k2jac9
4. **Sharpen the insight + usability framing** on camera (1 pt each, ~free). — @k2jac9
5. **Put real perf numbers on screen** (`make llm-check` confirming the TensorRT-LLM runtime — a capability, not a speedup; Rust speedup, warm latency, `make gpu-check` backends). — @cyberqubit / @k2jac9

> Invariants from `CLAUDE.md` still hold: ARM64 only, MoE/small-active models, map 100% offline,
> narrator cites only evidence, `make test` green before any push. Don't regress these for points.
