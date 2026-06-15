"""JSON-boundary helpers for the Urban-OS API (ADR-0022 extraction; ADR-0006 rules).

Every numeric payload the API returns is coerced from numpy to native Python here
— numpy scalars are NOT JSON-serializable and would otherwise leak across the
boundary — and non-finite floats (NaN/±inf, not legal JSON) are clamped to 0.0.
Pure functions, no urban_os imports, so this is a safe leaf module.
"""
from __future__ import annotations

import math
import numbers

import numpy as np


def r(x: float, places: int = 3) -> float:
    """Round to keep the payload small; always returns a native float.

    Coerces numpy scalars to a native ``float`` (numpy scalars are NOT
    JSON-serializable — this is the boundary that guarantees no numpy leaks into
    a response). Non-finite values (NaN/±inf) are clamped to ``0.0`` so a
    degenerate field can never produce an invalid JSON token.
    """
    v = float(x)
    if not math.isfinite(v):
        return 0.0
    return round(v, places)


def native(obj):
    """Recursively coerce a (possibly numpy-laced) structure to native Python.

    ``optimize.OptResult.to_dict()`` carries lever values straight off an
    ``np.arange`` grid, so its ``params``/``trials`` hold ``numpy.float64``
    scalars. Those happen to JSON-encode today (numpy floats subclass ``float``)
    but still violate the "no numpy leakage at the boundary" invariant and would
    break a stricter encoder. Non-finite floats are clamped to 0.0 to keep the
    JSON strictly valid.
    """
    if isinstance(obj, dict):
        return {k: native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [native(v) for v in obj]
    if isinstance(obj, bool):  # bool before int/float (bool is an int subclass)
        return bool(obj)
    if isinstance(obj, np.bool_):  # numpy bool is NOT a python bool/Integral
        return bool(obj)
    if isinstance(obj, numbers.Integral):
        return int(obj)
    if isinstance(obj, numbers.Real):
        f = float(obj)
        return f if math.isfinite(f) else 0.0
    return obj  # str / None / already-native pass through unchanged


def simulate_frames(result, sub) -> list[dict]:
    """Trim the dead timeline tail off a run and serialize the kept frames.

    The crowd fully drains well before the fixed horizon, so the last ~40% of
    frames are all-zero padding that makes the slider/playback span a window where
    nothing happens. We drop trailing frames whose total node load is below a small
    epsilon, keeping a short "drained" coda for a clean end. This touches ONLY the
    returned/displayed frame list — the physics, metrics series, and peak readout
    (computed over every step via ``result.peak``) are untouched. The peak frame is
    always retained. Returns native-python, payload-sized node frames.
    """
    raw = result.frames
    peak_t = float(result.peak_congestion()["t"])
    _LOAD_EPS = 1.0  # total people on the network below this == "drained"
    _CODA = 2        # keep this many frames past the last active one
    last_active = -1
    for idx, fr in enumerate(raw):
        if float(np.sum(fr["load"])) >= _LOAD_EPS or float(fr["t"]) <= peak_t:
            last_active = idx
    if last_active < 0:  # degenerate: nothing ever active — keep frames as-is
        kept = list(range(len(raw)))
    else:
        kept = list(range(min(len(raw), last_active + 1 + _CODA)))

    frames = []
    for idx in kept:
        fr = raw[idx]
        cong = fr["congestion"]
        load = fr["load"]
        risk = fr["risk"]
        frames.append(
            {
                "t": r(fr["t"], 1),
                "nodes": [
                    {
                        "id": sub.ids[i],
                        "load": r(load[i], 1),
                        "congestion": r(cong[i]),
                        "risk": r(risk[i]),
                    }
                    for i in range(sub.n)
                ],
            }
        )
    return frames


def peak_dict(result) -> dict:
    """A run's peak-congestion summary as a native dict (node/label/congestion/t)."""
    p = result.peak_congestion()
    return {
        "node": p["node"],
        "label": p["label"],
        "congestion": r(p["congestion"]),
        "t": r(p["t"], 1),
    }
