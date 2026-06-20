# Demo Video — Production Kit

Everything needed to record [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md): setup, box pre-flight,
shot list, take order, editing notes, and the slide-deck outline (the source of truth shared
by the recording and the Canva deck).

---

## 1. Recording setup
- **Tool:** Loom (free tier is fine) or OBS Studio. **Camera ON** for the intro (Section 1)
  and the final line (Section 5); screen-only for the live demo + architecture.
- **Resolution:** record at **1080p**, 30fps, full-screen browser (hide bookmarks/tabs).
- **Audio:** external mic if possible; record in a quiet room; do one mic-level test.
- **Cursor:** enable click-highlighting so judges can follow taps (✓-verify, lever drag).
- **Length target:** 3:45–4:30; **hard cap 5:00.**

## 2. Box / app pre-flight state
Get the demo surfaces live and warm **before** recording (see [`ON_THE_BOX.md`](../ON_THE_BOX.md)
and [`REMOTE_ACCESS.md`](../REMOTE_ACCESS.md)):

- [ ] **Unified shell on `:8001`** running (the four-lens city canvas). Confirm `GET /health`.
- [ ] **urbanos.risk `:8000`** running for `/analyze` + click-to-verify.
- [ ] Demo pins resolve: **500 Bloor St W** (hero), **40 Bay St** (alt high-Activity).
- [ ] `GET /optimize` returns the climax figures; **fill the numbers table** in VIDEO_SCRIPT
      from this exact surface.
- [ ] Map basemap cached (PMTiles) so the **unplug** truly shows it offline.
- [ ] (If using the agent beat) **NemoClaw / MCP** armed — `toronto-civic` tools reachable;
      Nemotron-3-Nano prewarmed (`LLM_PREWARM=1`, `LLM_REASONING_EFFORT=none`).
- [ ] Browser zoom set so the four-lens dock + cross-domain panel are fully visible.
- [ ] Repo on `main`, CI-green; the live numbers match the repo (issue #61: pull + restart
      `:8000`/`:8001` on the box if they don't).

## 3. Shot list (capture order — record in this order, assemble in script order)
Record the **live demo segments first** while the box is warm, then the talking-head bookends.

| # | Shot | Source | Notes |
|---|---|---|---|
| S1 | Unified shell boots + four-lens dock | `:8001` | The "real pixels" reveal. |
| S2 | **Unplug** the box, UI still live | physical + `:8001` | The money shot. Steady hands. |
| S3 | Safety lens → click **500 Bloor St W** → risk card | `:8001` / `:8000` | Two-index + citations. |
| S4 | **✓ verify** → source record flips open | `:8001` / `:8000` | The trust beat. |
| S5 | Flow lens → four venue pulses converge → **Union flares at ⟨peak⟩** | `:8001` | Let the time loop run. |
| S6 | **Drag the lever once** → all lenses move → combined-$ counter climbs | `:8001` | The climax. Single drag. |
| S7 | *(optional)* NemoClaw terminal → grounded MCP answer | terminal | Agent-drivable proof. |
| S8 | *(optional)* `/analyze` returns grounded one-liner fast | `:8000` | Shows narration speed. |
| C1 | Talking-head **intro** (Section 1) | face cam | Team + one-sentence what. |
| C2 | Talking-head **close** (Section 5 last line) | face cam | Warm sign-off. |
| A1 | Architecture diagram beat | Canva slide | Used over Section 4 VO. |

## 4. Editing notes
- **Minimize cuts** in S3–S6 — judges reward live, unedited core loops. Trim dead air only.
- Open on the **title card** (date visible) → straight into the hook; pixels by ~0:20.
- Overlay the **architecture slide** (A1) during Section 4 VO, then cut back to live UI.
- Lower-third captions for the **hero numbers** at the climax (so they're legible even if
  the on-screen counter is small) — but the spoken value must match the screen.
- Keep the **unplug** uncut if at all possible (authenticity).
- End on the lit-up unified dashboard, then the title card return.

## 5. Slide-deck outline (source of truth for the Canva deck)
Minimal companion deck — used for the title card, the architecture beat, and the closing
slide. Keep it visual; the video carries the words.

1. **Title** — "URBAN OS — One lever. Every lens." · subtitle: *An operating system for the
   city, 100% on the NVIDIA GX10.* · team ⟨name⟩ · date `2026-05-31`.
2. **The problem** — three disconnected dashboards (inspections / transit / events) that
   don't talk. One line: *"Cities optimize in silos."*
3. **The architecture** *(the key slide for Section 4)* — the microkernel diagram:
   **Open data → Substrate (road/transit graph) → Kernel (time loop + `source`/`transport`/
   `couple`/`observe`) → Lenses (City · Safety · Flow · Economy) → Governor/Optimizer →
   Narrator + Verifier → UI.** Annotate: *deterministic figures; model only phrases; ARM64
   GX10; Nemotron-3-Nano via Ollama.*
4. **The proof** — the FIFA convergence crunch: 4 venues, ⟨crowd⟩ people, Union ⟨peak⟩ →
   one lever → **⟨combined-$⟩ combined benefit** across transit + safety + business.
5. **So what / platform** — *"A new lens is ~90 lines, not a rewrite."* + the close line:
   *One city. One substrate. Every lens. On one box.*

> Numbers on slides 3–4 use the same `⟨tokens⟩` as VIDEO_SCRIPT — fill from the live
> `:8001 /optimize` surface before exporting. Don't bake a figure the demo can't reproduce.

## 6. Final checks before upload
- [ ] Total runtime ≤ 5:00 (target 3:45–4:30).
- [ ] Every `⟨token⟩` spoken matches what's on screen; one surface per breath.
- [ ] Camera-on intro + close present; date visible.
- [ ] Audio levels consistent; no clipping.
- [ ] Architecture slide legible at the target resolution.
