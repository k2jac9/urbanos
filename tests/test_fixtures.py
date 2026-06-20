"""Guard the shipped synthetic fixtures so `make demo` always works."""
from pathlib import Path

from urbanos.risk.agents.subagents import RiskNarratorAgent
from urbanos.risk.agents.supervisor import Supervisor
from urbanos.risk.graph.builder import CivicGraph
from urbanos.risk.ingest.loader import load_into_graph

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class _StubNarrator(RiskNarratorAgent):
    def __init__(self):
        pass

    def claims(self, address, findings):
        return [{"text": "stub", "source": None}]


def test_fixtures_load_across_all_datasets():
    graph = CivicGraph()
    summary = load_into_graph(graph, FIXTURES)
    assert summary == {"permits": 4, "dinesafe": 4, "311": 2, "licences": 3}


def test_demo_address_is_high_risk_and_clean_address_is_low():
    graph = CivicGraph()
    load_into_graph(graph, FIXTURES)
    sup = Supervisor(graph, narrator=_StubNarrator())

    hot = sup.analyze("100 Queen St W")   # 2 open permits + 2 failed inspection visits
    cold = sup.analyze("55 John St")      # closed permit + passing inspection

    # Two-index model (ADR 0014): construction activity and food safety are SEPARATE.
    # Activity = 1-exp(-0.06*2) = 0.113 (low). Safety is severity-weighted: 2 SEVERE
    # ("Fail") visits weigh 1.0 each → 1-exp(-0.45*2.0) = 0.593 (medium), unchanged.
    assert hot.risk_activity == 0.113 and hot.band_activity == "low"
    assert hot.risk_safety == 0.593 and hot.band_safety == "medium"
    assert cold.risk_safety == 0.0 and cold.band_safety == "none"
    assert cold.risk_activity == 0.0 and cold.band_activity == "none"
    assert hot.found and hot.matched_address
    # 2 permits + 2 inspections + 1 request + 1 licence all link to the hot address
    assert graph.records_for("100 Queen St W") and len(graph.records_for("100 Queen St W")) == 6
