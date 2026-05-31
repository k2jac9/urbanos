# Urban-OS — Pitch (flagship track: Urban Operations)

## Tagline
**An operating system for the city: on a peak FIFA World Cup 2026 day, fuse the
data, simulate four venues letting out at once, and optimize one coordinated lever
across transit, public safety, and local business — grounded, and 100% on one box.**

## Thesis (10 seconds)
Most civic tools are single-purpose dashboards. We built a **microkernel for urban
dynamics** — a domain-agnostic kernel + a driver model for cities + portable
domain *lenses* + a governor that optimizes interventions — and proved it with
**four lenses on one kernel**, end-to-end on an NVIDIA GX10, with **no cloud and
no hallucinated numbers**.

## Run-of-show (~90 seconds, spoken)

> "Everything you'll see runs **100% on this GX10** — no cloud, no tile server, no
> internet. Watch — I'll unplug it. *[unplug]*
>
> First, the **Safety lens**. This is downtown Toronto, offline. Every pin is
> risk-scored on **two independent indices — Safety and Activity** — so a busy
> construction zone isn't confused with an unsafe one. I click **500 Bloor St
> West**: **medium Activity** (8 open permits — active construction to verify) and
> a flagged food-safety item. And every claim is grounded: it cites the open
> permits, a DineSafe conditional pass, a licence — across **three real City of
> Toronto datasets**, fused on the address.
> I click **✓ verify** — there's the source record. The local Nemotron model only
> **phrases** the numbers; it can't invent them. It once claimed '9 permits' when
> the data showed 8 — our verifier caught it. **A hallucinated number physically
> cannot reach the screen.**
>
> Now the move: that risk app isn't a separate tool — it's **one lens on a
> kernel**. Watch what the kernel does with time. It's a peak **FIFA World Cup
> 2026** day downtown, and **four venues let out into the same corridor at once** —
> BMO Field's FIFA match, the Blue Jays ballgame, a Scotiabank Arena concert and
> the Fort York Fan Festival: **140,800 people**. Our simulation superimposes all
> four egress waves: **Union Station hits 4.0× safe capacity — and Exhibition GO,
> the single station for BMO Field's 46,000, is the secondary crush.**
>
> One coordinated lever: a **16-minute staggered release plus 80% shelter
> coverage** — *one city-wide release policy across every venue* — cuts Union's
> peak **75%**, back to **1.0×**.
>
> And the same lever, scored across **every** lens at once: it eliminates
> **$50,900** of public-safety exposure — the civic-risk data deciding we shouldn't
> crush a crowd through the least-safe districts — and recovers **$10,700** of
> local business a crush would have killed. **One lever. ~$455,000 of combined
> benefit.** Transit, public safety, and the local economy — optimized together.
> The Fan Festival is running a **$6.2M deficit**; this is the operations side of
> closing it."
>
> And it's agent-drivable: *[to the NemoClaw agent]* 'top three riskiest
> addresses.' *[it calls our tool]* — grounded, matching the data exactly. One OS,
> many lenses, on one box. Thank you."

## Why we win (mapped to the rubric)
1. **The flagship track's literal ask — raw data → on-box processing → actionable
   result.** We ingest Toronto open data, run a deterministic **simulation kernel**
   on the Spark, and emit a quantified, cited intervention. Not a lookup —
   *systems engineering.*
2. **The Verifiers bounty is the architecture, not a feature.** Every number is
   computed; the model only phrases it; a verifier rejects any unverified figure →
   deterministic fallback; click-to-verify makes it auditable live — and the
   **same guarantee holds through the NemoClaw agent** (its answer matched our tool
   exactly).
3. **A platform, demonstrated.** Four lenses — EventSurge (now **multi-venue**),
   Economic, **Safety (the civic risk app, made literal)**, **BusinessFlow
   (sports/economics)** — run on one kernel, optimized by one lever, against a
   **real FIFA-window convergence crunch** (four concurrent let-outs, 140,800
   people; see [ADR-0018](0018-fifa-convergence-crunch-substrate.md)). A new urban
   intelligence is a **plugin (~90 lines), not a rewrite.** That is the digital-twin
   / "operating system for the city" thesis, proven.

## Anticipated judge Q&A
- **"Is it really on-device?"** Fully. Local Nemotron via Ollama; self-hosted
  PMTiles basemap + vendored MapLibre — no CDN. Unplug it and the FIFA simulation
  keeps running. The point for a city handling sensitive permit/inspection data.
