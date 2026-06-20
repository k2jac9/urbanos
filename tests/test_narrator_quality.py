"""Narrator quality + guard regression (offline, no network).

The interactive narrator was nudged toward richer, plain-language, inspector-ready
sentences (naming the dataset/record type and what it implies). These tests pin that
the *quality* nudge did not weaken the hallucination guard: a rich-but-valid stubbed
claim must survive verification (no fallback), while a rich-but-bogus one (bad tag or
invented number) must fall back to the deterministic, source-backed claims.

Mirrors the stubbed-LLM approach in tests/test_verify.py — never hits a model.
"""
import json

from urbanos.risk.agents.subagents import Finding, RiskNarratorAgent
from urbanos.risk.agents.verify import (
    deterministic_claims,
    evidence_index,
    resolve_claims,
)

ADDRESS = "500 Bloor St W"
# A fused, hero-style address: open permit + adverse DineSafe inspection + a licence.
FINDINGS = [
    Finding(
        "retrieval",
        "3 linked records for '500 Bloor St W'.",
        [
            {"id": "p1", "kind": "permit", "dataset": "permits", "status": "open"},
            {"id": "i1", "kind": "inspection", "dataset": "dinesafe",
             "outcome": "Conditional Pass"},
            {"id": "l1", "kind": "licence", "dataset": "licences"},
        ],
    ),
    Finding("compliance", "1 open permit(s); 1 adverse inspection(s).", [],
            risk_safety=0.362, risk_activity=0.058),
]
TAGGED, TAG_MAP, ID_TO_TAG = evidence_index(FINDINGS)
VALID = {t["tag"] for t in TAGGED}


class _StubLLM:
    """Returns a canned reply, recording the prompts it was handed (no network)."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_system = None
        self.last_user = None

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        self.last_system, self.last_user = system, user
        return self.reply


def _tag_for(kind: str) -> str:
    return next(t["tag"] for t in TAGGED if t["kind"] == kind)


# A richer, plain-language, inspector-ready set of claims — still one real tag each
# and only numbers that appear in the Findings ("1").
RICH_VALID = [
    {"claim": "1 open building permit indicates active construction to verify on site.",
     "source": _tag_for("permit")},
    {"claim": "A DineSafe Conditional Pass means an unresolved food-safety item needs"
              " a follow-up.",
     "source": _tag_for("inspection")},
]


def test_rich_but_valid_claims_survive_the_guard():
    """The quality nudge must not cost us groundedness: a richer-but-honest claim set
    passes verification and is returned verbatim (no deterministic fallback)."""
    out = RiskNarratorAgent(llm=_StubLLM(json.dumps(RICH_VALID))).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(RICH_VALID, TAG_MAP)
    # The permit claim's resolved source really is the permit row (citation aligned).
    assert out[0]["source"]["kind"] == "permit"
    assert out[1]["source"]["kind"] == "inspection"


def test_rich_claim_with_bad_tag_falls_back():
    """Plausible-sounding prose with an invented source tag must NOT reach the user."""
    bad = json.dumps([
        {"claim": "1 open building permit indicates active construction to verify.",
         "source": "E99"},
    ])
    out = RiskNarratorAgent(llm=_StubLLM(bad)).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(
        deterministic_claims(ADDRESS, FINDINGS, TAGGED, ID_TO_TAG), TAG_MAP
    )


def test_rich_claim_with_invented_number_falls_back():
    """A fabricated count (47) inside otherwise-rich prose triggers the fallback."""
    lie = json.dumps([
        {"claim": "47 open building permits show major active construction on site.",
         "source": _tag_for("permit")},
    ])
    out = RiskNarratorAgent(llm=_StubLLM(lie)).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(
        deterministic_claims(ADDRESS, FINDINGS, TAGGED, ID_TO_TAG), TAG_MAP
    )
    assert all("47" not in c["text"] for c in out)


def test_prompt_still_pins_the_load_bearing_contract():
    """Guard the wording the verifier depends on: single-tag citation + numbers-only-
    from-Findings must stay in the SYSTEM prompt even as it gets richer."""
    sys = RiskNarratorAgent.SYSTEM.lower()
    assert "json array" in sys
    assert "only numbers" in sys
    assert "findings" in sys
    # The prompt must still steer toward one tag per claim.
    assert "one evidence tag" in sys or "exactly one real tag" in sys


def test_evidence_prompt_exposes_dataset_context_without_bare_invented_numbers():
    """The evidence block handed to the model names the dataset + status for each tag
    (so claims can be richer) while the only numbers offered live in the Findings."""
    stub = _StubLLM(json.dumps(RICH_VALID))
    RiskNarratorAgent(llm=stub).claims(ADDRESS, FINDINGS)
    user = stub.last_user
    # Dataset titles surface so the model can name the source in plain language.
    assert "DineSafe" in user and "Building Permits" in user
    # The findings (the only sanctioned number source) are clearly labelled as such.
    assert "ONLY numbers you may use" in user
    # Each evidence tag is offered as a citable source.
    for t in TAGGED:
        assert t["tag"] in user
