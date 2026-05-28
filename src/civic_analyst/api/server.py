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

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse

from ..agents.digest import city_digest
from ..agents.supervisor import Supervisor
from ..config import settings
from ..graph.builder import CivicGraph
from ..ingest.loader import load_into_graph

_STATIC = Path(__file__).parent / "static"
_graph = CivicGraph()
_supervisor = Supervisor(_graph)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.load_summary = load_into_graph(_graph, settings.data_dir)
    yield


app = FastAPI(title="Toronto Civic Risk Analyst", version="0.1.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC / "map.html").read_text()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "graph_nodes": len(_graph),
        "loaded": getattr(app.state, "load_summary", {}),
    }


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
    ranked = sorted(addresses(), key=lambda r: r["risk_score"], reverse=True)
    return {"digest": city_digest(ranked), "ranked": ranked}
