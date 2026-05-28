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


def evidence_index(findings, cap: int = 12) -> tuple[list[dict], dict[str, dict]]:
    """Tag each real record E1, E2, … → (tagged list, {tag: record}). The tags are
    the only valid `source` IDs a claim may cite."""
    seen: set = set()
    tagged: list[dict] = []
    tag_map: dict[str, dict] = {}
    for f in findings:
        for rec in f.evidence:
            rid = rec.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            key = rec.get("dataset")
            entry = {
                "tag": f"E{len(tagged) + 1}",
                "dataset": REGISTRY[key].title if key in REGISTRY else (key or "?"),
                "kind": rec.get("kind", "record"),
                "detail": rec.get("outcome") or rec.get("status") or "",
            }
            tagged.append(entry)
            tag_map[entry["tag"]] = entry
            if len(tagged) >= cap:
                return tagged, tag_map
    return tagged, tag_map


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


def deterministic_claims(address: str, findings, tagged: list[dict]) -> list[dict]:
    """Correct-by-construction claims (no LLM): finding summaries, each tied to a
    real evidence tag when one exists."""
    first = tagged[0]["tag"] if tagged else None
    claims = [{"claim": f.summary, "source": first} for f in findings]
    claims.append(
        {"claim": "Recommended action: schedule an on-site inspection to verify compliance.",
         "source": None}
    )
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
