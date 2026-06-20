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

import logging
import os
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

_log = logging.getLogger(__name__)

# Which backend computed the last substrate shortest-paths bake — "cugraph" (GPU,
# RAPIDS nx-cugraph) or "networkx" (CPU). Exposed for the `make gpu-check` proof and
# the wiring test; the value reflects what ACTUALLY ran, not what was requested.
GRAPH_BACKEND: str = "networkx"


def _gpu_graph_enabled() -> bool:
    """GPU graph backend is opt-in: set ``URBANOS_GPU_GRAPH=1`` (or the standard
    ``NX_CUGRAPH_AUTOCONFIG=True``) on a box where ``nx-cugraph`` is installed.

    Off by default so the demo venv / CI (no CUDA libs) and the tiny demo graph are
    untouched — exactly the Rust-accelerator opt-in pattern (ADR-0004/0009). The
    GPU backend pays off at city scale (real GTFS, thousands of nodes), not on the
    17/459-node demo substrate, where CPU is used and is faster."""
    return bool(
        os.environ.get("URBANOS_GPU_GRAPH", "").strip().lower() in {"1", "true", "yes"}
        or os.environ.get("NX_CUGRAPH_AUTOCONFIG", "").strip().lower() in {"1", "true"}
    )


# Sentinel id for the virtual super-source (NUL-prefixed so it can't collide with a
# real node id). See ``_supersource_sssp``.
_SUPERSOURCE = "\x00__supersource__"


def _supersource_sssp(rev: nx.DiGraph, sources: set, *, backend: str | None = None) -> dict:
    """Multi-source-to-nearest shortest paths via a virtual super-source + a SINGLE
    -source Dijkstra — the reformulation RAPIDS ``cugraph`` supports (it implements
    ``single_source_dijkstra_path_length`` but not the multi-source variant). Adding a
    zero-length edge from the super-source to every sink makes single-source distance
    == min-over-sinks distance, i.e. byte-identical to
    ``multi_source_dijkstra_path_length(rev, sources)``. Runs on a private copy, so the
    caller's graph is never mutated."""
    tmp = nx.DiGraph()
    tmp.add_weighted_edges_from(
        ((u, v, float(d.get("length", 1.0))) for u, v, d in rev.edges(data=True)),
        weight="length",
    )
    for s in sources:
        tmp.add_edge(_SUPERSOURCE, s, length=0.0)
    kwargs = {"backend": backend} if backend else {}
    out = nx.single_source_dijkstra_path_length(tmp, _SUPERSOURCE, weight="length", **kwargs)
    out.pop(_SUPERSOURCE, None)
    return dict(out)


def _multi_source_dijkstra_lengths(rev: nx.DiGraph, sources: set) -> dict:
    """Multi-source shortest-path lengths over edge ``length`` to the sink set.

    GPU path (``URBANOS_GPU_GRAPH=1`` + ``nx-cugraph`` installed): the super-source
    single-source reformulation runs on the ``cugraph`` GPU backend. Otherwise (or on
    any error) the well-tested networkx CPU ``multi_source_dijkstra_path_length`` runs.
    Records the backend in ``GRAPH_BACKEND``. Identical result either way — a drop-in
    accelerator, never a behaviour change (we fall back rather than trust a partial
    GPU result). On the demo-size graph CPU is used/faster; cugraph pays off at city
    scale (real GTFS, thousands of nodes)."""
    global GRAPH_BACKEND
    if _gpu_graph_enabled():
        try:
            lengths = _supersource_sssp(rev, sources, backend="cugraph")
            GRAPH_BACKEND = "cugraph"
            return lengths
        except Exception as exc:  # backend missing / unsupported / runtime error
            _log.warning("nx-cugraph backend unavailable, using CPU networkx: %s", exc)
    GRAPH_BACKEND = "networkx"
    return nx.multi_source_dijkstra_path_length(rev, sources, weight="length")


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
            # RAPIDS nx-cugraph GPU backend when enabled+installed, else CPU networkx
            # (identical result; see ``_multi_source_dijkstra_lengths``).
            lengths = _multi_source_dijkstra_lengths(rev, sink_set)
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
        # Per-step transport capacity multiplier (E,), reset to 1.0 each step by the
        # loop. Lenses that tax link throughput (e.g. WeatherLens rain) MULTIPLY into
        # this instead of mutating the shared, baked ``substrate.edge_cap`` — so the
        # substrate stays immutable across steps/runs/optimizer trials (ADR-0021).
        self.edge_cap_mult = np.ones(substrate.n_edges)

    def field(self, name: str) -> np.ndarray:
        """Get a field, creating a zeroed one on first use (lenses add fields)."""
        if name not in self.fields:
            self.fields[name] = np.zeros(self.substrate.n)
        return self.fields[name]
