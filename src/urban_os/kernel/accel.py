"""Backend-selecting transport step (numpy reference + optional Rust accelerator).

This mirrors the project's "no model -> deterministic fallback" rule: the Rust
core is a *drop-in accelerator*. A pure-numpy implementation is ALWAYS present
and is the bit-for-bit reference; the compiled crate (module ``urban_os_native``,
built from ``native/`` via maturin) only makes the "N x real-time" number real.

The numpy ``transport_step`` here reproduces ``operators.Operators.transport``
exactly (same f64 semantics, same safe-divide-by-zero -> 0). The kernel's
``transport`` mutates ``state.fields`` in place; this function instead returns
fresh ``(out_load, arrived_delta)`` arrays so it stays a pure, side-effect-free
unit the caller assigns back.

Importing this module NEVER raises: the Rust path sits behind try/except so a
missing or broken native build silently falls back to numpy.
"""
from __future__ import annotations

import numpy as np

# --- optional Rust backend -------------------------------------------------
# Built from native/ with: cd native && maturin develop --release
# The compiled extension installs as the top-level module ``urban_os_native``.
try:  # pragma: no cover - depends on whether the crate was built
    import urban_os_native as _native  # type: ignore

    if hasattr(_native, "transport_step"):
        BACKEND = "rust"
    else:  # module present but missing the symbol -> treat as absent
        _native = None  # type: ignore
        BACKEND = "numpy"
except ImportError:  # no compiled crate -> numpy fallback
    _native = None  # type: ignore
    BACKEND = "numpy"


def backend_name() -> str:
    """Return the active backend: ``"rust"`` or ``"numpy"``."""
    return BACKEND


def _safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """Elementwise num/den, yielding 0 where den<=0 (matches operators._safe_div)."""
    return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den > 0)


def _transport_step_numpy(
    load: np.ndarray,
    edge_src: np.ndarray,
    edge_dst: np.ndarray,
    edge_cap: np.ndarray,
    dist_to_sink: np.ndarray,
    is_sink: np.ndarray,
    capacity: np.ndarray,  # noqa: ARG001 - kept for signature parity with kernel
    dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Pure-numpy reference: one capacitated-drainage transport step.

    Returns ``(out_load, arrived_delta)`` as fresh float arrays; inputs are not
    mutated. People-conserving: ``out_load.sum() + arrived_delta.sum() ==
    load.sum()`` (to f64 round-off).
    """
    load = np.asarray(load, dtype=float)
    es = np.asarray(edge_src)
    ed = np.asarray(edge_dst)
    ec = np.asarray(edge_cap, dtype=float)
    dts = np.asarray(dist_to_sink, dtype=float)
    sink = np.asarray(is_sink, dtype=bool)
    n = load.shape[0]

    # A link drains iff its head is strictly closer to an exit than its tail.
    draining = dts[ed] < dts[es]
    edge_supply = np.where(draining, ec * dt, 0.0)

    # Share each tail's load across its draining links (never send > load held).
    tail_tot = np.zeros(n)
    np.add.at(tail_tot, es, edge_supply)
    tail_scale = np.minimum(1.0, _safe_div(load, tail_tot))
    edge_flow = edge_supply * tail_scale[es]

    out_per = np.zeros(n)
    in_per = np.zeros(n)
    np.add.at(out_per, es, edge_flow)
    np.add.at(in_per, ed, edge_flow)

    out_load = load - out_per
    arrived_delta = np.where(sink, in_per, 0.0)
    out_load = out_load + np.where(sink, 0.0, in_per)
    out_load = np.clip(out_load, 0.0, None)
    return out_load, arrived_delta


def transport_step(
    load: np.ndarray,
    edge_src: np.ndarray,
    edge_dst: np.ndarray,
    edge_cap: np.ndarray,
    dist_to_sink: np.ndarray,
    is_sink: np.ndarray,
    capacity: np.ndarray,
    dt: float,
) -> tuple[np.ndarray, np.ndarray]:
    """One transport step via the active backend.

    Signature mirrors what the kernel needs. Returns fresh
    ``(out_load, arrived_delta)`` numpy float arrays; never mutates inputs.
    """
    if _native is None:
        return _transport_step_numpy(
            load, edge_src, edge_dst, edge_cap, dist_to_sink, is_sink, capacity, dt
        )

    # Rust path: the crate takes flat Vec[f64]/Vec[i64] and returns two Vec[f64].
    # Convert at the boundary; rust runs the identical f64 algorithm.
    out_load, arrived_delta = _native.transport_step(
        np.asarray(load, dtype=np.float64).tolist(),
        np.asarray(edge_src, dtype=np.int64).tolist(),
        np.asarray(edge_dst, dtype=np.int64).tolist(),
        np.asarray(edge_cap, dtype=np.float64).tolist(),
        np.asarray(dist_to_sink, dtype=np.float64).tolist(),
        np.asarray(is_sink, dtype=bool).astype(np.int64).tolist(),
        float(dt),
    )
    return (
        np.asarray(out_load, dtype=float),
        np.asarray(arrived_delta, dtype=float),
    )
