"""Event Surge lens — the post-event egress wave.

When a match or concert lets out, a fixed crowd tries to leave through the
transit network over a short window. We model that as a Gaussian-in-time demand
pulse injected at the venue (and, by spatial decay, the stations around it).

The control lever is **staggered release**: holding the crowd and releasing it
in waves spreads the *same* people over a wider window, lowering the peak
injection rate — and therefore the peak platform density downstream. The total
crowd is conserved regardless of the lever, which is what makes the
before/after dollar comparison honest.
"""
from __future__ import annotations

import math

import numpy as np

from ..kernel.loop import SimResult
from ..kernel.operators import Lens, Lever, Operators
from ..kernel.state import State, Substrate
from .economic import VALUE_OF_TIME

# Each extra minute of staggered release widens the egress pulse by this much
# (minutes of σ). Tuned so a ~12-minute release visibly flattens the peak.
_WIDTH_PER_RELEASE_MIN = 0.5
# Staggered release isn't free: the crowd waits, just in an orderly concourse
# instead of a platform crush. We count that hold at a fraction of crush-delay
# value (orderly waiting is genuinely less costly — and far safer — than being
# stuck in an over-capacity crush). This is what stops the optimizer from
# holding the crowd forever, giving a real interior optimum.
_HOLD_DISCOUNT = 0.2


class EventSurge(Lens):
    name = "event_surge"

    def __init__(
        self,
        venue_id: str,
        crowd_size: float,
        *,
        event_end: float,
        base_width: float = 4.0,
        decay: float = 0.0015,
        max_release: float = 20.0,
        weight: float = 1.0,
    ) -> None:
        self.venue_id = venue_id
        self.crowd_size = crowd_size
        self.event_end = event_end          # minutes: center of the egress pulse
        self.base_width = base_width         # σ (minutes) with no intervention
        self.decay = decay                   # spatial spread of egress (degrees)
        self.max_release = max_release       # lever upper bound (minutes)
        self.weight = weight                 # weights the hold-cost J term
        self._venue_idx: int | None = None
        self._spatial: np.ndarray | None = None

    def configure(self, substrate: Substrate) -> None:
        self._venue_idx = substrate.idx(self.venue_id)
        w = Operators.spatial_decay(substrate, self._venue_idx, self.decay)
        s = w.sum()
        self._spatial = w / s if s > 0 else w

    def _width(self, release_minutes: float) -> float:
        return self.base_width + _WIDTH_PER_RELEASE_MIN * release_minutes

    def source(self, state: State, t: float) -> None:
        release = float(state.params.get("release_minutes", 0.0))
        width = self._width(release)
        dt = state.params.get("dt", 1.0)
        # Normalized Gaussian density (∫ over time = 1) × crowd × dt = people now.
        density = math.exp(-0.5 * ((t - self.event_end) / width) ** 2) / (
            width * math.sqrt(2 * math.pi)
        )
        people_now = self.crowd_size * density * dt
        if people_now <= 0:
            return
        state.field("load")[:] += people_now * self._spatial

    def levers(self) -> list[Lever]:
        # Staggered-release window in 2-minute steps, 0 (do nothing) → max.
        grid = list(np.arange(0.0, self.max_release + 1e-9, 2.0))
        return [Lever(name="release_minutes", values=grid, label="Staggered release (min)")]

    def cost(self, result: SimResult) -> float:
        """The dollar cost of the intervention itself: holding the crowd back
        ``release`` minutes makes the average attendee wait ~``release/2`` extra
        minutes (orderly, discounted vs. a crush). Zero when we do nothing."""
        release = float(result.params.get("release_minutes", 0.0))
        hold_person_min = self.crowd_size * (release / 2.0)
        return hold_person_min / 60.0 * VALUE_OF_TIME * _HOLD_DISCOUNT
