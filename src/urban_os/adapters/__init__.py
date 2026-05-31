"""City adapters — turn a city's open data into a kernel substrate.

An adapter is one half of the two-axis architecture: it builds the road/transit
graph and baseline fields for a city. Lenses then run on whatever an adapter
produces, unchanged. Toronto ships here; pointing a CKAN adapter at another
portal (``CKAN_URL`` swap) yields a new substrate with no lens changes.
"""
from __future__ import annotations

from .toronto import (
    Scenario,
    civic_activity_by_node,
    civic_safety_by_node,
    downtown_scenario,
)

__all__ = [
    "Scenario",
    "downtown_scenario",
    "civic_safety_by_node",
    "civic_activity_by_node",
]
