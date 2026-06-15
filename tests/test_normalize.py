"""Behavior-pinning table for civic_analyst.graph.builder.normalize_address.

This is a characterization test: it asserts the function's ACTUAL current
behavior (not a desired-but-absent ideal) so a future refactor can't silently
change the address-join key. Where a genuine bug exists it is pinned as-is and
flagged in the test name/comment rather than failing (see the BOM case).
"""
from __future__ import annotations

import pytest

from civic_analyst.graph.builder import normalize_address

CASES = [
    # --- street-type abbreviations (long spelling folds to canonical short) ---
    ("street_to_st", "100 Queen Street West", "100 QUEEN ST W"),
    ("avenue_to_ave", "14 Maple Avenue East", "14 MAPLE AVE E"),
    ("boulevard_to_blvd", "88 Bay Boulevard", "88 BAY BLVD"),
    ("drive_to_dr", "99 O'Connor Drive", "99 O'CONNOR DR"),
    ("road_to_rd", "12 Gardens Road", "12 GDNS RD"),
    ("crescent_to_cres", "7 Spadina Crescent", "7 SPADINA CRES"),
    ("terrace_to_ter", "5 Park Terrace", "5 PARK TER"),
    ("square_to_sq", "8 College Square", "8 COLLEGE SQ"),
    ("trail_to_trl", "50 Trail Drive", "50 TRL DR"),
    ("short_form_untouched", "100 QUEEN ST W", "100 QUEEN ST W"),
    # LANE is the odd one out: the abbreviated LN folds UP to LANE.
    ("lane_stays_lane", "45 Foo Lane", "45 FOO LANE"),
    ("ln_folds_to_lane", "45 Foo LN", "45 FOO LANE"),
    # --- directionals ---
    ("west_to_w", "500 Bloor Street West", "500 BLOOR ST W"),
    ("north_to_n", "1 Yonge Street North", "1 YONGE ST N"),
    ("compound_northwest_to_nw", "123 Main Street Northwest", "123 MAIN ST NW"),
    # Separate words map separately (no compound collapse across whitespace).
    ("split_south_west", "50 Yonge St South West", "50 YONGE ST S W"),
    # --- unit / suite numbers (trailing segment dropped) ---
    ("unit_dropped", "100 Queen St W Unit 5", "100 QUEEN ST W"),
    ("hash_unit_dropped", "100 Queen St W #5", "100 QUEEN ST W"),
    ("suite_dropped", "10 King St E Suite 200", "10 KING ST E"),
    ("apt_dropped", "100 Queen St W APT 3B", "100 QUEEN ST W"),
    ("floor_dropped", "100 Queen St W FLOOR 2", "100 QUEEN ST W"),
    ("ph_dropped", "100 Queen St W PH", "100 QUEEN ST W"),
    ("lower_dropped", "100 Queen St W LOWER", "100 QUEEN ST W"),
    ("rear_dropped", "100 Queen St W REAR", "100 QUEEN ST W"),
    # --- casing / punctuation / city-province / postal / NONE ---
    ("lowercase_uppercased", "  100 queen street west  ", "100 QUEEN ST W"),
    ("trailing_periods", "100 Queen St. W.", "100 QUEEN ST W"),
    ("city_province_postal_stripped",
     "100 Queen St W, Toronto, ON M5H 2N2", "100 QUEEN ST W"),
    ("none_placeholder_dropped", "20 Front St W None", "20 FRONT ST W"),
    ("bare_none_empties", "NONE", ""),
    ("empty_stays_empty", "", ""),
    # --- whitespace normalization ---
    ("tabs_collapse", "100\tQueen\tSt\tW", "100 QUEEN ST W"),
    ("multi_space_collapse", "100  Queen   St    W", "100 QUEEN ST W"),
]


@pytest.mark.parametrize(
    "expected,raw",
    [(c[2], c[1]) for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_normalize_address_table(expected, raw):
    assert normalize_address(raw) == expected


def test_two_spellings_collapse_to_same_key():
    """The whole point of the function: two formats of one address share a key."""
    assert normalize_address("100 Queen Street West") == normalize_address(
        "100 QUEEN ST W"
    )


def test_leading_bom_is_stripped():
    # A BOM-prefixed feed row (common in Excel/Windows CSV exports) joins cleanly
    # with the clean address key — normalize_address strips U+FEFF first.
    assert normalize_address("﻿100 Queen St W") == "100 QUEEN ST W"
