# UrbanOS — Team Workflow (read first)

Shared conventions for both teammates (**@cyberqubit**, **@k2jac9**) and **both Claude Code
sessions**. Anything here applies whether a human or Claude is making the change.

## Onboarding (Claude: do this on a fresh clone)
If `.venv/` is absent, this is a teammate's first run — **proactively greet them and offer to
set up the project**, then on yes run:
```bash
python -m venv .venv && . .venv/bin/activate
make install && make install-hooks      # deps + pre-push test gate
cp .env.example .env
```
Then confirm with `make test` (expect **584 green**) and tell them `make demo` opens the
offline map at http://localhost:8000/ (and `make urbanos` the simulation UI at :8001). Point
them at the workflow + "Current status" below.

## What this is
A **full, ongoing local-first project** — two apps over one architecture: `civic_analyst`
(address-level civic-risk) and `urban_os` (an urban-stress simulation kernel). FastAPI + a
supervisor/sub-agent pipeline over a `networkx` knowledge graph of Toronto open data, a local
Nemotron model (OpenAI-compatible endpoint), MapLibre + offline PMTiles map. It **began at
NVIDIA Spark Hack Toronto (May 2026)** and is now developed as a real project, not a demo —
that origin is preserved as history in older ADRs, the pitch, and the video kit; the
forward-looking framing here treats it as a maintained product.
Layout: `src/civic_analyst/{ingest,graph,agents,api}`, `src/urban_os/`, `tests/`, `scripts/`, `demo_data/`.

## Golden commands (run before every push)
- `make test`   — `PYTHONPATH=src pytest`; **must be green** (CI enforces it on main)
- `make demo`   — offline map + real downtown data at http://localhost:8000/
- `make demo-cli` — deterministic fixture check (100 Queen St W → two indices, ADR 0014:
  safety 0.593 "medium" · activity 0.113 "low")

## Collaboration (two people, two Claude sessions)
- **First clone setup:** `make install` then **`make install-hooks`** (enables a pre-push
  hook that blocks pushing a red test suite — run it once per clone, both teammates).
- **main is gated by CI** — never push broken code to main.
- Use a short-lived branch + PR: `git switch -c feat/<thing>` → push → `gh pr create` → merge **only when CI is green**.
- **`git pull --rebase origin main`** before you start and before you push.
- Small, frequent, clearly-messaged commits. **Never force-push main.**
- Rough ownership to avoid collisions (flex as needed, just announce it):
  **@cyberqubit → ingest / graph / data**, **@k2jac9 → agents / api / UI**.

## Repo hygiene
- **NEVER commit:** secrets / `.env`, `data/raw/` (raw datasets), `.claude/`, `.venv/`, `node_modules/`.
- **DO commit (intentional, makes the demo work offline):** `demo_data/` (small real slice),
  `src/.../static/toronto.pmtiles` (offline basemap), `src/.../static/vendor/` (MapLibre + pmtiles JS).
- Files < 500 lines; validate input at boundaries; **no `Co-Authored-By` trailer**.

## Local model
- Any OpenAI-compatible endpoint. Dev: Ollama (`LLM_MODEL=llama3.2:3b`).
- On the GX10: `LLM_MODEL=nemotron-3-nano` (interactive) + `LLM_BATCH_MODEL=gpt-oss:120b` (batch).
- Code is offline-safe: no model → deterministic fallback. **Don't "fix" the fallback.**

## Don't regress these (deployment + product invariants)
- **ARM64 only** — build aarch64 images, pre-pull ARM wheels/containers.
- **MoE / small-active models only** (128GB but ~273 GB/s; dense 70B ≈ 2.7 tok/s).
- **Map stays 100% offline** — no CDN, no tile servers (vendored assets + PMTiles).
- **Narrator cites only datasets passed in evidence** — don't loosen that prompt.

## Priorities (engineering discipline)
- **CORE (always green):** offline map, `/analyze` + `/optimize` with real model + real data,
  grounded citations, and the data-driven lenses — keep these working and CI-green.
- **Quality over breadth.** Ship coherent, tested, honest increments; don't overscope a single
  change. One small, correct, well-verified feature beats five half-built ones.
- **Stretch / research:** QLoRA fine-tune, deeper multi-dataset fusion, on-box GPU + LLM runtimes.

