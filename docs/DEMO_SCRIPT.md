# Demo Script — Urban OS unified shell (~90s spoken run-of-show)

The single-dashboard demo: **one persistent Toronto map** (the "city canvas") with a
dock of **four lenses — City · Safety · Flow · Economy** — that re-skin the *same*
city, climaxing in **"one lever, every lens."** Structured around two engineered
peaks (open + climax) for peak-end recall.

**Every number below is traceable to a command/surface** — see the provenance map at
the bottom. Cite the surface you're showing; never blend two. Source of truth:
[`PITCH.md`](PITCH.md) §"The numbers", [`ADR-0018`](adr/0018-fifa-convergence-crunch-substrate.md).

> **Honesty rule for the operator:** read a number off the screen, not off this page.
> If the live surface shows a different figure than written here, say the screen's
> number — this script is calibrated to the `:8001` 3-lens UI (release + shelter) for
> the climax. Numbers differ by lens stack *by design* (it's the platform point).

---

## The run-of-show (spoken ↔ clicked)

| # | Spoken (~90s) | What you click / what's on screen |
|---|---|---|
| **1. THE OPEN** *(boot, ~8s — engineered peak #1)* | "Everything you'll see runs **100% on this one box** — no cloud, no internet. *[unplug it]*" | Black screen → **URBAN OS** types on → the Toronto skyline rises → tagline **"One lever. Every lens."** → **Enter**. One persistent map loads; the four-lens dock sits at the edge. |
| **2. CITY lens** *(overview, ~10s)* | "This is Toronto — one city, one substrate. Four lenses read the *same* canvas: safety, flow, the local economy. Watch them re-skin it." | **City** lens active (default). Downtown overview, cross-domain headline visible. No data swap between lenses — same map, different read. |
| **3. SAFETY lens** *(the trust beat, ~22s)* | "**Safety lens.** Every pin is risk-scored on **two independent indices — Safety and Activity** — so a busy construction zone isn't mistaken for a dangerous one. I click **500 Bloor St West**: **medium Activity** — 8 open permits, active construction — and a flagged food-safety item. Every claim is grounded: open permits, a DineSafe conditional pass, a licence — **three real City of Toronto datasets, fused on the address.** I hit **✓ verify** — there's the source record. The local Nemotron model only **phrases** numbers; it can't invent them. It once said '9 permits' when the data showed 8 — the verifier caught it. **A hallucinated number physically cannot reach this screen.**" | Tap **Safety** in the dock → map re-skins to risk pins. Click pin **500 Bloor St W** → risk card: Safety + Activity indices + grounded citation listing the 3 datasets. Hit **✓ verify** → the actual DineSafe / permit record flips open inline. |
| **4. FLOW lens** *(the crunch, ~18s)* | "**Flow lens** — same city, now in motion. It's a peak **FIFA World Cup 2026** day, and **four downtown venues let out into the same corridor at once**: BMO Field's FIFA match, the Blue Jays game, a Scotiabank Arena concert, the Fort York Fan Festival — **140,800 people.** We superimpose all four egress waves and **Union Station hits 4.0× safe capacity**; Exhibition GO — the single station for BMO Field's 46,000 — is the secondary crush." | Tap **Flow** → map re-skins to the transit graph; time loop runs. Four venue pulses bloom and converge; **Union node flares red at 4.0×**, Exhibition GO flagged as secondary. |
| **5. THE CLIMAX** *("one lever, every lens", ~24s — engineered peak #2)* | "Now the whole point. One coordinated lever — a **16-minute staggered release plus 80% shelter coverage**, one city-wide policy across every venue. I drag it **once**… *[drag]* …and watch **every lens move together.** Union drops **4.0× → 1.0× — minus 75%.** Public-safety exposure: the risk data refuses to crush a crowd through the least-safe districts — **gone, $53.7k → $0.** Local business a crush would've killed — **$10.7k recovered.** **One lever. ~$458,000 of combined benefit** across transit, safety, and the local economy. The Fan Festival runs a **$6.2M deficit** — this is the operations side of closing it." | Drag the **staggered-release lever** once. All four lens meters animate in lockstep + the **combined-$ counter** climbs to **~$458k**. Union node fades red→green (4.0×→1.0×). Cross-domain panel rows update: safety $53.7k→$0, business +$10.7k. |
| **6. CLOSE** *(~8s)* | "**One city. One substrate. Every lens. 100% on this box** — still unplugged. It's even agent-drivable — *[to NemoClaw]* 'top three riskiest addresses' — and it answers grounded, matching the data exactly. Thank you." | *(Optional)* flip to the NemoClaw terminal; the local Nemotron agent calls the `toronto-civic` MCP tool and returns the same grounded answer. End on the lit-up unified dashboard. |

---

## 20-second short version (fallback if rushed / time-boxed)

> "One box, no cloud — *[unplug]*. This is Urban OS: one Toronto map, four lenses.
> **Safety** — I click 500 Bloor, every number is grounded and **✓-verifiable**; the
> model phrases numbers, it can't invent them. **Flow** — peak FIFA day, four venues
> let out at once, 140,800 people, **Union hits 4.0×.** I drag **one** release lever —
> Union drops **to 1.0×**, and **every lens moves: ~$458k combined** across transit,
> safety, and business. One lever. Every lens. On this box."

Clicks: unplug → Safety pin + ✓-verify → Flow (Union 4.0×) → drag lever (→1.0×, $458k).

---

## Anticipated judge Q&A

- **"Is it really on-device?"** Fully. Local Nemotron via Ollama; self-hosted PMTiles
  basemap + vendored MapLibre — no CDN, no tile server. We unplugged it on stage and
  the FIFA simulation kept running. That's the point for a city handling sensitive
  permit/inspection data.
- **"How do you know it isn't hallucinating?"** The model never *produces* numbers — it
  **phrases** them. Risk, the 4.0× peak, every dollar figure are computed
  deterministically; a verifier rejects any number/source not in the evidence and falls
  back to a deterministic phrasing. **✓-verify** audits any claim live against the source
  record. The "9 vs 8 permits" catch is a real rejection, not a story.
- **"Are the savings real or hardcoded?"** Reproducible every run — the optimizer
  grid-searches the release (and shelter) levers minimizing `J = Σ wₚ·Jₚ` on the box;
  the per-lens breakdowns are **emergent from the lenses, not stored.** **Which** number
  you get depends on which lens stack is active (we name each below so nothing drifts):
  transit-only `make urbanos-cli` ≈ **$218k**; `--safety --business` ≈ **$281k**; the
  live `:8001` UI adds the WeatherLens/shelter lever → release+shelter → **~$458k**
  combined. Calibration constants are synthetic and flagged in provenance; the *shape*
  is the claim.
- **"Is the crowd-overlap made up?"** Crowd sizes are anchored to announced capacities
  (BMO Field FIFA 45,736; Rogers Centre; Scotiabank Arena; Fort York fan zone). The
  concurrency is **real schedule overlap** — FIFA match + Blue Jays v Yankees (Jun 12
  7:07pm) + arena concert + the Jun 12–Jul 2 Fan Festival. Node/edge capacities and the
  overlap degree are plausibility-calibrated and **flagged in provenance, not measured**
  ([ADR-0018](adr/0018-fifa-convergence-crunch-substrate.md) "Honest-calibration
  caveat"). Worst-case simultaneity *is* the planning scenario a city ops chief prepares
  for — calibrating toward it is the honest choice, not inflation.
- **"Why is it 'OS' and not a dashboard?"** A microkernel (substrate + time loop), a
  syscall ABI (the four operators `source/transport/couple/observe`), a driver model
  (city adapters), portable apps (the lenses), and a governor (the optimizer). A new
  urban intelligence is a **plugin (~90 lines), not a rewrite** — that's why all four
  lenses read one canvas.

---

## Provenance map — every number → its surface (don't blend these)

| Number in the script | Surface / command it comes from |
|---|---|
| 140,800 people, 4 concurrent let-outs, 17 nodes / 25 edges | [ADR-0018](adr/0018-fifa-convergence-crunch-substrate.md) substrate |
| Union **4.0× → 1.0× (−75%)**, **16-min release + 80% shelter**, safety **$53.7k→$0**, business **+$10.7k**, **~$458k combined** | **Live `:8001` UI `GET /optimize`** (3-lens, incl. WeatherLens/shelter) — *the climax surface* |
| (alt) Union 3.7×, 14-min release, −67%, ~$218k | `make urbanos-cli` (2-lens, transit-only) — cite only if you're showing the CLI |
| (alt) ~$281k; safety $53.7k→$1.6k; business $10.4k | `PYTHONPATH=src python -m urban_os.cli --safety --business` (4-lens, no weather) |
| 500 Bloor St W: two-index Safety/Activity, 8 permits, 3 fused datasets, ✓-verify | civic_analyst `:8000` `/analyze` + click-to-verify (ADR-0014 two-index) |
| $6.2M Fan Festival deficit, $10 ticket | [ADR-0018](adr/0018-fifa-convergence-crunch-substrate.md) (toronto.ca / blogto.com anchors) |

**The climax narrates the `:8001` 3-lens UI numbers (release + shelter → ~$458k).** If
the live shell instead shows the 2-lens transit figures, say **3.7× / 14-min / ~$218k**
and don't mention shelter. One surface per breath.

Reproduce the headline surfaces:
```bash
make urbanos-cli                                            # A — transit core (2-lens): 3.7×, 14-min, ~$218k
PYTHONPATH=src python -m urban_os.cli --safety --business   # B — full cross-domain (4 lenses): ~$281k
# C — the live-UI optimum (3-lens w/ weather+shelter), the climax numbers:
PYTHONPATH=src python -c "from fastapi.testclient import TestClient; from urban_os.api import app; import json; print(json.dumps(TestClient(app).get('/optimize').json()['figures'], indent=2))"
```
