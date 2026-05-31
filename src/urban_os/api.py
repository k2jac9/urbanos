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

import math
import numbers
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from urban_os.adapters import civic_safety_by_node, downtown_scenario
from urban_os.adapters.toronto import NODE_GROUPS
from urban_os.kernel import Simulation
from urban_os.lenses import (
    BusinessFlow,
    EconomicLens,
    EventSurge,
    SafetyLens,
    WeatherLens,
)
from urban_os.narrate import build_insight
from urban_os.optimize import cost_breakdown, objective, optimize

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
    """Run civic_analyst's data-graph load under THIS (parent) app.

    GOTCHA: a mounted sub-app's ``lifespan`` does NOT reliably run when the parent
    app starts up under this Starlette version, so ``/civic/addresses`` would serve
    an empty graph (civic only loads its module-global ``_graph`` from inside its
    own lifespan). We reproduce civic's lifespan load here: clear the graph and
    re-run ``load_into_graph`` into the SAME module-global ``_graph`` the mounted
    sub-app's routes read. Best-effort and offline-safe — if no data is present the
    graph stays empty and the server still boots (civic's own contract)."""
    try:
        _civic_server._graph.clear()  # reload cleanly; never accumulate prior loads
        summary = _civic_server.load_into_graph(
            _civic_server._graph, _civic_server.settings.data_dir
        )
        # Mirror civic's lifespan side effect so /civic/health reports its load.
        civic_app.state.load_summary = summary
    except Exception:
        # Loading civic data must never block Urban-OS startup (offline invariant).
        pass


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
    """The three-lens stack the kernel/optimizer/narrator run against.

    Order matters: WeatherLens.couple multiplies the standing ``risk`` field, so
    it must run AFTER EconomicLens has populated it (see ADR-0007). The rain cell
    peaks with the egress wave (``peak_time = event_end``) so its drainage tax +
    crush-risk bonus land while the crowd is on the platforms. It contributes a
    second optimizer lever (shelter coverage) which the grid search composes with
    EventSurge's staggered release automatically.
    """
    return [
        EventSurge(events=sc.events),
        EconomicLens(),
        WeatherLens(
            peak_time=sc.event_end,
            intensity=0.7,
            width=20.0,
            crowd_size=sc.total_crowd,
        ),
    ]


def _r(x: float, places: int = 3) -> float:
    """Round to keep the payload small; always returns a native float.

    Coerces numpy scalars to a native ``float`` (numpy scalars are NOT
    JSON-serializable — this is the boundary that guarantees no numpy leaks into
    a response). Non-finite values (NaN/±inf) are clamped to ``0.0`` so a
    degenerate field can never produce an invalid JSON token (``NaN``/``Infinity``
    are not legal JSON and would break strict parsers in the browser).
    """
    v = float(x)
    if not math.isfinite(v):
        return 0.0
    return round(v, places)


def _native(obj):
    """Recursively coerce a (possibly numpy-laced) structure to native Python.

    ``optimize.OptResult.to_dict()`` carries lever values straight off an
    ``np.arange`` grid, so its ``params``/``trials`` hold ``numpy.float64``
    scalars. Those happen to JSON-encode today (numpy floats subclass ``float``)
    but still violate the "no numpy leakage at the boundary" invariant and would
    break a stricter encoder. We can't touch ``optimize.py`` (other workstreams
    own it), so we sanitize its blob here. Non-finite floats are clamped to 0.0
    to keep the JSON strictly valid.
    """
    if isinstance(obj, dict):
        return {k: _native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_native(v) for v in obj]
    if isinstance(obj, bool):  # bool before int/float (bool is an int subclass)
        return bool(obj)
    if isinstance(obj, np.bool_):  # numpy bool is NOT a python bool/Integral
        return bool(obj)
    if isinstance(obj, numbers.Integral):
        return int(obj)
    if isinstance(obj, numbers.Real):
        f = float(obj)
        return f if math.isfinite(f) else 0.0
    return obj  # str / None / already-native pass through unchanged


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


def _four_lens_stack(sc):
    """The full four-lens stack (transit + economic + civic safety + business),
    same composition ``_cross_domain`` uses. SafetyLens is made literal by the
    civic-risk → node fusion; BusinessFlow scores retail around the primary venue."""
    return [
        EventSurge(events=sc.events),
        EconomicLens(),
        SafetyLens(civic_safety_by_node(sc.substrate)),
        BusinessFlow(sc.venue_id),
    ]


