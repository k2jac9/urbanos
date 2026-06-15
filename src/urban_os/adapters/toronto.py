"""Toronto adapter — FIFA World Cup 2026 downtown concurrent-event scenario.

``downtown_scenario()`` returns a deterministic, fully-offline downtown substrate
plus the default Event-Surge scenario — the **Fan-Festival-window "convergence
crunch"**: on peak FIFA days multiple major downtown venues let out into the same
transit corridor at once. Coordinates are real downtown locations so the heatmap
lands on the offline basemap; capacities are plausibility-calibrated (flagged in
provenance), not measured.

Why this scenario (researched, real anchors — see ADR-0018):
- **BMO Field** ("Toronto Stadium") hosts Toronto's FIFA 2026 matches (opener
  Canada v Bosnia, Jun 12; Germany v Côte d'Ivoire, Jun 20; Round-of-32, Jul 2;
  FIFA capacity 45,736). Its *only* adjacent rail is **Exhibition GO**, one stop
  from Union on the Lakeshore West line — so ~46k funnel through a single station.
- **Rogers Centre** (Blue Jays) is ~500 m away; **Scotiabank Arena** (concerts)
  is attached to **Union** itself. Both empty straight onto Union.
- The **FIFA Fan Festival** (Fort York / The Bentway, Jun 12 – Jul 2, ticketed at
  $10 to offset a $6.2 M city deficit) plus pop-up pitches (Harbourfront futsal,
  Nathan Phillips Sq) add sustained fan-zone load.

The topology is built so the egress crowds funnel through **Union** — whose
outbound rail/subway throughput is the binding constraint — making Union the
convergence bottleneck the simulation surfaces, with **Exhibition GO** the
FIFA-specific secondary crush. The whole point: one coordinated release/shelter
lever, optimized across every concurrent event, is what saves the city money.
On the GX10 this graph is replaced by a real TTC GTFS + traffic-volume build via
the existing CKANClient; the lenses and kernel are unchanged (that swap is the
whole point of an adapter).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import networkx as nx

from ..kernel.state import Substrate

_log = logging.getLogger(__name__)

# (id, label, lat, lng, capacity[persons], group) — real downtown coordinates.
# `capacity` is a reference comfortable occupancy; load can exceed it (ρ > 1 is
# the crush). Sinks are effectively unbounded outflow lines.
# `group` drives the map: venue (event source) / fanzone (FIFA pop-up, toggleable)
# / transit (relay station) / exit (drain line).
_NODES: list[tuple[str, str, float, float, float, str]] = [
    # --- event sources (the concurrent let-outs) -----------------------------
    ("bmo_field", "BMO Field — FIFA (Canada v Bosnia)", 43.6332, -79.4185, 46000.0, "venue"),
    ("stadium", "Rogers Centre — Blue Jays v Yankees", 43.6414, -79.3894, 50000.0, "venue"),
    ("scotia", "Scotiabank Arena — concert", 43.6435, -79.3791, 19800.0, "venue"),
    # --- FIFA fan zones (toggleable so they don't over-populate the map) ------
    ("fort_york", "FIFA Fan Festival — Fort York", 43.6386, -79.4080, 30000.0, "fanzone"),
    ("harbourfront", "Floating Futsal — Harbourfront", 43.6386, -79.3833, 4000.0, "fanzone"),
    ("nathan_phillips", "Pop-up Pitch — Nathan Phillips Sq", 43.6525, -79.3839, 6000.0, "fanzone"),
    # --- transit relays -------------------------------------------------------
    ("exhibition_go", "Exhibition GO", 43.6346, -79.4163, 3600.0, "transit"),
    ("union", "Union Station", 43.6452, -79.3806, 6000.0, "transit"),
    ("bathurst", "Bathurst (504/511)", 43.6447, -79.4023, 2000.0, "transit"),
    ("st_andrew", "St Andrew", 43.6479, -79.3849, 2000.0, "transit"),
    ("king", "King", 43.6489, -79.3777, 2000.0, "transit"),
    ("queen", "Queen", 43.6526, -79.3793, 2000.0, "transit"),
    ("st_patrick", "St Patrick", 43.6549, -79.3884, 2000.0, "transit"),
    ("osgoode", "Osgoode", 43.6505, -79.3866, 2000.0, "transit"),
    # --- real exit lines (replace the old abstract sinks that clustered at Union)
    ("sink_lakeshore_w", "Lakeshore West → Mimico", 43.6300, -79.4270, 1.0e9, "exit"),
    ("sink_lakeshore_e", "Lakeshore East → Danforth", 43.6470, -79.3540, 1.0e9, "exit"),
    ("sink_line1", "Line 1 → Bloor (north)", 43.6600, -79.3870, 1.0e9, "exit"),
]

# id -> group, for the map UI (styling + the FIFA fan-zone toggle).
NODE_GROUPS: dict[str, str] = {nid: group for nid, _, _, _, _, group in _NODES}

# (src, dst, capacity[persons/min], length) — directed toward the exits.
# Union is the convergence bottleneck: Rogers Centre, Scotiabank Arena, the BMO
# Field overflow off Exhibition GO and the waterfront fan zones all route into it,
# while its outbound rail/subway throughput is only ~2,450/min — so a queue piles
# up there. Exhibition GO is the FIFA-specific secondary crush (one station for
# 46k). The subway relief paths (St Andrew/St Patrick/Osgoode) have ample
# downstream capacity, so they drain freely and never become the bottleneck.
#
# Edge `length` sets the routing gradient (``dist_to_sink`` = shortest length to
# an exit): load only flows "downhill". Lengths are chosen so the venues drain
# *through* Union (Union sits closest to the exit lines, dist 1.0), Exhibition GO
# routes its BMO crowd primarily into Union (one stop on Lakeshore West), and the
# St Andrew/King + St Patrick/Queen + Osgoode subway paths stay comparable-length
# so they remain active relief valves rather than dead uphill links.
_EDGES: list[tuple[str, str, float, float]] = [
    # BMO Field egress — almost everyone funnels to the single adjacent station.
    ("bmo_field", "exhibition_go", 1300.0, 0.5),
    ("bmo_field", "bathurst", 400.0, 1.0),       # 509/511 streetcar relief
    ("bmo_field", "fort_york", 200.0, 0.6),      # some drift to the fan festival
    # Rogers Centre egress — Union-dominant (the ballgame crowd).
    ("stadium", "union", 1400.0, 1.0),
    ("stadium", "st_andrew", 350.0, 1.0),
    ("stadium", "st_patrick", 300.0, 1.0),
    # Scotiabank Arena egress — attached to Union, dumps straight in.
    ("scotia", "union", 850.0, 0.5),
    ("scotia", "king", 300.0, 0.6),
    # Fan zones drain to the nearest transit.
    ("fort_york", "exhibition_go", 350.0, 0.8),
    ("fort_york", "bathurst", 400.0, 0.6),
    ("harbourfront", "union", 450.0, 0.9),       # 509 along the waterfront
    ("nathan_phillips", "queen", 400.0, 0.5),
    ("nathan_phillips", "osgoode", 350.0, 0.4),
    # Exhibition GO — the FIFA secondary crush (one station for 46k); most of its
    # crowd rides one stop into Union, a slice drains west on Lakeshore West.
    ("exhibition_go", "union", 1300.0, 0.8),
    ("exhibition_go", "sink_lakeshore_w", 300.0, 2.0),
    # Bathurst relief.
    ("bathurst", "union", 500.0, 0.8),
    ("bathurst", "sink_lakeshore_w", 600.0, 1.5),
    # Union — the convergence bottleneck (outbound ~2,450/min vs ≫ inflow).
    ("union", "sink_lakeshore_e", 850.0, 1.0),
    ("union", "sink_line1", 850.0, 1.0),
    ("union", "sink_lakeshore_w", 750.0, 1.2),
    # Subway relief valves — ample downstream capacity, never the bottleneck.
    ("st_andrew", "king", 800.0, 0.8),
    ("king", "sink_lakeshore_e", 900.0, 1.0),
    ("st_patrick", "queen", 800.0, 0.8),
    ("queen", "sink_line1", 900.0, 1.0),
    ("osgoode", "sink_line1", 900.0, 1.0),
]

# The concurrent let-outs that make up the convergence crunch: (venue_id,
# crowd_size, event_end[min into the window]). Staggered ends (28–42 min) model
# the realistic overlap — the FIFA match, the ballgame, the concert and the fan
# festival don't end at the same instant, but their egress tails pile up together.
_EVENTS: list[tuple[str, float, float]] = [
    ("bmo_field", 46000.0, 28.0),   # FIFA full-time
    ("fort_york", 30000.0, 35.0),   # fan festival wind-down
    ("scotia", 19800.0, 38.0),      # concert ends
    ("stadium", 45000.0, 42.0),     # ballgame ends
]


@dataclass
class Scenario:
    """A ready-to-run setup: the substrate plus default Event-Surge parameters.

    ``events`` is the full set of concurrent let-outs (the convergence crunch).
    ``venue_id``/``crowd_size``/``event_end`` mirror the *primary* event (BMO
    Field) so single-venue callers and tests keep working; ``total_crowd`` is the
    sum across all events (what the full multi-venue sim injects)."""

    substrate: Substrate
    venue_id: str
    crowd_size: float
    event_end: float       # minutes into the sim window
    horizon: int           # number of minute-steps to simulate
    dt: float = 1.0
    events: list[tuple[str, float, float]] = field(default_factory=list)

    @property
    def total_crowd(self) -> float:
        """People injected across every concurrent event (≥ the primary crowd)."""
        if not self.events:
            return self.crowd_size
        return float(sum(c for _, c, _ in self.events))


def _downtown_graph() -> nx.DiGraph:
    g = nx.DiGraph()
    for nid, label, lat, lng, cap, group in _NODES:
        g.add_node(nid, label=label, lat=lat, lng=lng, capacity=cap, group=group)
    for u, v, cap, length in _EDGES:
        g.add_edge(u, v, capacity=cap, length=length)
    return g


def downtown_substrate() -> Substrate:
    sinks = [nid for nid, *_ in _NODES if nid.startswith("sink_")]
    return Substrate.from_graph(_downtown_graph(), sinks=sinks)


def downtown_scenario(crowd_size: float | None = None) -> Scenario:
    """Default demo scenario: the FIFA-window convergence crunch — multiple
    downtown venues empty into the same corridor over a ~90-min window.

    ``crowd_size`` (optional) overrides the **primary** (BMO Field) crowd only,
    for single-venue callers/tests; the other concurrent events keep their
    researched sizes. With no override the full quad-crunch runs."""
    events = list(_EVENTS)
    if crowd_size is not None:
        # Override the primary (first) event's crowd; keep the rest.
        primary = events[0]
        events[0] = (primary[0], float(crowd_size), primary[2])
    primary_id, primary_crowd, primary_end = events[0]
    return Scenario(
        substrate=downtown_substrate(),
        venue_id=primary_id,
        crowd_size=primary_crowd,
        event_end=primary_end,
        horizon=120,
        dt=1.0,
        events=events,
    )


def _synthetic_safety_by_node(substrate) -> dict[str, float]:
    """Deterministic placeholder civic-safety overlay (no civic data needed):
    denser interchanges carry more street-level safety exposure. Bounded 0..0.6.
    Keeps Urban-OS standalone and tests offline when the civic graph is absent."""
    import numpy as np

    cap = substrate.capacity.astype(float)
    base = np.where(~substrate.is_sink, cap, 0.0)
    peak = float(base.max())
    vals = (base / peak) * 0.6 if peak > 0 else base
    return {nid: float(vals[i]) for i, nid in enumerate(substrate.ids)}


_CIVIC_ADDRS_CACHE: list | None = None


def reset_civic_address_cache() -> None:
    """Clear the cached civic-address overlay. Lets tests/long-running servers reset
    the process-global cache deterministically (ADR-0023)."""
    global _CIVIC_ADDRS_CACHE
    _CIVIC_ADDRS_CACHE = None


def _default_civic_addresses() -> list:
    """Default address provider: civic addresses (coords + safety risk), loaded ONCE.
    civic_analyst's ``load()`` accumulates into a module-global graph, so calling it
    per request drifts the aggregated risk — cache the result so the overlay is
    stable. This is the only place the adapter touches civic internals; callers that
    want isolation can inject their own provider into ``civic_safety_by_node``."""
    global _CIVIC_ADDRS_CACHE
    if _CIVIC_ADDRS_CACHE is None:
        from civic_analyst import mcp_server as civ

        civ.load()
        _CIVIC_ADDRS_CACHE = [a for a in civ.top_risk(limit=2000) if a.get("lat") is not None]
    return _CIVIC_ADDRS_CACHE


def _civic_field_by_node(
    substrate, *, field: str, radius_deg: float = 0.0045, address_provider=None
) -> dict[str, float]:
    """Map each substrate node → the proximity-weighted ``field`` of its surrounding
    civic addresses (the civic_analyst graph). The shared core behind the safety and
    activity overlays — the **real fusion** of address-level civic data onto kernel
    nodes.

    ``field`` selects which per-address index to lift (``risk_safety`` or
    ``risk_activity``; both ship on every ``top_risk`` row, ADR-0014).
    ``address_provider`` is an injectable ``() -> list[dict]`` (ADR-0023). Raises on
    empty/failed providers so callers can fall back to a deterministic synthetic
    overlay (keeping Urban-OS standalone and tests offline)."""
    import numpy as np

    provider = address_provider or _default_civic_addresses
    addrs = provider()
    if not addrs:
        raise RuntimeError("no civic addresses loaded")
    out: dict[str, float] = {}
    for i, nid in enumerate(substrate.ids):
        la, lo = float(substrate.lat[i]), float(substrate.lng[i])
        num = den = 0.0
        for a in addrs:
            dlat = a["lat"] - la
            dlng = (a["lng"] - lo) * np.cos(np.radians(la))
            w = float(np.exp(-(dlat * dlat + dlng * dlng) / (radius_deg * radius_deg)))
            num += w * float(a.get(field, 0.0))
            den += w
        out[nid] = (num / den) if den > 0 else 0.0
    return out


def civic_safety_by_node(
    substrate, *, radius_deg: float = 0.0045, address_provider=None
) -> dict[str, float]:
    """Per-node civic-SAFETY overlay — the **real fusion** that makes ``SafetyLens``
    literal: address-level compliance-safety risk → a node field. Falls back to a
    deterministic synthetic overlay if the civic provider yields nothing or raises."""
    try:
        return _civic_field_by_node(
            substrate, field="risk_safety", radius_deg=radius_deg,
            address_provider=address_provider,
        )
    except Exception as exc:
        _log.warning("civic safety overlay failed, using synthetic fallback: %s", exc)
        return _synthetic_safety_by_node(substrate)


def civic_activity_by_node(
    substrate, *, radius_deg: float = 0.0045, address_provider=None
) -> dict[str, float]:
    """Per-node civic-ACTIVITY overlay — the real development/livability signal that
    grounds ``NoiseLivabilityLens``: the Activity index (building permits + business
    licences fused, ADR-0014) lifted onto the substrate by proximity. Where activity
    clusters is where a late-night egress crush disturbs the most livability-sensitive
    blocks. Falls back to the deterministic synthetic overlay when civic data is
    absent (so the lens still runs offline)."""
    try:
        return _civic_field_by_node(
            substrate, field="risk_activity", radius_deg=radius_deg,
            address_provider=address_provider,
        )
    except Exception as exc:
        _log.warning("civic activity overlay failed, using synthetic fallback: %s", exc)
        return _synthetic_safety_by_node(substrate)


# --- observed time-series fusion (the temporal twin of the civic overlays) -------
# Where the civic overlays above fuse a STATIC per-address scalar onto each node, the
# functions below fuse a TIME-VARYING per-location count series onto each node — the
# observed-throughput marginal the CongestionNowcast lens calibrates against. Same
# proximity kernel, same injectable-provider + synthetic-fallback shape (ADR-0023).

_OBSERVED_COUNTS_CACHE: list | None = None


def reset_observed_counts_cache() -> None:
    """Clear the cached observed-count records (parity with the civic-address cache;
    lets tests/long-running servers reset the process-global deterministically)."""
    global _OBSERVED_COUNTS_CACHE
    _OBSERVED_COUNTS_CACHE = None


def _default_observed_counts() -> list:
    """Default observed-count provider: the TMC 15-min slice via civic_analyst's
    time-series loader, read ONCE and cached (the file is small and immutable for a
    run). The only place the adapter reaches into civic ingest for counts; callers
    wanting isolation inject their own provider."""
    global _OBSERVED_COUNTS_CACHE
    if _OBSERVED_COUNTS_CACHE is None:
        from civic_analyst.ingest import timeseries

        _OBSERVED_COUNTS_CACHE = timeseries.load_counts()
    return _OBSERVED_COUNTS_CACHE


def _synthetic_counts_by_node(substrate) -> dict[str, dict[float, float]]:
    """Deterministic placeholder observed-count series (no real data needed): a single
    Gaussian-in-time throughput bump per non-sink node, scaled by node capacity, on a
    15-min grid over the demo window. Keeps Urban-OS standalone and tests offline."""
    import numpy as np

    cap = substrate.capacity.astype(float)
    peak = float(np.where(~substrate.is_sink, cap, 0.0).max()) or 1.0
    bins = [float(m) for m in range(0, 121, 15)]
    center, width = 60.0, 25.0
    out: dict[str, dict[float, float]] = {}
    for i, nid in enumerate(substrate.ids):
        scale = 0.0 if substrate.is_sink[i] else float(cap[i]) / peak
        out[nid] = {
            b: scale * 1000.0 * float(np.exp(-0.5 * ((b - center) / width) ** 2))
            for b in bins
        }
    return out


def _observed_counts_by_node(
    substrate, *, mode: str | None = None, radius_deg: float = 0.0045, provider=None
) -> dict[str, dict[float, float]]:
    """Map each substrate node → a ``{minute: count}`` series, by proximity-weighted
    averaging of the observed location counts in each 15-min bin. The temporal analogue
    of :func:`_civic_field_by_node`. ``minute`` is rebased so the first observed bin is
    0 (a relative observed-time axis; aligning it to the sim clock is the calibration
    lens's job — kept out of the data layer so this stays honest). Raises on an empty
    provider so the wrapper can fall back to a synthetic series."""
    import numpy as np

    recs = (provider or _default_observed_counts)()
    recs = [r for r in recs if r.get("lat") is not None and r.get("lng") is not None]
    if mode:
        recs = [r for r in recs if r.get("mode") in (mode, "all")]
    if not recs:
        raise RuntimeError("no observed counts loaded")
    t0 = min(float(r["minute"]) for r in recs)
    by_bin: dict[float, list] = {}
    for r in recs:
        by_bin.setdefault(float(r["minute"]) - t0, []).append(r)
    out: dict[str, dict[float, float]] = {}
    for i, nid in enumerate(substrate.ids):
        la, lo = float(substrate.lat[i]), float(substrate.lng[i])
        series: dict[float, float] = {}
        for b in sorted(by_bin):
            num = den = 0.0
            for r in by_bin[b]:
                dlat = r["lat"] - la
                dlng = (r["lng"] - lo) * np.cos(np.radians(la))
                w = float(np.exp(-(dlat * dlat + dlng * dlng) / (radius_deg * radius_deg)))
                num += w * float(r["volume"])
                den += w
            if den > 0:
                series[b] = num / den
        out[nid] = series
    return out


def observed_counts_by_node(
    substrate, *, mode: str | None = None, radius_deg: float = 0.0045, provider=None
) -> dict[str, dict[float, float]]:
    """Per-node OBSERVED throughput series — the real Toronto 15-min counts (TMC) lifted
    onto the substrate by proximity, ``{node_id: {minute: count}}``. ``mode`` optionally
    filters to e.g. ``"ped"``/``"bike"`` (records tagged ``"all"`` always pass). Falls
    back to a deterministic synthetic series when no count data is present, so the
    calibration lens still runs offline."""
    try:
        return _observed_counts_by_node(
            substrate, mode=mode, radius_deg=radius_deg, provider=provider
        )
    except Exception:
        return _synthetic_counts_by_node(substrate)
