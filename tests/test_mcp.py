"""Test the MCP tool logic directly (no MCP runtime needed)."""
from pathlib import Path

from civic_analyst import mcp_server
from civic_analyst.graph.builder import normalize_address

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_list_datasets_includes_permits():
    keys = {d["key"] for d in mcp_server.list_datasets()}
    assert {"permits", "dinesafe", "311", "licences"} <= keys


def test_tools_operate_on_loaded_graph():
    summary = mcp_server.load(FIXTURES)
    assert summary["dinesafe"] == 4

    ranked = mcp_server.top_risk(limit=3)
    assert normalize_address(ranked[0]["address"]) == normalize_address("100 Queen St W")
    assert ranked[0]["risk_score"] == 1.0

    report = mcp_server.analyze_address("100 Queen St W")
    assert report["risk_score"] == 1.0
