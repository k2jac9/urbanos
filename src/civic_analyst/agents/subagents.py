"""Specialized sub-agents. Each does one job over the knowledge graph.

These are deliberately thin: deterministic signal-gathering + a focused LLM call.
The supervisor (supervisor.py) routes to them and composes the final answer.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..graph.builder import CivicGraph
from .llm import LocalLLM, interactive_llm


@dataclass
class Finding:
    agent: str
    summary: str
    evidence: list[dict]
    score: float  # 0..1 risk contribution


class RetrievalAgent:
    """Pulls every graph record attached to an address."""

    name = "retrieval"

    def run(self, graph: CivicGraph, address: str) -> Finding:
        records = graph.records_for(address)
        return Finding(
            agent=self.name,
            summary=f"{len(records)} linked records for {address!r}.",
            evidence=records,
            score=0.0,
        )


class ComplianceAgent:
    """Flags open permits and recent inspection infractions."""

    name = "compliance"

    def run(self, graph: CivicGraph, address: str) -> Finding:
        permits = graph.records_for(address, kind="permit")
        inspections = graph.records_for(address, kind="inspection")
        open_permits = [p for p in permits if str(p.get("status", "")).lower() != "closed"]
        infractions = [i for i in inspections if i.get("outcome") not in (None, "Pass")]
        score = min(1.0, 0.2 * len(open_permits) + 0.3 * len(infractions))
        return Finding(
            agent=self.name,
            summary=f"{len(open_permits)} open permit(s), {len(infractions)} infraction(s).",
            evidence=open_permits + infractions,
            score=score,
        )


class RiskNarratorAgent:
    """Turns the structured findings into a plain-language risk read + action.

    This is where the local model earns its keep: reasoning over heterogeneous
    municipal records and drafting an inspector-ready rationale, fully on-device.
    """

    name = "risk_narrator"
    SYSTEM = (
        "You are a municipal risk analyst. Given structured findings about a Toronto "
        "address, write a 3-sentence risk assessment and one concrete recommended action. "
        "Cite the dataset behind each claim. Be precise; do not invent records."
    )

    def __init__(self, llm: LocalLLM | None = None) -> None:
        self.llm = llm or interactive_llm()

    def run(self, address: str, findings: list[Finding]) -> str:
        bullets = "\n".join(f"- [{f.agent}] {f.summary}" for f in findings)
        user = f"Address: {address}\nFindings:\n{bullets}"
        try:
            return self.llm.chat(self.SYSTEM, user)
        except Exception as exc:  # offline / no model: deterministic fallback
            return f"(LLM unavailable: {exc})\nFindings:\n{bullets}"
