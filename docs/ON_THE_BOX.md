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
Sanity: open the map → pins render offline → click **500 Bloor St W** → two-index read
(medium Activity / low Safety, ADR-0014), findings across 3 datasets, **✓ verify** reveals real
source records. (For a *high* pin use **40 Bay St** or **1 Blue Jays Way** — high Activity.
Narratives are deterministic until
step 2.)

## 2. Wire the real local model (Nemotron via Ollama)
```bash
ollama pull nemotron-3-nano      # interactive tier (MoE, ~3B active → ~40-60 tok/s)
ollama pull nemotron3:33b        # batch tier for /digest (coexists with Nano)
# Ollama serves an OpenAI-compatible endpoint at http://localhost:11434/v1
```
These are the **defaults** (see `config.py`) — no `.env` needed if you pull these tags.
Restart `make demo`. Now `/analyze` narratives come from Nemotron; the verifier still
rejects any unverified number/source and falls back to the deterministic summary.

Two box-specific tunings (both default-on, in `config.py`):
- **`LLM_REASONING_EFFORT=none`** for the interactive narrator. Nemotron 3 is a reasoning
  model; left on, it emits a ~640-token chain-of-thought before the JSON answer (~10x the
  latency). The narrator does constrained extraction, so we disable it → **/analyze ≈ 1.6s
  warm** instead of ~25s. The batch digest keeps reasoning **on** (it's a real synthesis task).
- **`LLM_PREWARM=1`** loads the interactive model at server boot (daemon thread) so the
  first demo `/analyze` isn't paying the ~5s cold-load.

Why **`nemotron3:33b`** for batch, not a 120B: a 120B (super / gpt-oss) needs ~86–94GB and
**evicts** the resident Nano, so the next `/analyze` cold-loads. The 33B (≈32GB) + Nano
(≈27GB) both stay GPU-resident (~59GB of 121GB) — `/digest` never destabilizes `/analyze`.
For a bigger box, `LLM_BATCH_MODEL=nemotron-3-super` gives a stronger digest (≈82s).

Why these models: decode is **memory-bound** (`tok/s ≈ 190 GB/s ÷ active-bytes`), so
MoE/small-active + FP4 is the only responsive choice. Dense 70B ≈ 2.7 tok/s (avoid).

## 2b. (Stretch, ADR-0027) Serve Nemotron via **TensorRT-LLM** — capability, *not* a speedup
The narrator client only speaks OpenAI-compatible HTTP, so swapping Ollama for NVIDIA
**TensorRT-LLM** is a *config* change — no app code changes. **This was brought up live on
the box** (2026-05-31): Nemotron-3-Nano (NVFP4 / Blackwell FP4) serving via the NGC container.
⚠️ **Use the NGC container, not bare-metal pip** — bare-metal aarch64 hits an unfixable
torch-C++-ABI wall (see ADR-0027 "Box verification").
```bash
# Image + ungated NVFP4 checkpoint already staged under ~/trt-build on the box.
cat > ~/trt-build/options.yaml <<'EOF'
kv_cache_config:
  enable_block_reuse: false   # REQUIRED for the nemotron_h Mamba-hybrid KV cache
EOF
docker run -d --name trtllm-serve --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
  -p 8009:8009 -v ~/trt-build:/work nvcr.io/nvidia/tensorrt-llm/release:1.2.1 \
  trtllm-serve /work/models/nemotron-nano-nvfp4 --host 0.0.0.0 --port 8009 \
  --backend pytorch --extra_llm_api_options /work/options.yaml
# point the app at it + prove which runtime answered (capability, not a speed claim):
export LLM_RUNTIME=tensorrt-llm LLM_BASE_URL=http://localhost:8009/v1
make llm-check                                # expect runtime='tensorrt-llm'
docker stop trtllm-serve                       # ⚠️ stop when done — holds ~19 GB unified mem (OOM risk to live demo)
```
**Honesty / fallback (read before claiming anything):** TRT-LLM **is** serving Nemotron here
(capability — true), but **measured single-stream decode is NOT faster than Ollama** (54.5 vs
61.2 tok/s). **Do not claim a decode speedup.** Claim only *"Nemotron runs on TensorRT-LLM on
the box, runtime-portable narrator."* The throughput-under-load advantage is unproven (next-
step; full plan in ADR-0027). The live demo defaults to `LLM_RUNTIME=ollama` and is never
blocked. **Do not swap the live `civic-demo` to TRT-LLM during judging** (memory + no speed win).

