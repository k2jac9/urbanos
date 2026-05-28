"""MCP server exposing Toronto civic data + the risk engine as tools.

This lets an agent runtime (NemoClaw/OpenClaw, Claude, etc.) reach our datasets
and risk analysis over MCP instead of a bespoke client — the pattern the NYC
edition winner used. The `mcp` import is lazy so the tool logic stays importable
(and unit-testable) without the package installed.

Run (stdio transport):  python -m civic_analyst.mcp_server
"""
from __future__ import annotations

from pathlib import Path

from .agents.supervisor import Supervisor
from .config import settings
from .graph.builder import CivicGraph
from .ingest.ckan import CKANClient
from .ingest.datasets import REGISTRY
from .ingest.loader import load_into_graph

_graph = CivicGraph()
_supervisor = Supervisor(_graph)


def load(data_dir: Path | None = None) -> dict[str, int]:
    """Populate the shared graph from pre-downloaded data."""
    return load_into_graph(_graph, data_dir or settings.data_dir)


# --- Tool implementations (plain functions; registered with MCP in build_server) ---

def list_datasets() -> list[dict]:
    """List the Toronto open datasets this server can query."""
    return [
        {"key": k, "title": d.title, "cadence": d.cadence, "geo": d.geo, "slug": d.slug}
        for k, d in REGISTRY.items()
    ]


def dataset_resources(key: str) -> list[dict]:
    """List downloadable resources (CSV/JSON/...) for a dataset by registry key."""
    ds = REGISTRY[key]  # KeyError if unknown — surfaced to the caller
    with CKANClient() as ckan:
        return [
            {"name": r.get("name"), "format": r.get("format"), "url": r.get("url")}
            for r in ckan.resources(ds.slug)
        ]


def analyze_address(address: str) -> dict:
    """Full agentic risk read for one Toronto address."""
    return _supervisor.analyze(address).to_dict()


def top_risk(limit: int = 10) -> list[dict]:
    """Highest-risk geocoded addresses currently loaded (LLM-free scoring)."""
    scored = [
        {
            "address": a["label"],
            "lat": a["lat"],
            "lng": a["lng"],
            "risk_score": _supervisor.score_only(a["label"]),
        }
        for a in _graph.addresses(with_coords=True)
    ]
    return sorted(scored, key=lambda r: r["risk_score"], reverse=True)[:limit]


def build_server():
    """Build the FastMCP server (imports `mcp` lazily)."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("toronto-civic")
    for fn in (list_datasets, dataset_resources, analyze_address, top_risk):
        server.tool()(fn)
    return server


def main() -> None:
    load()
    build_server().run()


if __name__ == "__main__":
    main()
