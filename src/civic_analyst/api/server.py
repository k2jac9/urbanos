"""FastAPI surface for the demo.

- GET /            map UI (Leaflet) — the demo centerpiece
- GET /addresses   geocoded addresses + fast risk scores (no LLM) for the pins
- GET /analyze     full agentic risk read for one address (Nemotron Nano)
- GET /digest      city-wide briefing (batch tier: gpt-oss-120B MoE)
- GET /health      load summary

The knowledge graph is built once at startup from pre-downloaded datasets
(scripts/download_data.py → DATA_DIR). If no data is present the graph stays empty
and the server still boots, so the API is safe to run offline.

Public-surface hardening (this app rides the public Tailscale Funnel that judges
hit, so it gets the same posture urban_os got in ADR-0006):
- no stack-trace leak — every endpoint body and an app-level handler turn an
  internal failure into a clean generic 500 with no internals;
- explicit, restrictive CORS — same-origin only (no wildcard) for a read-only demo;
- /digest is cheap+safe — the warm path serves the cached digest, and a process
  lock prevents concurrent public hits from stacking heavy batch-model runs.
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..agents.digest import city_digest, digest_cached
from ..agents.llm import interactive_llm
from ..agents.supervisor import Supervisor
from ..agents.verify import risk_band
from ..config import settings
from ..graph.builder import CivicGraph
from ..ingest.loader import load_into_graph

_STATIC = Path(__file__).parent / "static"
_graph = CivicGraph()
_supervisor = Supervisor(_graph)

# Serializes the heavy batch-model digest run: on a cold cache the public /digest
# would otherwise let every concurrent hit launch its own ~15s batch job (a cheap
# DoS amplifier). With this lock the first caller computes + caches the digest and
# everyone waiting behind it then reads the now-warm cache, so the batch model runs
# at most once per ranking regardless of how many public requests pile up.
_digest_lock = threading.Lock()


def _prewarm_model() -> None:
    """Best-effort: load the interactive model into memory at boot so the first
    real /analyze isn't paying the ~5s cold-load on the GX10. Silently no-ops when
    the endpoint/model is absent (CI, offline) — never blocks or fails startup."""
    try:
        interactive_llm().chat("Reply with OK.", "OK", temperature=0.0)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _graph.clear()  # reload cleanly on (re)startup; don't accumulate prior loads
    app.state.load_summary = load_into_graph(_graph, settings.data_dir)
    if settings.llm_prewarm:
        threading.Thread(target=_prewarm_model, daemon=True).start()
    yield


app = FastAPI(title="Toronto Civic Risk Analyst", version="0.1.0", lifespan=lifespan)

# Cross-origin requests are intentionally disallowed: this is a public, read-only
# demo served same-origin behind the Tailscale Funnel, so no browser other-origin
# needs it. Pinning an explicit, empty allow-list (never allow_origins=["*"]) makes
# the locked-down posture deliberate rather than an implicit default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],          # same-origin only — no cross-origin access
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=[],
)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all so an unexpected internal error becomes a generic 500 with no
    traceback or internals leaked to the public client (HTTPExceptions raised by
    handlers are still rendered with their own status/detail by FastAPI)."""
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# Vendored Leaflet (offline-safe) lives under static/vendor.
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    try:
        return (_STATIC / "map.html").read_text()
    except OSError as exc:  # missing/unreadable page asset — fail loudly, not blank
        raise HTTPException(status_code=500, detail="map UI asset unavailable") from exc


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(_STATIC / "favicon.png", media_type="image/png")


@app.get("/health")
def health() -> dict:
    # digest_cached() reflects whether a *real* city digest is already memoized for
    # the current ranking, so the demo can tell a warm /digest from a cold ~15s one.
    return {
        "status": "ok",
        "graph_nodes": len(_graph),
        "loaded": getattr(app.state, "load_summary", {}),
        "interactive_model": settings.llm_model,
        "batch_model": settings.llm_batch_model,
        "digest_cached": digest_cached(_ranked_addresses()),
    }


def _worst_axis(row: dict) -> float:
    """A single hottest-axis sort key WITHOUT blending the two indices: a site
    ranks by whichever axis is most elevated (ADR 0014). Used only for ordering,
    never surfaced as a public score."""
    return max(float(row.get("risk_safety", 0.0)), float(row.get("risk_activity", 0.0)))


def _ranked_addresses() -> list[dict]:
    """Addresses sorted hottest-first — the ranked set the digest summarizes. Ordered
    by the worse of the two axes (either elevated axis flags a site), not a blend."""
    return sorted(addresses(), key=_worst_axis, reverse=True)


@app.get("/addresses")
def addresses() -> list[dict]:
    """Geocoded addresses with fast (LLM-free) per-axis risk — drives the map pins.

    Returns BOTH indices and BOTH bands (safety + activity); the pin is colored by
    whichever axis is hottest (ADR 0014) — never a single blended score."""
    out = []
    for a in _graph.addresses(with_coords=True):
        scores = _supervisor.score_only(a["label"])
        out.append(
            {
                "label": a["label"],
                "lat": a["lat"],
                "lng": a["lng"],
                "risk_safety": scores["risk_safety"],
                "band_safety": risk_band(scores["risk_safety"]),
                "risk_activity": scores["risk_activity"],
                "band_activity": risk_band(scores["risk_activity"]),
            }
        )
    return out


@app.get("/analyze")
def analyze(address: str = Query(..., min_length=3, max_length=200)) -> dict:
    # A bogus/unknown address is a normal, found=False result (not an error). Only a
    # genuine internal failure reaches the except, and it must not leak a traceback.
    try:
        return _supervisor.analyze(address).to_dict()
    except HTTPException:
        raise
    except Exception as exc:  # internal failure → clean 500, no stack-trace leak
        raise HTTPException(status_code=500, detail="analysis failed") from exc


@app.get("/digest")
def digest() -> dict:
    # The ranked set is deterministic from the (startup-loaded) graph; computing it
    # is cheap and LLM-free, so we always return the freshly ranked list.
    try:
        ranked = _ranked_addresses()
        # Warm path: a real digest for this exact ranking is already memoized, so
        # serve it WITHOUT taking the batch lock or re-running the model.
        if digest_cached(ranked):
            return {"digest": city_digest(ranked), "ranked": ranked}
        # Cold path: serialize the heavy batch run so concurrent public hits can't
        # stack ~15s batch-model jobs. Re-check the cache inside the lock — a request
        # that waited here while another warmed it just reads the now-warm result.
        with _digest_lock:
            return {"digest": city_digest(ranked), "ranked": ranked}
    except HTTPException:
        raise
    except Exception as exc:  # internal failure → clean 500, no stack-trace leak
        raise HTTPException(status_code=500, detail="digest failed") from exc
