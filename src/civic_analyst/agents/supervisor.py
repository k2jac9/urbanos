"""Supervisor agent: orchestrates sub-agents and composes the risk verdict.

Mirrors the NVIDIA DGX Spark playbook pattern (a supervisor coordinating
specialized sub-agents). Deterministic orchestration here; the reasoning is
delegated to the local model inside RiskNarratorAgent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..graph.builder import CivicGraph
from .subagents import ComplianceAgent, Finding, RetrievalAgent, RiskNarratorAgent


@dataclass
class RiskReport:
    address: str
    risk_score: float          # 0..1
    narrative: str
    findings: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


class Supervisor:
    def __init__(self, graph: CivicGraph, narrator: RiskNarratorAgent | None = None) -> None:
        self.graph = graph
        self.retrieval = RetrievalAgent()
        self.compliance = ComplianceAgent()
        self.narrator = narrator or RiskNarratorAgent()

    def _findings(self, address: str) -> list[Finding]:
        return [
            self.retrieval.run(self.graph, address),
            self.compliance.run(self.graph, address),
        ]

    def score_only(self, address: str) -> float:
        """Fast risk score with no LLM call — used to color every map pin."""
        return round(min(1.0, sum(f.score for f in self._findings(address))), 3)

    def analyze(self, address: str) -> RiskReport:
        findings = self._findings(address)
        risk = round(min(1.0, sum(f.score for f in findings)), 3)
        narrative = self.narrator.run(address, findings)
        return RiskReport(
            address=address,
            risk_score=risk,
            narrative=narrative,
            findings=[
                {"agent": f.agent, "summary": f.summary, "score": f.score}
                for f in findings
            ],
        )
