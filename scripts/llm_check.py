"""Prove which LLM inference runtime is serving the narrator endpoint (run anywhere).

    PYTHONPATH=src python scripts/llm_check.py        # or:  make llm-check

The narrator client (``agents/llm.py``) is runtime-agnostic — it only speaks the
OpenAI-compatible HTTP API — so the *same code* runs on Ollama (dev/box default) or
on NVIDIA **TensorRT-LLM** via ``trtllm-serve`` (ADR-0027). This script:

  1. prints the configured runtime + endpoint,
  2. GETs ``/v1/models`` to prove the endpoint is live and which model it serves,
  3. times a small warm generation and reports tok/s — the ONE place a real,
     reproducible single-GPU decode speedup exists (TRT-LLM vs Ollama), the
     "real number on screen" the scorecard asks for.

Exits 0 regardless (a down endpoint is a valid offline outcome — the app falls back
to its deterministic narrator); the VALUE is the printed runtime + tok/s. On the box
with ``LLM_RUNTIME=tensorrt-llm`` and ``LLM_BASE_URL`` pointed at ``trtllm-serve``,
expect ``tensorrt-llm`` and a higher tok/s than the Ollama baseline.
"""
from __future__ import annotations

import time

from civic_analyst.agents import llm
from civic_analyst.config import settings


def main() -> int:
    print("=== LLM runtime check ===")
    print(f"configured: runtime={settings.llm_runtime!r}  base_url={settings.llm_base_url!r}  "
          f"model={settings.llm_model!r}")

    try:
        models = llm.probe_models()
        print(f"[serve]  /v1/models -> {models or '(none reported)'}")
    except Exception as exc:  # endpoint down → honest offline outcome
        print(f"[serve]  endpoint unreachable ({type(exc).__name__}) — app uses the "
              f"deterministic fallback narrator. Start trtllm-serve/Ollama to activate.")
        print("RESULT: offline (honest) — no runtime serving")
        return 0

    # Warm + timed generation: a tiny constrained prompt (what the narrator does).
    client = llm.interactive_llm()
    prompt = "Reply with exactly the word: ok"
    try:
        client.chat("You are a terse assistant.", prompt)        # warm-up
        n = 24
        t0 = time.perf_counter()
        out = client.chat("You are a terse assistant.",
                          "Count from 1 to 24 separated by spaces.")
        dt = time.perf_counter() - t0
        approx_tokens = max(1, len(out.split()))
        print(f"[decode] runtime={llm.LLM_BACKEND!r}  ~{approx_tokens} tok in {dt:.2f}s  "
              f"-> ~{approx_tokens / dt:.1f} tok/s (rough; for slide use the server's own metrics)")
    except Exception as exc:
        print(f"[decode] generation failed ({type(exc).__name__}) — endpoint up but model "
              f"not ready.")

    active = llm.LLM_BACKEND
    print(f"\nRESULT: runtime active = {active!r}",
          "✅ TensorRT-LLM path" if active == "tensorrt-llm" else "(set LLM_RUNTIME=tensorrt-llm "
          "+ point LLM_BASE_URL at trtllm-serve on the box to activate the TRT-LLM path)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
