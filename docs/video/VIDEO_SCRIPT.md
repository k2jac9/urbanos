# Demo Video — 5-Minute Shot-by-Shot Script

Submission video for **NVIDIA Spark Hack Toronto** (Urban-OS / urbanos.risk). Target
**3:45–4:30**, hard cap **5:00**. Screen-recorded (Loom/OBS) with **camera on** for the
intro + close. Follows the official 5-section flow.

> **Honesty rule (inherited from [`DEMO_SCRIPT.md`](../DEMO_SCRIPT.md)):** read every number
> **off the screen, not off this page.** This script is calibrated to the live **`:8001`
> 3-lens UI** (release + shelter) for the climax. Numbers differ by lens stack *by design* —
> that's the platform point. **One surface per breath; never blend two.**

---

## Numbers — RESOLVED from live `/optimize` (single source of truth)
Resolved 2026-05-31 from the live `:8001` `GET /optimize` (3-lens, WeatherLens/shelter on) run
off current `main`; each row names the **command/surface** that reproduces it. Say the value the
**live screen** shows. NB: peak-drop is **75%** (4.0×→1.0× = 74.6%), correcting the stale "80%"
handoff note. See provenance in [`DEMO_SCRIPT.md`](../DEMO_SCRIPT.md) and [`PITCH.md`](../PITCH.md).

| Token | Meaning | Reproducing surface / command | Value (fill) |
|---|---|---|---|
| `⟨peak⟩` | Union pre-intervention peak (×capacity) | live `:8001` `GET /optimize` | `4.0×` |
| `⟨peak-after⟩` | Union post-intervention peak | live `:8001` `GET /optimize` | `1.0×` |
| `⟨peak-drop%⟩` | peak reduction | live `:8001` `GET /optimize` | `75%` |
| `⟨lever⟩` | the chosen lever (e.g. "16-min release + 80% shelter") | live `:8001` `GET /optimize` | `16-min release + 80% shelter` |
| `⟨safety-$⟩` | public-safety exposure avoided | live `:8001` `GET /optimize` | `$53,745` |
| `⟨business-$⟩` | local business recovered | live `:8001` `GET /optimize` | `$10,749` |
| `⟨combined-$⟩` | **combined cross-domain benefit (the headline)** | live `:8001` `GET /optimize` | `~$458k ($458,064)` |
| `⟨crowd⟩` | total people across 4 venues | ADR-0018 substrate | `140,800` |
| `⟨permits⟩` | open permits at 500 Bloor St W | civic `:8000` `/analyze` | `8` |
| `⟨deficit⟩` | Fan Festival deficit (context tie-in) | ADR-0018 anchors | `$6.2M` |

> If you record off the **CLI** (`make urbanos-cli`, transit-only) instead of the live UI,
> swap to that row's figures and **drop any mention of shelter** — see DEMO_SCRIPT provenance.

---

## Section 1 — Introduce the team  *(0:00–0:25, ~20–25s · camera on)*
| Time | On camera / voiceover | Screen | Cue |
|---|---|---|---|
| 0:00 | **[face cam]** "Hi — we're **⟨team name⟩**: ⟨name⟩ and ⟨name⟩. For Spark Hack Toronto we built **Urban-OS — an operating system for the city**, running entirely on the NVIDIA GX10." | Title card: **URBAN OS — One lever. Every lens.** + today's date `2026-05-31`. | Date visible = proves it's live. Keep it to two sentences. |

---

