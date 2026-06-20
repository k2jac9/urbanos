"""Build a knowledge graph linking addresses, premises, permits and inspections.

Nodes are typed (address / business / permit / inspection / request). Edges connect
a record to the address it occurred at, so a query for an address can traverse to
every related signal — the structure that won the NYC edition.
"""
from __future__ import annotations

import re

import networkx as nx


# Toronto bounding box (lat 43.5–43.9, lng −79.7 to −79.1). A swapped lat/lng or a
# coordinate from another city drops a pin in the ocean, so coordinates outside this
# box are rejected at the boundary and treated as missing. The ingest loader applies
# the same check pre-emptively; this is the last-line guard on the graph itself.
_TORONTO_LAT_MIN, _TORONTO_LAT_MAX = 43.5, 43.9
_TORONTO_LNG_MIN, _TORONTO_LNG_MAX = -79.7, -79.1


def in_toronto_bbox(lat: float | None, lng: float | None) -> bool:
    """True only if BOTH coordinates are present and inside the Toronto bbox."""
    if lat is None or lng is None:
        return False
    return (
        _TORONTO_LAT_MIN <= lat <= _TORONTO_LAT_MAX
        and _TORONTO_LNG_MIN <= lng <= _TORONTO_LNG_MAX
    )


# Long street-type words -> canonical abbreviation. Each rule is keyed on a *long*
# spelling, so a string already using the short form is left untouched — two formats
# of the same address therefore collapse to one key. (LANE has no shorter canonical
# in the data, so we fold the abbreviated "LN" up to "LANE" instead.)
_STREET_TYPES: dict[str, str] = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "BOULEVARD": "BLVD",
    "DRIVE": "DR",
    "ROAD": "RD",
    "COURT": "CRT",
    "CRESCENT": "CRES",
    "PLACE": "PL",
    "TERRACE": "TER",
    "PARKWAY": "PKWY",
    "HIGHWAY": "HWY",
    "SQUARE": "SQ",
    "TRAIL": "TRL",
    "GARDENS": "GDNS",
    "CIRCLE": "CIR",
    "LN": "LANE",
}

# Cardinal directions -> single letter. Longest compound forms first so "NORTHWEST"
# isn't half-consumed by the "NORTH" rule.
_DIRECTIONS: dict[str, str] = {
    "NORTHWEST": "NW",
    "NORTHEAST": "NE",
    "SOUTHWEST": "SW",
    "SOUTHEAST": "SE",
    "WEST": "W",
    "EAST": "E",
    "NORTH": "N",
    "SOUTH": "S",
}

# Unit / suite markers and everything that follows them is noise for a street-level
# join (a building fuses across its units). Matched as a whole trailing segment so
# "100 QUEEN ST W UNIT 5" -> "100 QUEEN ST W".
_UNIT_RE = re.compile(
    r"\b(?:UNIT|UNITS|STE|SUITE|APT|APARTMENT|FLR|FLOOR|RM|ROOM|PH|BSMT|"
    r"LOWER|UPPER|REAR)\b.*$"
)


