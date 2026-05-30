"""Domain lenses — portable across city adapters.

A lens plugs domain behaviour into the kernel through the four-operator contract
(see ``urban_os.kernel.operators.Lens``). P0 ships two:

- :class:`EventSurge` — an event's egress wave (a ``source``) with a
  staggered-release ``lever`` the optimizer can tune.
- :class:`EconomicLens` — turns congestion into crowd-safety ``risk`` and a
  dollar ``cost`` of commuter delay (a ``couple`` + ``observe`` + ``J`` term).
"""
from __future__ import annotations

from .economic import EconomicLens
from .event_surge import EventSurge

__all__ = ["EventSurge", "EconomicLens"]
