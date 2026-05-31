# Toronto Civic Risk Analyst — Team Workflow (read first)

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
Then confirm with `make test` (expect 26 green) and tell them `make demo` opens the offline
map at http://localhost:8000/. Point them at the workflow + "Current status" below.

## What this is
Local-first, multi-agent civic-risk app for **NVIDIA Spark Hack Toronto (May 29–31 2026)**.
FastAPI + a supervisor/sub-agent pipeline over a `networkx` knowledge graph of Toronto open
data, a local Nemotron model (OpenAI-compatible endpoint), MapLibre + offline PMTiles map.
Layout: `src/civic_analyst/{ingest,graph,agents,api}`, `tests/`, `scripts/`, `demo_data/`.

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

## Don't regress these (GX10 + demo invariants)
- **ARM64 only** — build aarch64 images, pre-pull ARM wheels/containers.
- **MoE / small-active models only** (128GB but ~273 GB/s; dense 70B ≈ 2.7 tok/s).
- **Map stays 100% offline** — no CDN, no tile servers (vendored assets + PMTiles).
- **Narrator cites only datasets passed in evidence** — don't loosen that prompt.

## Priorities (hackathon discipline)
- **CORE (keep working):** offline map, `/analyze` with real model + real data, grounded citations.
- **STRETCH (only if core is solid):** QLoRA fine-tune, multi-dataset fusion, NemoClaw on the box.
- Don't overscope. **One flawless demo > five half-features.**

## Current status (handoff — 2026-05-31, demo day)
**Full read for the next session:** `docs/HANDOFF.md` (@cyberqubit → @k2jac9), `docs/PITCH.md`
(the pitch), `docs/ON_THE_BOX.md` (box runbook). A fresh clone builds + passes all tests
(`make test` ≈ 311 green). Everything below is **merged on `main` + CI-green**.

**The project is two apps that share one architecture:**
- **`civic_analyst` (`:8000`)** — the address risk app: 3 fused Toronto datasets (DineSafe +
  permits + licences), deterministic risk (now **two-index: Safety + Activity**, ADR-0014),
  local-Nemotron narrator + **hallucination guard** + **click-to-verify**. Plus **Presentation
  Mode** (cyber theme + 3D real-building focus + floating info board) and a CSS design-token system.
- **`urban_os` (`:8001`)** — the flagship: a simulation **kernel** (substrate + time loop + the four
  operators) with **four lenses** — EventSurge · Economic · **Safety (the civic risk app, made a
  *literal* kernel lens)** · **BusinessFlow** — and an optimizer. One staggered-release lever
  (`make urbanos-cli`: 14-min / **−62% peak** / ~$60k transit) is scored across all lenses:
  **~$116k** combined (transit + public safety + local business). The UI has a **cross-domain panel
  + lens toggles** (☑ Public safety ☑ Local business — the user picks which lenses count).

**NemoClaw / MCP bounty — DONE & verified on the box** (no longer "optional/left"): a local
Nemotron agent calls our `toronto-civic` MCP tools and answers **grounded** (matched the tool
exactly). Steps + the demo command in `docs/ON_THE_BOX.md §3`. NB: the box's `~/.openclaw/openclaw.json`
got **additive** changes (MCP server + an ollama/nemotron provider; backed up; defaults untouched).

**Left — box-side only (see `docs/HANDOFF.md`, issue #61):** **pull `main` on the box + restart
`:8000` (`systemctl --user restart civic-demo`) and the `:8001` process** so the live demo matches
the repo (the box still serves the *old* Urban-OS numbers). The civic-demo `:8000` is a supervised
user service (linger + Restart=always); the public judge URL is the Tailscale Funnel
`https://gx10-4428.taila9fe06.ts.net`. Optional stretch: QLoRA fine-tune.

**Demo tips:** civic hero pin **500 Bloor St W** (3-dataset fusion); flip **◢ Presentation** for the
3D building; on `:8001` use **lens toggles** to show "one lever, every lens." Real-data slices are
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
