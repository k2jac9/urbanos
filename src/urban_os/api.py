"""FastAPI surface for Urban-OS — the offline map UI over the simulation kernel.

The simulation kernel is owned elsewhere (kernel / lenses / adapters / optimize /
narrate); this module is the thin web layer that runs it and serves the map. All
endpoints return JSON (the map page is HTML) and every numeric payload is
converted from numpy to native Python so it is JSON-serializable (numpy scalars
are NOT JSON-serializable — converting at the boundary is the only safe place).

Offline invariant: the page reuses the *already-vendored* MapLibre + PMTiles
assets and the offline ``toronto.pmtiles`` basemap from the civic_analyst static
dir — no CDN, no tile server. We mount that existing dir at ``/static`` so the
UI loads everything from this origin.

Endpoints:
- GET /          map UI (urban_os.html)
- GET /health    {status, nodes, edges}
- GET /scenario  substrate nodes + edges + scenario meta (for drawing the map)
- GET /simulate  per-step frames + metrics + peak for the heatmap/time-slider
- GET /optimize  optimizer result + cited insight for the before/after view
"""
from __future__ import annotations

import logging
import math
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from urban_os.adapters import downtown_scenario
from urban_os.adapters.toronto import NODE_GROUPS
from urban_os.kernel import Simulation
from urban_os.narrate import build_insight
from urban_os.optimize import cost_breakdown, optimize
from urban_os.scenarios import default_lens_stack, extra_display_lenses as _extra_display_lenses
from urban_os.serialize import native as _native, peak_dict as _peak_dict, r as _r
from urban_os.services import (
    BENEFIT_DEFINITIONS,
    cross_domain_block as _cross_domain_block,
    cross_domain_components as _cross_domain_components,
    extra_lens_report as _extra_lens_report,
    four_lens_J as _four_lens_J,
    four_lens_stack as _four_lens_stack,
)

# The civic address-risk app, mounted same-origin at /civic so the unified shell
# can reach /civic/addresses, /civic/analyze, /civic/health and /civic/ without a
# second server/origin. Imported as a sub-app — see ``_load_civic_graph`` for the
# lifespan caveat that makes its data actually load under this parent app.
from civic_analyst.api.server import app as civic_app
from civic_analyst.api import server as _civic_server

# Our own page + the proven offline assets (vendored MapLibre/PMTiles + basemap).
_HERE = Path(__file__).parent
_UI_DIR = _HERE / "static"
_OFFLINE_ASSETS = (
    Path(__file__).resolve().parents[1] / "civic_analyst" / "api" / "static"
)


def _load_civic_graph() -> None:
    """Ensure the mounted civic sub-app's knowledge graph is loaded under THIS app.

    GOTCHA: a mounted sub-app's ``lifespan`` does NOT reliably run when the parent
    app starts up under this Starlette version, so ``/civic/addresses`` would serve
    an empty graph. We call civic's PUBLIC ``load_graph`` entrypoint (ADR-0023) rather
    than reaching into its private module globals, so a civic-side refactor can no
    longer silently break ``/civic/*`` here. Offline-safe: a load failure is LOGGED
    (not silently swallowed) and never blocks Urban-OS startup."""
    try:
        _civic_server.load_graph()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "civic graph load failed; /civic/* will serve an empty graph: %s", exc
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the mounted civic sub-app has its knowledge graph loaded (its own
    # lifespan won't fire under the parent — see _load_civic_graph).
    _load_civic_graph()
    yield


app = FastAPI(title="Urban-OS", version="0.1.0", lifespan=lifespan)

# Serve vendored maplibre-gl.js/.css, pmtiles.js and toronto.pmtiles fully offline.
app.mount("/static", StaticFiles(directory=_OFFLINE_ASSETS), name="static")

# The civic address-risk app, same-origin under /civic (its data is loaded by this
# app's lifespan above, not the sub-app's own lifespan).
app.mount("/civic", civic_app)


@lru_cache(maxsize=1)
def _scenario():
    """The default downtown demo scenario, built once."""
    return downtown_scenario()


def _lenses(sc):
    """The optimizer/narrator stack (EventSurge + Economic + Weather).

    Delegates to the shared :func:`urban_os.scenarios.default_lens_stack` so the
    CLI and API can never run different stacks (ADR-0022). WeatherLens contributes
    the shelter-coverage optimizer lever and must follow Economic (ADR-0007)."""
    return default_lens_stack(sc, weather=True)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """The unified "Urban OS" shell (one city canvas + a lens dock). Falls back to
    the classic single-view ``urban_os.html`` if the shell asset is missing, so the
    page is never blank. The classic view is also always at ``/classic``."""
    page = _UI_DIR / "os.html"
    if not page.is_file():
        page = _UI_DIR / "urban_os.html"
    try:
        return page.read_text(encoding="utf-8")
    except OSError as exc:  # missing/unreadable page asset — fail loudly, not blank
        raise HTTPException(status_code=500, detail="map UI asset unavailable") from exc


@app.get("/os", response_class=HTMLResponse)
def os_shell() -> FileResponse:
    """The forthcoming unified "Urban OS" shell page (built by another worker).

    ``/`` is intentionally left serving the CURRENT ``urban_os.html`` so the live
    demo never breaks mid-build; we flip ``/`` → ``os.html`` manually at the very
    end. Until ``os.html`` exists this 404s gracefully (rather than 500), so adding
    the route now is safe and purely additive."""
    page = _UI_DIR / "os.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="os shell not built yet")
    return FileResponse(page, media_type="text/html")


@app.get("/classic", response_class=HTMLResponse)
def classic() -> str:
    """The current Urban-OS map page under a stable path, so it stays reachable
    after ``/`` is later flipped to the new ``os.html`` shell."""
    page = _UI_DIR / "urban_os.html"
    try:
        return page.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="map UI asset unavailable") from exc


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(_OFFLINE_ASSETS / "favicon.png", media_type="image/png")


