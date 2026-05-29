"""Guard the shipped synthetic fixtures so `make demo` always works."""
from pathlib import Path

from civic_analyst.agents.subagents import RiskNarratorAgent
from civic_analyst.agents.supervisor import Supervisor
from civic_analyst.graph.builder import CivicGraph
from civic_analyst.ingest.loader import load_into_graph

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

    hot = sup.analyze("100 Queen St W")   # 2 open permits + 2 failed inspections
    cold = sup.analyze("55 John St")      # closed permit + passing inspection

    # Graded score (#6): 2 open (0.5) + 2 severe (2.0) -> 1-exp(-0.35*5) = 0.826, "high".
    assert hot.risk_score == 0.826 and hot.risk_band == "high"
    assert cold.risk_score == 0.0 and cold.risk_band == "none"
    assert hot.found and hot.matched_address
    # 2 permits + 2 inspections + 1 request + 1 licence all link to the hot address
    assert graph.records_for("100 Queen St W") and len(graph.records_for("100 Queen St W")) == 6
