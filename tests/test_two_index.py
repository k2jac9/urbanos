"""Focused unit tests for the two-index scoring model (ADR 0014).

Construction *activity* (open permits) and food *safety* (adverse inspection visits)
are SEPARATE, never-blended indices, each read through the shared band thresholds.
These pin the formulas, the per-index bands, the deterministic two-line narrative,
the digest's two-list split, and that no single blended score leaks anywhere.
"""
import math

import urbanos.risk.agents.digest as digest
from urbanos.risk.agents.digest import _priorities, _safety, _activity, city_digest
from urbanos.risk.agents.verify import (
    activity_index,
    risk_band,
    safety_index,
    two_line_narrative,
)


# --------------------------------------------------------------------------- #
# Formulas                                                                     #
# --------------------------------------------------------------------------- #
def test_activity_index_formula():
    # 1 - exp(-0.06 * open_permits), rounded to 3 dp.
    assert activity_index(0) == 0.0
    assert activity_index(1) == round(1 - math.exp(-0.06), 3) == 0.058
    assert activity_index(2) == round(1 - math.exp(-0.12), 3) == 0.113
    # Monotone, saturating, capped below 1.
    assert activity_index(1000) <= 1.0
    assert activity_index(10) > activity_index(5) > activity_index(1)


def test_safety_index_formula():
    # SEVERITY-WEIGHTED (ADR 0014 §6): 1 - exp(-0.45 * (0.3*minor + 1.0*severe)).
    assert safety_index(0, 0) == 0.0
    # Severe visits weigh 1.0 — same as the old unweighted count.
    assert safety_index(0, 1) == round(1 - math.exp(-0.45), 3) == 0.362
    assert safety_index(0, 2) == round(1 - math.exp(-0.9), 3) == 0.593
    # Minor (Conditional Pass) visits weigh only 0.3.
    assert safety_index(1, 0) == round(1 - math.exp(-0.45 * 0.3), 3) == 0.126
    assert safety_index(2, 0) == round(1 - math.exp(-0.45 * 0.6), 3) == 0.237
    # Saturating + monotone; a severe visit always outweighs a minor one.
    assert safety_index(0, 1000) <= 1.0
    assert safety_index(0, 1) > safety_index(1, 0)


def test_negative_counts_are_clamped_to_zero():
    assert activity_index(-5) == 0.0
    assert safety_index(-5, -5) == 0.0


def test_minor_only_addresses_land_in_low_not_medium():
    """The fix's whole point: an unweighted count made LOW structurally dead (1 visit
    → 0.362 ≥ MEDIUM). Severity-weighting puts Conditional-only sites back in LOW."""
    assert risk_band(safety_index(1, 0)) == "low"   # 0.126
    assert risk_band(safety_index(2, 0)) == "low"   # 0.237
    assert risk_band(safety_index(3, 0)) == "low"   # 0.347? check — see below
    assert risk_band(safety_index(4, 0)) == "medium"  # 0.417


def test_golden_100_queen_st_w():
    """The two-index golden survives severity weighting: 100 Queen St W has 2 open
    permits + 2 SEVERE ('Fail') visits → severe weight 1.0 each, so safety is
    unchanged from the unweighted count."""
    assert activity_index(2) == 0.113 and risk_band(activity_index(2)) == "low"
    assert safety_index(0, 2) == 0.593 and risk_band(safety_index(0, 2)) == "medium"


# --------------------------------------------------------------------------- #
# Bands applied to EACH index independently                                   #
# --------------------------------------------------------------------------- #
def test_bands_per_index_are_independent():
    # none ≤ 0 < low < 0.34 ≤ medium < 0.67 ≤ high
    assert risk_band(activity_index(0)) == "none"
    assert risk_band(activity_index(1)) == "low"          # 0.058
    assert risk_band(safety_index(0, 1)) == "medium"      # 1 severe → 0.362
    # A high safety band needs several severe visits.
    assert risk_band(safety_index(0, 2)) == "medium"      # 0.593
    assert risk_band(safety_index(0, 3)) == "high"        # 0.741


def test_band_threshold_edges():
    assert risk_band(0.0) == "none"
    assert risk_band(0.001) == "low"
    assert risk_band(0.34) == "medium"
    assert risk_band(0.67) == "high"


# --------------------------------------------------------------------------- #
# Two-line deterministic narrative (ADR 0014 §8)                              #
# --------------------------------------------------------------------------- #
def test_two_line_narrative_has_both_axes():
    # 0 minor + 2 severe visits + 2 open permits (the 100 Queen St W shape).
    out = two_line_narrative(minor_visits=0, severe_visits=2, open_permits=2)
    assert "Food safety —" in out
    assert "Construction activity —" in out
    # Counts appear verbatim (grounded — no invented numbers) and severity is named.
    assert "2 inspection visits (2 severe)" in out
    assert "2 open permits" in out


def test_two_line_narrative_wording_tracks_bands():
    # 2 severe visits → safety medium → "moderate"; 2 permits → activity low → "low".
    out = two_line_narrative(0, 2, 2)
    assert "Food safety — moderate." in out
    assert "Construction activity — low." in out
    # A Conditional-only site reads "moderate" wording but its 2 minors are not severe.
    minor_only = two_line_narrative(2, 0, 0)
    assert "2 inspection visits of concern" in minor_only  # no "(N severe)" note
    assert "severe" not in minor_only
    # Clean site reads clear / low and singular/plural is correct.
    clean = two_line_narrative(0, 0, 1)
    assert "Food safety — clear. 0 inspection visits" in clean
    assert "Construction activity — low. 1 open permit." in clean


# --------------------------------------------------------------------------- #
# Digest splits into two independent priority lists                           #
# --------------------------------------------------------------------------- #
def _ranked():
    return [
        {"label": "A St", "risk_safety": 0.8, "risk_activity": 0.0},
        {"label": "B St", "risk_safety": 0.0, "risk_activity": 0.6},
        {"label": "C St", "risk_safety": 0.4, "risk_activity": 0.2},
    ]


def test_priorities_are_per_axis_and_drop_zeros():
    safety = _priorities(_ranked(), _safety)
    activity = _priorities(_ranked(), _activity)
    # Safety list ranks by safety, drops the zero-safety site (B St).
    assert [a for a, _ in safety] == ["A St", "C St"]
    # Activity list ranks by activity, drops the zero-activity site (A St).
    assert [a for a, _ in activity] == ["B St", "C St"]


class _CapturingLLM:
    def __init__(self, reply="BRIEFING"):
        self.user = None
        self.reply = reply

    def chat(self, system, user, temperature=0.2):
        self.user = user
        return self.reply


def _reset_cache():
    with digest._lock:
        digest._cache.clear()


def test_digest_prompt_presents_both_lists():
    _reset_cache()
    llm = _CapturingLLM()
    city_digest(_ranked(), llm=llm)
    assert "FOOD SAFETY priorities" in llm.user
    assert "CONSTRUCTION ACTIVITY priorities" in llm.user


class _BoomLLM:
    def chat(self, system, user, temperature=0.2):
        raise RuntimeError("offline")


def test_digest_fallback_names_top_of_each_axis():
    _reset_cache()
    out = city_digest(_ranked(), llm=_BoomLLM())
    assert "food-safety site: A St" in out
    assert "construction-activity site: B St" in out