@app.get("/health")
def health() -> dict:
    sub = _scenario().substrate
    return {"status": "ok", "nodes": int(sub.n), "edges": int(sub.n_edges)}


@app.get("/scenario")
def scenario() -> dict:
    """The substrate the map draws: nodes (with lat/lng/capacity/sink) + edges
    (by node id) + scenario meta. Everything is native python (no numpy leakage)."""
    sc = _scenario()
    sub = sc.substrate
    nodes = [
        {
            "id": sub.ids[i],
            "label": sub.labels[i],
            "lat": _r(sub.lat[i], 6),
            "lng": _r(sub.lng[i], 6),
            "capacity": _r(sub.capacity[i], 1),
            "is_sink": bool(sub.is_sink[i]),
            # Map grouping: venue / fanzone / transit / exit — drives styling and
            # the FIFA fan-zone toggle in the UI.
            "group": NODE_GROUPS.get(sub.ids[i], "transit"),
        }
        for i in range(sub.n)
    ]
    edges = [
        {"src": sub.ids[int(sub.edge_src[e])], "dst": sub.ids[int(sub.edge_dst[e])]}
        for e in range(sub.n_edges)
    ]
    # The concurrent let-outs (the convergence crunch), each by venue node id so
    # the UI can label the multi-event scenario. ``crowd_size`` here is the TOTAL
    # injected across every event (≥ the primary venue's crowd).
    by_id = {sub.ids[i]: sub.labels[i] for i in range(sub.n)}
    events = [
        {
            "venue_id": vid,
            "label": by_id.get(vid, vid),
            "crowd_size": _r(crowd, 1),
            "event_end": _r(end, 1),
        }
        for vid, crowd, end in sc.events
    ]
    meta = {
        "venue_id": sc.venue_id,
        "crowd_size": _r(sc.total_crowd, 1),
        "event_end": _r(sc.event_end, 1),
        "horizon": int(sc.horizon),
        "events": events,
    }
    return {"nodes": nodes, "edges": edges, "meta": meta}


