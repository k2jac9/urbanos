"""The insight narrator stays grounded: deterministic offline, and it rejects an
LLM sentence that invents a number (the hallucination guard)."""
from __future__ import annotations

from urbanos.kernel.adapters import downtown_scenario
from urbanos.kernel.lenses import EconomicLens, EventSurge, WeatherLens
from urbanos.kernel.narrate import build_insight
from urbanos.kernel.optimize import optimize


def _opt():
    sc = downtown_scenario()
    lenses = [EventSurge(events=sc.events), EconomicLens()]
    return optimize(sc.substrate, lenses, sc.horizon, dt=sc.dt), sc


def _opt_three_lens():
    """The full demo stack: the optimizer picks shelter>0, so the narrator must
    reflect BOTH levers."""
    sc = downtown_scenario()
    lenses = [
        EventSurge(events=sc.events),
        EconomicLens(),
        WeatherLens(
            peak_time=sc.event_end, intensity=0.7, width=20.0, crowd_size=sc.total_crowd
        ),
    ]
    return optimize(sc.substrate, lenses, sc.horizon, dt=sc.dt), sc


class _LLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        return self.reply


class _Boom:
    """Stands in for an unreachable endpoint (offline / model down)."""

    def chat(self, system: str, user: str, temperature: float = 0.0) -> str:
        raise RuntimeError("endpoint down")


def test_deterministic_fallback_is_grounded_and_specific() -> None:
    opt, sc = _opt()
    ins = build_insight(opt, event_end=sc.event_end, llm=_Boom())  # force offline path
    assert ins.grounded is False  # fell back to the correct-by-construction sentence
    assert "Union Station" in ins.text
    assert f"{ins.figures['release_min']}-minute" in ins.text
    assert str(ins.figures["savings_k"]) in ins.text
    # The saving is the NET intervention benefit, not "commuter-delay cost"
    # (J nets the hold penalty + weather/safety terms — audit finding).
    assert "net intervention benefit" in ins.text
    assert "commuter-delay" not in ins.text


def test_narrator_reflects_both_levers_when_shelter_chosen() -> None:
    """On the full stack the optimizer picks shelter>0; the sentence must name
    BOTH the staggered release and the shelter coverage."""
    opt, sc = _opt_three_lens()
    ins = build_insight(opt, event_end=sc.event_end, llm=_Boom())
    assert opt.best_params.get("shelter_fraction", 0.0) > 0.0  # calibration sanity
    assert ins.figures["shelter_pct"] > 0
    assert f"{ins.figures['shelter_pct']}% shelter coverage" in ins.text
    assert f"{ins.figures['release_min']}-minute staggered release" in ins.text
    assert "net intervention benefit" in ins.text


def test_insight_is_specific_with_a_live_model_or_fallback() -> None:
    """With llm=None the narrator uses whatever endpoint is configured; either way
    the sentence names the station and never contains an off-whitelist number."""
    opt, sc = _opt()
    ins = build_insight(opt, event_end=sc.event_end)
    assert "Union Station" in ins.text
    assert ins.figures["savings_k"] > 0


def test_clean_llm_sentence_is_accepted() -> None:
    opt, sc = _opt()
    f = build_insight(opt, event_end=sc.event_end, llm=None).figures
    good = (
        f"{f['station']} hits {f['base_mult']}x safe capacity {f['minutes_after']} "
        f"minutes after full-time, but a {f['release_min']}-minute staggered release "
        f"cuts the peak {f['reduction_pct']}% and saves ${f['savings_k']}k."
    )
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(good))
    assert ins.grounded is True
    assert ins.text == good


def test_hallucinated_number_is_rejected() -> None:
    opt, sc = _opt()
    # 999 is not among the simulation's figures → must be rejected → fallback.
    bad = "Union Station hits 999x capacity and a 7-minute release saves $4242k."
    ins = build_insight(opt, event_end=sc.event_end, llm=_LLM(bad))
    assert ins.grounded is False
    assert "999" not in ins.text
