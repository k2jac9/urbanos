# On the Box — GX10 Runbook (Friday)

Get the demo running on the **ASUS Ascent GX10 (NVIDIA GB10)** with the real Nemotron,
then wire NemoClaw. Do these in order. Budget ~45 min; validate step 1 *first* — Arm
mismatches are the #1 time-sink.

## 0. Validate the environment (don't skip)
```bash
uname -m          # expect: aarch64  (ARM64, not x86)
nvidia-smi        # GPU visible
python3 --version # 3.12+
```
All Docker images / pip wheels must be **ARM64**. If something only ships x86, find an
aarch64 build before you burn time compiling.

## 1. App up on real data (deterministic — works before any model)
```bash
git clone https://github.com/cyberqubit/spark-hack-toronto && cd spark-hack-toronto
python -m venv .venv && . .venv/bin/activate
make install && make install-hooks
cp .env.example .env
make test          # expect 26 green
make demo          # offline map at http://localhost:8000/  (DATA_DIR=demo_data)
```
Sanity: open the map → pins render offline → click **500 Bloor St W** → risk ~0.92 ("high"),
findings, **✓ verify** reveals real source records. (Narratives are deterministic until
step 2.)

## 2. Wire the real local model (Nemotron via Ollama)
```bash
ollama pull nemotron-3-nano      # interactive tier (MoE, ~3B active → ~40-60 tok/s)
ollama pull gpt-oss:120b         # batch tier for /digest (optional)
# Ollama serves an OpenAI-compatible endpoint at http://localhost:11434/v1
```
In `.env` set: `LLM_MODEL=nemotron-3-nano`, `LLM_BATCH_MODEL=gpt-oss:120b`. Restart
`make demo`. Now `/analyze` narratives come from Nemotron; the verifier still rejects any
unverified number/source and falls back to the deterministic summary.

Why these models: decode is **memory-bound** (`tok/s ≈ 190 GB/s ÷ active-bytes`), so
MoE/small-active + FP4 is the only responsive choice. Dense 70B ≈ 2.7 tok/s (avoid).

## 3. Wire NemoClaw + our MCP tools (the bounty)
Our risk engine is already an MCP server (`mcp_server.py`, 4 tools) and config is committed
at `config/nemoclaw.mcp.json`.
```bash
python -m civic_analyst.mcp_server   # sanity: starts a stdio MCP server (Ctrl-C to stop)
```
Install **NemoClaw** via the DGX Spark playbook (authoritative: build.nvidia.com/spark and
the NVIDIA/dgx-spark-playbooks repo — follow their exact installer). Point NemoClaw at
`config/nemoclaw.mcp.json` so it launches our server and discovers the tools, with Nemotron
as the model + OpenShell sandbox. Smoke test:
> "Use the toronto-civic tools: what are the top-3 riskiest addresses and why?"
Expect it to call `top_risk` → `analyze_address` and answer with source-backed results.

## 4. Pre-demo backup
- Record a 60-sec screen capture of the working map + click-to-verify (WiFi insurance).
- Confirm the map needs **no network** (offline PMTiles) — unplug to prove it.

## Demo run-of-show (~60s)
Open map (offline) → "27 downtown businesses, red = high risk" → click **500 Bloor St W**
→ risk ~0.92 ("high"), findings → **click ✓ verify** to reveal the source record across DineSafe +
Building Permits + licences → close with `/digest` (city-wide briefing) or the NemoClaw
agent answering a live question.

## If it breaks
- Map blank but pins show → tiles issue; the data still works (offline basemap is `static/toronto.pmtiles`).
- `/analyze` always falls back to template → model not reachable; check `LLM_BASE_URL`/`ollama list`.
- Pins off-map → address outside the basemap bbox; rebuild slice/basemap (`make demo-data`, `scripts/build_tiles.sh`).
- Emergency push with red tests → `git push --no-verify` (last resort).