## Current status (updated 2026-06-20)

> **Now a full project (not a hackathon demo).** It shipped at NVIDIA Spark Hack Toronto and
> is now maintained as a real, ongoing project: `main` is CI-gated, work lands via small
> reviewed PRs, and the data-driven lenses are grounded in real Toronto open data
> (Bike Share #105, TTC boardings #107, GTFS transit supply #108) reachable through a hardened
> CKAN client + `scripts/catalog.py` (#106). The "demo"/"hackathon" framing in the ADRs, the
> pitch, and the video kit is preserved as honest origin history. **Suite: 584 green / 1 skipped.**

> **Data-driven roadmap update (2026-06-20).** The roadmap
> (`docs/research/tpf-and-data-driven-lenses.md`) is shipping phase-by-phase — every step
> **opt-in + CPU-fallback + advisory**, so the **default demo numbers stay byte-identical**
> (do-nothing **J $323,222** → best 14-min release **$105,050**, peak cut 67%). Landed:
> **Phase 0** TMC 15-min ingest → **Phase 1** `CongestionNowcastLens` calibration (kernel-vs-
> observed shape agreement, #94) → **Phase 2** learned-dynamics Action-Matching floor
> (**ADR-0028**, #96), now surfaced in the `:8001` UI labelled *learned/approximate* (#98) →
> **Fit C** `TransitLoadLens` (**ADR-0029**, #100): real measured Toronto throughput injected
> as a `source()` (`URBANOS_TRANSIT_LOAD`, **off by default**, no lever / no J term; flag-on CLI
> reads J $366,940 → $113,315, flag-off unchanged). **Phase 3 (TPF) is a documented NO-GO** —
> the Phase-2 win is 100% gradient / 0% rotational, so the roadmap §8.4 gate is never met; the
> next step is more Fit C lenses, not TPF. Also shipped: **MobilityDemand** display lens
> (**ADR-0030**, #103) grounded in a real Bike Share slice (#105) + a `bike_demand` map overlay
> (#104); **TTC boardings** TransitLoad source (**ADR-0031**, #107, real-magnitude/modelled-shape);
> a **GTFS transit-supply** overlay (**ADR-0032**, #108); the **hardened CKAN client +
> `scripts/catalog.py`** (#106); the micromobility-relief panel (#109). Supporting: narrator-guard
> comma-form fix (#95), idempotent `mcp_server.load` (#94), `make gpu-check-wsl` (#97),
> property/edge tests (#99). **Suite: 584 passed / 1 skipped.** All honesty invariants intact;
> the original deployment (below) remains live.

> **UrbanOS platform-unification + UX redesign (2026-06-20, ADR-0033).** The two apps are now
> **one product**: a single CI-gated UrbanOS shell (`urban_os.api:app` at `/`) with a lens rail
> (City · Risk · Flow · Economy) over one map; the civic risk app is the **Risk lens**, mounted
> same-origin at `/civic`. Shipped (all merged + CI-green): **#112** rebrand + ADR-0033 · **#113**
> unified shell (Safety→Risk display rename; `make demo` serves the one app) · **#114** identity v1
> (wordmark + lens rail) · **#115** **Identity v2** (signature **azure→iris** brand palette in
> `tokens.css` — `--brand-1/-2/-grad/-glow`, `--accent` re-anchored to azure; gradient wordmark +
> bolder boot/hero) · **#116** **civic fold** (map.html fetches made mount-relative so `/civic/`
> works under the shell — was 404-ing — plus bidirectional nav: "‹ UrbanOS" ↔ "Open the full Risk
> view ↗") · **#111** map-heat grouping + legend · **#117** the **City lens** now shows the
> optimizer's grounded insight + before/after (was Flow-only). **Visual/integration only — golden
> numbers, the offline map, and the hallucination guard are unchanged; Suite still 584 green / 1
> skipped.** Python packages stay `urban_os`/`civic_analyst` for now; the source-package + local
> folder rename to UrbanOS are **deliberately deferred** (their own future step, not started).

**Context & origin docs:** `docs/ON_THE_BOX.md` (box runbook, operational), `docs/HANDOFF.md`,
`docs/PITCH.md`, `docs/video/` — the last three are **origin/hackathon artifacts**, kept as
honest history (not maintained as current product docs). A fresh clone builds + passes all
tests (`make test` ≈ **584 green**). Everything below is **merged on `main` + CI-green**, and
the **original GPU deployment remains live** (see "GPU stack" below).

**The project is two apps that share one architecture:**
- **`civic_analyst` (`:8000`)** — the address risk app: 3 fused Toronto datasets (DineSafe +
  permits + licences), deterministic risk (now **two-index: Safety + Activity**, ADR-0014),
  local-Nemotron narrator + **hallucination guard** + **click-to-verify**. Plus **Presentation
  Mode** (cyber theme + 3D real-building focus + floating info board) and a CSS design-token system.
- **`urban_os` (`:8001`)** — the flagship: a simulation **kernel** (substrate + time loop + the four
  operators) with **four lenses** — EventSurge · Economic · **Safety (the civic risk app, made a
  *literal* kernel lens)** · **BusinessFlow** — and an optimizer. One staggered-release lever
  (`make urbanos-cli`: Union Station 3.73× capacity @ t=47min; do-nothing J $323,222 → best
  release at **14min → J $105,050**, **saves ~$218k**, **peak cut 67%**) is scored across all
  lenses (transit + public safety + local business). The UI has a **cross-domain panel + lens
  toggles** (☑ Public safety ☑ Local business — the user picks which lenses count).
  **For live numbers defer to README** (it is the source of truth).

**NemoClaw / MCP bounty — DONE & verified on the box** (no longer "optional/left"): a local
Nemotron agent calls our `toronto-civic` MCP tools and answers **grounded** (matched the tool
exactly). Steps + the demo command in `docs/ON_THE_BOX.md §3`. NB: the box's `~/.openclaw/openclaw.json`
got **additive** changes (MCP server + an ollama/nemotron provider; backed up; defaults untouched).

**Shipped this session (ADR-0019 → 0027, all merged + CI-green):** two-index **benefit-number
semantics** (0019); **civic narrator-guard parity** kind-match + decimal-safe (0020); **kernel
conservation-under-noise + per-State capacity overlay** (0021); **api.py split + one shared lens
stack** (0022); **two-app decoupling** via public `ensure_loaded()` + injected provider (0023);
**RAPIDS GPU seams** (0024) — nx-cugraph (substrate dijkstra via super-source SSSP) + cuDF-via-Polars
(ingest); **cuOpt evacuation max-flow `/flow` + cuML risk-hotspot `/clusters`** (0025); **public-UI
clarity + animations** (0026, "How it works" dialog, legends, provenance, honesty notes, motion
gated by `prefers-reduced-motion`, /flow+/clusters surfaced); **TensorRT-LLM narrator runtime +
PhysicsNeMo J-surrogate seams** (0027). Plus civic public-API hardening + data-layer robustness.

**GPU stack — LIVE on the box.** The `civic-demo`/`urbanos-demo` user services run on the
`~/rapids-probe` venv (full RAPIDS + Polars) with the opt-in flags set, so the public demo genuinely
executes on the GB10: `/flow`→`cuopt`, `/clusters`→`cuml`, ingest→`cudf-polars`, substrate→`cugraph`
(all proven via `make gpu-check`). **Rollback:** `cp ~/.config/systemd/user/*.service.bak …` →
`daemon-reload` + restart (the old CPU `.venv`). Public Funnels (both live): civic
`https://gx10-4428.taila9fe06.ts.net` · urban `…:8443`. `make funnel-off-all` tears both down.
Every GPU/seam is opt-in + CPU-fallback, so CI/dev never need CUDA. **Numbers/honesty unchanged.**

**NEXT — resume here (TensorRT-LLM NGC bring-up, ADR-0027 §"what's next"):** the narrator client is
OpenAI-API-only, so TRT-LLM is **config not code**. On the box, in the pulled NGC TRT-LLM container
(must be **aarch64 + support GB10 sm_121**): build the Nemotron engine, run `trtllm-serve` (e.g.
`:8080`), then set `LLM_RUNTIME=tensorrt-llm` + `LLM_BASE_URL=http://localhost:8080/v1` on the
services and `systemctl --user restart`. Verify with **`make llm-check`** (`llm.LLM_BACKEND` ==
`tensorrt-llm`, `/optimize` still `grounded: True`) and capture the **decode tok/s vs Ollama** — the
one on-camera GPU-speedup number. Keep Ollama up as fallback; watch VRAM. **PhysicsNeMo** ships
**interface-only** (no checkpoint → exact kernel decides every result; training a checkpoint is the
documented stretch). Optional stretch: QLoRA fine-tune.

**Demo tips:** civic hero pin **500 Bloor St W** (3-dataset fusion). NB scoring is **two-index now
(Safety + Activity, ADR-0014)** — 500 Bloor reads **medium Activity / low Safety**, *not* the old
"0.92 high"; for a genuinely **high** pin use **40 Bay St** or **1 Blue Jays Way** (high Activity,
permit-heavy). Flip **◢ Presentation** for the 3D building; on `:8001` use **lens toggles** to show
"one lever, every lens." ⚠ **Numbers differ by surface (defer to README for live figures):**
`make urbanos-cli` (no weather) ≈ **14-min release → J $105,050, saves ~$218k, peak cut 67%**
(do-nothing J $323,222); the **`:8001` UI** includes the **WeatherLens/shelter lever** (ADR-0007)
so its combined number is larger (≈ **16-min / 80% / ~$455k**) — cite whichever surface you're
showing, not both. Real-data slices are
committed; regenerate with `make demo-data` (needs the `pmtiles` CLI via `scripts/build_tiles.sh`).
First-clone setup: `python -m venv .venv && . .venv/bin/activate` → `make install` →
`make install-hooks` → `cp .env.example .env`.

---

# Ruflo — Claude Code Configuration

## Rules

- Do what has been asked; nothing more, nothing less
- NEVER create files unless absolutely necessary — prefer editing existing files
- NEVER create documentation files unless explicitly requested
- NEVER save working files or tests to root — use `/src`, `/tests`, `/docs`, `/config`, `/scripts`
- ALWAYS read a file before editing it
- NEVER commit secrets, credentials, or .env files
- NEVER add a `Co-Authored-By` trailer to user commits unless this project's `.claude/settings.json` has `attribution.commit` set (#2078). The Claude Code Bash tool may suggest one in its default commit-message template — ignore it. `Co-Authored-By` is semantic authorship attribution under git/GitHub convention; the tool is the facilitator, not a co-author.
- Keep files under 500 lines
- Validate input at system boundaries

## Agent Comms (SendMessage-First Coordination)

Named agents coordinate via `SendMessage`, not polling or shared state.

```
Lead (you) ←→ architect ←→ developer ←→ tester ←→ reviewer
              (named agents message each other directly)
```

### Spawning a Coordinated Team

```javascript
// ALL agents in ONE message, each knows WHO to message next
Agent({ prompt: "Research the codebase. SendMessage findings to 'architect'.",
  subagent_type: "researcher", name: "researcher", run_in_background: true })
Agent({ prompt: "Wait for 'researcher'. Design solution. SendMessage to 'coder'.",
  subagent_type: "system-architect", name: "architect", run_in_background: true })
Agent({ prompt: "Wait for 'architect'. Implement it. SendMessage to 'tester'.",
  subagent_type: "coder", name: "coder", run_in_background: true })
Agent({ prompt: "Wait for 'coder'. Write tests. SendMessage results to 'reviewer'.",
  subagent_type: "tester", name: "tester", run_in_background: true })
Agent({ prompt: "Wait for 'tester'. Review code quality and security.",
  subagent_type: "reviewer", name: "reviewer", run_in_background: true })

// Kick off the pipeline
SendMessage({ to: "researcher", summary: "Start", message: "[task context]" })
```

### Patterns

| Pattern | Flow | Use When |
|---------|------|----------|
| **Pipeline** | A → B → C → D | Sequential dependencies (feature dev) |
| **Fan-out** | Lead → A, B, C → Lead | Independent parallel work (research) |
| **Supervisor** | Lead ↔ workers | Ongoing coordination (complex refactor) |

### Rules

- ALWAYS name agents — `name: "role"` makes them addressable
- ALWAYS include comms instructions in prompts — who to message, what to send
- Spawn ALL agents in ONE message with `run_in_background: true`
- After spawning: STOP, tell user what's running, wait for results
- NEVER poll status — agents message back or complete automatically

## Swarm & Routing

### Config
- **Topology**: hierarchical-mesh (anti-drift)
- **Max Agents**: 15
- **Memory**: hybrid
- **HNSW**: Enabled
- **Neural**: Enabled

```bash
npx @claude-flow/cli@latest swarm init --topology hierarchical --max-agents 8 --strategy specialized
```

### Agent Routing

| Task | Agents | Topology |
|------|--------|----------|
| Bug Fix | researcher, coder, tester | hierarchical |
| Feature | architect, coder, tester, reviewer | hierarchical |
| Refactor | architect, coder, reviewer | hierarchical |
| Performance | perf-engineer, coder | hierarchical |
| Security | security-architect, auditor | hierarchical |

### When to Swarm
- **YES**: 3+ files, new features, cross-module refactoring, API changes, security, performance
- **NO**: single file edits, 1-2 line fixes, docs updates, config changes, questions

### 3-Tier Model Routing

| Tier | Handler | Use Cases |
|------|---------|-----------|
| 1 | Agent Booster (WASM) | Simple transforms — skip LLM, use Edit directly |
| 2 | Haiku | Simple tasks, low complexity |
| 3 | Sonnet/Opus | Architecture, security, complex reasoning |

## Memory & Learning

### Before Any Task
```bash
npx @claude-flow/cli@latest memory search --query "[task keywords]" --namespace patterns
npx @claude-flow/cli@latest hooks route --task "[task description]"
```

### After Success
```bash
npx @claude-flow/cli@latest memory store --namespace patterns --key "[name]" --value "[what worked]"
npx @claude-flow/cli@latest hooks post-task --task-id "[id]" --success true --store-results true
```

### MCP Tools (use `ToolSearch("keyword")` to discover)

| Category | Key Tools |
|----------|-----------|
| **Memory** | `memory_store`, `memory_search`, `memory_search_unified` |
| **Bridge** | `memory_import_claude`, `memory_bridge_status` |
| **Swarm** | `swarm_init`, `swarm_status`, `swarm_health` |
| **Agents** | `agent_spawn`, `agent_list`, `agent_status` |
| **Hooks** | `hooks_route`, `hooks_post-task`, `hooks_worker-dispatch` |
| **Security** | `aidefence_scan`, `aidefence_is_safe`, `aidefence_has_pii` |
| **Hive-Mind** | `hive-mind_init`, `hive-mind_consensus`, `hive-mind_spawn` |

### Background Workers

| Worker | When |
|--------|------|
| `audit` | After security changes |
| `optimize` | After performance work |
| `testgaps` | After adding features |
| `map` | Every 5+ file changes |
| `document` | After API changes |

```bash
npx @claude-flow/cli@latest hooks worker dispatch --trigger audit
```

## Agents

**Core**: `coder`, `reviewer`, `tester`, `planner`, `researcher`
**Architecture**: `system-architect`, `backend-dev`, `mobile-dev`
**Security**: `security-architect`, `security-auditor`
**Performance**: `performance-engineer`, `perf-analyzer`
**Coordination**: `hierarchical-coordinator`, `mesh-coordinator`, `adaptive-coordinator`
**GitHub**: `pr-manager`, `code-review-swarm`, `issue-tracker`, `release-manager`

Any string works as a custom agent type.

## Build & Test

- ALWAYS run tests after code changes
- ALWAYS verify build succeeds before committing

```bash
npm run build && npm test
```

## CLI Quick Reference

```bash
npx @claude-flow/cli@latest init --wizard           # Setup
npx @claude-flow/cli@latest swarm init --v3-mode     # Start swarm
npx @claude-flow/cli@latest memory search --query "" # Vector search
npx @claude-flow/cli@latest hooks route --task ""    # Route to agent
npx @claude-flow/cli@latest doctor --fix             # Diagnostics
npx @claude-flow/cli@latest security scan            # Security scan
npx @claude-flow/cli@latest performance benchmark    # Benchmarks
```

26 commands, 140+ subcommands. Use `--help` on any command for details.

## Setup

```bash
claude mcp add claude-flow -- npx -y @claude-flow/cli@latest
npx @claude-flow/cli@latest daemon start
npx @claude-flow/cli@latest doctor --fix
```

**Agent tool** handles execution (agents, files, code, git). **MCP tools** handle coordination (swarm, memory, hooks). **CLI** is the same via Bash.