- **"How do you know it isn't hallucinating?"** The model never produces numbers —
  it phrases them. Figures (risk, peak, the dollar benefits) are computed
  deterministically; the verifier rejects invented numbers/sources; audit any claim
  with ✓-verify. The "9 vs 8 permits" catch is a real rejection.
- **"The savings — real or hardcoded?"** Reproducible, and **which number depends on
  which lens stack you're looking at** (we name each below so nothing drifts from the
  live demo). The optimizer runs a grid search over the release (and shelter) levers
  minimizing `J = Σ wₚ·Jₚ` on the box every run; the breakdowns are emergent from
  the lenses, not stored. Calibration constants are synthetic and flagged in
  provenance; the *shape* is the claim.
- **"Why four different dollar figures?"** Different surfaces enable different lenses
  — that's the platform point, not a discrepancy. `make urbanos-cli` is transit-only
  (2-lens, **~$218k**); `--safety --business` adds the cross-domain lenses
  (**~$281k**); the live `:8001` UI's `/optimize` adds the **WeatherLens/shelter
  lever** ([ADR-0007](0007-third-lens-weather.md)/[0016](0016-shelter-interior-optimum-coverage-premium.md))
  so its lever is *release + shelter* and its combined benefit is **~$455k**. Cite
  the surface you're showing.
- **"Is the FIFA crowd made up?"** Crowd sizes are anchored to announced capacities
  (BMO Field FIFA 45,736; Rogers Centre; Scotiabank Arena; Fort York fan zone);
  the concurrency is real schedule overlap (FIFA match + Blue Jays v Yankees +
  arena concert + the Jun 12–Jul 2 Fan Festival). Node/edge capacities and overlap
  degree are plausibility-calibrated and flagged. The worst-case simultaneity *is*
  the planning scenario — see [ADR-0018](0018-fifa-convergence-crunch-substrate.md).
- **"What's 'OS' about it?"** A microkernel (substrate + time loop), a syscall ABI
  (the four operators `source/transport/couple/observe`), a driver model (city
  adapters), portable apps (lenses), and a governor (the optimizer) — same
  architecture as a real OS, applied to a digital twin of the city.

## The numbers (reproducible, current — FIFA convergence crunch)
Scenario: **4 concurrent FIFA-day let-outs, 140,800 people, 17 nodes / 25 edges**
([ADR-0018](0018-fifa-convergence-crunch-substrate.md)). **Three surfaces, three
lens stacks — each row names the command that reproduces it** (a judge can verify;
the pitch never drifts from the live demo):

**A. Transit core — `make urbanos-cli` (2-lens: EventSurge + Economic)**
| | value |
|---|---|
| Union peak | **3.7×** capacity @ t=47 min (19 min after full-time) |
| Lever | **14-min** staggered release → **−67% peak** |
| Net intervention benefit | **~$218k** (J $323k → $105k) |

**B. Full cross-domain — `PYTHONPATH=src python -m urban_os.cli --safety --business`**
| | value |
|---|---|
| Net intervention benefit | **~$281k** (J $388k → $107k) |
| Public safety | **$53.7k → $1.6k** (crush avoided through least-safe districts) |
| Local business | **$10.4k** recovered |

**C. Live `:8001` UI — `GET /optimize` (3-lens incl. WeatherLens/shelter)**
| | value |
|---|---|
| Union peak | **4.0× → 1.0×** (**−75%**), 24 min after full-time (t=52) |
| Lever | **16-min release + 80% shelter coverage** |
| Net intervention benefit (J) | **~$394k** (J $533k → $140k) |
| Public safety | **$50.9k → $0** |
| Local business | **$10.7k** recovered |
| **Combined cross-domain benefit** | **~$455k** |

The deficit tie-in: one coordinated lever, optimized across *every* concurrent
event, is the **operations** side of offsetting the Fan Festival's **$6.2M deficit**.

Reproduce:
```bash
make urbanos-cli                                            # A — transit egress insight (2-lens)
PYTHONPATH=src python -m urban_os.cli --safety --business   # B — full cross-domain (4 lenses)
# C — the live-UI optimum (3-lens with weather/shelter):
PYTHONPATH=src python -c "from fastapi.testclient import TestClient; from urban_os.api import app; import json; print(json.dumps(TestClient(app).get('/optimize').json()['figures'], indent=2))"
```
