import textwrap
from pathlib import Path

import pytest

from civic_analyst.graph.builder import CivicGraph
from civic_analyst.ingest.loader import load_into_graph

# Repo-root demo_data slice (tests live in <repo>/tests/).
_DEMO_DATA = Path(__file__).resolve().parent.parent / "demo_data"


def _write(p: Path, name: str, content: str) -> None:
    (p / name).write_text(textwrap.dedent(content).strip() + "\n")


def _write_raw(p: Path, name: str, content: str) -> None:
    """Write content verbatim (no dedent/strip) — for headers with exact
    whitespace/BOM that the matcher must tolerate."""
    (p / name).write_text(content)


def test_loads_single_address_and_composite_address(tmp_path: Path):
    # DineSafe-style: single address column + a STATUS column -> inspection.outcome
    _write(
        tmp_path,
        "dinesafe__sample.csv",
        """
        _id,Establishment Name,Establishment Address,STATUS
        1,Joe's Diner,100 Queen St W,Fail
        2,Cafe Ok,200 King St E,Pass
        """,
    )
    # Permit-style: composite address columns + STATUS -> permit.status
    _write(
        tmp_path,
        "permits__sample.csv",
        """
        PERMIT_NUM,STREET_NUM,STREET_NAME,STREET_TYPE,STATUS
        P1,100,QUEEN,ST,open
        """,
    )

    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)

    assert summary == {"permits": 1, "dinesafe": 2}

    inspections = graph.records_for("100 Queen St W", kind="inspection")
    assert len(inspections) == 1
    assert inspections[0]["outcome"] == "Fail"

    permits = graph.records_for("100 QUEEN ST", kind="permit")
    assert len(permits) == 1 and permits[0]["status"] == "open"


def test_missing_data_dir_is_safe(tmp_path: Path):
    assert load_into_graph(CivicGraph(), tmp_path / "nope") == {}


