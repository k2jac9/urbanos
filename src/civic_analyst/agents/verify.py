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

import math
import re

from ..ingest.datasets import REGISTRY

EVIDENCE_CAP = 12  # max evidence rows surfaced per analysis (disclosed, never silent)

# Two-index scoring (ADR 0014). Construction activity and food safety are SEPARATE
# axes — a busy permit address and a failed-inspection address are different problems,
# so we never blend them into one number. Each is a smooth saturating function of its
# own signal, then read through the shared `risk_band` thresholds independently.
_ACTIVITY_K = 0.06  # open permits → activity index
_SAFETY_K = 0.45    # severity-weighted adverse VISITS → safety index

# Section-6 severity weights for the safety index. Counting a gentle Conditional Pass
# as a full adverse visit saturates the score: unweighted, 1 visit → 1-exp(-0.45) =
# 0.362 ≥ 0.34 = MEDIUM, so NO integer count can land in LOW (a structurally dead
# band). Down-weighting minors restores a real gradient: a Conditional Pass is a
# routine follow-up (0.3), a Fail/Closed/conviction is enforcement-grade (1.0).
_W_MINOR_VISIT = 0.3
_W_SEVERE_VISIT = 1.0

# Shared risk-band cutoffs (ADR 0014). A score in [0, _BAND_LOW) reads "low",
# [_BAND_LOW, _BAND_HIGH) "medium", and >= _BAND_HIGH "high" (0 is "none"). These are
# the SINGLE documented source for the bands: the map's pin colors in
# src/civic_analyst/api/static/map.html (the `bandOf` helper and the circle-color
# `step` stops) MUST mirror these exact cutoffs — update both together.
_BAND_LOW = 0.34
_BAND_HIGH = 0.67


def activity_index(open_permits: int) -> float:
    """Construction-activity index from the count of open building permits."""
    return round(1.0 - math.exp(-_ACTIVITY_K * max(0, open_permits)), 3)


def safety_index(minor_visits: int, severe_visits: int) -> float:
    """Food-safety index from a SEVERITY-WEIGHTED sum of adverse inspection visits
    (ADR 0014 §6). Conditional-Pass (minor) visits weigh 0.3, Fail/Closed/conviction
    (severe) visits weigh 1.0 — so a Conditional-only address reads LOW while a real
    enforcement site stands out. Visits are already de-duped one-per-visit (ADR 0013)."""
    weight = _W_MINOR_VISIT * max(0, minor_visits) + _W_SEVERE_VISIT * max(0, severe_visits)
    return round(1.0 - math.exp(-_SAFETY_K * weight), 3)


def classify_inspection(outcome) -> str:
    """A DineSafe outcome's severity: 'pass' | 'minor' (conditional) | 'severe'."""
    o = str(outcome or "").strip().lower()
    if not o or o == "pass":
        return "pass"
    if o.startswith("conditional"):
        return "minor"
    return "severe"  # Closed, Fail, Suspended, …


def partition_inspections(inspections) -> dict[str, list[dict]]:
    """Classify each inspection record ONCE and bucket it by severity.

    Returns {"pass": [...], "minor": [...], "severe": [...]} so callers don't
    re-run classify_inspection 3-4x over the same records. ``flagged`` (minor +
    severe) is the non-pass set used by the safety index and recommendations."""
    parts: dict[str, list[dict]] = {"pass": [], "minor": [], "severe": []}
    for rec in inspections:
        parts[classify_inspection(rec.get("outcome"))].append(rec)
    return parts


def risk_band(score: float) -> str:
    """Non-color risk label (mirrors the map's color thresholds)."""
    if score <= 0:
        return "none"
    if score < _BAND_LOW:
        return "low"
    if score < _BAND_HIGH:
        return "medium"
    return "high"


# Per-axis qualitative words for the two-line narrative (ADR 0014 §8). The bands map
# to plain words so a non-color reader gets the gist; the two axes use their own
# vocabulary (safety reads clear/moderate/elevated, activity low/moderate/elevated).
_SAFETY_WORD = {"none": "clear", "low": "moderate", "medium": "moderate", "high": "elevated"}
_ACTIVITY_WORD = {"none": "low", "low": "low", "medium": "moderate", "high": "elevated"}


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def two_line_narrative(minor_visits: int, severe_visits: int, open_permits: int) -> str:
    """Deterministic two-line risk read (ADR 0014 §8): one Safety line, one
    Construction line. Every figure traces straight to the visit/permit counts —
    no LLM, so it can never hallucinate a number. The Safety line keeps severity
    honest: it names the total adverse visits and breaks out the severe ones."""
    adverse = minor_visits + severe_visits
    sb = _SAFETY_WORD[risk_band(safety_index(minor_visits, severe_visits))]
    ab = _ACTIVITY_WORD[risk_band(activity_index(open_permits))]
    severe_note = f" ({severe_visits} severe)" if severe_visits else ""
    safety = (f"Food safety — {sb}. "
              + _plural(adverse, "inspection visit") + severe_note + " of concern.")
    construction = (f"Construction activity — {ab}. "
                    + _plural(open_permits, "open permit") + ".")
    return safety + " " + construction