> **PhysicsNeMo (Modulus) — interface only, no box step.** The optimizer's surrogate seam
> (`urbanos/kernel/surrogate.py`, `URBANOS_SURROGATE=1`) ships *without* a trained checkpoint, so
> the exact kernel decides every result. There is nothing to activate on the box; training a
> checkpoint is the documented next step (ADR-0027). Don't claim a working surrogate.

## 3. Wire NemoClaw + our MCP tools (the bounty) — ✅ DONE & VERIFIED
Our risk engine is an MCP server (`mcp_server.py`, 5 tools: `list_datasets`, `dataset_resources`,
`analyze_address`, `top_risk`, `city_digest`). OpenClaw/NemoClaw is installed on the box; we
registered the server and ran a local **Nemotron** agent that called `top_risk` and answered with
data **matching the tool exactly** (grounded — the Verifiers guarantee at the agent layer).

Reproduce (run as the box user that owns `~/.openclaw`):
```bash
# 1) Register our MCP server. OpenClaw BLOCKS PYTHONPATH for stdio-startup safety, so set it
#    *inside* a shell wrapper (not via the env map), with absolute paths + the repo venv:
openclaw mcp set toronto-civic '{"command":"/bin/sh","args":["-c","cd /home/asus/dev/spark-hack-toronto && PYTHONPATH=src DATA_DIR=demo_data exec .venv/bin/python -m urbanos.risk.mcp_server"],"env":{"LLM_BASE_URL":"http://localhost:11434/v1","LLM_MODEL":"nemotron-3-nano"}}'
openclaw mcp list           # → toronto-civic

# 2) Give OpenClaw a working local model (Ollama/Nemotron) and allow-list it for the agent:
#    in ~/.openclaw/openclaw.json add a provider `ollama`
#    (baseUrl http://localhost:11434/v1, api openai-completions, model nemotron-3-nano),
#    and add "ollama/nemotron-3-nano" to agents.defaults.models.

# 3) Demo — Nemotron orchestrating our tools, on-device:
openclaw agent --local --model ollama/nemotron-3-nano \
  -m "Use the toronto-civic tools: top 3 riskiest addresses and why."
```
Gotchas (all hit + fixed): **PYTHONPATH is stripped** → shell-wrap it; a `--model` override must be
**allow-listed per agent**; OpenClaw's default model wants **vLLM on :8000** — the *same port as the
civic demo* — so use the **Ollama :11434** path and the agent + demo coexist. Editing
`~/.openclaw/openclaw.json` is additive and reversible (OpenClaw writes a `.bak` on each change).

Original from-scratch install (if the box is ever rebuilt): NemoClaw via the DGX Spark playbook
(authoritative: build.nvidia.com/spark + the NVIDIA/dgx-spark-playbooks repo).

## 4. Pre-demo backup
- Record a 60-sec screen capture of the working map + click-to-verify (WiFi insurance).
- Confirm the map needs **no network** (offline PMTiles) — unplug to prove it.

## Demo run-of-show (~60s)
Open map (offline) → "27 downtown businesses, scored on Safety + Activity" → click **500 Bloor St W**
→ two-index read + findings → **click ✓ verify** to reveal the source record across DineSafe +
Building Permits + licences → close with `/digest` (city-wide briefing) or the NemoClaw
agent answering a live question.

## If it breaks
- Map blank but pins show → tiles issue; the data still works (offline basemap is `static/toronto.pmtiles`).
- `/analyze` always falls back to template → model not reachable; check `LLM_BASE_URL`/`ollama list`.
- Pins off-map → address outside the basemap bbox; rebuild slice/basemap (`make demo-data`, `scripts/build_tiles.sh`).
- Emergency push with red tests → `git push --no-verify` (last resort).
