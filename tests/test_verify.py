"""The hallucination guard: claims must cite real source IDs and real numbers."""
import json

from civic_analyst.agents.subagents import Finding, RiskNarratorAgent
from civic_analyst.agents.verify import (
    EVIDENCE_CAP,
    _BAND_HIGH,
    _BAND_LOW,
    deterministic_claims,
    evidence_index,
    partition_inspections,
    resolve_claims,
    risk_band,
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
TAGGED, TAG_MAP, ID_TO_TAG = evidence_index(FINDINGS)
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


# --- band thresholds are named constants, mirrored by map.html ---------------- #
def test_band_constants_are_the_documented_cutoffs():
    # The map.html pin colors MUST mirror these exact values (single source).
    assert (_BAND_LOW, _BAND_HIGH) == (0.34, 0.67)


def test_risk_band_uses_constants_at_boundaries():
    assert risk_band(0.0) == "none"
    assert risk_band(_BAND_LOW - 0.001) == "low"
    assert risk_band(_BAND_LOW) == "medium"          # inclusive lower edge of medium
    assert risk_band(_BAND_HIGH - 0.001) == "medium"
    assert risk_band(_BAND_HIGH) == "high"           # inclusive lower edge of high


def test_partition_inspections_classifies_once_into_buckets():
    recs = [
        {"id": "a", "kind": "inspection", "outcome": "Pass"},
        {"id": "b", "kind": "inspection", "outcome": "Conditional Pass"},
        {"id": "c", "kind": "inspection", "outcome": "Fail"},
        {"id": "d", "kind": "inspection", "outcome": "Closed"},
    ]
    parts = partition_inspections(recs)
    assert [r["id"] for r in parts["pass"]] == ["a"]
    assert [r["id"] for r in parts["minor"]] == ["b"]
    assert [r["id"] for r in parts["severe"]] == ["c", "d"]


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


# --- ADR-0020: decimal-safe numbers + record-kind matching ------------------- #
def test_decimal_number_not_smuggled_via_digit_runs():
    # "2.5" must NOT be accepted just because 2 and 5 appear in the evidence —
    # the old digit-run guard split "2.5" into {2,5} and let it through.
    bad = [{"claim": "Risk rose 2.5x after the 1 infraction.", "source": "E1"}]
    issues = verify_claims(bad, ADDRESS, FINDINGS, VALID)
    assert any("number" in i and "2.5" in i for i in issues)


def test_year_like_number_still_exempt():
    ok = [{"claim": "A 2019 inspection recorded 1 infraction.", "source": "E1"}]
    assert verify_claims(ok, ADDRESS, FINDINGS, VALID) == []


def test_kind_mismatch_caught_with_tag_map():
    # E1 is an INSPECTION row, E2 a PERMIT row. A permit/construction claim that
    # cites the inspection row must be rejected when the tag_map is supplied.
    bad = [{"claim": "An open building permit indicates active construction.",
            "source": "E1"}]
    issues = verify_claims(bad, ADDRESS, FINDINGS, TAG_MAP)
    assert any("kind mismatch" in i for i in issues)


def test_kind_match_passes_with_tag_map():
    good = [
        {"claim": "An open building permit indicates active construction.", "source": "E2"},
        {"claim": "A failed food inspection was recorded.", "source": "E1"},
    ]
    assert verify_claims(good, ADDRESS, FINDINGS, TAG_MAP) == []


def test_kind_matching_skipped_for_bare_tag_set():
    # Back-compat: passing the bare tag SET (not the map) does not kind-check.
    claim = [{"claim": "An open building permit indicates active construction.",
              "source": "E1"}]
    assert verify_claims(claim, ADDRESS, FINDINGS, VALID) == []


def test_narrator_keeps_clean_claims():
    out = RiskNarratorAgent(llm=_StubLLM(json.dumps(CLEAN))).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(CLEAN, TAG_MAP)
    assert out[0]["source"]["tag"] == "E2"


def test_narrator_falls_back_on_hallucination():
    lie = json.dumps([{"claim": "There are 42 infractions.", "source": "E9"}])
    out = RiskNarratorAgent(llm=_StubLLM(lie)).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(
        deterministic_claims(ADDRESS, FINDINGS, TAGGED, ID_TO_TAG), TAG_MAP
    )
    assert all("42" not in c["text"] for c in out)


def test_narrator_falls_back_on_malformed_json():
    out = RiskNarratorAgent(llm=_StubLLM("sorry, here is the answer")).claims(ADDRESS, FINDINGS)
    assert out == resolve_claims(
        deterministic_claims(ADDRESS, FINDINGS, TAGGED, ID_TO_TAG), TAG_MAP
    )


def test_deterministic_claims_link_to_distinct_sources():
    # Topic claims cite the kind of record that backs them — not all E1 (#4).
    claims = deterministic_claims(ADDRESS, FINDINGS, TAGGED, ID_TO_TAG)
    by_text = {c["claim"]: c["source"] for c in claims}
    permit_src = next(s for t, s in by_text.items() if "permit" in t)
    insp_src = next(s for t, s in by_text.items() if "inspection" in t)
    assert permit_src != insp_src                 # genuinely distinct citations
    assert TAG_MAP[permit_src]["kind"] == "permit"
    assert TAG_MAP[insp_src]["kind"] == "inspection"
    # Evidence is traceable: a real record id is exposed for display (#5).
    resolved = resolve_claims(claims, TAG_MAP)
    assert resolved[0]["source"]["ref"] == "i1"


def test_minor_inspection_reported_as_conditional_pass_not_adverse():
    # Prose honesty (#3a): a Conditional Pass is a minor follow-up, reported as
    # "Conditional Pass", never "adverse" (which is reserved for severe outcomes).
    recs = [{"id": "i1", "kind": "inspection", "dataset": "dinesafe",
             "outcome": "Conditional Pass", "deficiency_count": 9}]
    findings = [Finding("retrieval", "1 linked record.", recs, 0.0),
                Finding("compliance", "0 open permit(s); 1 Conditional Pass visit(s); "
                        "0 adverse inspection(s).", [], 0.0)]
    tagged, _, id_map = evidence_index(findings)
    claims = deterministic_claims("12 Main St", findings, tagged, id_map)
    text = " ".join(c["claim"] for c in claims)
    assert "conditional pass" in text.lower()
    # The minor visit is NOT called "adverse" anywhere.
    assert "adverse" not in text.lower()
    # Collapsed visit surfaces its deficiency count for display (1 visit, 9 deficiencies).
    assert "9 deficiencies" in text


def test_severe_inspection_still_called_adverse():
    recs = [{"id": "i1", "kind": "inspection", "dataset": "dinesafe", "outcome": "Fail"}]
    findings = [Finding("retrieval", "1 linked record.", recs, 0.0),
                Finding("compliance", "0 open permit(s); 1 adverse inspection(s).", [], 0.0)]
    tagged, _, id_map = evidence_index(findings)
    text = " ".join(c["claim"] for c in
                    deterministic_claims("x", findings, tagged, id_map))
    assert "adverse" in text.lower()


def test_recommendation_is_conditional_on_risk():
    # No issues -> explicit "no action", with no fabricated source (#7).
    clean = [Finding("retrieval", "0 linked records.", [], 0.0),
             Finding("compliance", "0 open permit(s); 0 adverse inspection(s).", [], 0.0)]
    tagged, _, id_map = evidence_index(clean)
    rec = deterministic_claims("nowhere", clean, tagged, id_map)[-1]
    assert "no action required" in rec["claim"].lower() and rec["source"] is None


def test_licence_surfaces_despite_cap_as_nonrisk_context():
    # A fused address (hero pin 500 Bloor) links a 3rd dataset — business licences.
    # Even when permits alone fill the evidence cap, the licence must still surface
    # (no dataset silently hidden) and produce a neutral, click-to-verify context
    # claim that carries NO risk weight.
    recs = [{"id": f"p{i}", "kind": "permit", "dataset": "permits", "status": "open"}
            for i in range(EVIDENCE_CAP)]
    recs.append({"id": "l1", "kind": "licence", "dataset": "licences"})
    findings = [Finding("retrieval", f"{len(recs)} linked records.", recs, 0.0),
                Finding("compliance", f"{EVIDENCE_CAP} open permit(s); 0 adverse.", [], 0.0)]
    tagged, tag_map, id_map = evidence_index(findings)
    # The licence (last record, past the cap by raw order) survives via per-kind coverage.
    assert any(t["kind"] == "licence" for t in tagged), "licence dataset hidden by cap"
    assert id_map.get("l1") is not None
    assert tag_map[id_map["l1"]]["dataset"] == "Business Licences & Permits"
    # …and it shows up as a neutral, source-backed claim — not a risk number.
    claims = deterministic_claims("500 Bloor St W", findings, tagged, id_map)
    lic = [c for c in claims if "licence" in c["claim"].lower()]
    assert lic and lic[0]["source"] is not None
    assert "not a risk signal" in lic[0]["claim"].lower()
