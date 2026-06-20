"""Event Surge lens — the post-event egress wave(s).

When a match or concert lets out, a fixed crowd tries to leave through the
transit network over a short window. We model that as a Gaussian-in-time demand
pulse injected at the venue (and, by spatial decay, the stations around it).

**Multiple concurrent events** (the FIFA convergence crunch — a match, a
ballgame, a concert and the fan festival all emptying into the same corridor)
are modelled by carrying a list of ``(venue, crowd, event_end)`` injection
points in *one* lens: each contributes its own Gaussian pulse at its own venue
and time, and they superimpose on the shared ``load`` field. Keeping them in a
single lens (rather than one lens per venue) means exactly one shared
``release_minutes`` lever — a single coordinated city-wide release policy — and
one ``event_surge`` cost term (the total hold), so the optimizer and the J
breakdown stay clean.

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
        venue_id: str | None = None,
        crowd_size: float | None = None,
        *,
        event_end: float | None = None,
        events: list[tuple[str, float, float]] | None = None,
        base_width: float = 4.0,
        decay: float = 0.0015,
        max_release: float = 20.0,
        weight: float = 1.0,
    ) -> None:
        # Two construction modes: a single ``(venue_id, crowd_size, event_end)``
        # (back-compat) or an ``events`` list of those triples (concurrent
        # let-outs). Internally we always carry the list.
        if events is None:
            if venue_id is None or crowd_size is None or event_end is None:
                raise ValueError(
                    "EventSurge needs either (venue_id, crowd_size, event_end) "
                    "or an events=[(venue, crowd, event_end), ...] list"
                )
            events = [(venue_id, float(crowd_size), float(event_end))]
        if not events:
            raise ValueError("EventSurge events list must be non-empty")
        self.events: list[tuple[str, float, float]] = [
            (v, float(c), float(e)) for v, c, e in events
        ]
        # Scalar mirrors of the PRIMARY (first) event for back-compat callers,
        # plus the TOTAL crowd (what ``cost`` prices — the whole held population).
        self.venue_id = self.events[0][0]
        self.event_end = self.events[0][2]
        self.crowd_size = float(sum(c for _, c, _ in self.events))
        self.base_width = base_width         # σ (minutes) with no intervention
        self.decay = decay                   # spatial spread of egress (degrees)
        self.max_release = max_release       # lever upper bound (minutes)
        self.weight = weight                 # weights the hold-cost J term
        self._venue_idx: int | None = None   # primary venue (back-compat)
        self._spatial: np.ndarray | None = None  # primary spatial (back-compat)
        # Per-event injection: (crowd, event_end, normalized spatial vector).
        self._injectors: list[tuple[float, float, np.ndarray]] = []

    def _spatial_for(self, substrate: Substrate, venue_id: str) -> np.ndarray:
        w = Operators.spatial_decay(substrate, substrate.idx(venue_id), self.decay)
        # Never seed the egress wave directly into a sink. Spatial decay weights
        # by raw lat/lng proximity across ALL nodes, so a nearby exit (or an
        # orphaned sink with no inbound edges) would get a slug of people injected
        # on the spot and never routed through the real graph — the drawn graph
        # would not equal the simulated routing (audit finding). Zeroing the sink
        # entries before normalizing seeds the crowd only at non-sink nodes;
        # people reach sinks solely via real edges.
        w = np.where(substrate.is_sink, 0.0, w)
        s = w.sum()
        return w / s if s > 0 else w

    def configure(self, substrate: Substrate) -> None:
        self._injectors = [
            (crowd, end, self._spatial_for(substrate, vid))
            for vid, crowd, end in self.events
        ]
        # Back-compat handles for tests/callers that read the primary venue.
        self._venue_idx = substrate.idx(self.venue_id)
        self._spatial = self._injectors[0][2]

    def _width(self, release_minutes: float) -> float:
        return self.base_width + _WIDTH_PER_RELEASE_MIN * release_minutes

    def source(self, state: State, t: float) -> None:
        release = float(state.params.get("release_minutes", 0.0))
        width = self._width(release)
        dt = state.params.get("dt", 1.0)
        load = state.field("load")
        for crowd, end, spatial in self._injectors:
            # Normalized Gaussian density (∫ over time = 1) × crowd × dt = people now.
            density = math.exp(-0.5 * ((t - end) / width) ** 2) / (
                width * math.sqrt(2 * math.pi)
            )
            people_now = crowd * density * dt
            if people_now <= 0:
                continue
            load[:] += people_now * spatial

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
