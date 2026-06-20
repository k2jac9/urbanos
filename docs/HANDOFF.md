# Handoff — @cyberqubit session → @k2jac9

## 🆕 FIFA convergence-crunch reshape (branch `feat/urbanos-fifa-triple-crunch`)
The Urban-OS downtown scenario is reshaped from a single abstract stadium let-out
into the **FIFA World Cup 2026 Fan-Festival "convergence crunch"**: **4 concurrent
venue let-outs** (BMO Field FIFA 46k + Rogers Centre 45k + Scotiabank Arena 19.8k +
Fort York fan festival 30k = **140,800 people**) superimposing their egress pulses
into the **Union / Exhibition-GO corridor**, under **one coordinated release lever**.
`EventSurge` gained multi-venue injection; abstract sinks are now real exit lines
(Lakeshore W/E, Line 1). 17 nodes / 25 edges. Union is the convergence bottleneck;
**Exhibition GO** is the FIFA-specific secondary crush (only rail adjacent to BMO
Field). Rationale + real anchors + the honest-calibration caveat:
[ADR-0018](adr/0018-fifa-convergence-crunch-substrate.md).

**New headline numbers (each reproduced by a named command — see PITCH §"The numbers"):**
- `make urbanos-cli` (2-lens): Union **3.7×** → **−67%** with a **14-min** release, **~$218k**.
- `--safety --business` (cross-domain): **~$281k**; safety $53.7k→$1.6k, business $10.4k.
- live `:8001` `/optimize` (3-lens + weather/shelter): Union **4.0×→1.0×** (**−75%**),
  **16-min release + 80% shelter**, J benefit **~$394k**, **combined ~$458k**.

The framing: the saving is the **operations** side of offsetting the Fan Festival's
**$6.2M deficit**. (Docs reshaped on this branch; code/UI reshaped by the other
worker. Pull `main`/the branch onto the box and restart `:8001` so the live demo
serves these numbers — the old 14-min/$116k figures are superseded.)

---

Everything below is **merged, CI-green, and additive**. Two things need your hand
(the box is yours). `main` is at the latest as of this note.

## ⚡ TL;DR — 2 action items

**1. Pull `main` onto the box + restart, so the live demo matches the repo.** The
box is a few commits behind, and `:8001` is still serving *old* Urban-OS numbers
(18-min / $46k).
```bash
# on the box, as asus, in the repo:
cd ~/dev/spark-hack-toronto && git pull --rebase
systemctl --user restart civic-demo          # :8000 — picks up the Python changes
# restart your :8001 urbanos.kernel process too (it serves the stale optimize numbers)
```
After that, `make urbanos-cli` and `:8001`'s "Find best intersection" show the
current FIFA convergence-crunch numbers (see the top section: 2-lens **14-min /
−67% / ~$218k**; live `:8001` 3-lens **16-min + 80% shelter / 4.0×→1.0× / ~$458k
combined**), plus the cross-domain panel.

**2. Heads-up: I touched your `~/.openclaw/openclaw.json`** (additively, backed up —
see NemoClaw below). Your default Qwen/vLLM setup is **unchanged**.

## 🧩 What landed on `main` (mostly `urbanos/kernel/` + the civic map UI)
- **#33** Presentation Mode on the civic map (`:8000`): cyber theme + 3D building
  focus + info board (you refined the footprint highlight in #47–49 — thanks).
- **#38** design-token refactor of `map.html` (Conservative pixel-identical).
- **#53** README Urban-OS numbers synced to `make urbanos-cli`.
- **#54 BusinessFlow** + **#56 SafetyLens** — two new lenses. **SafetyLens makes the
  civic risk app *literally* a kernel lens** (`adapters.civic_safety_by_node` fuses
  address `risk_safety` → a node field). Both **opt-in** (`--safety` / `--business`),
  read-only, additive — a test asserts they don't change EventSurge/Economic.
- **#57** cross-domain panel in the `:8001` optimize view + `docs/PITCH.md`. Rebased
  on your **#58** (kept your `breakdownRowsHTML` helper + `BEST_PARAMS`).

One fix worth knowing: `urbanos.risk.mcp_server.load()` **accumulates** into its
module-global graph on repeated calls — I added a cache in `civic_safety_by_node`
so the per-request safety number stays stable ($21,730). Flagging in case you call
`load()` elsewhere.

## 🤖 NemoClaw / MCP (the bounty — wired + verified)
A local **Nemotron agent calls our `toronto-civic` MCP tools and answers grounded**
(its answer matched the tool exactly). I added to `~/.openclaw/openclaw.json` —
**additive, your defaults untouched**, backups at `openclaw.json.bak-preMCP` (+
OpenClaw's own `.bak`):
- MCP server `toronto-civic` (shell-wrapped — OpenClaw strips `PYTHONPATH`).
- An `ollama/nemotron-3-nano` provider + allow-listed it for the agent.

Demo:
```bash
openclaw agent --local --model ollama/nemotron-3-nano \
  -m "Use the toronto-civic tools: top 3 riskiest addresses and why."
```
**⚠️ Port note:** your OpenClaw default model wants **vLLM on `:8000`** — the same
port as the civic demo. The agent path uses **Ollama `:11434`**, so the agent + the
demo coexist (just don't start the vLLM-on-8000 script during the demo). Full steps
in [`docs/ON_THE_BOX.md` §3](ON_THE_BOX.md).

Also: I briefly created a *system* `civic-demo.service` that collided with your
*user* one — I **removed it**. Your user service (linger + `Restart=always`) is the
one running and it's solid. No leftover.

## State of the demo
Four lenses on one kernel (EventSurge **(multi-venue)** · Economic · **Safety =
civic risk** · **BusinessFlow**), one coordinated lever optimizing across transit +
public safety + local business on the **FIFA convergence crunch** (4 concurrent
let-outs, 140,800 people) — **~$458k** combined on the live `:8001` 3-lens surface
(see the top section for the per-surface breakdown), grounded narration,
agent-drivable via NemoClaw, **100% offline on the GX10**. Pitch in
[`docs/PITCH.md`](PITCH.md).