def compliance_counts(findings) -> tuple[int, int, int]:
    """(minor_visits, severe_visits, open_permits) across a report's findings — the
    raw counts that drive both indices and the two-line narrative. Reads the same
    de-duped evidence records the indices are computed from, so the prose and the
    scores can never disagree. Severity is classified per visit (ADR 0013)."""
    recs = unique_records(findings).values()
    open_permits = sum(
        1 for r in recs
        if r.get("kind") == "permit" and str(r.get("status", "")).lower() != "closed"
    )
    parts = partition_inspections(r for r in recs if r.get("kind") == "inspection")
    return len(parts["minor"]), len(parts["severe"]), open_permits


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


def _coverage_order(records: dict[str, dict]) -> list[tuple[str, dict]]:
    """Order records so the first row of each distinct kind leads, then the rest in
    original order. Ensures the evidence cap never silently hides an entire dataset:
    at least one row of every kind (permit / inspection / licence) always survives,
    so a fused address shows all its datasets, not just the most numerous (#3)."""
    head: list[tuple[str, dict]] = []
    tail: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for rid, rec in records.items():
        kind = rec.get("kind", "record")
        (head if kind not in seen else tail).append((rid, rec))
        seen.add(kind)
    return head + tail


def evidence_index(
    findings, cap: int = EVIDENCE_CAP
) -> tuple[list[dict], dict[str, dict], dict[str, str]]:
    """Tag each distinct record E1, E2, … → (tagged list capped at `cap`,
    {tag: entry}, {node_id: tag}). The tags are the only valid `source` IDs a
    claim may cite; the node_id map lets a claim cite the specific row it used."""
    tagged: list[dict] = []
    tag_map: dict[str, dict] = {}
    id_to_tag: dict[str, str] = {}
    for rid, rec in _coverage_order(unique_records(findings)):
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


# ADR-0020: a "number" is an integer OR a decimal (optionally with a fractional
# part). We keep decimals intact (``2.5``) rather than splitting them into ``{2, 5}``
# — the digit-run flaw ADR-0010 fixed in urban_os/narrate, now back-ported here so a
# claim like "risk rose 2.5x" can't smuggle ``2.5`` past a whitelist of ``{2, 5}``.
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _canon(val: float) -> str:
    """Canonical string for a number so int/float compare on value, not rendering
    (``2.0`` -> ``"2"``, ``"2.50"`` -> ``"2.5"``)."""
    if not math.isfinite(val):
        return "nan"
    if float(val).is_integer():
        return str(int(val))
    return repr(round(float(val), 6)).rstrip("0").rstrip(".")


def _nums(s: str) -> set[str]:
    """Canonical numeric tokens in ``s`` (decimals preserved, not split)."""
    out: set[str] = set()
    for tok in _NUM_RE.findall(s or ""):
        try:
            out.add(_canon(float(tok)))
        except ValueError:  # pragma: no cover - regex guarantees parseability
            continue
    return out


def _is_year(tok: str) -> bool:
    """Years are descriptive context, not findings — exempt 1900..2100 (as ADR-0010)."""
    try:
        v = float(tok)
    except ValueError:  # pragma: no cover
        return False
    return v.is_integer() and 1900 <= v <= 2100


# Keyword → record kind, for checking a claim cites the RIGHT TYPE of evidence
# (ADR-0020): the system prompt already demands "the cited tag's record type must
# match what the claim is about"; this enforces it in code so an inspection claim
# can't cite a permit row and slip through.
_CLAIM_KIND_HINTS: dict[str, tuple[str, ...]] = {
    "permit": ("permit", "construction", "building", "demolition", "renovation", "scope"),
    "inspection": (
        "inspection", "dinesafe", "food", "health", "conditional pass", "fail",
        "closed", "infraction", "re-check", "recheck", "premises", "violation",
    ),
    "licence": ("licence", "license", "business licen"),
}


def _claim_kind(text: str) -> str | None:
    """The single record kind a claim is unambiguously about, else None.

    Conservative on purpose: if a claim's wording matches zero kinds, or more than
    one, we return None and skip kind-matching for it — we reject mis-citations, not
    merely ambiguous phrasings."""
    t = (text or "").lower()
    hits = {kind for kind, kws in _CLAIM_KIND_HINTS.items() if any(k in t for k in kws)}
    return next(iter(hits)) if len(hits) == 1 else None


