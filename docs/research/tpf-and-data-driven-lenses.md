# Research: Two-Parameter Flows (TPF) & Data-Driven Intelligence Lenses

> **Status:** Research note (not an ADR — feeds a future ADR if we proceed). Post-hackathon
> R&D, written 2026-06-03. Demo day was May 31; nothing here is required for the shipped demo.
> **Scope:** Can we learn *real* urban dynamics from Toronto open data and run it as a new
> kernel lens — using the Two-Parameter Flows method — without breaking the deterministic,
> auditable pitch? **Verdict: yes, as an opt-in CPU-fallback seam, exactly like cuGraph /
> cuOpt / PhysicsNeMo (ADR-0024/0025/0027).** Reimplementation required (the reference repo
> has private deps). Recommended path is **Fit B** below.

---

## 1. Executive summary

- **TPF** ([arXiv 2605.26285](https://arxiv.org/html/2605.26285), [Algopaul/tpf](https://github.com/Algopaul/tpf))
  learns how a *probability distribution evolves over physics-time* from **unlabelled
  time-marginal snapshots only** — sets of samples at each time, with **no per-individual
  trajectories**. That is the exact data shape Toronto publishes (counts per place per
  15-minute bin), and the exact shape our kernel already emits per step.
- **Two framings.** ❌ *Not* the existing `surrogate.py` J-seam (that is scalar
  lever→J regression; TPF learns a velocity *field*, wrong shape). ✅ **Fit A** — TPF as a
  fast surrogate of the transport time-loop (honest only at city scale). ✅ **Fit B** — TPF
  as a **data-driven "LearnedDynamics" lens** trained on real Toronto marginals; the
  genuinely novel one, because it captures crowd **circulation** the kernel's
  downhill-to-sink transport structurally cannot.
- **Honest catches:** (1) the repo cannot `pip install` TPF — it imports private packages
  (`flanch`, `hdfx`, `hdfv`), so we reimplement the CFM→regression core, not vendor it;
  (2) a learned field is a black box, which cuts against the deterministic-simulation pitch —
  keep the repo's established pattern **"learned predicts, exact kernel decides"** (ADR-0027).
- **Recommendation:** prototype **Fit B as a calibration/validation lens** that *fits the
  kernel's transport capacities and a residual circulation term against real TMC counts*,
  reported side-by-side with the exact kernel, never replacing it.

---

## 2. What TPF actually is (grounded technical summary)

**Problem.** Given marginal sample sets `{x_{t_k}^(i)} ~ ρ(t_k)` at times `t_0<…<t_K` (each a
cloud of independent samples; **no coupling across time**), recover a velocity field
`u(x,t)` whose flow ODE `ẋ = u(x,t)` reproduces the observed marginal evolution `ρ(t)`.

**The two-time-axis trick.** TPF separates:
- **sampling-time `s ∈ [0,1]`** — a standard conditional-flow-matching (CFM) transport from a
  base Gaussian `ν` to *each* observed marginal `ρ(t)`. (Learned directly.)
- **physics-time `t ∈ [0,T]`** — the real dynamics, *extracted implicitly* from the family of
  s-flows via a consistency condition.

**Stage 1 — CFM.** Train `v(x,s,t;θ)` with stochastic-interpolant paths
`I_s(a,x_t)=α(s)a+β(s)x_t`, so `Φ(·,t,1)♯ν = ρ(t)` for every physics-time `t`.

**Stage 2 — physics-time extraction via vanishing Lie bracket.** Because the flow map `Φ` is a
`C²` diffeomorphism, mixed partials commute (`∂_t∂_sΦ ≡ ∂_s∂_tΦ`), giving the **compatibility
PDE** `∂_s u + v·∇u − u·∇v − ∂_t v = 0` (paper Eq. 9). This *uniquely* pins down the
physics-time velocity `u`. In practice TPF samples `a^(i)~ν`, integrates the s-flow at each
`t_k` to get coupled synthetic states `x̂_{t_k}^(i)`, and regresses `u_θ` on finite
differences `(x̂_{t_{k+1}} − x̂_{t_k})/Δt` (Eq. 15) — implemented in the repo as a normalised
"difference" target `x_{t+1} = x_t + diff_scale · model(x_t,t,p)`.

**Why it matters for us (claimed advantages):**
1. **No trajectories needed** — marginals suffice (matches Toronto data exactly).
2. **Non-gradient / rotational dynamics** — unlike optimal-transport / JKO methods that force
   `u=∇φ` (pure downhill), TPF represents **curl/circulation**. Our kernel's transport is
   strictly downhill to the nearest sink (`dist_to_sink`, `kernel/state.py`); real crowds
   eddy around corridors and that is exactly what we *can't* express today.
3. **Scalable** — avoids per-step O(N³) OT couplings; validated to `d>10⁴`.
4. **Fast inference** — one network eval per step; 100–1000× speedup over the physics solver
   on their fluid benchmark.
5. **Smoothness guarantee** — `u` inherits `C¹` regularity from a `C²` CFM field (Prop. 2.3).

**Validated on:** evolving Gaussian mixtures (d=2), barotropic + Kolmogorov turbulence
(d=128²=16,384), and Vlasov–Poisson plasma instabilities (W₂ ≈ 3e-4, beating DICE / HOAM /
JKOnet* / Action-Matching on bump-on-tail).

**Stated limitation:** `u` inherits an inductive bias from the chosen base→marginal transport;
beyond matching marginals + regularity bounds, there is no a-priori control over
minimal-energy / minimal-curl / interpretability properties. **This is the crux of the
black-box tension for us** and the reason the kernel must stay the source of truth.

---

## 3. The reference repo — reality check

[`Algopaul/tpf`](https://github.com/Algopaul/tpf) is a clean 5-step Hydra/`just` pipeline
(`01_process_trajectories → 01b_convert_to_wds → 02_train_cfm → 03_gen_cond_trajectories →
04_process_regression_data → 05_train_regression`), logging to W&B, data in Zarr/WebDataset.

**Blocker:** the actual model/training code lives in **three private packages** —
`flanch` (`EmbMLP`, `UNet`, optimiser/train-step/recorder), `hdfx` (zarr shuffle, trajectory
flattening, statistics), `hdfv` (visualisation). They are **not on PyPI**, so we **cannot
install or run it**. The published repo is effectively a *blueprint*, not a library.

**Implication:** "applying TPF" here means **reimplementing the core** — a CFM net + a
difference-regression net + the synthetic-trajectory coupling step — in PyTorch against our
own data. That is moderate, self-contained work (two small nets + two losses), and it keeps us
free of private deps. It would live behind a seam like `surrogate.py`, off by default.

---

## 4. Related research — where TPF sits (so we pick the best tool, not just the newest)

| Method | Idea | Relevance to us |
|---|---|---|
| **Action Matching** — Neklyudov 2022, [2210.06662](https://hf.co/papers/2210.06662) | Canonical "learn dynamics from uncorrelated temporal marginals"; no ODE backprop, no OT solver. | The **direct, simpler ancestor/competitor** to TPF. Strong, well-tested baseline — worth implementing *first* as the floor before TPF's extra machinery. |
| **Multi-marginal Schrödinger Bridges** — Shen 2024, [2408.06277](https://hf.co/papers/2408.06277) | Trajectory inference across many snapshots with a *reference-dynamics class*, not a single fixed prior. | Lets us inject the **kernel as the reference dynamic** and learn only the residual — the cleanest "grey-box" fit to our honesty constraint. |
| **Variational Grey-Box Dynamics Matching** — 2026, [2602.17477](https://hf.co/papers/2602.17477), [code](https://github.com/DMML-Geneva/VGB-DM) | Embeds an **incomplete physics model inside** a flow-matching generative model; learns the missing terms only. | **The conceptual match for "kernel + learned residual."** This is the framing that most preserves the deterministic pitch. |
| **Metric Flow Matching** — 2024, [2405.14780](https://hf.co/papers/2405.14780) | Geodesic interpolants on the data manifold; SOTA single-cell trajectory inference. | The marginals→dynamics problem is *mature* in single-cell biology; this is the SOTA there and a good architecture reference. |
| **Neural Spatio-Temporal Point Processes** — Chen 2020, [2011.04583](https://hf.co/papers/2011.04583) | Events localised in continuous space+time; validated on **urban mobility**. | Better fit for **event/311/incident** data (discrete events) than for density fields. A candidate for a *separate* event-intensity lens. |
| **Probabilistic Traffic Forecasting (GMM)** — 2026, [2604.16084](https://hf.co/papers/2604.16084) · **STGNN survey** — [2301.10569](https://hf.co/papers/2301.10569) | Mainstream supervised spatiotemporal forecasting on road networks. | The **boring-but-robust alternative**: if all we want is "predict next-step counts per node," a STGNN is simpler than TPF. TPF wins only if we need a *generative, trajectory-capable* field. |
| **CrowdES** — 2025, [2504.04756](https://hf.co/papers/2504.04756) | Generates continuous crowd trajectories from density/probability maps. | Reference for **density-map → crowd-flow** if we ever want synthetic agents for validation. |

**Take-away:** TPF is the most capable (rotational, scalable, generative) but the heaviest.
The honest engineering order is **Action Matching (floor) → grey-box residual (kernel as
reference) → TPF (if circulation/scale demands it)**.

---

## 5. The data match — Toronto publishes exactly the input TPF needs

TPF's premise is "**density snapshots over time, never per-person paths**." That is precisely
what the [City of Toronto Open Data Portal](https://open.toronto.ca/) provides, and what our
current pipeline does **not** yet exploit (we use DineSafe + permits + licences, which are
*static* address attributes — see `urbanos/risk/ingest/datasets.py`). New, dynamic,
marginal-shaped datasets:

| Dataset | Shape | Why it's a TPF marginal |
|---|---|---|
| **Multimodal Intersection Turning Movement Counts (TMC)** — [portal](https://open.toronto.ca/) | Cars/trucks/buses/**cyclists/pedestrians** in **15-min intervals** at intersections, 1984→present (30k+ counts, 56M peds observed). | **The gold seam.** Per-node density vs. time, no trajectories — a textbook marginal series for learning a pedestrian/vehicle velocity field over the downtown substrate. |
| **Automatic Traffic Recorder (ATR) counts** | Segment-level volumes over time. | Edge-level flux → directly calibrates our **edge capacities** (`edge_cap`). |
| **TTC Ridership Analysis** — [dataset](https://open.toronto.ca/dataset/ttc-ridership-analysis/) | Boardings (first point of payment) per station/route. | A real **`source()` term** — replace synthetic event injection at transit relays with measured boardings. |
| **Bike Share Toronto Ridership** — [dataset](https://open.toronto.ca/dataset/bike-share-toronto-ridership-data/) | Anonymised trip **OD + timestamps**, 900+ stations, 7.8M trips/yr. | Weakly *coupled* (two endpoints) → a real **demand/OD signal** and a partial validation of learned flow direction. |
| **King St Pilot — Bluetooth travel-time + Miovision counts** — [portal](https://www.toronto.ca/services-payments/streets-parking-transportation/road-safety/big-data-innovation-team/) | Inter-sensor travel times + granular turning counts. | The closest thing to a **measured velocity** — ground-truth to validate a learned `u`. |

**Key point for the pitch:** the deterministic kernel *cannot ingest these* — it has no place
for "observed density evolution." A learned lens does. This turns "we use real Toronto data"
from a static-attribute claim into a **dynamics-from-data** claim.

---

## 6. How it maps onto our kernel (grounded in the lens contract)

Our lens contract (`src/urbanos/kernel/kernel/operators.py:104`):

```python
class Lens:
    name: str; weight: float
    def configure(self, substrate): ...
    def source(self, state, t): ...      # inject forcing
    def couple(self, state, t): ...      # field → field
    def observe(self, state, t) -> dict[str,float]: ...
    def levers(self) -> list[Lever]: ...
    def cost(self, result) -> float: ...
```

`transport` is **kernel-owned** (`operators.py:64`, capacitated downhill drainage). The loop
order is `source → transport → couple → observe` (`kernel/loop.py`), and each step already
emits frames `{t, load, congestion, risk, arrived}` — i.e. **the marginals a TPF model both
trains on and predicts.** Three concrete ways to plug a learned field in:

### Fit A — TPF as a transport surrogate (acceleration)
Train on kernel frames, then roll the load field forward in a few network steps instead of
integrating capacitated drainage + every lens each minute. **Honest value only at city scale**
(real GTFS, thousands of nodes, noise ensembles for the optimiser's lever search). At the
demo's 17-node substrate the exact kernel is already faster, so this is a *documented-stretch*
seam, same status as PhysicsNeMo. **Lower novelty; skip unless we scale the substrate.**

### Fit B — Data-driven "LearnedDynamics" lens (recommended)
A new lens that learns from **real TMC marginals** and contributes a **measured-vs-modelled**
signal. Cleanest honest form is **grey-box** (per §4, VGB-DM / Schrödinger-bridge framing):
- The **kernel transport is the reference dynamic**; the lens learns only a **residual
  circulation field** `u_resid` that the downhill drainage can't represent.
- It writes an advisory field (e.g. `learned_flow`) in `couple()` and emits a **calibration
  metric** in `observe()` — *how far the kernel's predicted node densities sit from observed
  TMC counts at matching times/places*.
- It declares **no levers** initially (pure validation), so it **cannot change the chosen
  intervention** — it only tells you how trustworthy the kernel is on a given corridor. This
  is the safest first step and directly strengthens the honesty story.

### Fit C — Real source/demand lenses (low-risk, high-credibility, no TPF needed)
Independently of TPF, the datasets in §5 enable conventional lenses that make the demo more
*real* today:
- **TransitLoad lens** — `source()` injects **measured TTC boardings** at relay nodes.
- **MobilityDemand lens** — Bike Share OD as a real demand field / display overlay.
- **CongestionNowcast lens** — King St Bluetooth travel-times as an observed-congestion field
  to validate the kernel's `congestion = load/capacity`.

These are pure-data, deterministic, and ship the "uses live-shaped Toronto data" story without
any black-box risk — a good **parallel track** while TPF is prototyped.

---

## 7. Honesty constraints (do not regress these — per CLAUDE.md & ADR-0027)

1. **Learned predicts, exact kernel decides.** A learned field may inform or validate, but the
   optimiser's chosen lever and every headline number must come from the exact kernel `J`
   (mirror `optimize.py` + `surrogate.py`: surrogate recorded *alongside*, never decisive).
2. **Opt-in + CPU fallback.** Off by default (env flag, e.g. `URBANOS_LEARNED_DYNAMICS`);
   absent checkpoint → lens is a no-op. CI/dev never need a trained model or CUDA.
3. **Provenance honesty.** Any learned overlay is **labelled "learned / approximate"** in the
   UI, distinct from kernel-exact fields (consistent with the §provenance work in ADR-0026).
4. **Narrator boundary.** The hallucination guard (ADR-0010/0020) must **not** cite a learned
   number as if it were a measured/kernel figure. A learned value reaching the narrator needs
   its own evidence kind.
5. **No private deps.** Reimplement; never vendor `flanch`/`hdfx`/`hdfv`.

---

## 8. Recommended path (phased, each phase independently shippable)

1. **Phase 0 — data ingest (no ML).** Add a TMC/ATR loader (15-min counts → per-node series
   aligned to the downtown substrate). Ship **Fit C** lenses (TransitLoad / CongestionNowcast)
   first — real data, deterministic, immediate demo credibility.
2. **Phase 1 — calibration metric (no learned field yet).** Compute kernel-vs-observed density
   error per node from real TMC counts; surface as a `observe()` metric. This alone is a
   strong "we validate against ground truth" result.
3. **Phase 2 — Action Matching floor.** Reimplement Action Matching (simpler than TPF) to learn
   a velocity field from TMC marginals; compare its rollout to the kernel and to observed
   counts. Establishes whether a learned field beats the kernel at all.
4. **Phase 3 — TPF / grey-box residual.** Only if Phase 2 shows the kernel missing
   **rotational** structure, add the TPF CFM→regression core as a **residual** on top of the
   kernel reference (VGB-DM framing). Keep it advisory.
5. **Phase 4 (stretch) — Fit A surrogate** for city-scale optimiser acceleration, *if* we grow
   the substrate to real GTFS scale.

**ADR when we commit:** "ADR-0028 — Learned-dynamics lens (data-driven transport calibration),
opt-in, advisory-only." Mirror the scope/honesty language of ADR-0027.

---

## 9. Open questions

- **Spatial representation.** TPF was validated on grids/particles; our substrate is a small
  directed graph (17 nodes). Do we learn `u` on **node features** (graph) or on a **rasterised
  density field** over downtown? Graph-native (a GNN velocity head) is more faithful but less
  like the paper; a raster is closer to TPF but loses the substrate.
- **Time alignment.** TMC counts are 15-min and sparse per location; the kernel runs at
  ~1-min steps over a single event afternoon. We need a defensible temporal binning + a
  "typical FIFA-day" construction (the real data is not from a World Cup convergence).
- **Validation target.** What's the honest success metric — W₂ between learned and observed
  node-density marginals? Per-corridor count MAE? Decide before training so we don't fish.
- **Is TPF overkill?** If Phase 2 (Action Matching) or a plain STGNN already matches observed
  marginals, TPF's extra two-time-axis machinery may not earn its complexity. Re-evaluate at
  Phase 3.

---

## 10. References

**Primary**
- Two-Parameter Flows — [arXiv 2605.26285](https://arxiv.org/html/2605.26285) ·
  code [github.com/Algopaul/tpf](https://github.com/Algopaul/tpf) (private deps: `flanch`,
  `hdfx`, `hdfv` — reimplement, do not vendor).

**Related methods**
- Action Matching — [2210.06662](https://hf.co/papers/2210.06662)
- Multi-marginal Schrödinger Bridges — [2408.06277](https://hf.co/papers/2408.06277)
- Variational Grey-Box Dynamics Matching — [2602.17477](https://hf.co/papers/2602.17477) ·
  [code](https://github.com/DMML-Geneva/VGB-DM)
- Metric Flow Matching — [2405.14780](https://hf.co/papers/2405.14780)
- Neural Spatio-Temporal Point Processes — [2011.04583](https://hf.co/papers/2011.04583)
- Probabilistic Traffic Forecasting (GMM) — [2604.16084](https://hf.co/papers/2604.16084)
- Spatio-Temporal GNN Survey — [2301.10569](https://hf.co/papers/2301.10569)
- CrowdES (continuous crowd generation) — [2504.04756](https://hf.co/papers/2504.04756)

**Toronto open data**
- [Open Data Portal](https://open.toronto.ca/) ·
  [Transportation Data & Analytics / Big Data Innovation Team](https://www.toronto.ca/services-payments/streets-parking-transportation/road-safety/big-data-innovation-team/)
- Multimodal Intersection Turning Movement Counts (TMC) + ATR counts (portal search)
- [TTC Ridership Analysis](https://open.toronto.ca/dataset/ttc-ridership-analysis/)
- [Bike Share Toronto Ridership](https://open.toronto.ca/dataset/bike-share-toronto-ridership-data/)
- King Street Transit Pilot — Bluetooth travel-time + Miovision counts (City dashboards)

**In-repo anchors**
- Lens contract — `src/urbanos/kernel/kernel/operators.py:104` · Lever — `:24` ·
  transport — `:64`
- State/Substrate fields — `src/urbanos/kernel/kernel/state.py` · loop order + frames —
  `src/urbanos/kernel/kernel/loop.py`
- Existing surrogate seam (honesty template) — `src/urbanos/kernel/surrogate.py` · optimiser —
  `src/urbanos/kernel/optimize.py`
- Static civic ingest (what we have today) — `src/urbanos/risk/ingest/datasets.py`,
  `loader.py`
- Prior honesty/seam ADRs — `docs/adr/0024`, `0025`, `0027`
