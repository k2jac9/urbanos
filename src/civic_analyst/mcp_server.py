"""MCP server exposing Toronto civic data + the risk engine as tools.

This lets an agent runtime (NemoClaw/OpenClaw, Claude, etc.) reach our datasets
and risk analysis over MCP instead of a bespoke client — the pattern the NYC
edition winner used. The `mcp` import is lazy so the tool logic stays importable
(and unit-testable) without the package installed.

Every tool validates its input at the boundary and degrades gracefully: when the
model or a remote dataset is unavailable the tools return structured fallbacks
rather than crashing the runtime (the demo is offline-first).

Run (stdio transport):  python -m civic_analyst.mcp_server
"""
from __future__ import annotations

from pathlib import Path

from .agents.digest import city_digest as _city_digest
from .agents.supervisor import Supervisor
from .agents.verify import risk_band
from .config import settings
from .graph.builder import CivicGraph
from .ingest.ckan import CKANClient
from .ingest.datasets import REGISTRY
from .ingest.loader import load_into_graph

_graph = CivicGraph()
_supervisor = Supervisor(_graph)

# A defensible upper bound so a caller can't ask the server to sort/serialize an
# unbounded result set (and so a bad/huge `limit` is clamped, not honored).
MAX_LIMIT = 500


def load(data_dir: Path | None = None) -> dict[str, int]:
    """Populate the shared graph from pre-downloaded data.

    Idempotent: clears the process-global graph first so a reload *replaces*
    rather than accumulates. Without this, calling load() twice doubles every
    edge (MultiDiGraph allows parallels), drifting risk scores upward — a real
    bug for any client that reloads, and a source of test-order fragility.
    """
    _graph.clear()
    return load_into_graph(_graph, data_dir or settings.data_dir)


# --- Input validation helpers (boundary guards) ---

def _require_address(address: object) -> str:
    """Coerce/validate a free-text address argument from an untrusted caller."""
    if not isinstance(address, str):
        raise ValueError("address must be a string")
    cleaned = address.strip()
    if not cleaned:
        raise ValueError("address must be a non-empty string")
    if len(cleaned) > 200:
        raise ValueError("address is too long (max 200 chars)")
    return cleaned


def _clamp_limit(limit: object, default: int = 10) -> int:
    """Validate + clamp a list-length argument to a sane [1, MAX_LIMIT] range."""
    if limit is None:
        return default
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return min(limit, MAX_LIMIT)


def _require_dataset_key(key: object) -> str:
    """Validate a registry key against the known dataset set."""
    if not isinstance(key, str) or not key.strip():
        raise ValueError("key must be a non-empty string")
    cleaned = key.strip()
    if cleaned not in REGISTRY:
        known = ", ".join(sorted(REGISTRY))
        raise ValueError(f"unknown dataset key {cleaned!r}; known keys: {known}")
    return cleaned


# --- Tool implementations (plain functions; registered with MCP in build_server) ---

def list_datasets() -> list[dict]:
    """List the Toronto open datasets this server can query."""
    return [
        {"key": k, "title": d.title, "cadence": d.cadence, "geo": d.geo, "slug": d.slug}
        for k, d in REGISTRY.items()
    ]


def dataset_resources(key: str) -> list[dict]:
    """List downloadable resources (CSV/JSON/...) for a dataset by registry key.

    Validates the key against the registry; on a network error (offline demo)
    returns an empty list rather than raising into the runtime.
    """
    ds = REGISTRY[_require_dataset_key(key)]
    try:
        with CKANClient() as ckan:
            return [
                {"name": r.get("name"), "format": r.get("format"), "url": r.get("url")}
                for r in ckan.resources(ds.slug)
            ]
    except Exception:  # offline / CKAN unreachable — degrade, don't crash
        return []


def analyze_address(address: str) -> dict:
    """Full agentic risk read for one Toronto address.

    Validates the address at the boundary. The narrator already falls back to
    deterministic claims when the model is unavailable, so this never crashes on
    a missing LLM — only on a genuinely malformed argument.
    """
    return _supervisor.analyze(_require_address(address)).to_dict()


def top_risk(limit: int = 10) -> list[dict]:
    """Highest-risk geocoded addresses currently loaded (LLM-free scoring).

    Each row carries BOTH independent indices (safety + activity) and their bands
    (ADR 0014). Ranking is by whichever axis is hottest — either elevated axis flags
    a site — never a blended score."""
    n = _clamp_limit(limit)
    scored = []
    for a in _graph.addresses(with_coords=True):
        s = _supervisor.score_only(a["label"])
        scored.append({
            "address": a["label"],
            "lat": a["lat"],
            "lng": a["lng"],
            "risk_safety": s["risk_safety"],
            "band_safety": risk_band(s["risk_safety"]),
            "risk_activity": s["risk_activity"],
            "band_activity": risk_band(s["risk_activity"]),
        })
    scored.sort(key=lambda r: max(r["risk_safety"], r["risk_activity"]), reverse=True)
    return scored[:n]


def city_digest(limit: int = 25) -> str:
    """Plain-language city-wide risk briefing over the top-N risky addresses.

    Uses the batch model; the digest helper already degrades to a deterministic
    summary when no model is reachable, so this is offline-safe.
    """
    return _city_digest(top_risk(limit=_clamp_limit(limit, default=25)))


def build_server():
    """Build the FastMCP server (imports `mcp` lazily)."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("toronto-civic")
    for fn in (list_datasets, dataset_resources, analyze_address, top_risk, city_digest):
        server.tool()(fn)
    return server


def main() -> None:
    load()
    build_server().run()


if __name__ == "__main__":
    main()
