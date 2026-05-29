"""Build a knowledge graph linking addresses, premises, permits and inspections.

Nodes are typed (address / business / permit / inspection / request). Edges connect
a record to the address it occurred at, so a query for an address can traverse to
every related signal — the structure that won the NYC edition.
"""
from __future__ import annotations

import re

import networkx as nx


def normalize_address(raw: str) -> str:
    """Cheap address key. Deterministic cleanup of the real-world quirks seen in
    Toronto open data (embedded 'None' for missing units, trailing postal codes,
    city/province suffixes). The harder fuzzy entity-resolution is the local-LLM
    job — see agents/subagents."""
    s = raw.upper().strip()
    s = re.sub(r"[.,]", " ", s)
    # Drop Canadian postal codes (e.g. "M4A 1X1") and literal 'NONE' unit placeholders.
    s = re.sub(r"\b[A-Z]\d[A-Z]\s*\d[A-Z]\d\b", " ", s)
    s = re.sub(r"\bNONE\b", " ", s)
    s = re.sub(r"\b(TORONTO|ONTARIO|ON|CANADA)\b", " ", s)
    s = re.sub(r"\bSTREET\b", "ST", s)
    s = re.sub(r"\bAVENUE\b", "AVE", s)
    s = re.sub(r"\bBOULEVARD\b", "BLVD", s)
    s = re.sub(r"\bWEST\b", "W", s)
    s = re.sub(r"\bEAST\b", "E", s)
    s = re.sub(r"\bNORTH\b", "N", s)
    s = re.sub(r"\bSOUTH\b", "S", s)
    return re.sub(r"\s+", " ", s).strip()


class CivicGraph:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()

    def add_address(
        self, raw_address: str, lat: float | None = None, lng: float | None = None
    ) -> str:
        key = normalize_address(raw_address)
        node = f"address:{key}"
        if node not in self.g:
            self.g.add_node(node, kind="address", label=raw_address)
        if lat is not None and lng is not None:
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
