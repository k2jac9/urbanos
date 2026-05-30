"""Hardening + property tests for the urban_os insight narrator's hallucination
guard (Workstream E / ADR 0010).

The single invariant under test: ``build_insight`` never invents a number — every
numeric token in ``insight.text`` traces to ``insight.figures`` (years excepted),
the ``grounded`` flag is correct, and the narrator stays deterministic, offline,
and crash-free across degenerate scenarios. These tests are additive; they do not
touch ``tests/test_urban_narrate.py``.
"""
from __future__ import annotations

import re

import networkx as nx
import pytest

from urban_os.adapters import downtown_scenario
from urban_os.kernel.state import Substrate
from urban_os.lenses import EconomicLens, EventSurge
from urban_os.narrate import (
    _canon,
    _nums,
    _whitelist,
    build_insight,
    is_grounded,
)
from urban_os.optimize import optimize

# --- the same numeric-token extractor the narrator uses, for assertions --------
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


class _LLM:
    """A stub model that always returns ``reply``."""

    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        return self.reply


class _Boom:
    """An unreachable endpoint (offline / model down)."""

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        raise RuntimeError("endpoint down")


def _opt(crowd_size: float = 45000.0):
    sc = downtown_scenario(crowd_size=crowd_size)
    lenses = [
        EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
        EconomicLens(),
    ]
    return optimize(sc.substrate, lenses, sc.horizon, dt=sc.dt), sc


def _allowed_tokens(figures: dict) -> set[str]:
    """Canonical numeric tokens drawn from the figure values (the whitelist)."""
    return _whitelist(figures)


def _text_numbers(text: str) -> set[str]:
    """Canonical numeric tokens that actually appear in a sentence."""
    return {_canon(float(t)) for t in _NUM_RE.findall(text)}


def _years(text: str) -> set[str]:
    out = set()
    for t in _NUM_RE.findall(text):
        v = float(t)
        if v.is_integer() and 1900 <= v <= 2100:
            out.add(_canon(v))
    return out


# --- core invariant: every number in the text is a figure ----------------------


def test_fallback_text_has_no_number_outside_figures() -> None:
    opt, sc = _opt()
    ins = build_insight(opt, event_end=sc.event_end, llm=_Boom())
    assert ins.grounded is False
    extraneous = _text_numbers(ins.text) - _allowed_tokens(ins.figures) - _years(ins.text)
    assert extraneous == set(), f"fallback invented numbers: {extraneous}"


def test_is_grounded_predicate_agrees_with_flag_on_fallback() -> None:
    opt, sc = _opt()
    ins = build_insight(opt, event_end=sc.event_end, llm=_Boom())
    # The deterministic fallback satisfies the invariant by construction even
    # though it reports grounded=False (which means "not a verified LLM line").
    assert is_grounded(ins.text, ins.figures) is True


@pytest.mark.parametrize("crowd_size", [1000.0, 8000.0, 20000.0, 45000.0, 90000.0])
def test_property_every_number_in_text_is_a_figure(crowd_size: float) -> None:
    """Property-style: across a sweep of crowd sizes, the produced sentence (live
    endpoint or fallback) never contains an off-whitelist number."""
    opt, sc = _opt(crowd_size)
    ins = build_insight(opt, event_end=sc.event_end)  # llm=None -> real or fallback
    extraneous = _text_numbers(ins.text) - _allowed_tokens(ins.figures) - _years(ins.text)
    assert extraneous == set(), f"crowd={crowd_size}: invented {extraneous}"
    # And the public predicate agrees with whatever path was taken.
    assert is_grounded(ins.text, ins.figures) is True


# --- grounded-flag correctness -------------------------------------------------


def test_clean_llm_sentence_sets_grounded_true() -> None:
    opt, sc = _opt()
    f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
    good = (
        f"{f['station']} hits {f['base_mult']}x safe capacity {f['minutes_after']} "
        f"minutes after full-time; a {f['release_min']}-minute release cuts the "
        f"peak {f['reduction_pct']}% and saves ${f['savings_k']}k."
    )
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(good))
    assert ins.grounded is True
    assert ins.text == good


def test_invented_number_forces_fallback() -> None:
    opt, sc = _opt()
    bad = "Union Station hits 777x capacity; a 3-minute release saves $9090k."
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(bad))
    assert ins.grounded is False
    assert "777" not in ins.text and "9090" not in ins.text


def test_decimal_is_not_confused_with_concatenated_integer() -> None:
    """A figure of 2.5x must NOT whitelist the integer 25 (the old _ints split
    ``2.5`` -> {2,5}; we keep decimals intact so 2.5 != 25)."""
    opt, sc = _opt()
    f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
    # Only meaningful when the demo peak really is a decimal like 2.5.
    if isinstance(f["base_mult"], float) and not float(f["base_mult"]).is_integer():
        digits = str(f["base_mult"]).replace(".", "")  # "2.5" -> "25"
        if digits not in _allowed_tokens(f):
            bad = f"{f['station']} hits {digits}x safe capacity at peak."
            ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(bad))
            assert ins.grounded is False


def test_missing_station_name_forces_fallback() -> None:
    """A sentence that omits the exact station name is rejected even if its
    numbers happen to be clean — the insight must be specific."""
    opt, sc = _opt()
    f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
    no_station = (
        f"The bottleneck hits {f['base_mult']}x capacity and a "
        f"{f['release_min']}-minute release saves ${f['savings_k']}k."
    )
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(no_station))
    assert ins.grounded is False