@app.get("/simulate")
def simulate(
    release_minutes: float = Query(0.0, ge=0.0, le=20.0),
    shelter_fraction: float = Query(0.0, ge=0.0, le=1.0),
    frame_every: int = Query(2, ge=1, le=60),
) -> dict:
    """Run the sim at the given staggered-release + shelter-coverage levers and
    return per-step frames (subsampled by ``frame_every`` to cap payload size) for
    the heatmap + slider, plus the J cost-breakdown.

    Exposing ``shelter_fraction`` here makes any ``(release, shelter)`` the
    optimizer evaluates reproducible on the map. Bounds are enforced declaratively
    by ``Query`` (out-of-range → 422). We add boundary guards: ``release_minutes``
    and ``shelter_fraction`` are rejected if not finite (a client can send
    ``=nan``, which satisfies neither ``ge`` nor ``le`` in some stacks, so we check
    explicitly), and ``frame_every`` is capped at the horizon so a large value
    still yields at least the first frame.
    """
    sc = _scenario()
    sub = sc.substrate

    release = float(release_minutes)
    if not math.isfinite(release):
        raise HTTPException(status_code=422, detail="release_minutes must be finite")
    shelter = float(shelter_fraction)
    if not math.isfinite(shelter):
        raise HTTPException(status_code=422, detail="shelter_fraction must be finite")
    # Never subsample coarser than the run length (always at least one frame).
    frame_every = min(int(frame_every), max(1, int(sc.horizon)))

    lenses = _lenses(sc)
    sim = Simulation(
        sub,
        lenses,
        params={"release_minutes": release, "shelter_fraction": shelter},
        dt=sc.dt,
    )
    try:
        result = sim.run(sc.horizon, frame_every=frame_every)
    except Exception as exc:  # kernel failure — surface a clean 500, no stack leak
        raise HTTPException(status_code=500, detail="simulation failed") from exc

    # Trim the dead timeline tail: the crowd fully drains well before the fixed
    # horizon, so the last ~40% of frames are all-zero padding that makes the
    # slider/playback span a window where nothing happens. We drop trailing frames
    # whose total node load is below a small epsilon, keeping a short "drained"
    # coda for a clean end. This touches ONLY the returned/displayed frame list —
    # the physics, the metrics series, and the peak readout (computed over every
    # step via ``result.peak``) are untouched. The peak frame is always retained.
    raw = result.frames
    peak_t = float(result.peak_congestion()["t"])
    _LOAD_EPS = 1.0  # total people on the network below this == "drained"
    _CODA = 2        # keep this many frames past the last active one
    last_active = -1
    for idx, fr in enumerate(raw):
        if float(np.sum(fr["load"])) >= _LOAD_EPS or float(fr["t"]) <= peak_t:
            last_active = idx
    if last_active < 0:  # degenerate: nothing ever active — keep frames as-is
        kept = list(range(len(raw)))
    else:
        kept = list(range(min(len(raw), last_active + 1 + _CODA)))

    frames = []
    for idx in kept:
        fr = raw[idx]
        cong = fr["congestion"]
        load = fr["load"]
        risk = fr["risk"]
        frames.append(
            {
                "t": _r(fr["t"], 1),
                "nodes": [
                    {
                        "id": sub.ids[i],
                        "load": _r(load[i], 1),
                        "congestion": _r(cong[i]),
                        "risk": _r(risk[i]),
                    }
                    for i in range(sub.n)
                ],
            }
        )

    metrics = {name: [_r(v) for v in series] for name, series in result.metrics.items()}
    peak = result.peak_congestion()
    peak = {
        "node": peak["node"],
        "label": peak["label"],
        "congestion": _r(peak["congestion"]),
        "t": _r(peak["t"], 1),
    }
    # J cost-breakdown for this exact (release, shelter) so the UI can show WHY a
    # run scores as it does and reconcile the heatmap with the optimizer's pick.
    breakdown = {k: _r(v, 2) for k, v in cost_breakdown(result, lenses).items()}
    return {
        "times": [_r(t, 1) for t in result.times],
        "frames": frames,
        "metrics": metrics,
        "peak": peak,
        "release_minutes": _r(release_minutes, 1),
        "shelter_fraction": _r(shelter, 2),
        "cost_breakdown": breakdown,
    }


