"""Specialized sub-agents. Each does one job over the knowledge graph.

These are deliberately thin: deterministic signal-gathering + a focused LLM call.
The supervisor (supervisor.py) routes to them and composes the final answer.
"""
from __future__ import annotations

from dataclasses import dataclass

import json

from ..graph.builder import CivicGraph
from .llm import LocalLLM, interactive_llm
from .verify import (
    activity_index,
    classify_inspection,
    deterministic_claims,
    evidence_index,
    narrative_text,
    resolve_claims,
    safety_index,
    verify_claims,
)


@dataclass
class Finding:
    agent: str
    summary: str
    evidence: list[dict]
    # Two independent risk indices (ADR 0014). Construction-permit activity and
    # food-safety inspections are NEVER summed into one number — they answer
    # different questions, so each carries its own 0..1 index. Most findings
    # (e.g. retrieval) contribute 0 to both.
    risk_safety: float = 0.0
    risk_activity: float = 0.0


class RetrievalAgent:
    """Pulls every graph record attached to an address."""

    name = "retrieval"

    def run(self, graph: CivicGraph, address: str) -> Finding:
        records = graph.records_for(address)
        return Finding(
            agent=self.name,
            summary=f"{len(records)} linked records for {address!r}.",
            evidence=records,
        )


class ComplianceAgent:
    """Computes the two independent risk signals: a construction *activity* index from
    open building permits and a food-safety index from adverse inspection visits. The
    two are kept distinct (a DineSafe conditional pass is NOT a permit infraction) and
    are never blended into one score (ADR 0014)."""

    name = "compliance"

    def run(self, graph: CivicGraph, address: str) -> Finding:
        permits = graph.records_for(address, kind="permit")
        inspections = graph.records_for(address, kind="inspection")
        open_permits = [p for p in permits if str(p.get("status", "")).lower() != "closed"]
        # `inspections` are already de-duped to one record per VISIT by the loader
        # (ADR 0013), so each non-pass visit counts once toward the safety index.
        flagged = [i for i in inspections if classify_inspection(i.get("outcome")) != "pass"]
        minor = [i for i in flagged if classify_inspection(i.get("outcome")) == "minor"]
        severe = [i for i in flagged if classify_inspection(i.get("outcome")) == "severe"]
        # Prose honesty (#3a): "adverse" names SEVERE outcomes only (fail/closed/
        # conviction); a Conditional Pass is a minor follow-up, reported as such.
        # The safety index is SEVERITY-WEIGHTED (ADR 0014 §6): minors weigh 0.3, severe
        # 1.0 — so a Conditional-only address reads LOW, not a saturated MEDIUM.
        parts = [f"{len(open_permits)} open permit(s)"]
        if minor:
            parts.append(f"{len(minor)} Conditional Pass visit(s)")
        parts.append(f"{len(severe)} adverse inspection(s)")
        return Finding(
            agent=self.name,
            summary="; ".join(parts) + ".",
            evidence=open_permits + flagged,
            risk_safety=safety_index(len(minor), len(severe)),
            risk_activity=activity_index(len(open_permits)),
        )


class RiskNarratorAgent:
    """Turns the structured findings into a plain-language risk read + action.

    This is where the local model earns its keep: reasoning over heterogeneous
    municipal records and drafting an inspector-ready rationale, fully on-device.
    """

    name = "risk_narrator"
    SYSTEM = (
        "You are a municipal risk analyst briefing a city inspector. You are given "
        "Evidence items — each with a tag (E1, E2, …), its source dataset, record type, "
        "and status/outcome — plus deterministic Findings. Output ONLY a JSON array of "
        "2-4 objects, each exactly {\"claim\": \"<one sentence>\", \"source\": \"<one "
        "evidence tag, e.g. E1>\"}.\n"
        "Write each claim as a clear, plain-language sentence an inspector can act on: "
        "name the dataset or record type behind it and what it implies on the ground "
        "(an open building permit means active construction to verify on site; a DineSafe "
        "Conditional Pass means a food-safety re-check is due). Prefer concrete, useful "
        "wording over bare counts like 'X are present'. Cite the one evidence tag that "
        "best backs the claim.\n"
        "Style example (numbers/tags are illustrative — use the real ones): "
        "{\"claim\": \"8 open building permits indicate active construction here that "
        "should be checked against approved scope.\", \"source\": \"E4\"}, "
        "{\"claim\": \"A DineSafe Conditional Pass means this food premises has an "
        "unresolved health item flagged for follow-up.\", \"source\": \"E2\"}.\n"
        "Hard rules (a claim that breaks any of these is discarded): every claim must be "
        "supported by its cited evidence item, and the cited tag's record type must match "
        "what the claim is about (cite a permit row for a permit claim, an inspection row "
        "for an inspection claim); cite exactly one real tag from the list; and use ONLY "
        "numbers that literally appear in the Findings — never invent, estimate, total, "
        "or round numbers, and never invent sources, tags, dates, or dataset names. "
        "Output the JSON array and nothing else."
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
        ev = "\n".join(
            f"{t['tag']}: {t['dataset']} — {t['kind']} record"
            + (f", status/outcome '{t['detail']}'" if t["detail"] else "")
            + (f" ({t['date']})" if t.get("date") else "")
            for t in tagged
        ) or "(no records)"
        bullets = "\n".join(f"- {f.summary}" for f in findings)
        user = (
            f"Address: {address}\n"
            f"Evidence (cite one tag per claim; these are the only valid sources):\n{ev}\n"
            f"Findings (the ONLY numbers you may use):\n{bullets}"
        )
        try:
            parsed = self._parse_json_array(self.llm.chat(self.SYSTEM, user, temperature=0.0))
        except Exception:  # offline / malformed output
            parsed = None
        # Pass the tag_map (not just the tag set) so the guard also enforces
        # record-KIND matching — a permit claim must cite a permit row (ADR-0020).
        if parsed is None or verify_claims(parsed, address, findings, tag_map):
            parsed = deterministic_claims(address, findings, tagged, id_to_tag)
        return resolve_claims(parsed, tag_map)

    def run(self, address: str, findings: list[Finding]) -> str:
        """Joined narrative text (CLI / back-compat)."""
        return narrative_text(self.claims(address, findings))
