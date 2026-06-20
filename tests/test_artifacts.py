"""Cheap guards for the NemoClaw config and the fine-tune sample dataset."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_nemoclaw_mcp_config_is_valid():
    cfg = json.loads((ROOT / "config" / "nemoclaw.mcp.json").read_text())
    server = cfg["mcpServers"]["toronto-civic"]
    assert server["command"] == "python"
    assert server["args"] == ["-m", "urbanos.risk.mcp_server"]


def test_finetune_sample_dataset_parses():
    rows = [
        json.loads(line)
        for line in (ROOT / "fixtures" / "address_resolution.sample.jsonl")
        .read_text()
        .splitlines()
        if line.strip()
    ]
    assert rows and all({"raw", "canonical"} <= r.keys() for r in rows)
