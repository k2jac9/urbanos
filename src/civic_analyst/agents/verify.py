"""Deterministic guards against LLM hallucination in the risk narrative.

The risk score and findings are computed WITHOUT an LLM. The model only proposes
a set of *claims*, each tied to a source-record tag (E1, E2, …). These functions
verify that every claim's number traces to the findings AND that its cited source
tag is a real evidence record — so a fabricated number or invented source can never
reach the user (we fall back to deterministic, correct-by-construction claims).
Maps to the Prime Intellect "Verifiers" bounty.

No import from subagents here (avoids a cycle); `findings` are duck-typed objects
exposing `.summary` (str) and `.evidence` (list[dict]).
"""
from __future__ import annotations

import re

from ..ingest.datasets import REGISTRY

EVIDENCE_CAP = 12  # max evidence rows surfaced per analysis (disclosed, never silent)


def classify_inspection(outcome) -> str:
    """A DineSafe outcome's severity: 'pass' | 'minor' (conditional) | 'severe'."""
    o = str(outcome or "").strip().lower()
    if not o or o == "pass":
        return "pass"
    if o.startswith("conditional"):
        return "minor"
    return "severe"  # Closed, Fail, Suspended, …


def risk_band(score: float) -> str:
    """Non-color risk label (mirrors the map's color thresholds)."""
    if score <= 0:
        return "none"
    if score < 0.34:
        return "low"
    if score < 0.67:
        return "medium"
    return "high"


def _ref(rec: dict) -> str:
    """Human-facing source-record id (strip the 'kind:' node prefix)."""
    return str(rec.get("id") or "").split(":", 1)[-1]


def unique_records(findings) -> dict[str, dict]:
    """All distinct records across findings, keyed by their (node) id."""
    out: dict[str, dict] = {}
    for f in findings:
        for rec in f.evidence:
            rid = rec.get("id")
            if rid is not None and rid not in out:
                out[rid] = rec
    return out


def evidence_total(findings) -> int:
    return len(unique_records(findings))


def evidence_index(
    findings, cap: int = EVIDENCE_CAP
) -> tuple[list[dict], dict[str, dict], dict[str, str]]:
    """Tag each distinct record E1, E2, … → (tagged list capped at `cap`,
    {tag: entry}, {node_id: tag}). The tags are the only valid `source` IDs a
    claim may cite; the node_id map lets a claim cite the specific row it used."""
    tagged: list[dict] = []
    tag_map: dict[str, dict] = {}
    id_to_tag: dict[str, str] = {}
    for rid, rec in unique_records(findings).items():
        if len(tagged) >= cap:
            break
        key = rec.get("dataset")
        entry = {
            "tag": f"E{len(tagged) + 1}",
            "dataset": REGISTRY[key].title if key in REGISTRY else (key or "?"),
            "kind": rec.get("kind", "record"),
            "detail": rec.get("outcome") or rec.get("status") or "",
            "ref": _ref(rec),
            "date": str(rec.get("date") or ""),
        }
        tagged.append(entry)
        tag_map[entry["tag"]] = entry
        id_to_tag[rid] = entry["tag"]
    return tagged, tag_map, id_to_tag


def _ints(s: str) -> set[int]:
    return {int(x) for x in re.findall(r"\d+", s or "")}


def source_tags(src) -> list[str]:
    """A claim may cite one tag ('E1'), several ('E1, E2'), or a list. Return them all."""
    if isinstance(src, list):
        items = src
    elif isinstance(src, str):
        items = re.split(r"[,\s]+", src.strip())
    else:
        return []
    return [t for t in (str(i).strip() for i in items) if t]


def _allowed_numbers(address: str, findings) -> set[int]:
    allowed = _ints(address)
    for f in findings:
        allowed |= _ints(f.summary)
        for rec in f.evidence:
            allowed |= _ints(str(rec.get("outcome", ""))) | _ints(str(rec.get("status", "")))
    return allowed


def verify_claims(claims, address: str, findings, valid_tags: set[str]) -> list[str]:
    """Return hallucination issues; empty means every claim checks out."""
    if not isinstance(claims, list) or not claims:
        return ["no claims produced"]
    allowed = _allowed_numbers(address, findings)
    issues: list[str] = []
    for c in claims:
        if not isinstance(c, dict) or not str(c.get("claim", "")).strip():
            issues.append("malformed claim")
            continue
        tags = source_tags(c.get("source"))
        if not tags or any(t not in valid_tags for t in tags):
            issues.append(f"unverified source id: {c.get('source')!r}")
        bad = {n for n in (_ints(str(c.get("claim"))) - allowed) if not 1900 <= n <= 2100}
        if bad:
            issues.append(f"unverified number(s): {sorted(bad)}")
    return issues


def _first_tag(evidence: list[dict], id_to_tag: dict[str, str]) -> str | None:
    for rec in evidence:
        tag = id_to_tag.get(rec.get("id"))
        if tag:
            return tag
    return None


def _recommendation(findings, id_to_tag: dict[str, str]) -> dict:
    """Conditional next-step, tied to the evidence that motivates it (not a constant)."""
    recs = unique_records(findings).values()
    open_permits = [r for r in recs
                    if r.get("kind") == "permit" and str(r.get("status", "")).lower() != "closed"]
    adverse = [r for r in recs
               if r.get("kind") == "inspection" and classify_inspection(r.get("outcome")) != "pass"]
    severe = [r for r in adverse if classify_inspection(r.get("outcome")) == "severe"]
    if severe:
        return {"claim": "Recommended action: an adverse food-safety inspection is on record"
                " — prioritize an on-site re-inspection.",
                "source": id_to_tag.get(severe[0].get("id"))}
    if open_permits or adverse:
        return {"claim": "Recommended action: schedule an on-site inspection to verify"
                " compliance.",
                "source": _first_tag(open_permits + adverse, id_to_tag)}
    return {"claim": "No open permits or adverse inspections on record — no action required.",
            "source": None}


def deterministic_claims(address: str, findings, tagged: list[dict],
                         id_to_tag: dict[str, str]) -> list[dict]:
    """Correct-by-construction claims (no LLM). Each claim is topic-specific and cites
    the kind of record that substantiates it — a permit claim points at a permit row, an
    inspection claim at an inspection row — so claims aren't all collapsed onto E1 (#4)."""
    recs = unique_records(findings)
    open_permits = [r for r in recs.values()
                    if r.get("kind") == "permit" and str(r.get("status", "")).lower() != "closed"]
    adverse = [r for r in recs.values()
               if r.get("kind") == "inspection" and classify_inspection(r.get("outcome")) != "pass"]

    claims = [{"claim": f"{len(recs)} linked record(s) for {address!r}.",
               "source": next(iter(id_to_tag.values()), None)}]
    if open_permits:
        claims.append({"claim": f"{len(open_permits)} open building permit(s).",
                       "source": id_to_tag.get(open_permits[0].get("id"))})
    if adverse:
        claims.append({"claim": f"{len(adverse)} adverse food-safety inspection(s).",
                       "source": id_to_tag.get(adverse[0].get("id"))})
    claims.append(_recommendation(findings, id_to_tag))
    return claims


def resolve_claims(claims, tag_map: dict[str, dict]) -> list[dict]:
    """Attach the first cited source record (or None) to each claim for display."""
    out = []
    for c in claims:
        tags = source_tags(c.get("source"))
        src = tag_map.get(tags[0]) if tags else None
        out.append({"text": str(c.get("claim")).strip(), "source": src})
    return out


def narrative_text(resolved_claims) -> str:
    return " ".join(c["text"] for c in resolved_claims)
