"""Supervisor agent: orchestrates sub-agents and composes the risk verdict.

Mirrors the NVIDIA DGX Spark playbook pattern (a supervisor coordinating
specialized sub-agents). Deterministic orchestration here; the reasoning is
delegated to the local model inside RiskNarratorAgent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..graph.builder import CivicGraph
from .subagents import ComplianceAgent, Finding, RetrievalAgent, RiskNarratorAgent
from .verify import evidence_index, evidence_total, narrative_text, risk_band


@dataclass
class RiskReport:
    address: str               # the query as asked
    found: bool                # did the address resolve to a known record? (#2)
    matched_address: str | None  # canonical label that matched (echo for the analyst)
    risk_score: float          # 0..1, graded by count + severity (#6)
    risk_band: str             # none | low | medium | high (non-color cue, #10)
    narrative: str             # joined claim text (display / back-compat)
    findings: list[dict]
    evidence: list[dict]       # tagged source records, capped (#3); see evidence_total
    evidence_total: int        # true number of distinct records before the cap (#3)
    claims: list[dict]         # [{text, source: {tag,dataset,kind,detail,ref,date}|None}]

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
        claims = self.narrator.claims(address, findings)
        tagged, _, _ = evidence_index(findings)
        return RiskReport(
            address=address,
            found=self.graph.has_address(address),
            matched_address=self.graph.matched_label(address),
            risk_score=risk,
            risk_band=risk_band(risk),
            narrative=narrative_text(claims),
            findings=[
                {"agent": f.agent, "summary": f.summary, "score": f.score}
                for f in findings
            ],
            evidence=tagged,
            evidence_total=evidence_total(findings),
            claims=claims,
        )
