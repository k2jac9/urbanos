"""Command-line entry point for the Urban-OS demo loop.

    python -m urbanos.kernel.cli                 # run + optimize the downtown egress scenario
    python -m urbanos.kernel.cli --release 12    # force a fixed staggered-release, skip search
    python -m urbanos.kernel.cli --json          # machine-readable output

Runs the whole pipeline on-device: build substrate → simulate the event surge →
optimize the intervention → emit the cited killer insight. Deterministic; the
narrator falls back to a correct-by-construction sentence when no local model is
reachable, so this always prints a grounded result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .adapters import downtown_scenario
from .kernel import Simulation
from .lenses import transit_load_enabled
from .narrate import build_insight
from .optimize import objective, optimize
from .scenarios import default_lens_stack


def _lenses(
    sc, *, business: bool = False, safety: bool = False,
    transit_load: bool = False, transit_source: str = "tmc",
):
    """The CLI lens stack, via the shared builder so the CLI and API can never run
    different stacks (ADR-0022). The CLI omits WeatherLens (no shelter lever) — the
    deliberate, documented reason ``make urbanos-cli`` and the :8001 UI report
    different headline numbers. ``transit_load`` is opt-in and adds no lever/cost
    (ADR-0029), so the golden numbers are unchanged when it is off; ``transit_source``
    picks its real series (tmc throughput | ttc boardings, ADR-0031)."""
    return default_lens_stack(
        sc, safety=safety, business=business,
        transit_load=transit_load, transit_source=transit_source,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="urbanos.kernel")
    p.add_argument("--crowd", type=float, default=None, help="event crowd size")
    p.add_argument(
        "--release",
        type=float,
        default=None,
        help="force a fixed staggered-release (min); skips the optimizer search",
    )
    p.add_argument("--json", action="store_true", help="emit JSON instead of a briefing")
    p.add_argument("--business", action="store_true",
                   help="add the Sports/Business-Flow lens (local trade lost to the crush)")
    p.add_argument("--safety", action="store_true",
                   help="add the Safety lens (urbanos.risk address risk → node field)")
    p.add_argument("--transit-load", dest="transit_load", action="store_true",
                   default=transit_load_enabled(),
                   help="add the TransitLoad lens (real measured background ridership as "
                        "a source; opt-in, no lever/cost — ADR-0029). Default from "
                        "URBANOS_TRANSIT_LOAD.")
    p.add_argument("--transit-source", dest="transit_source",
                   choices=("tmc", "ttc"),
                   default=os.environ.get("URBANOS_TRANSIT_SOURCE", "tmc"),
                   help="real series feeding TransitLoad: 'tmc' (throughput, default) or "
                        "'ttc' (subway boardings, real magnitude/modelled shape — ADR-0031). "
                        "Default from URBANOS_TRANSIT_SOURCE.")
    args = p.parse_args(argv)

    sc = downtown_scenario(**({"crowd_size": args.crowd} if args.crowd else {}))
    lenses = _lenses(
        sc, business=args.business, safety=args.safety,
        transit_load=args.transit_load, transit_source=args.transit_source,
    )

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

    biz = None
    if args.business:
        base_lost = float(sum(opt.baseline_result.series("business_lost")))
        best_lost = float(sum(opt.best_result.series("business_lost")))
        biz = {"baseline_lost": base_lost, "best_lost": best_lost,
               "recovered": base_lost - best_lost}

    saf = None
    if args.safety:
        sl = next(ln for ln in lenses if ln.name == "safety")
        base_c = float(sl.cost(opt.baseline_result))
        best_c = float(sl.cost(opt.best_result))
        saf = {"baseline_cost": base_c, "best_cost": best_c, "reduced": base_c - best_c}

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
            "business": biz,
            "safety": saf,
        }, indent=2))
        return 0

    print("Urban-OS — downtown FIFA convergence-crunch scenario")
    n_events = len(sc.events) or 1
    print(f"  substrate: {sc.substrate.n} nodes, {sc.substrate.n_edges} links; "
          f"{n_events} concurrent events, crowd {sc.total_crowd:,.0f} total, "
          f"first full-time at t={sc.event_end:.0f} min")
    print(f"  bottleneck: {peak['label']} peaks at {peak['congestion']:.2f}x capacity "
          f"@ t={peak['t']:.0f} min")
    print(f"  do-nothing cost J: ${opt.baseline_J:,.0f}")
    print(f"  best intervention: release_minutes={opt.best_params.get('release_minutes')} "
          f"→ J ${opt.best_J:,.0f}  (saves ${opt.savings:,.0f})")
    if saf is not None:
        print(f"  public safety: civic risk overlaid on the substrate; crush through the "
              f"least-safe districts costs ${saf['baseline_cost']:,.0f}, "
              f"cut to ${saf['best_cost']:,.0f} by the optimized release.")
    if biz is not None:
        print(f"  business: a crush destroys ${biz['baseline_lost']:,.0f} in local trade; "
              f"the optimized release recovers ${biz['recovered']:,.0f}.")
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