def test_messy_headers_bom_whitespace_and_case(tmp_path: Path):
    # Header row carries a UTF-8 BOM on the first column, surrounding spaces, and
    # mixed case — column resolution must still find address/status/id/coords.
    _write_raw(
        tmp_path,
        "dinesafe__messy.csv",
        "﻿ _id ,  Establishment Address  , STATUS ,Latitude,Longitude\n"
        "1,100 Queen St W,Fail,43.65,-79.38\n",
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    assert summary == {"dinesafe": 1}

    recs = graph.records_for("100 Queen St W", kind="inspection")
    assert len(recs) == 1
    assert recs[0]["outcome"] == "Fail"
    # Coords resolved despite the messy 'Latitude'/'Longitude' headers.
    coords = graph.addresses(with_coords=True)
    assert coords and coords[0]["lat"] == 43.65 and coords[0]["lng"] == -79.38


def test_missing_state_and_date_columns_are_skipped_not_crashed(tmp_path: Path):
    # No STATUS, no DATE column at all — load still succeeds, attrs just omitted.
    _write(
        tmp_path,
        "dinesafe__bare.csv",
        """
        _id,Establishment Address
        1,55 Bloor St E
        """,
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    assert summary == {"dinesafe": 1}
    rec = graph.records_for("55 Bloor St E", kind="inspection")[0]
    assert "outcome" not in rec and "date" not in rec


def test_empty_address_parts_and_stray_whitespace(tmp_path: Path):
    # Row 1: composite parts present -> address built.
    # Row 2: every street part blank -> skipped (no address).
    # Row 3: single-column dinesafe with embedded newline + extra spaces -> cleaned.
    _write(
        tmp_path,
        "permits__parts.csv",
        """
        PERMIT_NUM,STREET_NUM,STREET_NAME,STREET_TYPE,STATUS
        P1,100,QUEEN,ST,open
        P2,,,,closed
        """,
    )
    _write_raw(
        tmp_path,
        "dinesafe__ws.csv",
        "_id,Establishment Address,STATUS\n"
        '1,"  200   King\nSt  E  ",Pass\n',
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    # Only 1 permit (the all-blank-parts row is skipped) and 1 inspection.
    assert summary == {"permits": 1, "dinesafe": 1}
    assert len(graph.records_for("100 QUEEN ST", kind="permit")) == 1
    # Embedded newline + runs of spaces collapsed so the address still resolves.
    assert len(graph.records_for("200 King St E", kind="inspection")) == 1


def test_malformed_coord_and_date_do_not_raise(tmp_path: Path):
    _write(
        tmp_path,
        "dinesafe__badcoords.csv",
        """
        _id,Establishment Address,STATUS,Latitude,Longitude,inspectionDate
        1,300 Yonge St,Fail,not-a-number,,
        """,
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    assert summary == {"dinesafe": 1}
    # Bad lat / empty lng -> no coords attached, no crash, no stray date attr.
    assert graph.addresses(with_coords=True) == []
    rec = graph.records_for("300 Yonge St", kind="inspection")[0]
    assert "date" not in rec


def test_malformed_file_is_skipped_not_fatal(tmp_path: Path):
    # A broken JSON file for one key must not abort ingest of a valid CSV for another.
    (tmp_path / "licences__broken.json").write_text("{ this is not valid json ")
    _write(
        tmp_path,
        "dinesafe__ok.csv",
        """
        _id,Establishment Address,STATUS
        1,400 Spadina Ave,Pass
        """,
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    # Broken licences file skipped; the valid dinesafe file still loaded.
    assert summary == {"dinesafe": 1}


def test_malformed_file_is_logged_loudly(tmp_path: Path, caplog):
    # A corrupt slice must be VISIBLE in logs (not a silent "low risk everywhere").
    (tmp_path / "licences__broken.json").write_text("{ this is not valid json ")
    with caplog.at_level("WARNING", logger="civic_analyst.ingest.loader"):
        load_into_graph(CivicGraph(), tmp_path)
    assert any(
        "skipping" in r.message and "licences__broken.json" in r.getMessage()
        for r in caplog.records
    )


def test_out_of_toronto_coords_are_dropped(tmp_path: Path):
    # A swapped lat/lng (43.65 / -79.38 flipped) lands in the ocean — it must be
    # treated as missing at the ingest boundary, so the address carries no coords.
    _write(
        tmp_path,
        "dinesafe__swapped.csv",
        """
        _id,Establishment Address,STATUS,Latitude,Longitude
        1,500 Bloor St W,Pass,-79.38,43.65
        """,
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    assert summary == {"dinesafe": 1}              # the record still loads
    assert graph.addresses(with_coords=True) == []  # but with no (bogus) pin


def test_in_toronto_coords_are_kept(tmp_path: Path):
    _write(
        tmp_path,
        "dinesafe__good.csv",
        """
        _id,Establishment Address,STATUS,Latitude,Longitude
        1,500 Bloor St W,Pass,43.667,-79.41
        """,
    )
    graph = CivicGraph()
    load_into_graph(graph, tmp_path)
    coords = graph.addresses(with_coords=True)
    assert coords and coords[0]["lat"] == 43.667 and coords[0]["lng"] == -79.41


def test_inspection_visits_dedup_by_address_and_date(tmp_path: Path):
    # DineSafe line-items one row per deficiency: 3 same-day rows at one address are
    # ONE visit; a different date is a second visit. The collapsed visit keeps the
    # worst severity and exposes deficiency_count for display (#3).
    _write(
        tmp_path,
        "dinesafe__visits.csv",
        """
        _id,Establishment Address,inspectionStatus,inspectionDate
        1,12 Main St,Conditional Pass,2024-01-10
        2,12 Main St,Pass,2024-01-10
        3,12 Main St,Conditional Pass,2024-01-10
        4,12 Main St,Pass,2024-06-01
        """,
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    assert summary == {"dinesafe": 2}  # 2 visits, not 4 line-items
    recs = sorted(graph.records_for("12 Main St", kind="inspection"),
                  key=lambda r: r.get("date"))
    assert [r["date"] for r in recs] == ["2024-01-10", "2024-06-01"]
    # First visit: 3 deficiency rows collapsed, worst severity (Conditional) wins.
    assert recs[0]["deficiency_count"] == 3
    assert recs[0]["outcome"] == "Conditional Pass"
    assert recs[1]["deficiency_count"] == 1


def test_distinct_establishments_same_address_and_date_stay_separate(tmp_path: Path):
    # Over-collapse guard (#3): two DIFFERENT establishments (estIds) at the SAME
    # address inspected the SAME day — e.g. food vendors sharing a stadium — must
    # remain TWO inspection records. Keying on (estId, date) keeps them apart; only
    # one establishment's own line-items collapse.
    _write(
        tmp_path,
        "dinesafe__shared.csv",
        """
        _id,estId,Establishment Address,inspectionStatus,inspectionDate
        1,AAA,1 Blue Jays Way,Pass,2025-10-20
        2,AAA,1 Blue Jays Way,Conditional Pass,2025-10-20
        3,BBB,1 Blue Jays Way,Pass,2025-10-20
        """,
    )
    graph = CivicGraph()
    summary = load_into_graph(graph, tmp_path)
    # 2 establishments -> 2 visits (AAA's 2 line-items collapse; BBB stays separate),
    # NOT 1 over-collapsed visit and NOT 3 per-row records.
    assert summary == {"dinesafe": 2}
    recs = graph.records_for("1 Blue Jays Way", kind="inspection")
    assert len(recs) == 2
    defs = sorted(r["deficiency_count"] for r in recs)
    assert defs == [1, 2]  # BBB -> 1 line-item, AAA -> 2 collapsed


def test_no_date_column_falls_back_to_per_row(tmp_path: Path):
    # No usable date column -> do NOT collapse (other fixtures/feeds unaffected).
    _write(
        tmp_path,
        "dinesafe__nodate.csv",
        """
        _id,Establishment Address,STATUS
        1,12 Main St,Fail
        2,12 Main St,Fail
        """,
    )
    graph = CivicGraph()
    assert load_into_graph(graph, tmp_path) == {"dinesafe": 2}
    assert len(graph.records_for("12 Main St", kind="inspection")) == 2


def test_conviction_outcome_escalates_visit_to_severe(tmp_path: Path):
    # A Pass/Conditional visit whose OutcomeDesc names a conviction/order is SEVERE,
    # additively — the real enforcement signal that was previously invisible (#3b).
    _write(
        tmp_path,
        "dinesafe__conviction.csv",
        """
        _id,Establishment Address,inspectionStatus,inspectionDate,OutcomeDesc
        1,99 King St,Conditional Pass,2024-02-01,Conviction - Fined
        2,77 Bay St,Conditional Pass,2024-02-01,
        """,
    )
    from civic_analyst.agents.verify import classify_inspection

    graph = CivicGraph()
    load_into_graph(graph, tmp_path)
    convicted = graph.records_for("99 King St", kind="inspection")[0]
    routine = graph.records_for("77 Bay St", kind="inspection")[0]
    assert classify_inspection(convicted["outcome"]) == "severe"
    assert classify_inspection(routine["outcome"]) == "minor"  # status stays primary


@pytest.mark.skipif(
    not (_DEMO_DATA / "dinesafe__downtown.csv").exists(),
    reason="demo_data/ slice not present (offline CI without the real slice)",
)
def test_demo_data_counts_are_stable():
    # Regression guard: risk scores depend on these exact ingest counts. If a
    # heuristic change shifts them, this fails loudly before it hits the demo.
    graph = CivicGraph()
    summary = load_into_graph(graph, _DEMO_DATA)
    # dinesafe is now de-duped per VISIT keyed by (estId, inspectionDate), not per
    # line-item: the 250 raw deficiency rows collapse to 135 distinct establishment
    # visits (#3). Keying on estId (not address) keeps distinct vendors that share a
    # building+date separate — e.g. the 7 food stands at Rogers Centre — so this does
    # NOT over-collapse to the ~76 an (address, date) key would have produced.
    assert summary == {"permits": 192, "dinesafe": 135, "licences": 105}
