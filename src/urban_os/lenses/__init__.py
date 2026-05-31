"""Domain lenses — portable across city adapters.

A lens plugs domain behaviour into the kernel through the four-operator contract
(see ``urban_os.kernel.operators.Lens``). P0 ships two, plus a third domain lens:

- :class:`EventSurge` — an event's egress wave (a ``source``) with a
  staggered-release ``lever`` the optimizer can tune.
- :class:`EconomicLens` — turns congestion into crowd-safety ``risk`` and a
  dollar ``cost`` of commuter delay (a ``couple`` + ``observe`` + ``J`` term).
- :class:`WeatherLens` — rain that slows network drainage (a transient tax on
  link capacity) and amplifies crowd-safety ``risk``, with a shelter-deployment
  ``lever`` (a ``source`` + ``couple`` + ``observe`` + ``J`` term). Place it
  *after* :class:`EconomicLens` in the stack so its risk multiplier lands on a
  populated ``risk`` field.
- :class:`BusinessFlow` — local trade lost to the post-event crush (the sports
  angle): a read-only ``couple`` + ``observe`` + ``J`` term that prices the shop
  and food-premises revenue a crush destroys, so the staggered-release lever gets
  credit for the business it preserves.
"""
from __future__ import annotations

from .business_flow import BusinessFlow
from .economic import EconomicLens
from .emissions import EmissionsLens
from .ems_access import EmsAccessLens
from .event_surge import EventSurge
from .fare_revenue import FareRevenueLens
from .noise_livability import NoiseLivabilityLens
from .safety import SafetyLens
from .weather import WeatherLens

__all__ = [
    "EventSurge",
    "EconomicLens",
    "WeatherLens",
    "BusinessFlow",
    "SafetyLens",
    # Supplementary intelligence lenses (additive, display-only — see
    # scenarios.extra_display_lenses): not summed into the optimizer's objective.
    "EmsAccessLens",
    "EmissionsLens",
    "NoiseLivabilityLens",
    "FareRevenueLens",
]
