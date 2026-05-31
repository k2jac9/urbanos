"""Runtime configuration, loaded from environment / .env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Local LLM (OpenAI-compatible: Ollama on the GX10 at :11434/v1, or NIM).
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    # Which inference runtime serves that endpoint. The client is runtime-agnostic
    # (it only speaks OpenAI-compatible HTTP), so swapping Ollama for NVIDIA
    # TensorRT-LLM's ``trtllm-serve`` is a *config* change, not a code change — point
    # LLM_BASE_URL at the TRT-LLM server and set this to "tensorrt-llm" so the seam
    # records which runtime actually answered (ADR-0027). Default Ollama (dev/box);
    # this is the ONE place a real, on-camera single-GPU decode speedup exists.
    llm_runtime: str = "ollama"          # ollama | tensorrt-llm | nim | vllm
    # Two tiers: a small-active model for snappy interactive calls, and a larger
    # MoE for heavier batch reasoning (both decode acceptably on the GB10's
    # ~273 GB/s bandwidth because they're low-active-param / MoE).
    llm_model: str = "nemotron-3-nano"          # interactive
    # Batch tier for /digest. On the GX10 this coexists with the interactive Nano
    # (33B + Nano ≈ 59GB, both stay resident) so the city digest never evicts the
    # interactive model mid-demo — a 120B (super / gpt-oss) would, then /analyze
    # cold-loads again. Override via LLM_BATCH_MODEL for a bigger box.
    llm_batch_model: str = "nemotron3:33b"      # batch / heavy reasoning
    # Nemotron 3 is a *reasoning* model: left alone it emits a long chain-of-thought
    # before answering (~10x the latency). The interactive narrator only does
    # constrained JSON extraction, so we disable reasoning there ("none"). Empty
    # string omits the field entirely for strict OpenAI endpoints (e.g. NIM); the
    # batch tier overrides this to keep reasoning on for the harder city digest.
    llm_reasoning_effort: str = "none"          # none | low | medium | high | ""
    # Warm the interactive model at server boot (one tiny call in a daemon thread)
    # so the first /analyze of the demo isn't paying the ~5s cold-load. Off for CI.
    llm_prewarm: bool = True

    # City of Toronto CKAN endpoint.
    ckan_base_url: str = "https://ckan0.cf.opendata.inter.prod-toronto.ca"

    data_dir: Path = Path("./data/raw")


settings = Settings()
