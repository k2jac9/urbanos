"""Substrate (the graph + its baked-down arrays) and State (named fields).

The substrate is domain-agnostic: a directed graph whose nodes are places
(stations / intersections / venues / exits) and whose edges carry a per-minute
throughput *capacity*. A city adapter produces one of these; lenses never build
graphs themselves.

For the hot loop we bake the graph into flat numpy arrays once. Everything a
step needs — who drains to whom, how much each link can pass, how far each node
is from an exit — is precomputed here so the integrator is pure array math.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
import numpy as np


@dataclass
class Substrate:
    """A baked road/transit graph. Build via :meth:`from_graph`.

    Node arrays are indexed ``0..N-1`` in a fixed order; edge arrays are indexed
    ``0..E-1``. ``dist_to_sink`` drives transport: load flows "downhill" toward
    the nearest exit, so a link is *draining* iff its head is closer to an exit
    than its tail.
    """

    ids: list[str]                 # node id per index (stable order)
    labels: list[str]              # human label per index
    lat: np.ndarray                # (N,) latitude
    lng: np.ndarray                # (N,) longitude
    capacity: np.ndarray           # (N,) holding capacity (persons) — density scale
    is_sink: np.ndarray            # (N,) bool: exits/home — absorb arriving load
    edge_src: np.ndarray           # (E,) tail node index
    edge_dst: np.ndarray           # (E,) head node index
    edge_cap: np.ndarray           # (E,) link throughput (persons / minute)
    dist_to_sink: np.ndarray       # (N,) graph distance to nearest sink
    index: dict[str, int] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.ids)

    @property
    def n_edges(self) -> int:
        return int(self.edge_src.size)

    def idx(self, node_id: str) -> int:
        return self.index[node_id]

    @classmethod
    def from_graph(cls, g: nx.DiGraph, sinks: list[str]) -> "Substrate":
        """Bake a networkx DiGraph. Node attrs read: ``label``, ``lat``, ``lng``,
        ``capacity`` (default 1.0). Edge attr read: ``capacity`` (persons/min,
        default 1.0), ``length`` (for routing distance, default 1.0)."""
        ids = list(g.nodes())
        index = {nid: i for i, nid in enumerate(ids)}
        n = len(ids)
        labels = [str(g.nodes[nid].get("label", nid)) for nid in ids]
        lat = np.array([float(g.nodes[nid].get("lat", 0.0)) for nid in ids])
        lng = np.array([float(g.nodes[nid].get("lng", 0.0)) for nid in ids])
        capacity = np.array(
            [float(g.nodes[nid].get("capacity", 1.0)) for nid in ids], dtype=float
        )
        sink_set = set(sinks)
        is_sink = np.array([nid in sink_set for nid in ids], dtype=bool)

        e_src, e_dst, e_cap = [], [], []
        for u, v, data in g.edges(data=True):
            e_src.append(index[u])
            e_dst.append(index[v])
            e_cap.append(float(data.get("capacity", 1.0)))

        # Distance to the nearest sink, over edge `length`, on the *reversed*
        # graph (we want "how far is an exit reachable from here"). Unreachable
        # nodes get +inf and simply never drain.
        rev = g.reverse(copy=False)
        dist = np.full(n, np.inf)
        if sink_set:
            lengths = nx.multi_source_dijkstra_path_length(
                rev, sink_set, weight="length"
            )
            for nid, d in lengths.items():
                dist[index[nid]] = float(d)

        return cls(
            ids=ids,
            labels=labels,
            lat=lat,
            lng=lng,
            capacity=capacity,
            is_sink=is_sink,
            edge_src=np.array(e_src, dtype=np.int64),
            edge_dst=np.array(e_dst, dtype=np.int64),
            edge_cap=np.array(e_cap, dtype=float),
            dist_to_sink=dist,
            index=index,
        )


class State:
    """Named fields over the substrate's nodes, plus the clock.

    Fields are ``(N,)`` float arrays addressed by name. ``load`` (people present)
    is the conserved quantity transport moves; couplings derive ``congestion``
    and ``risk`` from it. Lenses read/write fields by name and never touch the
    substrate's baked arrays.
    """

    def __init__(self, substrate: Substrate, params: dict | None = None) -> None:
        self.substrate = substrate
        self.params: dict = dict(params or {})
        self.t: float = 0.0            # minutes since start
        self.step: int = 0
        self.fields: dict[str, np.ndarray] = {}
        # Always-present fields the kernel relies on.
        self.fields["load"] = np.zeros(substrate.n)
        self.fields["congestion"] = np.zeros(substrate.n)
        self.fields["risk"] = np.zeros(substrate.n)
        self.fields["arrived"] = np.zeros(substrate.n)  # cumulative absorbed at sinks

    def field(self, name: str) -> np.ndarray:
        """Get a field, creating a zeroed one on first use (lenses add fields)."""
        if name not in self.fields:
            self.fields[name] = np.zeros(self.substrate.n)
        return self.fields[name]