def _four_lens_J(stack, result) -> float:
    """Objective J of a four-lens run = the sum of every lens's cost (the same
    additive objective the optimizer minimises). Native float, no numpy leak."""
    return float(sum(float(ln.cost(result)) for ln in stack))


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
        current = Simulation(
            sc.substrate,
            cur_stack,
            params={"release_minutes": release, "shelter_fraction": shelter},
            dt=sc.dt,
        ).run(sc.horizon)
        base_stack = _four_lens_stack(sc)
        baseline = Simulation(
            sc.substrate,
            base_stack,
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

    # Additive cross-domain benefit — the SAME composition /optimize reports as its
    # headline "combined_benefit": 3-lens transit-J savings (the WeatherLens/shelter
    # stack the optimizer searches) + civic-safety reduction + business recovered.
    # The UI's combined counter ticks to THIS so the live ripple and the optimizer's
    # reveal agree on one number (two more sims; still no grid search).
    t_cur_stack, t_base_stack = _lenses(sc), _lenses(sc)
    t_cur = Simulation(sc.substrate, t_cur_stack,
        params={"release_minutes": release, "shelter_fraction": shelter}, dt=sc.dt).run(sc.horizon)
    t_base = Simulation(sc.substrate, t_base_stack,
        params={"release_minutes": 0.0, "shelter_fraction": 0.0}, dt=sc.dt).run(sc.horizon)
    transit_savings = objective(t_base, t_base_stack) - objective(t_cur, t_cur_stack)
    safety_reduction = float(safety_lens.cost(baseline)) - float(safety_lens.cost(current))
    cross_domain_benefit = transit_savings + safety_reduction + (base_lost - cur_lost)

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
            # Single-objective J avoided (the conservative, no-double-count number).
            "combined_benefit": _r(base_J - cur_J, 2),
            # Additive cross-domain benefit (matches /optimize's headline ~$458k) —
            # what the shell's combined-$ counter displays.
            "cross_domain_benefit": _r(cross_domain_benefit, 2),
        }
    )


def _peak_dict(result) -> dict:
    p = result.peak_congestion()
    return {
        "node": p["node"],
        "label": p["label"],
        "congestion": _r(p["congestion"]),
        "t": _r(p["t"], 1),
    }


def _cross_domain(sc, best_params: dict) -> dict:
    """Impact of the *same* optimized release on the other two lenses — computed
    separately so the optimizer + J breakdown above are untouched (no headline
    change). Honest framing: the release the optimizer picked also does this for
    public safety + local business. Two cheap extra sims (baseline vs best); never
    re-runs the lever search.
    """
    stack = [
        EventSurge(events=sc.events),
        EconomicLens(),
        SafetyLens(civic_safety_by_node(sc.substrate)),  # civic risk → node field
        BusinessFlow(sc.venue_id),                       # retail around the primary venue
    ]
    safety = next(ln for ln in stack if ln.name == "safety")
    base = Simulation(sc.substrate, stack, params={"release_minutes": 0.0}, dt=sc.dt).run(sc.horizon)
    best = Simulation(sc.substrate, stack, params=dict(best_params), dt=sc.dt).run(sc.horizon)
    base_lost = float(sum(base.series("business_lost")))
    best_lost = float(sum(best.series("business_lost")))
    return {
        "safety": {"baseline": _r(safety.cost(base), 0), "best": _r(safety.cost(best), 0)},
        "business": {"baseline_lost": _r(base_lost, 0), "recovered": _r(base_lost - best_lost, 0)},
    }


@app.get("/optimize")
def optimize_endpoint(
    safety: bool = Query(True), business: bool = Query(True)
) -> dict:
    """Run the lever optimizer + the cited narrator and return everything the UI
    needs for the before/after panel (insight sentence, peaks, savings, levers).

    ``safety``/``business`` toggle whether each cross-domain lens counts toward the
    reported ``combined_benefit`` (and appears in ``cross_domain``) — so the user
    picks which urban concerns to value. The core transit optimization is identical
    regardless; only the reported combined benefit changes with the toggles."""
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
        # Surface the J decomposition so the chosen (release, shelter) is
        # reproducible from on-screen dollar terms (delay/hold/exposure/staffing/
        # safety/total), not just the headline saving.
        "cost_breakdown": best_breakdown,
        "baseline_cost_breakdown": baseline_breakdown,
        # The same release, scored across the user-selected cross-domain lenses.
        **_cross_domain_block(sc, opt.best_params, opt.savings, safety, business),
    }


def _cross_domain_safe(sc, best_params: dict):
    """Never let the cross-domain extras break the core /optimize response."""
    try:
        return _cross_domain(sc, best_params)
    except Exception:
        return None


def _cross_domain_block(sc, best_params: dict, savings: float,
                        safety: bool, business: bool) -> dict:
    """Cross-domain panel data filtered by the user's lens toggles, plus the
    combined benefit = transit savings + the ENABLED lenses' contributions. The
    user turning a lens off literally removes its dollars from the combined J."""
    full = _cross_domain_safe(sc, best_params)
    combined = float(savings)
    cd = None
    if full:
        cd = {}
        if safety and full.get("safety"):
            cd["safety"] = full["safety"]
            combined += full["safety"]["baseline"] - full["safety"]["best"]
        if business and full.get("business"):
            cd["business"] = full["business"]
            combined += full["business"]["recovered"]
    return {
        "cross_domain": cd,
        "enabled": {"safety": bool(safety), "business": bool(business)},
        "combined_benefit": _r(combined, 2),
    }