## Section 2 — Elevator pitch / the hook  *(0:25–1:05, ~30–40s)*
| Time | Voiceover | Screen | Cue |
|---|---|---|---|
| 0:25 | "Most civic tools are **single-purpose dashboards** — inspections here, transit there, events somewhere else. They never talk, so nobody can optimize *across* them." | Quick montage: 3 disconnected dashboards → dissolve. | The problem, in one breath. |
| 0:38 | "So we built a **microkernel for urban dynamics**: one kernel, one Toronto map, and **four lenses — City, Safety, Flow, Economy — that re-skin the *same* city.** A governor then optimizes **one coordinated lever** across all of them." | **Real product pixels by here** (~0:20-relative): the unified shell loads, four-lens dock visible. | Pixels on screen ≤ 0:45 absolute. |
| 0:52 | "Everything runs **100% on this one box** — no cloud, no internet. Watch — **I'll unplug it.** *[unplug]* Still running. For a city's sensitive permit and inspection data, **that's the point.**" | **[cut to the physical box / the cord being pulled]**, then back to the still-live UI. | The money shot + "why on-box matters" (Policy-Angel pattern). |

---

## Section 3 — Live demo: the core loop  *(1:05–2:05, ~45–60s)*
The core loop = **input (click an address / pick a scenario) → on-box processing (grounded
narration + deterministic sim) → output (verified facts + an optimized lever).**

