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

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from urban_os.adapters import downtown_scenario
from urban_os.kernel import Simulation
from urban_os.lenses import EconomicLens, EventSurge
from urban_os.narrate import build_insight
from urban_os.optimize import optimize

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
    """The two-lens stack the kernel/optimizer/narrator run against."""
    return [
        EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
        EconomicLens(),
    ]


def _r(x: float, places: int = 3) -> float:
    """Round to keep the payload small; always returns a native float."""
    return round(float(x), places)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_UI_DIR / "urban_os.html").read_text()


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
    frame_every: int = Query(2, ge=1, le=60),
) -> dict:
    """Run the sim at the given staggered-release lever and return per-step frames
    (subsampled by ``frame_every`` to cap payload size) for the heatmap + slider."""
    sc = _scenario()
    sub = sc.substrate
    lenses = _lenses(sc)
    sim = Simulation(
        sub, lenses, params={"release_minutes": float(release_minutes)}, dt=sc.dt
    )
    result = sim.run(sc.horizon, frame_every=frame_every)

    frames = []
    for fr in result.frames:
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
    return {
        "times": [_r(t, 1) for t in result.times],
        "frames": frames,
        "metrics": metrics,
        "peak": peak,
        "release_minutes": _r(release_minutes, 1),
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
    opt = optimize(sc.substrate, lenses, sc.horizon, dt=sc.dt)
    insight = build_insight(opt, event_end=sc.event_end)
    return {
        "insight": insight.text,
        "grounded": bool(insight.grounded),
        "figures": insight.figures,
        "optimization": opt.to_dict(),
        "baseline_peak": _peak_dict(opt.baseline_result),
        "best_peak": _peak_dict(opt.best_result),
        "best_params": {k: _r(v, 3) for k, v in opt.best_params.items()},
        "savings": _r(opt.savings, 2),
    }
