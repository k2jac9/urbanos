from civic_analyst.agents.subagents import RiskNarratorAgent
from civic_analyst.agents.supervisor import Supervisor
from civic_analyst.graph.builder import CivicGraph


class _StubNarrator(RiskNarratorAgent):
    """Avoid needing a live local model in CI."""

    def __init__(self):
        pass

    def claims(self, address, findings):
        return [{"text": f"stub narrative for {address} ({len(findings)} findings)", "source": None}]


def test_supervisor_scores_open_permit_and_infraction():
    g = CivicGraph()
    g.add_record("permit", "P1", "1 Demo St", status="open")
    g.add_record("inspection", "I1", "1 Demo St", outcome="Fail")

    report = Supervisor(g, narrator=_StubNarrator()).analyze("1 Demo St")

    assert report.risk_score > 0
    assert report.address == "1 Demo St"
    assert "stub narrative" in report.narrative
    assert len(report.findings) == 2


def test_clean_address_has_zero_risk():
    g = CivicGraph()
    report = Supervisor(g, narrator=_StubNarrator()).analyze("2 Empty Ave")
    assert report.risk_score == 0
