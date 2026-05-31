# Toronto Civic Risk Analyst

[![CI](https://github.com/cyberqubit/spark-hack-toronto/actions/workflows/ci.yml/badge.svg)](https://github.com/cyberqubit/spark-hack-toronto/actions/workflows/ci.yml)

A **local-first, multi-agent** civic intelligence app for the **NVIDIA Spark Hack — Toronto**
(May 29–31, 2026). It fuses several City of Toronto open datasets into a knowledge graph,
then a supervisor agent + specialized sub-agents (running on a **local Nemotron model**
on the ASUS Ascent GX10 / NVIDIA GB10) produce an **actionable risk read** for any address
or business — with sources and a drafted action. No data leaves the device.

> **🔴 Live demo (during the event):** **https://gx10-4428.taila9fe06.ts.net** — the real app
> served straight from the GX10 box over Tailscale Funnel (read-only). May be offline outside
> demo windows; to bring it up, see [docs/REMOTE_ACCESS.md](docs/REMOTE_ACCESS.md).

---

# 🟢 Urban-OS — on-device urban-stress OS (flagship: Urban Operations)

The risk app above is now **one lens** on a deeper system. **Urban-OS** is a local
simulation **kernel** that ingests Toronto open data, runs an urban-dynamics model
**entirely on the DGX Spark**, and produces a *quantified, cited* intervention. The
kernel owns a substrate (a road/transit graph) and a time loop; every behaviour is a
plugin using four operators — `source` (inject forcing), `transport` (move a quantity
on the graph), `couple` (field→field), `observe` (fields→metrics + a cost term `J`).
An optimizer searches plugin-declared levers to minimize `J = Σ wₚ·Jₚ`.

**Two plugin axes:** *city adapters* turn a city's data into the substrate; *domain
lenses* (event surge, economics, safety…) are portable across adapters for free. The
static risk app becomes the **Safety/Public-Services lens** running on this kernel —
proving the adapter×lens architecture.

### The killer insight (live, from the model)
On a peak **FIFA World Cup 2026** day, four downtown venues let out into the same
corridor at once (BMO Field FIFA + Rogers Centre + Scotiabank Arena + the Fort York
Fan Festival — **140,800 people**; see [ADR-0018](docs/adr/0018-fifa-convergence-crunch-substrate.md)):
> *"Union Station reaches **3.7× safe capacity 19 minutes after full-time**; a
> **14-minute staggered release** cuts the peak by **67%** — a net intervention
> benefit of **~$218k** (cost J $323k → $105k)."* — `make urbanos-cli`

Add the cross-domain lenses (`--safety --business`) → **~$281k** combined; the live
`:8001` `/optimize` (3-lens, with the weather/shelter lever) lands on a **16-min
release + 80% shelter**, Union **4.0× → 1.0×**, **~$458k** combined benefit. One
coordinated lever is the operations side of offsetting the Fan Festival's **$6.2M
deficit**.

Specific station, timing, lever, dollars — emergent from the dynamics, and **grounded**:
the figures are computed deterministically and the local model only phrases them, behind
the same hallucination guard as the risk app (any invented number → deterministic
fallback). See [ADR-0003](docs/adr/0003-delay-model-and-honest-optimum.md).

### Run it
```bash
make urbanos-cli     # run + optimize the downtown egress scenario, print the cited insight
make urbanos         # offline map + heatmap/time-slider at http://localhost:8000/
make urbanos-accel   # (optional, on the box) build the Rust core; prints the active backend
```
Endpoints: `GET /scenario` (substrate) · `GET /simulate?release_minutes=…` (per-step
heatmap frames) · `GET /optimize` (before/after + the cited insight) · `GET /health`.

### Architecture
```
City of Toronto Open Data (CKAN)  ──►  City adapter (adapters/toronto.py)
  TTC GTFS · traffic volumes · event permits        builds the road/transit substrate
        │                                            (offline-deterministic synthetic
        ▼                                             downtown; real GTFS on the GX10)
   KERNEL  (urban_os/kernel)                          numpy fields over a networkx graph
   ┌─ source ─ transport ─ couple ─ observe ─┐  ◄── transport runs on a Rust core
   │   time loop: integrate at N× real-time   │       (drop-in; numpy fallback, ADR-0004)
   └──────────────────────────────────────────┘
        │  lenses: EventSurge (egress wave) + Economic (risk = ρ^2.5, $ delay)
        ▼
   Optimizer (optimize.py)  ──►  J-minimizing intervention  (deterministic grid search)
        │
        ▼
   Narrator (narrate.py, local model + hallucination guard)  ──►  the cited one-liner
        │
        ▼
   FastAPI + offline MapLibre/PMTiles heatmap + time slider (api.py)
```

### NVIDIA stack (on the GX10)
Each accelerator is **wired with a CPU fallback** (the demo never blocks if a GPU lib
is absent) and **opt-in** on the box. Install with `make gpu-install`; prove which
backend actually ran with **`make gpu-check`** (prints `cugraph` / `cudf-polars` on the
box, CPU fallback elsewhere). Honest scale note: these pay off on full-city data, not
the tiny demo substrate — same as the Rust accelerator (ADR-0009).

- **NeMo / Nemotron (local)** — the insight narrator and agentic lenses, fully on-device.
  *Wired and live* (verified grounded on the box).
- **`nx-cugraph` (RAPIDS)** — GPU backend for the substrate shortest-paths bake
  (`kernel/state.py`), enabled by `URBANOS_GPU_GRAPH=1`. Falls back to networkx CPU.
- **cuDF (RAPIDS) via Polars** — the civic ingest uses **Polars**, whose
  `collect(engine="gpu")` runs on **cuDF**; enabled by `URBANOS_GPU_DF=1`. Falls back to
  Polars-CPU, then pandas. Drop-in: identical rows, golden numbers unchanged.
- **cuOpt (RAPIDS)** — solves the **optimal evacuation max-flow** on the capacitated
  substrate (`GET /flow`, `urban_os/flow.py`): the theoretical ceiling the staggered
  -release sim approaches. A real LP (cuOpt's wheelhouse) — *not* the lever search
  (cuOpt can't evaluate the black-box sim). `URBANOS_GPU_FLOW=1`; networkx max-flow CPU
  fallback. Verified on the GB10.
- **cuML (RAPIDS)** — clusters the scored civic addresses into **spatial risk hotspots**
  (`GET /clusters`, `civic_analyst/cluster.py`) via GPU KMeans. `URBANOS_GPU_CLUSTER=1`;
  deterministic numpy KMeans CPU fallback.
- **TensorRT-LLM** — the narrator client is runtime-agnostic (OpenAI-compatible HTTP), so
  serving Nemotron behind `trtllm-serve` is a *config* swap: `LLM_RUNTIME=tensorrt-llm` +
  point `LLM_BASE_URL` at it. `make llm-check` reports the runtime + a real decode tok/s —
  the one seam with an on-GPU speedup (needs a box-side engine build). Falls back to
  Ollama / the deterministic narrator. (ADR-0027)
- **PhysicsNeMo (Modulus)** — a neural **surrogate of the optimizer objective `J(levers)`**
  for *city-scale* search (`urban_os/surrogate.py`, `URBANOS_SURROGATE=1`). Shipped as an
  **interface only**: the exact kernel still decides every result (the surrogate's
  prediction is recorded alongside, never used to choose); a trained checkpoint is the
  documented next step. Default off → identical to the grid optimizer. (ADR-0027)
- **Rust core + 128 GB unified memory** — the full graph, live sim state, and the model
  coexist; the kernel steps at **N× real-time** (measure with `make urbanos-accel`).

Design decisions are recorded in [docs/adr/](docs/adr/).

---

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
make install-hooks              # enable the pre-push test gate (run once per clone)
cp .env.example .env            # point LLM_BASE_URL at your local Ollama/NIM endpoint

python scripts/download_data.py # pre-fetch datasets (do this BEFORE the venue!)
make serve                      # FastAPI on :8000  → GET /analyze?address=...
# or
python -m civic_analyst.cli analyze "100 Queen St W"
```

## Instant demo
`make demo` serves the offline map against **committed slices of real downtown
Toronto data** (`demo_data/`) — DineSafe inspections, business licences, **and**
active building permits that share addresses, so ~12 establishments link all three
sources on one pin (real cross-dataset fusion, not staged; permits + infractions both
feed the risk score). Filtered to the basemap's bbox so every pin lands on the map.
`make demo-cli` runs a deterministic check on synthetic fixtures.
```bash
make demo        # offline map + real downtown establishments at http://localhost:8000/
make demo-cli    # deterministic report on synthetic fixtures (100 Queen St W → 1.0)
make demo-data   # rebuild the real slice from the live dataset
```
Then open **http://localhost:8000/** — a **fully offline** map (MapLibre GL rendering
a self-hosted PMTiles vector basemap of downtown Toronto, `static/toronto.pmtiles`)
with pins colored by risk (red = high). No tile servers, no CDN — demo-proof against
flaky venue WiFi. Click a pin to run the agentic read. Endpoints:
- `GET /`           map UI
- `GET /addresses`  geocoded addresses + fast risk score (no LLM) — drives the pins
- `GET /analyze?address=…`  full agentic read (Nemotron Nano, interactive tier)
- `GET /digest`     city-wide briefing (gpt-oss-120B MoE, batch tier)

The basemap is committed (`static/toronto.pmtiles`, ~6 MB). To refresh or widen it:
```bash
scripts/build_tiles.sh    # needs the `pmtiles` CLI; pulls only the bbox via range requests
```

## Hallucination resistance
The risk score and findings are computed **without an LLM**. The model only proposes
**per-claim** output — each claim is a JSON object tied to a source-record tag (E1, E2, …).
Every claim is then **verified** (`agents/verify.py`): each cited tag must be a *real*
evidence record, and every number must trace to the actual findings. Any claim that
invents a number or a source ID is rejected and we fall back to **deterministic,
correct-by-construction claims** — so a hallucinated figure or fabricated source can
never reach the user. The map panel renders each claim with a **✓ verify** link that
reveals the exact source record behind it (click-to-verify). Caught in testing: the model
once claimed "9 permits" when the data showed 8 → rejected. Maps to the Prime Intellect
"Verifiers" bounty.

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
