"""Shared lens-stack builder — the single source of truth for which lenses run.

ADR-0022: the CLI and the API used to each build their own lens stack, so the two
surfaces could (and did) silently run *different* stacks — the audit's "numbers
differ by surface" footgun. Both now call :func:`default_lens_stack` with explicit
flags, so any divergence is a deliberate, visible argument rather than two drifting
copies.

Stack order is fixed: EventSurge → Economic → [Weather] → [Safety] → [Business].
WeatherLens MUST follow EconomicLens — it multiplies the standing ``risk`` field
that Economic populates (ADR-0007).
"""
from __future__ import annotations

from .adapters import (
    bikeshare_demand_by_node,
    civic_activity_by_node,
    civic_safety_by_node,
    observed_counts_by_node,
    ttc_boardings_by_node,
)
from .lenses import (
    BusinessFlow,
    CongestionNowcastLens,
    EconomicLens,
    EmissionsLens,
    EmsAccessLens,
    EventSurge,
    FareRevenueLens,
    MobilityDemandLens,
    NoiseLivabilityLens,
    SafetyLens,
    TransitLoadLens,
    WeatherLens,
)

# WeatherLens calibration for the default downtown demo (a passing rain cell that
# peaks with the egress wave). Kept here so both surfaces get identical weather.
_WEATHER_INTENSITY = 0.7
_WEATHER_WIDTH = 20.0


def default_lens_stack(
    sc,
    *,
    weather: bool = False,
    safety: bool = False,
    business: bool = False,
    transit_load: bool = False,
    transit_source: str = "tmc",
) -> list:
    """Build the Urban-OS lens stack for scenario ``sc``.

    - ``weather``      → append WeatherLens (the shelter-coverage optimizer lever).
    - ``safety``       → append SafetyLens (civic address risk fused onto the substrate).
    - ``business``     → append BusinessFlow (local trade lost to the crush).
    - ``transit_load`` → append TransitLoadLens (REAL measured background ridership as a
      ``source``, opt-in; ADR-0029). It adds no lever and no J cost — a realism source,
      not a priced lever — so the optimizer's choice and every headline number are
      unmoved. **Default False keeps the stack byte-identical to before**, so the golden
      CLI numbers (do-nothing J $323,222, best 14-min → $105,050) are untouched unless a
      caller explicitly opts in.
    - ``transit_source`` → which real series feeds TransitLoad when it's on:
      ``"tmc"`` (default) = real Toronto TMC 15-min throughput (real intraday shape);
      ``"ttc"`` = real TTC subway boardings distributed by a modelled evening shape
      (real magnitude / modelled shape, ADR-0031). Ignored when ``transit_load`` is off.

    The base (EventSurge + Economic) always runs. Callers:
    - API optimizer/narrator stack: ``default_lens_stack(sc, weather=True)``
    - API cross-domain 4-lens stack: ``default_lens_stack(sc, safety=True, business=True)``
    - CLI: ``default_lens_stack(sc, safety=args.safety, business=args.business,
      transit_load=args.transit_load)``
    """
    stack = [EventSurge(events=sc.events), EconomicLens()]
    if weather:
        stack.append(
            WeatherLens(
                peak_time=sc.event_end,
                intensity=_WEATHER_INTENSITY,
                width=_WEATHER_WIDTH,
                crowd_size=sc.total_crowd,
            )
        )
    if safety:
        # The civic risk app, made literal: lift address-level safety risk onto the
        # substrate and price crowd crush through the least-safe districts.
        stack.append(SafetyLens(civic_safety_by_node(sc.substrate)))
    if business:
        # Price the local trade a crush destroys, so the levers are optimized for
        # transit + safety + economics together.
        stack.append(BusinessFlow(sc.venue_id))
    if transit_load:
        # Add REAL background ridership as an honest extra source term — people entering
        # the transit system on top of the event egress. No lever, no J cost (ADR-0029).
        # Source: TMC throughput (default) or TTC subway boardings (ADR-0031).
        if transit_source == "ttc":
            counts = ttc_boardings_by_node(sc.substrate)
        else:
            counts = observed_counts_by_node(sc.substrate)
        stack.append(TransitLoadLens(counts))
    return stack


def extra_display_lenses(sc=None) -> list:
    """The four supplementary intelligence lenses — EMS-access, emissions,
    noise/livability, fare-revenue.

    These are **additive and display-only**: each reads only the crowd fields and
    contributes its own per-node field + priced term, surfaced in ``/lenses`` with
    a baseline/optimized/saved figure (and proven non-perturbing by the additivity
    contract test). They are deliberately NOT summed into the optimizer's objective
    ``J``, so promoting a lens to a *decision* objective (which would move the
    headline numbers) stays an explicit, separate choice — the demo's calibrated
    transit+safety+business figures are unchanged.

    When a scenario ``sc`` is given, ``NoiseLivabilityLens`` is grounded in the REAL
    civic Activity overlay (building permits + business licences fused onto nodes,
    ADR-0014) — the same address→node fusion ``SafetyLens`` uses — and
    ``CongestionNowcastLens`` is grounded in the REAL observed-count series (Toronto
    TMC 15-min counts fused onto nodes, the temporal twin of that fusion). Without
    ``sc`` (or if data is absent) both fall back to deterministic synthetic series.

    ``CongestionNowcastLens`` is the data-driven *calibration* lens (Phase 1 of
    ``docs/research/tpf-and-data-driven-lenses.md``): advisory-only, no levers, no
    cost — it reports how well the kernel's crowd profile matches what was actually
    measured, and like the others is excluded from the optimizer's objective ``J``.

    ``MobilityDemandLens`` is the data-driven *demand* display lens (Fit C, ADR-0030):
    Bike Share trip origins ("demand to leave") lifted onto the substrate via
    ``adapters.bikeshare_demand_by_node`` (synthetic fallback until a slice is committed).
    It writes only its own ``bike_demand`` overlay — read-only on the crowd fields, no
    lever, no cost — so it too is advisory-only and excluded from ``J``.
    """
    if sc is not None:
        noise = NoiseLivabilityLens(civic_activity_by_node(sc.substrate))
        nowcast = CongestionNowcastLens(observed_counts_by_node(sc.substrate))
        mobility = MobilityDemandLens(bikeshare_demand_by_node(sc.substrate))
    else:
        noise = NoiseLivabilityLens()
        nowcast = CongestionNowcastLens()
        mobility = MobilityDemandLens()
    return [EmsAccessLens(), EmissionsLens(), noise, FareRevenueLens(), nowcast, mobility]