def test_empty_llm_reply_forces_fallback() -> None:
    opt, sc = _opt()
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM("   "))
    assert ins.grounded is False
    assert ins.text  # still a full sentence


def test_multiline_reply_first_line_only_and_grounded() -> None:
    """The narrator keeps only the first line; a clean first line is accepted even
    if a noisy second line would have contained a bad number."""
    opt, sc = _opt()
    f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
    good_first = (
        f"{f['station']} peaks at {f['base_mult']}x capacity {f['minutes_after']} "
        f"minutes after full-time; a {f['release_min']}-minute release cuts it "
        f"{f['reduction_pct']}% saving ${f['savings_k']}k."
    )
    reply = good_first + '\n(internal note: estimated 5000 extra riders)'
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(reply))
    assert ins.grounded is True
    assert "5000" not in ins.text


def test_quoted_reply_is_unwrapped_and_grounded() -> None:
    opt, sc = _opt()
    f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
    good = (
        f'"{f["station"]} peaks at {f["base_mult"]}x capacity; a '
        f'{f["release_min"]}-minute release saves ${f["savings_k"]}k."'
    )
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(good))
    assert ins.grounded is True
    assert not ins.text.startswith('"')


def test_year_is_allowed_in_grounded_sentence() -> None:
    """A descriptive year (e.g. 2026) is exempt from the whitelist, mirroring the
    civic_analyst verifier — it does not flip grounded to False."""
    opt, sc = _opt()
    f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
    with_year = (
        f"In 2026, {f['station']} peaks at {f['base_mult']}x capacity; a "
        f"{f['release_min']}-minute release saves ${f['savings_k']}k."
    )
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(with_year))
    assert ins.grounded is True
    assert "2026" in ins.text


# --- edge cases: degenerate / empty / zero-savings runs ------------------------


def test_zero_crowd_no_congestion_does_not_crash_or_fabricate() -> None:
    """No crowd -> no congestion peak -> station is None. The narrator must say so
    plainly (never the literal 'None'), never crash, and stay grounded."""
    opt, sc = _opt(crowd_size=0.0)
    ins = build_insight(opt, event_end=sc.event_end, llm=_Boom())
    assert ins.figures["station"] is None
    assert ins.grounded is False
    assert "None" not in ins.text
    assert is_grounded(ins.text, ins.figures) is True
    extraneous = _text_numbers(ins.text) - _allowed_tokens(ins.figures) - _years(ins.text)
    assert extraneous == set()


def test_zero_savings_reports_zero_not_a_fabricated_figure() -> None:
    opt, sc = _opt(crowd_size=0.0)
    f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
    assert f["savings_k"] == 0
    assert f["reduction_pct"] == 0


def _empty_scenario():
    """A substrate with a single isolated sink and no event surge — a maximally
    degenerate run (no frames produce congestion)."""
    g = nx.DiGraph()
    g.add_node("only_exit", label="Only Exit", lat=43.0, lng=-79.0, capacity=1.0e9)
    sub = Substrate.from_graph(g, sinks=["only_exit"])
    return sub


def test_empty_substrate_run_is_grounded_and_crash_free() -> None:
    sub = _empty_scenario()
    lenses = [EconomicLens()]
    opt = optimize(sub, lenses, horizon=10, dt=1.0)
    ins = build_insight(opt, event_end=5.0, llm=_Boom())
    assert ins.grounded is False
    assert ins.text
    assert "None" not in ins.text
    assert is_grounded(ins.text, ins.figures) is True


def test_baseline_equals_best_yields_zero_reduction_and_savings() -> None:
    """When no lever beats doing nothing, savings and reduction are exactly 0 and
    the sentence reflects that without inventing improvement numbers."""
    sub = _empty_scenario()
    lenses = [EconomicLens()]
    opt = optimize(sub, lenses, horizon=10, dt=1.0)
    assert opt.best_J == opt.baseline_J
    assert opt.savings == 0.0
    f = build_insight(opt, event_end=5.0, llm=_Boom()).figures
    assert f["savings_k"] == 0
    assert f["reduction_pct"] == 0


# --- determinism + offline-safety ---------------------------------------------


def test_offline_is_fully_deterministic() -> None:
    opt, sc = _opt()
    a = build_insight(opt, event_end=sc.event_end, llm=_Boom())
    b = build_insight(opt, event_end=sc.event_end, llm=_Boom())
    assert a.text == b.text
    assert a.figures == b.figures
    assert a.grounded == b.grounded is False


def test_reduction_pct_is_clamped_to_0_100() -> None:
    """The reported peak reduction can never be negative or exceed 100%."""
    for crowd in (0.0, 5000.0, 45000.0, 120000.0):
        opt, sc = _opt(crowd)
        f = build_insight(opt, event_end=sc.event_end, llm=_Boom()).figures
        assert 0 <= f["reduction_pct"] <= 100


def test_negative_event_end_does_not_make_minutes_negative() -> None:
    """A pathological event_end after the peak still yields minutes_after >= 0."""
    opt, sc = _opt()
    f = build_insight(opt, event_end=10_000.0, llm=_Boom()).figures
    assert f["minutes_after"] >= 0


def test_nums_canonicalizes_int_float_and_padding() -> None:
    assert _nums("2.0 and 2") == {"2"}
    assert _nums("07 minutes") == {"7"}
    assert _nums("2.5 vs 25") == {"2.5", "25"}
    assert _nums("no numbers here") == set()
    assert _nums("") == set()
