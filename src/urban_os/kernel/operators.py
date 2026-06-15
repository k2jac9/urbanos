"""Operators and the plugin (lens) contract.

The kernel owns one operator — ``transport`` — because moving a conserved
quantity on the graph is domain-agnostic. The other three (``source``,
``couple``, ``observe``) are supplied by *lenses*: a lens is anything with the
hooks below. Hooks are optional; the base class no-ops them, so a lens only
overrides what it needs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import accel
from .state import State, Substrate


def _safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """Elementwise num/den, yielding 0 where den==0 (no warnings, no NaNs)."""
    return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den > 0)


@dataclass
class Lever:
    """A control a lens exposes to the optimizer.

    ``values`` is the discrete grid the optimizer searches; ``apply`` writes the
    chosen value into ``state.params`` (read back by the lens's source/couple)."""

    name: str
    values: list[float]
    label: str = ""

    def set(self, params: dict, value: float) -> None:
        params[self.name] = value


class Operators:
    """Math helpers shared by lenses, plus the kernel's transport integrator."""

    @staticmethod
    def gaussian_pulse(t: float, center: float, width: float, amplitude: float) -> float:
        """A single Gaussian bump in time — the building block for event demand."""
        if width <= 0:
            return 0.0
        z = (t - center) / width
        return float(amplitude * np.exp(-0.5 * z * z))

    @staticmethod
    def spatial_decay(sub: Substrate, origin_idx: int, decay: float) -> np.ndarray:
        """Great-circle-free proximity weight ``e^{-d/decay}`` from a node, using
        a cheap planar distance in degrees (fine at city scale, fully offline)."""
        dlat = sub.lat - sub.lat[origin_idx]
        dlng = (sub.lng - sub.lng[origin_idx]) * np.cos(np.radians(sub.lat[origin_idx]))
        d = np.sqrt(dlat * dlat + dlng * dlng)
        if decay <= 0:
            w = np.zeros(sub.n)
            w[origin_idx] = 1.0
            return w
        return np.exp(-d / decay)

    @staticmethod
    def transport(state: State, *, dt: float) -> None:
        """Move ``load`` one step downhill toward sinks (exits/home).

        Capacitated drainage: a link passes at most ``capacity·dt`` people per
        step, and a node can't send more than it holds. A queue builds wherever
        inflow outruns a node's *outbound* link capacity — that backlog, growing
        past the node's reference capacity (ρ > 1), is the post-event crush.

        Nodes serve at their link rate regardless of their own crowding (a
        platform keeps loading trains when packed), so there is no gridlock; the
        slow-down a crowd actually feels is the economic lens's delay coupling.
        Sinks absorb without limit (into ``arrived``). People-conserving.

        The step itself runs through :mod:`urban_os.kernel.accel`, which uses the
        compiled Rust core when built and a bit-for-bit numpy reference otherwise
        (ADR-0004). We keep the in-place field contract here — ``accel`` returns
        fresh arrays, the operator owns the write-back — because lenses and the
        loop hold references to the same field objects.
        """
        sub = state.substrate
        # Effective link capacity = baked dry capacity × the per-step multiplier a
        # lens may have applied (e.g. WeatherLens' rain tax). Default multiplier is
        # all-ones, so this is a no-op unless a lens taxed throughput this step. The
        # substrate's ``edge_cap`` itself is never mutated (ADR-0021).
        mult = getattr(state, "edge_cap_mult", None)
        edge_cap = sub.edge_cap if mult is None else sub.edge_cap * mult
        out_load, arrived_delta = accel.transport_step(
            load=state.fields["load"],
            edge_src=sub.edge_src,
            edge_dst=sub.edge_dst,
            edge_cap=edge_cap,
            dist_to_sink=sub.dist_to_sink,
            is_sink=sub.is_sink,
            capacity=sub.capacity,
            dt=dt,
        )
        state.fields["load"][:] = out_load        # preserve the field object identity
        state.fields["arrived"] += arrived_delta


class Lens:
    """Base class for a domain lens. Override only the hooks you use.

    A lens is configured once against the substrate (resolve node ids → indices),
    then participates in every step via ``source``/``couple``/``observe``. It may
    expose ``levers`` for the optimizer and contribute a ``cost`` term to ``J``.
    """

    name: str = "lens"
    weight: float = 1.0

    def configure(self, substrate: Substrate) -> None:  # noqa: D401
        """Resolve any node references against the baked substrate. Default: none."""

    def source(self, state: State, t: float) -> None:
        """Inject forcing into fields (e.g. event demand). Default: no-op."""

    def couple(self, state: State, t: float) -> None:
        """Map field → field (e.g. load → risk). Default: no-op."""

    def observe(self, state: State, t: float) -> dict[str, float]:
        """Return scalar metrics for this step. Default: none."""
        return {}

    def levers(self) -> list[Lever]:
        """Controls the optimizer may set. Default: none."""
        return []

    def cost(self, result: "object") -> float:
        """This lens's contribution to ``J`` for a finished run. Default: 0."""
        return 0.0
