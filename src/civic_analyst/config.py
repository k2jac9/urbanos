"""Runtime configuration, loaded from environment / .env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Local LLM (OpenAI-compatible: Ollama on the GX10 at :11434/v1, or NIM).
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    # Two tiers: a small-active model for snappy interactive calls, and a larger
    # MoE for heavier batch reasoning (both decode acceptably on the GB10's
    # ~273 GB/s bandwidth because they're low-active-param / MoE).
    llm_model: str = "nemotron-3-nano"          # interactive
    llm_batch_model: str = "gpt-oss:120b"       # batch / heavy reasoning (MoE)

    # City of Toronto CKAN endpoint.
    ckan_base_url: str = "https://ckan0.cf.opendata.inter.prod-toronto.ca"

    data_dir: Path = Path("./data/raw")


settings = Settings()
