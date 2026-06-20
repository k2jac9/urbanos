from urbanos.risk.agents.subagents import RiskNarratorAgent
from urbanos.risk.agents.supervisor import Supervisor
from urbanos.risk.graph.builder import CivicGraph


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

    # Two independent indices (ADR 0014): 1 open permit + 1 SEVERE ("Fail") visit.
    # Activity = 1-exp(-0.06) = 0.058 (low); Safety = 1-exp(-0.45*1.0) = 0.362 (medium).
    assert report.risk_activity == 0.058 and report.band_activity == "low"
    assert report.risk_safety == 0.362 and report.band_safety == "medium"
    assert report.address == "1 Demo St"
    # The narrative is the deterministic two-line read (safety + construction).
    assert "Food safety" in report.narrative and "Construction activity" in report.narrative
    assert len(report.findings) == 2


def test_clean_address_has_zero_risk():
    g = CivicGraph()
    report = Supervisor(g, narrator=_StubNarrator()).analyze("2 Empty Ave")
    assert report.risk_safety == 0 and report.risk_activity == 0
    assert report.band_safety == "none" and report.band_activity == "none"