def source_tags(src) -> list[str]:
    """A claim may cite one tag ('E1'), several ('E1, E2'), or a list. Return them all."""
    if isinstance(src, list):
        items = src
    elif isinstance(src, str):
        items = re.split(r"[,\s]+", src.strip())
    else:
        return []
    return [t for t in (str(i).strip() for i in items) if t]


def _allowed_numbers(address: str, findings) -> set[str]:
    allowed = _nums(address)
    for f in findings:
        allowed |= _nums(f.summary)
        for rec in f.evidence:
            allowed |= _nums(str(rec.get("outcome", ""))) | _nums(str(rec.get("status", "")))
    return allowed


def verify_claims(claims, address: str, findings, tags) -> list[str]:
    """Return hallucination issues; empty means every claim checks out.

    ``tags`` may be either a ``tag_map`` (dict ``{tag: entry}``) — which enables
    record-KIND matching (a permit claim must cite a permit row, etc., per ADR-0020)
    — or a bare set of valid tag strings (back-compat: tag-existence + numbers only).
    """
    if not isinstance(claims, list) or not claims:
        return ["no claims produced"]
    if isinstance(tags, dict):
        valid_tags = set(tags)
        tag_kind = {t: (e or {}).get("kind") for t, e in tags.items()}
    else:
        valid_tags = set(tags)
        tag_kind = {}
    allowed = _allowed_numbers(address, findings)
    issues: list[str] = []
    for c in claims:
        if not isinstance(c, dict) or not str(c.get("claim", "")).strip():
            issues.append("malformed claim")
            continue
        ctags = source_tags(c.get("source"))
        if not ctags or any(t not in valid_tags for t in ctags):
            issues.append(f"unverified source id: {c.get('source')!r}")
        bad = {n for n in (_nums(str(c.get("claim"))) - allowed) if not _is_year(n)}
        if bad:
            issues.append(f"unverified number(s): {sorted(bad)}")
        # Kind-matching: the cited tag's record type must match the claim's topic.
        if tag_kind:
            kind = _claim_kind(str(c.get("claim")))
            cited_kinds = {tag_kind.get(t) for t in ctags if t in valid_tags}
            cited_kinds.discard(None)
            if kind and cited_kinds and kind not in cited_kinds:
                issues.append(
                    f"source kind mismatch: claim about {kind} cites {sorted(cited_kinds)}"
                )
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
    parts = partition_inspections(r for r in recs if r.get("kind") == "inspection")
    severe = parts["severe"]
    flagged = parts["minor"] + severe
    if severe:
        return {"claim": "Recommended action: an adverse food-safety inspection is on record"
                " — prioritize an on-site re-inspection.",
                "source": id_to_tag.get(severe[0].get("id"))}
    if open_permits or flagged:
        return {"claim": "Recommended action: schedule an on-site inspection to verify"
                " compliance.",
                "source": _first_tag(open_permits + flagged, id_to_tag)}
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
    parts = partition_inspections(r for r in recs.values() if r.get("kind") == "inspection")
    minor = parts["minor"]
    severe = parts["severe"]
    licences = [r for r in recs.values() if r.get("kind") == "licence"]

    claims = [{"claim": f"{len(recs)} linked record(s) for {address!r}.",
               "source": next(iter(id_to_tag.values()), None)}]
    if open_permits:
        claims.append({"claim": f"{len(open_permits)} open building permit(s).",
                       "source": id_to_tag.get(open_permits[0].get("id"))})
    # Prose honesty (#3a): a Conditional Pass is a minor follow-up, not "adverse";
    # surface deficiency_count so a collapsed visit reads "1 visit (N deficiencies)".
    if minor:
        defs = sum(int(r.get("deficiency_count", 1) or 1) for r in minor)
        suffix = f" ({defs} deficiencies)" if defs > len(minor) else ""
        claims.append({"claim": f"{len(minor)} Conditional Pass inspection visit(s)"
                       f"{suffix} — food-safety re-check due.",
                       "source": id_to_tag.get(minor[0].get("id"))})
    if severe:
        claims.append({"claim": f"{len(severe)} adverse food-safety inspection(s).",
                       "source": id_to_tag.get(severe[0].get("id"))})
    # Licences are identity context, not a risk signal (no score weight) — surfaced
    # so a fused address visibly cites all three datasets, with a click-to-verify tag.
    if licences:
        claims.append({"claim": f"{len(licences)} business licence(s) on record "
                       "(identity link across datasets, not a risk signal).",
                       "source": id_to_tag.get(licences[0].get("id"))})
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
