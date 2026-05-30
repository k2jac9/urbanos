"""FastAPI surface for the demo.

- GET /            map UI (Leaflet) — the demo centerpiece
- GET /addresses   geocoded addresses + fast risk scores (no LLM) for the pins
- GET /analyze     full agentic risk read for one address (Nemotron Nano)
- GET /digest      city-wide briefing (batch tier: gpt-oss-120B MoE)
- GET /health      load summary

The knowledge graph is built once at startup from pre-downloaded datasets
(scripts/download_data.py → DATA_DIR). If no data is present the graph stays empty
and the server still boots, so the API is safe to run offline.
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from ..agents.digest import city_digest, digest_cached
from ..agents.llm import interactive_llm
from ..agents.supervisor import Supervisor
from ..config import settings
from ..graph.builder import CivicGraph
from ..ingest.loader import load_into_graph

_STATIC = Path(__file__).parent / "static"
_graph = CivicGraph()
_supervisor = Supervisor(_graph)


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

# Vendored Leaflet (offline-safe) lives under static/vendor.
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC / "map.html").read_text()


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


def _ranked_addresses() -> list[dict]:
    """Addresses sorted hottest-first — the ranked set the digest summarizes."""
    return sorted(addresses(), key=lambda r: r["risk_score"], reverse=True)


@app.get("/addresses")
def addresses() -> list[dict]:
    """Geocoded addresses with a fast (LLM-free) risk score — drives the map pins."""
    out = []
    for a in _graph.addresses(with_coords=True):
        out.append(
            {
                "label": a["label"],
                "lat": a["lat"],
                "lng": a["lng"],
                "risk_score": _supervisor.score_only(a["label"]),
            }
        )
    return out


@app.get("/analyze")
def analyze(address: str = Query(..., min_length=3, max_length=200)) -> dict:
    return _supervisor.analyze(address).to_dict()


@app.get("/digest")
def digest() -> dict:
    ranked = _ranked_addresses()
    return {"digest": city_digest(ranked), "ranked": ranked}
