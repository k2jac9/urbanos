# ADR-0027 — TensorRT-LLM narrator runtime + PhysicsNeMo (Modulus) J-surrogate seams

**Status:** Accepted · **Date:** 2026-05-31 · **Relates:** ADR-0024/0025 (RAPIDS seams + honest scoping), ADR-0009 (Rust accel opt-in pattern), ADR-0001 (kernel + optimizer)

## Context

The SCORECARD's honesty guardrail listed **TensorRT** and **Modulus** as "do NOT claim
— not wired." They were the last two NVIDIA libraries named anywhere without code
behind them. Following the exact ADR-0024 discipline — wire only what *genuinely fits*,
each as an opt-in seam with a verified non-GPU reference, and be honest about scope — we
add both as seams. One is high-value and low-risk; the other is honest-interface-only.

## Decision

1. **TensorRT-LLM — narrator inference runtime (`agents/llm.py`, `config.py`,
   `scripts/llm_check.py`, `make llm-check`).** The narrator client is already
   runtime-agnostic: it only speaks the OpenAI-compatible HTTP API. So serving Nemotron
   behind NVIDIA **TensorRT-LLM** (`trtllm-serve`, which *is* an OpenAI-compatible
   server) is a **config change, not a code change** — point `LLM_BASE_URL` at it and
   set `LLM_RUNTIME=tensorrt-llm`. The seam records which runtime actually answered in
   `llm.LLM_BACKEND` (mirroring `GRAPH_BACKEND`/`FLOW_BACKEND`/`CLUSTER_BACKEND`), and
   `make llm-check` probes `/v1/models` + times a warm decode. **This is the one seam
   with a real, on-camera-reproducible single-GPU speedup** (decode tok/s, TRT-LLM vs
   Ollama) — the "real number on screen" the scorecard wants. Default runtime is Ollama
   (dev/box); endpoint-down → the existing deterministic fallback narrator (unchanged).

2. **PhysicsNeMo (formerly Modulus) — J-surrogate seam (`urban_os/surrogate.py`, wired
   into `optimize.py`).** `optimize()` is simulation-in-the-loop: every lever combo runs
   a full kernel. At *city scale* that grid is intractable, which is exactly where a
   learned **surrogate operator** of `J(levers)` belongs (the substrate transport
   dynamics is PDE-like — PhysicsNeMo's domain). We wire the **interface with the exact
   kernel as the reference**: when `URBANOS_SURROGATE=1` *and* a trained checkpoint
   (`URBANOS_SURROGATE_CKPT`) is present, it predicts `J` per combo and records it as
   `J_surrogate` *next to* the exact value — but `best` is **always** chosen by the exact
   kernel `J`. An approximate number can never reach the UI. `OptResult.surrogate_backend`
   / `surrogate.SURROGATE_BACKEND` record what ran (`none` | `physicsnemo`).

Both follow the ADR-0024 template: opt-in env flag, graceful fallback (live demo never
blocked), backend recorded, proof script (`make llm-check`, plus a surrogate line in
`make gpu-check`). Box-side markers live in `requirements-gpu.txt`.

## Honesty notes (the #1 credibility rule)

- **TensorRT-LLM is real and demoable** — but it needs a per-model **engine build** on
  the box (aarch64/Grace for the GB10), not a pure pip step. Claim the capability + the
  decode-speedup number from `make llm-check`; don't claim a benchmark you can't
  reproduce on camera.
- **PhysicsNeMo ships as an INTERFACE ONLY.** There is no trained checkpoint, so the
  exact kernel decides every result today — identical to the pure grid. A learned
  surrogate is a *black box*, which is why it never touches the decision (only the
  search ordering, at city scale). **Training + validating a checkpoint is the
  documented next step** — pretending a working surrogate ships would be the exact
  overstatement ADR-0024 rejected for cuOpt. Default off → byte-identical to grid; the
  golden urban_os numbers are unchanged.

## Verification

`tests/test_gpu_seams.py`: `LLM_BACKEND` defaults to the configured runtime without any
network; a `LocalLLM` carries a `runtime` override; the surrogate is off by default and
`load()` returns None without a checkpoint; `optimize()` reports `surrogate_backend=none`
and leaks no `J_surrogate` into trials, with `best` unchanged. `make llm-check` reports
the runtime (or an honest offline result); `make gpu-check` reports the surrogate seam.
Full suite: **417 passed**, 1 skipped, 1 xfailed.
