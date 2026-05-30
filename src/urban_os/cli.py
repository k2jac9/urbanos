"""Command-line entry point for the Urban-OS demo loop.

    python -m urban_os.cli                 # run + optimize the downtown egress scenario
    python -m urban_os.cli --release 12    # force a fixed staggered-release, skip search
    python -m urban_os.cli --json          # machine-readable output

Runs the whole pipeline on-device: build substrate → simulate the event surge →
optimize the intervention → emit the cited killer insight. Deterministic; the
narrator falls back to a correct-by-construction sentence when no local model is
reachable, so this always prints a grounded result.
"""
from __future__ import annotations

import argparse
import json
import sys

from .adapters import downtown_scenario
from .kernel import Simulation
from .lenses import EconomicLens, EventSurge
from .narrate import build_insight
from .optimize import objective, optimize


def _lenses(sc):
    return [
        EventSurge(sc.venue_id, sc.crowd_size, event_end=sc.event_end),
        EconomicLens(),
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="urban_os")
    p.add_argument("--crowd", type=float, default=None, help="event crowd size")
    p.add_argument(
        "--release",
        type=float,
        default=None,
        help="force a fixed staggered-release (min); skips the optimizer search",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of a briefing")
    args = p.parse_args(argv)

    sc = downtown_scenario(**({"crowd_size": args.crowd} if args.crowd else {}))
    lenses = _lenses(sc)

    if args.release is not None:
        # Single deterministic run at a fixed lever — no search.
        res = Simulation(sc.substrate, lenses, params={"release_minutes": args.release},
                         dt=sc.dt).run(sc.horizon)
        base = Simulation(sc.substrate, lenses, params={"release_minutes": 0.0},
                          dt=sc.dt).run(sc.horizon)
        opt = _AsOpt(base, res, {"release_minutes": 0.0},
                     {"release_minutes": args.release}, lenses)
    else:
        opt = optimize(sc.substrate, lenses, sc.horizon, dt=sc.dt)

    insight = build_insight(opt, event_end=sc.event_end)
    peak = opt.baseline_result.peak_congestion()

    if args.json:
        print(json.dumps({
            "insight": insight.text,
            "grounded": insight.grounded,
            "figures": insight.figures,
            "baseline_J": opt.baseline_J,
            "best_J": opt.best_J,
            "savings": opt.savings,
            "best_params": opt.best_params,
            "baseline_peak": peak,
        }, indent=2))
        return 0

    print("Urban-OS — downtown event-egress scenario")
    print(f"  substrate: {sc.substrate.n} nodes, {sc.substrate.n_edges} links; "
          f"crowd {sc.crowd_size:,.0f}, full-time at t={sc.event_end:.0f} min")
    print(f"  bottleneck: {peak['label']} peaks at {peak['congestion']:.2f}x capacity "
          f"@ t={peak['t']:.0f} min")
    print(f"  do-nothing cost J: ${opt.baseline_J:,.0f}")
    print(f"  best intervention: release_minutes={opt.best_params.get('release_minutes')} "
          f"→ J ${opt.best_J:,.0f}  (saves ${opt.savings:,.0f})")
    src = "local model" if insight.grounded else "deterministic fallback"
    print(f"\n  INSIGHT [{src}]:\n  {insight.text}")
    return 0


class _AsOpt:
    """Adapt a forced single-release run to the OptResult shape build_insight wants."""

    def __init__(self, base_res, best_res, base_params, best_params, lenses) -> None:
        self.baseline_result = base_res
        self.best_result = best_res
        self.baseline_params = base_params
        self.best_params = best_params
        self.baseline_J = objective(base_res, lenses)
        self.best_J = objective(best_res, lenses)

    @property
    def savings(self) -> float:
        return self.baseline_J - self.best_J


if __name__ == "__main__":
    sys.exit(main())
