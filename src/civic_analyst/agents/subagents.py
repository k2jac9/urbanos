"""Specialized sub-agents. Each does one job over the knowledge graph.

These are deliberately thin: deterministic signal-gathering + a focused LLM call.
The supervisor (supervisor.py) routes to them and composes the final answer.
"""
from __future__ import annotations

from dataclasses import dataclass

import json
import math

from ..graph.builder import CivicGraph
from .llm import LocalLLM, interactive_llm
from .verify import (
    classify_inspection,
    deterministic_claims,
    evidence_index,
    narrative_text,
    resolve_claims,
    verify_claims,
)

# Severity weights for the graded risk score (#6): an open permit is a mild signal,
# a conditional-pass inspection moderate, a failed/closed inspection serious. The
# score is a smooth saturating function of total weight, so 1 vs 12 issues differ.
_W_OPEN_PERMIT = 0.5
_W_MINOR_INSPECTION = 0.8
_W_SEVERE_INSPECTION = 2.0
_RISK_K = 0.35


def graded_score(open_permits: int, minor: int, severe: int) -> float:
    weight = (_W_OPEN_PERMIT * open_permits + _W_MINOR_INSPECTION * minor
              + _W_SEVERE_INSPECTION * severe)
    return round(1.0 - math.exp(-_RISK_K * weight), 3)


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
    """Flags open building permits and adverse food-safety inspections — kept as two
    distinct signals (a DineSafe conditional pass is NOT a permit infraction)."""

    name = "compliance"

    def run(self, graph: CivicGraph, address: str) -> Finding:
        permits = graph.records_for(address, kind="permit")
        inspections = graph.records_for(address, kind="inspection")
        open_permits = [p for p in permits if str(p.get("status", "")).lower() != "closed"]
        adverse = [i for i in inspections if classify_inspection(i.get("outcome")) != "pass"]
        minor = [i for i in adverse if classify_inspection(i.get("outcome")) == "minor"]
        severe = [i for i in adverse if classify_inspection(i.get("outcome")) == "severe"]
        return Finding(
            agent=self.name,
            summary=(f"{len(open_permits)} open permit(s); "
                     f"{len(adverse)} adverse inspection(s)."),
            evidence=open_permits + adverse,
            score=graded_score(len(open_permits), len(minor), len(severe)),
        )


class RiskNarratorAgent:
    """Turns the structured findings into a plain-language risk read + action.

    This is where the local model earns its keep: reasoning over heterogeneous
    municipal records and drafting an inspector-ready rationale, fully on-device.
    """

    name = "risk_narrator"
    SYSTEM = (
        "You are a municipal risk analyst. You are given Evidence items, each with a "
        "tag (E1, E2, …), and deterministic Findings. Output ONLY a JSON array of 2-4 "
        "objects, each exactly {\"claim\": \"<one sentence>\", \"source\": \"<one "
        "evidence tag, e.g. E1>\"}. Every claim must be supported by the cited "
        "evidence item. Use only numbers that appear in the Findings; never invent "
        "numbers, sources, or tags. Output the JSON array and nothing else."
    )

    def __init__(self, llm: LocalLLM | None = None) -> None:
        self.llm = llm or interactive_llm()

    @staticmethod
    def _parse_json_array(raw: str) -> list:
        """Extract the first JSON array from the model output; raise on failure."""
        start, end = raw.find("["), raw.rfind("]")
        if start == -1 or end <= start:
            raise ValueError("no JSON array in output")
        parsed = json.loads(raw[start : end + 1])
        if not isinstance(parsed, list):
            raise ValueError("not a JSON array")
        return parsed

    def claims(self, address: str, findings: list[Finding]) -> list[dict]:
        """Verified, per-claim assessment. Each claim is tied to a real source
        record; any claim with an invented number or unknown source tag causes a
        fall back to deterministic claims (so output is always source-backed)."""
        tagged, tag_map, id_to_tag = evidence_index(findings)
        valid_tags = {t["tag"] for t in tagged}
        ev = "\n".join(
            f"{t['tag']} [{t['dataset']}] {t['kind']}" + (f": {t['detail']}" if t["detail"] else "")
            for t in tagged
        ) or "(no records)"
        bullets = "\n".join(f"- {f.summary}" for f in findings)
        user = f"Address: {address}\nEvidence:\n{ev}\nFindings:\n{bullets}"
        try:
            parsed = self._parse_json_array(self.llm.chat(self.SYSTEM, user, temperature=0.0))
        except Exception:  # offline / malformed output
            parsed = None
        if parsed is None or verify_claims(parsed, address, findings, valid_tags):
            parsed = deterministic_claims(address, findings, tagged, id_to_tag)
        return resolve_claims(parsed, tag_map)

    def run(self, address: str, findings: list[Finding]) -> str:
        """Joined narrative text (CLI / back-compat)."""
        return narrative_text(self.claims(address, findings))
