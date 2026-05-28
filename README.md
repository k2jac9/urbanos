# Toronto Civic Risk Analyst

A **local-first, multi-agent** civic intelligence app for the **NVIDIA Spark Hack — Toronto**
(May 29–31, 2026). It fuses several City of Toronto open datasets into a knowledge graph,
then a supervisor agent + specialized sub-agents (running on a **local Nemotron model**
on the ASUS Ascent GX10 / NVIDIA GB10) produce an **actionable risk read** for any address
or business — with sources and a drafted action. No data leaves the device.

## Why this shape
- **Track:** Public Services (frames cleanly as Economic Systems for the investor pitch).
- **Winning pattern** (mirrors the NYC Spark Hack overall winner): multi-dataset knowledge
  graph + multi-agent + an *actionable* output + an obvious commercial buyer (city
  inspections, insurers, lenders, commercial real estate) + a 100% on-device story.
- **Hardware reality:** GB10 has 128 GB unified memory but ~273 GB/s bandwidth — use
  **MoE / small-active models** (Nemotron Nano, or gpt-oss-120B MoE) for a snappy live demo.
  Dense 70B+ decode is too slow (~2.7 tok/s).

## Architecture
```
City of Toronto Open Data (CKAN)
  building permits · DineSafe inspections · 311 requests · business licences
        │  ingest/ckan.py + ingest/datasets.py
        ▼
   Knowledge graph (graph/builder.py, networkx)
        │
        ▼
   Supervisor agent  ──►  sub-agents (retrieval · compliance · risk)
   agents/supervisor.py     agents/subagents.py
        │  local LLM via OpenAI-compatible endpoint (agents/llm.py)
        ▼
   FastAPI  /analyze?address=...   (api/server.py)  +  CLI (cli.py)
```

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # point LLM_BASE_URL at your local Ollama/NIM endpoint

python scripts/download_data.py # pre-fetch datasets (do this BEFORE the venue!)
make serve                      # FastAPI on :8000  → GET /analyze?address=...
# or
python -m civic_analyst.cli analyze "100 Queen St W"
```

## Instant demo (no downloads)
Synthetic fixtures live in `fixtures/`, so you can show a populated demo without
fetching any real data:
```bash
make demo        # serves the API + map against fixtures/
make demo-cli    # prints a populated report and exits
```
Then open **http://localhost:8000/** — a Leaflet map with pins colored by risk
(red = high). Click a pin to run the agentic read. Endpoints:
- `GET /`           map UI
- `GET /addresses`  geocoded addresses + fast risk score (no LLM) — drives the pins
- `GET /analyze?address=…`  full agentic read (Nemotron Nano, interactive tier)
- `GET /digest`     city-wide briefing (gpt-oss-120B MoE, batch tier)

## Two model tiers
`LLM_MODEL` (Nemotron Nano) handles snappy interactive `/analyze`; `LLM_BATCH_MODEL`
(gpt-oss-120B MoE) handles the heavier `/digest`. Both are MoE / small-active so they
decode acceptably within the GB10's ~273 GB/s bandwidth.

## Agentic tools over MCP (NemoClaw / OpenClaw)
The datasets and risk engine are exposed as MCP tools (`list_datasets`,
`dataset_resources`, `analyze_address`, `top_risk`) so a local agent runtime can
call them — the pattern the NYC winner used:
```bash
python -m civic_analyst.mcp_server      # stdio MCP server
```
On the GX10, point **NemoClaw** (running Nemotron locally via OpenShell) at
`config/nemoclaw.mcp.json` so the agent answers civic-risk questions through our
tools — the "Best Use of Nemotron/NemoClaw" integration.

## Stretch goal: QLoRA fine-tune (GX10 GPU)
Messy address matching is our hard problem. `scripts/finetune_address_resolution.py`
trains a Nemotron-Nano QLoRA adapter (Unsloth/TRL) on `fixtures/address_resolution.sample.jsonl`,
served back via `vllm serve --enable-lora`. Optional — only if the core demo is solid.

## Local model (on the GX10)
The GX10 ships with Ollama + DGX OS (ARM64). Pull a small-active model and serve its
OpenAI-compatible endpoint:
```bash
ollama pull nemotron-3-nano        # or: gpt-oss:120b  (MoE, ~35-40 tok/s)
# Ollama exposes http://localhost:11434/v1  -> set LLM_BASE_URL accordingly
```

## Pre-event checklist
- [ ] Apply as a full 4–5 person team (30-team cap, host-approved).
- [ ] Resolve the Luma wallet/token gate with organizers.
- [ ] Run `scripts/download_data.py` at home — don't rely on venue Wi-Fi.
- [ ] Build the dev image **ARM64-native** (`docker build` on the GX10 or `--platform linux/arm64`).
- [ ] Verify a building-inspections dataset / use permit status fields as the inspection signal.

See `docs/`/the team brief for the full strategy. Built for the hackathon; MIT-style use.
