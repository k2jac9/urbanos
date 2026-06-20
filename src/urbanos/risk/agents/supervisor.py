"""Supervisor agent: orchestrates sub-agents and composes the risk verdict.

Mirrors the NVIDIA DGX Spark playbook pattern (a supervisor coordinating
specialized sub-agents). Deterministic orchestration here; the reasoning is
delegated to the local model inside RiskNarratorAgent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..graph.builder import CivicGraph
from .subagents import ComplianceAgent, Finding, RetrievalAgent, RiskNarratorAgent
from .verify import (
    compliance_counts,
    evidence_index,
    evidence_total,
    risk_band,
    two_line_narrative,
)


@dataclass
class RiskReport:
    address: str               # the query as asked
    found: bool                # did the address resolve to a known record? (#2)
    matched_address: str | None  # canonical label that matched (echo for the analyst)
    # Two INDEPENDENT indices (ADR 0014) — never blended into one public score.
    risk_safety: float         # 0..1, food-safety axis (adverse inspection visits)
    band_safety: str           # none | low | medium | high (non-color cue, #10)
    risk_activity: float       # 0..1, construction axis (open building permits)
    band_activity: str         # none | low | medium | high
    narrative: str             # two-line deterministic read (safety + construction)
    findings: list[dict]
    evidence: list[dict]       # tagged source records, capped (#3); see evidence_total
    evidence_total: int        # true number of distinct records before the cap (#3)
    claims: list[dict]         # [{text, source: {tag,dataset,kind,detail,ref,date}|None}]

    def to_dict(self) -> dict:
        return asdict(self)


def _axis_scores(findings: list[Finding]) -> tuple[float, float]:
    """The two independent axis scores for a set of findings: each is the max over
    the findings' per-axis contribution (a single finding carries the signal today,
    but max keeps this correct if signals ever split across agents). The axes are
    NEVER summed — that's the whole point of the two-index model (ADR 0014)."""
    safety = round(max((f.risk_safety for f in findings), default=0.0), 3)
    activity = round(max((f.risk_activity for f in findings), default=0.0), 3)
    return safety, activity


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

    def score_only(self, address: str) -> dict:
        """Fast per-axis risk scores with no LLM call — used to color every map pin.

        Returns BOTH indices ({risk_safety, risk_activity}); a site is flagged if
        EITHER axis is elevated, so callers that need a single sort key take the
        max locally (we never reintroduce a blended public score)."""
        safety, activity = _axis_scores(self._findings(address))
        return {"risk_safety": safety, "risk_activity": activity}

    def analyze(self, address: str) -> RiskReport:
        findings = self._findings(address)
        safety, activity = _axis_scores(findings)
        minor_visits, severe_visits, open_permits = compliance_counts(findings)
        claims = self.narrator.claims(address, findings)
        tagged, _, _ = evidence_index(findings)
        return RiskReport(
            address=address,
            found=self.graph.has_address(address),
            matched_address=self.graph.matched_label(address),
            risk_safety=safety,
            band_safety=risk_band(safety),
            risk_activity=activity,
            band_activity=risk_band(activity),
            narrative=two_line_narrative(minor_visits, severe_visits, open_permits),
            findings=[
                {"agent": f.agent, "summary": f.summary,
                 "risk_safety": f.risk_safety, "risk_activity": f.risk_activity}
                for f in findings
            ],
            evidence=tagged,
            evidence_total=evidence_total(findings),
            claims=claims,
        )
