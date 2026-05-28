"""The hallucination guard: claims must cite real source IDs and real numbers."""
import json

from civic_analyst.agents.subagents import Finding, RiskNarratorAgent
from civic_analyst.agents.verify import (
    deterministic_claims,
    evidence_index,
    resolve_claims,
    verify_claims,
)

ADDRESS = "100 Queen St W"
FINDINGS = [
    Finding(
        "retrieval",
        "3 linked records for '100 Queen St W'.",
        [
            {"id": "i1", "kind": "inspection", "dataset": "dinesafe", "outcome": "Fail"},
            {"id": "p1", "kind": "permit", "dataset": "permits", "status": "open"},
        ],
        0.0,
    ),
    Finding("compliance", "1 open permit(s), 1 infraction(s).", [], 0.5),
]
TAGGED, TAG_MAP = evidence_index(FINDINGS)
VALID = {t["tag"] for t in TAGGED}

CLEAN = [
    {"claim": "There is 1 open permit.", "source": "E2"},
    {"claim": "There is 1 infraction.", "source": "E1"},
]


class _StubLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        return self.reply


def test_evidence_index_tags_records():
    assert VALID == {"E1", "E2"}
    assert TAG_MAP["E1"]["dataset"] == "DineSafe — Food Premises Inspections"
    assert TAG_MAP["E2"]["dataset"] == "Building Permits — Active Permits"


def test_clean_claims_pass():
    assert verify_claims(CLEAN, ADDRESS, FINDINGS, VALID) == []


def test_invented_source_id_is_caught():
    bad = [{"claim": "There is 1 issue.", "source": "E9"}]
    assert any("source id" in i for i in verify_claims(bad, ADDRESS, FINDINGS, VALID))


def test_fabricated_number_is_caught():
    bad = [{"claim": "There are 42 infractions.", "source": "E1"}]
    assert any("number" in i for i in verify_claims(bad, ADDRESS, FINDINGS, VALID))


def test_multi_tag_source_accepted():
    # The model may cite several supporting records — fine, as long as all are real.
    csv = [{"claim": "There is 1 issue.", "source": "E1, E2"}]
    lst = [{"claim": "There is 1 issue.", "source": ["E1", "E2"]}]
    assert verify_claims(csv, ADDRESS, FINDINGS, VALID) == []
    assert verify_claims(lst, ADDRESS, FINDINGS, VALID) == []


def test_partial_invalid_tag_rejected():
    bad = [{"claim": "There is 1 issue.", "source": "E1, E9"}]
    assert any("source id" in i for i in verify_claims(bad, ADDRESS, FINDINGS, VALID))


def test_narrator_keeps_clean_claims():
    out = RiskNarratorAgent(llm=_StubLLM(json.dumps(CLEAN))).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(CLEAN, TAG_MAP)
    assert out[0]["source"]["tag"] == "E2"


def test_narrator_falls_back_on_hallucination():
    lie = json.dumps([{"claim": "There are 42 infractions.", "source": "E9"}])
    out = RiskNarratorAgent(llm=_StubLLM(lie)).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(deterministic_claims(ADDRESS, FINDINGS, TAGGED), TAG_MAP)
    assert all("42" not in c["text"] for c in out)


def test_narrator_falls_back_on_malformed_json():
    out = RiskNarratorAgent(llm=_StubLLM("sorry, here is the answer")).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(deterministic_claims(ADDRESS, FINDINGS, TAGGED), TAG_MAP)
