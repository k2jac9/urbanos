"""Toronto adapter.

`downtown_scenario()` returns a deterministic, fully-offline downtown substrate
plus the default Event-Surge scenario (a stadium egress wave). Coordinates are
real downtown locations so the heatmap lands on the offline basemap; capacities
are plausibility-calibrated (flagged in provenance), not measured.

The topology is built so the egress crowd funnels through **Union** — whose
outbound rail/subway throughput is the binding constraint — making Union the
station the simulation surfaces as the bottleneck. On the GX10 this graph is
replaced by a real TTC GTFS + traffic-volume build via the existing CKANClient;
the lenses and kernel are unchanged (that swap is the whole point of an adapter).
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from ..kernel.state import Substrate

# (id, label, lat, lng, capacity[persons]) — real downtown coordinates.
# `capacity` is a reference comfortable occupancy; load can exceed it (ρ > 1 is
# the crush). Sinks are effectively unbounded outflow lines.
_NODES: list[tuple[str, str, float, float, float]] = [
    ("stadium", "Rogers Centre (venue)", 43.6414, -79.3894, 60000.0),
    ("union", "Union Station", 43.6452, -79.3806, 6000.0),
    ("st_andrew", "St Andrew", 43.6479, -79.3849, 2000.0),
    ("king", "King", 43.6489, -79.3777, 2000.0),
    ("queen", "Queen", 43.6526, -79.3793, 2000.0),
    ("st_patrick", "St Patrick", 43.6549, -79.3884, 2000.0),
    ("sink_east", "GO/Lakeshore East", 43.6450, -79.3700, 1.0e9),
    ("sink_north", "Line 1 North", 43.6600, -79.3850, 1.0e9),
    ("sink_west", "GO/Lakeshore West", 43.6400, -79.4000, 1.0e9),
]

# (src, dst, capacity[persons/min], length) — directed toward the exits.
# Most of the crowd routes to Union (high inbound link), but Union's outbound
# rail/subway throughput is only ~800/min — the binding constraint — so a queue
# piles up there. The St Andrew / St Patrick paths are relief valves with ample
# downstream capacity, so they drain freely and never become the bottleneck.
_EDGES: list[tuple[str, str, float, float]] = [
    ("stadium", "union", 1500.0, 1.0),     # dominant route — most of the crowd
    ("stadium", "st_andrew", 300.0, 1.2),
    ("stadium", "st_patrick", 250.0, 1.4),
    ("union", "sink_east", 400.0, 2.0),    # bottleneck (Union outbound ~800/min)
    ("union", "sink_north", 400.0, 2.0),   # bottleneck (Union outbound ~800/min)
    ("st_andrew", "king", 800.0, 0.6),
    ("king", "sink_east", 800.0, 1.2),
    ("st_patrick", "queen", 800.0, 0.8),
    ("queen", "sink_north", 800.0, 1.2),
]


@dataclass
class Scenario:
    """A ready-to-run setup: the substrate plus default Event-Surge parameters."""

    substrate: Substrate
    venue_id: str
    crowd_size: float
    event_end: float       # minutes into the sim window
    horizon: int           # number of minute-steps to simulate
    dt: float = 1.0


def _downtown_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    for nid, label, lat, lng, cap in _NODES:
        g.add_node(nid, label=label, lat=lat, lng=lng, capacity=cap)
    for u, v, cap, length in _EDGES:
        g.add_edge(u, v, capacity=cap, length=length)
    return g


def downtown_substrate() -> Substrate:
    sinks = [nid for nid, *_ in _NODES if nid.startswith("sink_")]
    return Substrate.from_graph(_downtown_graph(), sinks=sinks)


def downtown_scenario(crowd_size: float = 45000.0) -> Scenario:
    """Default demo scenario: a ~45k stadium empties ~30 min into a 90-min window."""
    return Scenario(
        substrate=downtown_substrate(),
        venue_id="stadium",
        crowd_size=crowd_size,
        event_end=30.0,
        horizon=120,
        dt=1.0,
    )