def normalize_address(raw: str) -> str:
    """Cheap address key. Deterministic cleanup of the real-world quirks seen in
    Toronto open data (embedded 'None' for missing units, trailing postal codes,
    city/province suffixes, varied street-type spellings, unit/suite noise). The
    harder fuzzy entity-resolution is the local-LLM job — see agents/subagents."""
    # Drop a UTF-8 BOM first: str.strip() does NOT remove U+FEFF, so a
    # BOM-prefixed feed row (common in Excel/Windows CSV exports) would otherwise
    # fail to join with the clean address key and silently drop its records.
    s = raw.replace("\ufeff", "").upper().strip()
    # '#' introduces a unit; turn it into a UNIT marker so the unit segment is dropped
    # below (and a trailing unit number can't masquerade as a street number).
    s = s.replace("#", " UNIT ")
    # Strip punctuation that varies between feeds ("ST." vs "ST", "1/2", "A;B").
    # Apostrophes are preserved so O'CONNOR stays one token.
    s = re.sub(r"[.,;:/\\]", " ", s)
    # Drop Canadian postal codes (e.g. "M4A 1X1") and literal 'NONE' unit placeholders.
    s = re.sub(r"\b[A-Z]\d[A-Z]\s*\d[A-Z]\d\b", " ", s)
    s = re.sub(r"\bNONE\b", " ", s)
    s = re.sub(r"\b(TORONTO|ONTARIO|ON|CANADA)\b", " ", s)
    # Strip unit/suite noise (and everything after it) before canonicalising tokens.
    s = _UNIT_RE.sub(" ", s)
    for long, short in _STREET_TYPES.items():
        s = re.sub(rf"\b{long}\b", short, s)
    for long, short in _DIRECTIONS.items():
        s = re.sub(rf"\b{long}\b", short, s)
    return re.sub(r"\s+", " ", s).strip()


class CivicGraph:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()

    def clear(self) -> None:
        """Drop all nodes/edges in place, keeping this instance (sub-agents hold a
        reference to it). Lets the app reload cleanly on (re)startup instead of
        accumulating — so a fresh lifespan rebuilds from the current DATA_DIR rather
        than stacking datasets from a previous load (also makes API tests order-safe)."""
        self.g.clear()

    def add_address(
        self, raw_address: str, lat: float | None = None, lng: float | None = None
    ) -> str:
        key = normalize_address(raw_address)
        node = f"address:{key}"
        if node not in self.g:
            self.g.add_node(node, kind="address", label=raw_address)
        # Validate at the boundary: only attach coordinates that fall inside Toronto
        # (a swapped lat/lng or out-of-region pair is ignored, i.e. treated as missing).
        if in_toronto_bbox(lat, lng):
            self.g.nodes[node]["lat"] = lat
            self.g.nodes[node]["lng"] = lng
        return node

    def add_record(
        self,
        kind: str,
        record_id: str,
        address: str,
        lat: float | None = None,
        lng: float | None = None,
        **attrs: object,
    ) -> str:
        """Attach a typed record (permit/inspection/request/...) to its address."""
        node = f"{kind}:{record_id}"
        self.g.add_node(node, kind=kind, **attrs)
        addr_node = self.add_address(address, lat=lat, lng=lng)
        self.g.add_edge(addr_node, node, kind="has_" + kind)
        return node

    def addresses(self, with_coords: bool = False) -> list[dict]:
        """All address nodes; optionally only those carrying lat/lng."""
        out = []
        for node, data in self.g.nodes(data=True):
            if data.get("kind") != "address":
                continue
            if with_coords and ("lat" not in data or "lng" not in data):
                continue
            out.append(
                {"label": data["label"], "lat": data.get("lat"), "lng": data.get("lng")}
            )
        return out

    def has_address(self, raw_address: str) -> bool:
        """Whether this address resolves to a known node (distinguishes a real
        low-risk address from a not-found / mistyped query)."""
        return f"address:{normalize_address(raw_address)}" in self.g

    def matched_label(self, raw_address: str) -> str | None:
        """The canonical stored label for a query (so the UI can echo what matched)."""
        node = f"address:{normalize_address(raw_address)}"
        return self.g.nodes[node].get("label") if node in self.g else None

    def records_for(self, raw_address: str, kind: str | None = None) -> list[dict]:
        addr_node = f"address:{normalize_address(raw_address)}"
        if addr_node not in self.g:
            return []
        out = []
        for _, target, data in self.g.out_edges(addr_node, data=True):
            node_data = self.g.nodes[target]
            if kind is None or node_data.get("kind") == kind:
                out.append({"id": target, **node_data})
        return out

    def __len__(self) -> int:
        return self.g.number_of_nodes()