@app.get("/lenses")
def lenses_endpoint(
    release_minutes: float = Query(0.0, ge=0.0, le=20.0),
    shelter_fraction: float = Query(0.0, ge=0.0, le=1.0),
) -> dict:
    """Run the FULL four-lens stack at the EXACT lever params and return the
    cross-domain costs (transit + safety + business + combined J) so the UI can
    animate every meter together as the slider moves — the demo's "one lever, every
    lens" live ripple.

    Fast by design: exactly TWO sims (the requested ``(release, shelter)`` plus a
    ``(0, 0)`` baseline) — never the optimizer grid. Bounds are enforced
    declaratively by ``Query`` (out-of-range → 422); we also reject non-finite
    levers explicitly (a client can send ``=nan``, which satisfies neither bound in
    some stacks)."""
    release = float(release_minutes)
    if not math.isfinite(release):
        raise HTTPException(status_code=422, detail="release_minutes must be finite")
    shelter = float(shelter_fraction)
    if not math.isfinite(shelter):
        raise HTTPException(status_code=422, detail="shelter_fraction must be finite")

    sc = _scenario()
    try:
        cur_stack = _four_lens_stack(sc)
        # Supplementary display lenses ride along in the SAME two sims so they cost
        # nothing extra; they are excluded from cur_J/base_J (those sum cur_stack /
        # base_stack only), so the headline numbers are unchanged (ADR: additive).
        extra = _extra_display_lenses(sc)
        current = Simulation(
            sc.substrate,
            cur_stack + extra,
            params={"release_minutes": release, "shelter_fraction": shelter},
            dt=sc.dt,
        ).run(sc.horizon)
        base_stack = _four_lens_stack(sc)
        baseline = Simulation(
            sc.substrate,
            base_stack + extra,
            params={"release_minutes": 0.0, "shelter_fraction": 0.0},
            dt=sc.dt,
        ).run(sc.horizon)
    except Exception as exc:  # kernel failure — clean 500, no stack leak
        raise HTTPException(status_code=500, detail="lens evaluation failed") from exc

    safety_lens = next(ln for ln in cur_stack if ln.name == "safety")
    cur_lost = float(sum(current.series("business_lost")))
    base_lost = float(sum(baseline.series("business_lost")))
    cur_J = _four_lens_J(cur_stack, current)
    base_J = _four_lens_J(base_stack, baseline)
    peak = current.peak_congestion()

    # Additive cross-domain benefit — computed by the shared ``_cross_domain_components``
    # helper that /optimize ALSO uses, so the live ripple and the optimizer's reveal
    # report the identical number at the same levers (contract-tested). It is the sum
    # of transit-J savings + civic-safety reduction + business recovered; labelled in
    # ``benefit_definitions`` as additive (not the conservative single-objective J).
    comp = _cross_domain_components(sc, release=release, shelter=shelter)

    return _native(
        {
            "release_minutes": _r(release, 1),
            "shelter_fraction": _r(shelter, 2),
            "transit": {
                "peak_label": peak["label"],
                "peak_congestion": _r(peak["congestion"]),
                "delay_cost": _r(sum(current.series("delay_cost")), 2),
            },
            "safety": {"cost": _r(safety_lens.cost(current), 2)},
            "business": {
                "lost": _r(cur_lost, 2),
                "recovered_vs_baseline": _r(base_lost - cur_lost, 2),
            },
            "combined_cost": _r(cur_J, 2),
            "baseline_combined": _r(base_J, 2),
            # Conservative single-objective: four-lens J avoided (no double-count).
            # Kept under the legacy ``combined_benefit`` key; see benefit_definitions.
            "combined_benefit": _r(base_J - cur_J, 2),
            # Canonical additive headline — shared with /optimize, labelled as additive.
            "cross_domain_benefit": _r(comp["total"], 2),
            "cross_domain_components": {k: _r(v, 2) for k, v in comp.items() if k != "total"},
            # Supplementary intelligence lenses (additive, display-only): each lens's
            # baseline/optimized/saved dollars + one natural-units metric, at these
            # exact levers. NOT part of combined_cost / cross_domain_benefit.
            "extra_lenses": _extra_lens_report(extra, baseline, current),
            "benefit_definitions": BENEFIT_DEFINITIONS,
        }
    )