| Time | Voiceover | Screen action | Cue |
|---|---|---|---|
| 1:05 | "**Safety lens first.** Every pin is scored on **two independent indices — Safety and Activity** — so a busy construction zone isn't mistaken for a dangerous one." | Tap **Safety** in the dock → map re-skins to risk pins. | Two-index = ADR-0014. |
| 1:18 | "I click **500 Bloor St West**: **medium Activity — ⟨permits⟩ open permits, active construction** — and a flagged food-safety item. Every claim is grounded — open permits, a DineSafe conditional pass, a licence: **three real City of Toronto datasets, fused on the address.**" | Click pin **500 Bloor St W** → risk card with Safety + Activity + citations. | Hero pin. Alt high-Activity pin: **40 Bay St**. |
| 1:34 | "I hit **✓ verify** — there's the **source record.** The local Nemotron model only **phrases** these numbers; it can't invent them. It once said '9 permits' when the data showed 8 — the verifier caught it. **A hallucinated number physically cannot reach this screen.**" | Click **✓ verify** → real DineSafe/permit record flips open inline. | The trust beat — verbatim from PITCH/DEMO_SCRIPT. |
| 1:50 | "Now the **Flow lens** — same city, in motion. Peak **FIFA World Cup 2026** day: **four venues let out into the same corridor at once — ⟨crowd⟩ people** — and **Union Station hits ⟨peak⟩ safe capacity.**" | Tap **Flow** → transit graph; time loop runs; four venue pulses converge; **Union flares red at ⟨peak⟩.** | Exhibition GO = secondary crush (BMO Field's 46k). |

---

## Section 4 — How we built it  *(2:05–3:35, ~60–90s)*
Stay on the product where possible; cut to the **architecture slide** (Canva deck) for the
data-flow diagram, then back.

| Time | Voiceover | Screen | Cue |
|---|---|---|---|
| 2:05 | "Under the hood it's a real **microkernel**: a **substrate** — Toronto's road and transit graph from open data — plus a **time loop** and four operators: `source`, `transport`, `couple`, `observe`. Each lens is a **plugin** on that kernel." | Cut to **architecture slide**: kernel + operators + lenses + governor. | Name the parts (OS framing). |
| 2:25 | "The figures are **computed deterministically** in a numpy field engine — with an optional **Rust core** drop-in — over a `networkx` graph. The model never *produces* a number; a **verifier** rejects anything not in the evidence and falls back to deterministic phrasing." | Diagram highlights: data → kernel → optimizer → narrator+verifier → UI. | Verifiers-bounty = architecture. |
| 2:40 | "And the heavy numerics ride **NVIDIA RAPIDS**: the graph on **cugraph**, ingest on **cuDF**, the evacuation-flow solve on **cuOpt**, risk hotspots on **cuML** — each an **opt-in seam with a CPU fallback**, so the demo never *needs* the GPU. On this small demo graph there's no speedup; the payoff is at **city scale**." | *(Optional)* terminal: `make gpu-check` → `GRAPH_BACKEND=cugraph · DF_BACKEND=cudf-polars · FLOW_BACKEND=cuopt · CLUSTER_BACKEND=cuml`. | "The Stack" — RAPIDS (4 of the six NVIDIA libs; NeMo + TensorRT-LLM are the 2:45 beat), honest about scale. Cut this beat first if over time. |
| 2:45 | "It's all **local on the GX10**: **Nemotron-3-Nano** for interactive narration — warm in **under two seconds**, served behind **NVIDIA TensorRT-LLM** (NVFP4/Blackwell FP4), a **runtime-portable narrator** with an **Ollama fallback** — and a larger MoE Nemotron for batch digests. We deliberately chose **small-active MoE models** for the box's memory bandwidth, and built **ARM64 / aarch64** end to end." | `make llm-check` confirming the runtime is **TensorRT-LLM** (capability / proof-of-invocation — Nemotron served via TRT-LLM on the box), **NOT a speedup**: single-stream decode is **not** faster than Ollama (54.5 vs 61.2 tok/s). Then back to live UI. | Best-use-of-Nemotron + ARM + **runtime-portable narrator** (ADR-0027). Claim the **capability**, never a decode speedup; throughput-under-load advantage is unproven (next-step). |
| 3:05 | "The hardest part was **honesty at speed**: keeping every dollar figure traceable while the model talks. So a number is either **computed and cited — or it doesn't render.** Same guarantee even when an **agent** drives it: NemoClaw calls our tools over **MCP** and answers grounded." | *(Optional)* flip to NemoClaw terminal: agent calls `toronto-civic` MCP tool, returns the grounded answer. | Challenge → solution beat. |
| 3:20 | "And because a lens is just a plugin — **about 90 lines, not a rewrite** — the platform extends to any domain: logistics, utilities, public health." | Architecture slide: a new lens snapping into the kernel. | Extensibility / platform thesis. |

---

## Section 5 — The climax + "so what?"  *(3:35–4:25, ~30–45s · camera back on for the last line)*
| Time | Voiceover | Screen action | Cue |
|---|---|---|---|
| 3:35 | "Back to the crunch — and **the whole point.** One coordinated lever: **⟨lever⟩** — one city-wide policy across every venue. I drag it **once**… *[drag]* …and **every lens moves together.**" | Drag the **staggered-release lever** once. All lens meters animate in lockstep. | Engineered peak #2. |
| 3:50 | "Union drops **⟨peak⟩ → ⟨peak-after⟩ — minus ⟨peak-drop%⟩.** Public-safety exposure: **⟨safety-$⟩**, gone — the risk data refusing to crush a crowd through the least-safe districts. Local business a crush would've killed: **⟨business-$⟩ recovered.** **One lever. ⟨combined-$⟩ of combined benefit.**" | Union node fades red→green; cross-domain panel rows update; combined-$ counter climbs to **⟨combined-$⟩**. | Say the screen's numbers. One surface. |
| 4:05 | "Transit, public safety, and the local economy — **optimized together.** The Fan Festival runs a **⟨deficit⟩ deficit**; this is the **operations side** of closing it." | Hold on the lit-up cross-domain panel. | The "so what" — real value to a city ops chief. |
| 4:15 | **[face cam]** "**One city. One substrate. Every lens. 100% on this box — still unplugged.** That's Urban-OS. Thanks for watching." | End on the unified dashboard, four lenses lit; title card returns. | Warm, confident close. |

---

## Fallback (if a take runs long): cut Section 4 to 60s
Drop the NemoClaw terminal beat (3:05) and the explicit ARM line; keep kernel + verifier +
Nemotron + "~90 lines." This lands the whole video at ~3:45.

## Pre-record checklist
- [ ] Numbers table above filled from the **live** surface you'll record.
- [ ] Box pre-flight done (see [`PRODUCTION.md`](PRODUCTION.md)) — unified shell on `:8001`,
      civic `:8000` ready, pins resolve, `/optimize` returns, NemoClaw armed (if used).
- [ ] Architecture slide(s) exported from the Canva deck.
- [ ] Today's date visible on the title card.
- [ ] One dry run for timing (≤ 5:00).
