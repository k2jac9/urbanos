"""The optimizer finds the honest interior optimum and reports a real saving."""
from __future__ import annotations

from urban_os.adapters import downtown_scenario
from urban_os.lenses import EconomicLens, EventSurge
from urban_os.optimize import optimize


def _lenses(sc):
    return [
        EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
        EconomicLens(),
    ]


def test_optimizer_picks_interior_release_and_saves_money() -> None:
    sc = downtown_scenario()
    opt = optimize(sc.substrate, _lenses(sc), sc.horizon, dt=sc.dt)
    best = opt.best_params["release_minutes"]
    # Not the corner solutions: doing nothing (0) loses to a real release, and
    # holding forever (max, 20) is over-corrected by the hold-cost term.
    assert 0 < best < 20
    assert opt.savings > 0
    assert opt.best_J < opt.baseline_J


def test_baseline_is_do_nothing() -> None:
    sc = downtown_scenario()
    opt = optimize(sc.substrate, _lenses(sc), sc.horizon, dt=sc.dt)
    assert opt.baseline_params["release_minutes"] == 0.0
    # The chosen intervention lowers the peak crush vs. doing nothing.
    base_peak = opt.baseline_result.peak_congestion()["congestion"]
    best_peak = opt.best_result.peak_congestion()["congestion"]
    assert best_peak < base_peak


def test_trials_cover_the_whole_lever_grid() -> None:
    sc = downtown_scenario()
    lenses = _lenses(sc)
    opt = optimize(sc.substrate, lenses, sc.horizon, dt=sc.dt)
    grid = lenses[0].levers()[0].values
    assert len(opt.trials) == len(grid)