@app.get("/overlays")
def overlays_endpoint() -> dict:
    """Per-node static intelligence overlays for the map's layer toggle: EMS-access
    criticality, civic Activity (the noise/livability grounding), and a do-nothing
    emissions hotspot. One cheap baseline sim; every field normalised 0..1 so the
    client can drive the heatmap weight directly. Static (lever-independent) by
    design — these are *where* each domain is exposed, not the live ripple."""
    sc = _scenario()
    extra = _extra_display_lenses(sc)
    stack = default_lens_stack(sc, weather=True) + extra
    try:
        res = Simulation(
            sc.substrate, stack,
            params={"release_minutes": 0.0, "shelter_fraction": 0.0}, dt=sc.dt,
        ).run(sc.horizon)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="overlay computation failed") from exc

    sub = sc.substrate
    ems = np.asarray(next(l for l in extra if l.name == "ems_access")._crit, dtype=float)
    resid = np.asarray(next(l for l in extra if l.name == "noise_livability")._res, dtype=float)
    # Emissions hotspot = peak over-capacity crowding per node (the field the lens
    # prices), derived from the recorded frame loads so /simulate stays untouched.
    emit = np.zeros(sub.n)
    for fr in res.frames:
        emit = np.maximum(emit, np.maximum(0.0, np.asarray(fr["load"]) - sub.capacity))

    def _norm(a):
        m = float(a.max())
        return a / m if m > 0 else a

    ems_n, resid_n, emit_n = _norm(ems), _norm(resid), _norm(emit)
    nodes = [
        {
            "id": sub.ids[i],
            "lat": float(sub.lat[i]),
            "lng": float(sub.lng[i]),
            "ems_access": _r(float(ems_n[i]), 3),
            "residential": _r(float(resid_n[i]), 3),
            "emissions": _r(float(emit_n[i]), 3),
        }
        for i in range(sub.n)
    ]
    return _native({"nodes": nodes})


@app.get("/optimize")
def optimize_endpoint(
    safety: bool = Query(True), business: bool = Query(True)
) -> dict:
    """Run the lever optimizer + the cited narrator and return everything the UI
    needs for the before/after panel (insight sentence, peaks, savings, levers).

    ``safety``/``business`` toggle whether each cross-domain lens counts toward the
    reported ``cross_domain_benefit`` (and appears in ``cross_domain``) — so the user
    picks which urban concerns to value. The core transit optimization is identical
    regardless; only the reported cross-domain benefit changes with the toggles.

    Two clearly-labelled benefit numbers (ADR-0019, see ``benefit_definitions``):
    ``j_avoided`` (the conservative single-objective J reduction = the narrator's net
    benefit) and ``cross_domain_benefit`` (the additive cross-domain framing)."""
    sc = _scenario()
    lenses = _lenses(sc)
    try:
        opt = optimize(sc.substrate, lenses, sc.horizon, dt=sc.dt)
        insight = build_insight(opt, event_end=sc.event_end)
    except Exception as exc:  # optimizer/narrator failure — clean 500, no stack leak
        raise HTTPException(status_code=500, detail="optimization failed") from exc
    best_breakdown = {k: _r(v, 2) for k, v in (opt.best_breakdown or {}).items()}
    baseline_breakdown = {k: _r(v, 2) for k, v in (opt.baseline_breakdown or {}).items()}
    return {
        "insight": insight.text,
        "grounded": bool(insight.grounded),
        "figures": _native(insight.figures),
        "optimization": _native(opt.to_dict()),
        "baseline_peak": _peak_dict(opt.baseline_result),
        "best_peak": _peak_dict(opt.best_result),
        "best_params": {k: _r(v, 3) for k, v in opt.best_params.items()},
        "savings": _r(opt.savings, 2),
        # Conservative single-objective headline (= ``savings``), explicitly named so
        # the UI can label it distinctly from the additive cross_domain_benefit below.
        "j_avoided": _r(opt.savings, 2),
        # Surface the J decomposition so the chosen (release, shelter) is
        # reproducible from on-screen dollar terms (delay/hold/exposure/staffing/
        # safety/total), not just the headline saving.
        "cost_breakdown": best_breakdown,
        "baseline_cost_breakdown": baseline_breakdown,
        # The same release, scored across the user-selected cross-domain lenses.
        **_cross_domain_block(sc, opt.best_params, safety, business),
        "benefit_definitions": BENEFIT_DEFINITIONS,
    }


@app.get("/flow")
def flow_endpoint() -> dict:
    """Optimal evacuation capacity of the substrate — the max crowd the capacitated
    network can drain to its exits over the egress window (a max-flow LP; ADR-0025).
    The *theoretical ceiling* the staggered-release sim approaches. Solved by cuOpt on
    GPU when enabled (``URBANOS_GPU_FLOW=1``), else networkx max-flow on CPU."""
    from urban_os.flow import optimal_evacuation_flow

    sc = _scenario()
    demands = {vid: crowd for vid, crowd, _ in sc.events}
    try:
        return _native(optimal_evacuation_flow(sc.substrate, demands, horizon=sc.horizon))
    except Exception as exc:  # never break the surface — clean 500, no stack leak
        raise HTTPException(status_code=500, detail="flow computation failed") from exc
