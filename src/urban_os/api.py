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
from functools import lru_cache
from pathlib import Path

import numpy as np

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from urban_os.adapters import downtown_scenario
from urban_os.kernel import Simulation
from urban_os.lenses import EconomicLens, EventSurge, WeatherLens
from urban_os.narrate import build_insight
from urban_os.optimize import cost_breakdown, optimize

# Our own page + the proven offline assets (vendored MapLibre/PMTiles + basemap).
_HERE = Path(__file__).parent
_UI_DIR = _HERE / "static"
_OFFLINE_ASSETS = (
    Path(__file__).resolve().parents[1] / "civic_analyst" / "api" / "static"
)

app = FastAPI(title="Urban-OS", version="0.1.0")

# Serve vendored maplibre-gl.js/.css, pmtiles.js and toronto.pmtiles fully offline.
app.mount("/static", StaticFiles(directory=_OFFLINE_ASSETS), name="static")


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
        EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
        EconomicLens(),
        WeatherLens(
            peak_time=sc.event_end,
            intensity=0.7,
            width=20.0,
            crowd_size=sc.crowd_size,
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
    page = _UI_DIR / "urban_os.html"
    try:
        return page.read_text(encoding="utf-8")
    except OSError as exc:  # missing/unreadable page asset — fail loudly, not blank
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
        }
        for i in range(sub.n)
    ]
    edges = [
        {"src": sub.ids[int(sub.edge_src[e])], "dst": sub.ids[int(sub.edge_dst[e])]}
        for e in range(sub.n_edges)
    ]
    meta = {
        "venue_id": sc.venue_id,
        "crowd_size": _r(sc.crowd_size, 1),
        "event_end": _r(sc.event_end, 1),
        "horizon": int(sc.horizon),
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


def _peak_dict(result) -> dict:
    p = result.peak_congestion()
    return {
        "node": p["node"],
        "label": p["label"],
        "congestion": _r(p["congestion"]),
        "t": _r(p["t"], 1),
    }


@app.get("/optimize")
def optimize_endpoint() -> dict:
    """Run the lever optimizer + the cited narrator and return everything the UI
    needs for the before/after panel (insight sentence, peaks, savings, levers)."""
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
    }
