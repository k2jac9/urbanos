"""Urban-OS — an on-device urban-dynamics OS for Toronto.

A small simulation *kernel* owns the substrate (a road/transit graph) and the
time loop; every domain behaviour is a *plugin* that uses four operators:

    source    inject forcing into fields           (e.g. an event's demand)
    transport move a conserved quantity on the graph (people draining to exits)
    couple    map field -> field                    (load -> congestion -> risk)
    observe   fields -> metrics + a cost term J      (delay $, peak density)

Two plugin axes: *city adapters* turn a city's open data into the substrate;
*domain lenses* (event surge, economics, safety, ...) are portable across
adapters for free. The optimizer searches lens-declared levers to minimize
``J = Σ wₚ·Jₚ``.

The kernel is pure Python/numpy and deterministic under a seed; a Rust core is
an optional drop-in accelerator (numpy is the always-present fallback, mirroring
the project's "no model → deterministic fallback" rule).
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
