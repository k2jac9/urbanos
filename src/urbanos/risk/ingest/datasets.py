"""Registry of the City of Toronto open datasets this project fuses.

Slugs verified against open.toronto.ca. Freshness notes drive which we lean on:
permits + DineSafe are daily/frequent and address-level; 311 is monthly and
ward-level only; business licences enrich the entity graph.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dataset:
    slug: str            # CKAN package id on open.toronto.ca
    title: str
    cadence: str         # update frequency
    geo: str             # finest geography available
    notes: str


REGISTRY: dict[str, Dataset] = {
    "permits": Dataset(
        slug="building-permits-active-permits",
        title="Building Permits — Active Permits",
        cadence="daily",
        geo="address",
        notes="Includes review/inspection stages; freshest, richest signal.",
    ),
    "permits_cleared": Dataset(
        slug="building-permits-cleared-permits",
        title="Building Permits — Cleared Permits",
        cadence="daily",
        geo="address",
        notes="Historical closures; pairs with active for the permit lifecycle.",
    ),
    "dinesafe": Dataset(
        slug="dinesafe",
        title="DineSafe — Food Premises Inspections",
        cadence="daily",
        geo="address",
        notes="Real inspection outcomes/infractions — strong safety-risk signal.",
    ),
    "311": Dataset(
        slug="311-service-requests-customer-initiated",
        title="311 Service Requests (Customer Initiated)",
        cadence="monthly",
        geo="ward / intersection / FSA",
        notes="No lat/long; ~30-35% coverage, 6 of 45 divisions. Use as area signal.",
    ),
    "licences": Dataset(
        slug="municipal-licensing-and-standards-business-licences-and-permits",
        title="Business Licences & Permits",
        cadence="daily",
        geo="address",
        notes="Ties a premises to an operator entity for the knowledge graph.",
    ),
    # --- dynamic, time-marginal datasets (the observed-flow signal) --------------
    # Unlike the static address attributes above, these carry a TIME axis: counts /
    # boardings in repeated buckets. They are the "density snapshot over time" shape
    # the LearnedDynamics lens consumes (docs/research/tpf-and-data-driven-lenses.md)
    # and that the deterministic CongestionNowcast lens calibrates the kernel against.
    "tmc": Dataset(
        slug="traffic-volumes-at-intersections-for-all-modes",
        title="Traffic Volumes — Multimodal Intersection Turning-Movement Counts",
        cadence="daily",
        geo="intersection",
        notes="Cars/cyclists/PEDESTRIANS in 15-min buckets at intersections (lat/lng). "
        "Per-node observed throughput vs time — no per-person trajectories.",
    ),
    "ttc_ridership": Dataset(
        slug="ttc-ridership-analysis",
        title="TTC Ridership Analysis",
        cadence="periodic",
        geo="station / route",
        notes="Boardings (first point of payment) — a real source term for transit relays.",
    ),
    "bikeshare": Dataset(
        slug="bike-share-toronto-ridership-data",
        title="Bike Share Toronto Ridership",
        cadence="monthly",
        geo="station",
        notes="Anonymised trip OD + timestamps (1000+ stations; coords via the GBFS station "
        "feed). Read here as ORIGINS-AS-DEMAND: trip starts per station per 15-min bin = the "
        "local 'demand to leave' field the MobilityDemand display lens (ADR-0030) lifts onto "
        "the substrate. A committed downtown slice (demo_data/bikeshare__downtown.csv, built by "
        "scripts/fetch_bikeshare.py) backs the demo; synthetic fallback in CI/dev.",
    ),
    "ttc_station_usage": Dataset(
        slug="ttc-ridership-subway-scarborough-rt-station-usage",
        title="TTC Subway Station Usage",
        cadence="periodic",
        geo="station",
        notes="Real typical-weekday boardings per subway station (XLSX). The REAL MAGNITUDE "
        "behind the TTC TransitLoad source (ADR-0031): a committed downtown slice "
        "(demo_data/ttc_boardings__downtown.csv, built by scripts/fetch_ttc_boardings.py) "
        "carries the real per-station daily totals; the intraday shape is modelled in the "
        "adapter. Daily totals only — no 15-min/APC data is public, so the shape is modelled.",
    ),
    "ttc_gtfs": Dataset(
        slug="ttc-routes-and-schedules",
        title="TTC Routes and Schedules (GTFS)",
        cadence="periodic",
        geo="stop",
        notes="GTFS ZIP (stops + stop_times). Used for transit SUPPLY: real scheduled evening "
        "departures per stop (ADR-0032), the supply signal paired with the demand sources. "
        "Committed downtown slice demo_data/transit_supply__downtown.csv via "
        "scripts/fetch_gtfs_supply.py; synthetic fallback in CI/dev. (No clean subway-station "
        "coords here — only mixed platform/surface stops.)",
    ),
}


def get(name: str) -> Dataset:
    if name not in REGISTRY:
        raise KeyError(f"unknown dataset {name!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[name]
