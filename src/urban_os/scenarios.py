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

from .adapters import civic_activity_by_node, civic_safety_by_node
from .lenses import (
    BusinessFlow,
    EconomicLens,
    EmissionsLens,
    EmsAccessLens,
    EventSurge,
    FareRevenueLens,
    NoiseLivabilityLens,
    SafetyLens,
    WeatherLens,
)

# WeatherLens calibration for the default downtown demo (a passing rain cell that
# peaks with the egress wave). Kept here so both surfaces get identical weather.
_WEATHER_INTENSITY = 0.7
_WEATHER_WIDTH = 20.0


def default_lens_stack(
    sc, *, weather: bool = False, safety: bool = False, business: bool = False
) -> list:
    """Build the Urban-OS lens stack for scenario ``sc``.

    - ``weather``  → append WeatherLens (the shelter-coverage optimizer lever).
    - ``safety``   → append SafetyLens (civic address risk fused onto the substrate).
    - ``business`` → append BusinessFlow (local trade lost to the crush).

    The base (EventSurge + Economic) always runs. Callers:
    - API optimizer/narrator stack: ``default_lens_stack(sc, weather=True)``
    - API cross-domain 4-lens stack: ``default_lens_stack(sc, safety=True, business=True)``
    - CLI: ``default_lens_stack(sc, safety=args.safety, business=args.business)``
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
    ADR-0014) — the same address→node fusion ``SafetyLens`` uses. Without ``sc`` (or
    if civic data is absent) it falls back to its deterministic synthetic weight.
    """
    noise = (
        NoiseLivabilityLens(civic_activity_by_node(sc.substrate))
        if sc is not None
        else NoiseLivabilityLens()
    )
    return [EmsAccessLens(), EmissionsLens(), noise, FareRevenueLens()]
