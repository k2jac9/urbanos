"""City adapters — turn a city's open data into a kernel substrate.

An adapter is one half of the two-axis architecture: it builds the road/transit
graph and baseline fields for a city. Lenses then run on whatever an adapter
produces, unchanged. Toronto ships here; pointing a CKAN adapter at another
portal (``CKAN_URL`` swap) yields a new substrate with no lens changes.
"""
from __future__ import annotations

from .toronto import (
    Scenario,
    bikeshare_demand_by_node,
    civic_activity_by_node,
    civic_safety_by_node,
    downtown_scenario,
    observed_counts_by_node,
    reset_bikeshare_demand_cache,
    reset_observed_counts_cache,
    footfall_by_node,
    reset_road_disruption_cache,
    reset_road_risk_cache,
    reset_transit_supply_cache,
    reset_ttc_boardings_cache,
    road_disruption_by_node,
    road_risk_by_node,
    transit_supply_by_node,
    ttc_boardings_by_node,
)

__all__ = [
    "Scenario",
    "downtown_scenario",
    "civic_safety_by_node",
    "civic_activity_by_node",
    "observed_counts_by_node",
    "reset_observed_counts_cache",
    # Bike Share trip-origin demand (origins-as-demand) — the MobilityDemand grounding.
    "bikeshare_demand_by_node",
    "reset_bikeshare_demand_cache",
    # TTC subway boardings (real magnitude, modelled shape) — a TransitLoad source (ADR-0031).
    "ttc_boardings_by_node",
    "reset_ttc_boardings_cache",
    # Transit supply (real GTFS evening departures) — a display overlay (ADR-0032).
    "transit_supply_by_node",
    "reset_transit_supply_cache",
    # Road risk (real Vision Zero / KSI collisions) — a display overlay (ADR-0036).
    "road_risk_by_node",
    "reset_road_risk_cache",
    # Ambient pedestrian footfall (TMC ped counts, mode="ped") — the Footfall display lens (ADR-0037).
    "footfall_by_node",
    # Road disruption (real active road closures / restrictions) — a display overlay (ADR-0038).
    "road_disruption_by_node",
    "reset_road_disruption_cache",
]
