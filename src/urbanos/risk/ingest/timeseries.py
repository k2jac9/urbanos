"""Load Toronto **time-marginal** count datasets as observed-throughput records.

Where :mod:`loader` ingests *static* address attributes into the knowledge graph,
this reads datasets that carry a **time axis** — counts / boardings in repeated
buckets — and returns a flat list of observed records. That is the "density snapshot
over time" shape the Urban-OS ``CongestionNowcast`` lens calibrates the kernel against
and that the (later) LearnedDynamics lens trains on
(see ``docs/research/tpf-and-data-driven-lenses.md``).

The committed demo slice is a small **normalized** form — one row per
``(location, 15-min bin, mode)`` with a single ``volume`` — produced from the raw
City TMC schema by ``scripts/fetch_tmc.py``. Reading is heuristic and tolerant (same
philosophy as :mod:`loader`): a missing column or a malformed row is skipped, never
fatal. Offline-safe: absent files → empty list, and callers fall back to a synthetic
series (so dev / CI never need network or the slice).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import settings
from ..graph.builder import in_toronto_bbox
from .loader import _coord, _find_col, _read_rows


def _parse_minute(val: Any) -> float | None:
    """Minutes-from-midnight for a time/timestamp cell. Accepts an ISO timestamp
    (``2020-01-08T07:30:00``), a ``HH:MM[:SS]`` clock string, a ``YYYY-MM-DD HH:MM``
    datetime, or a plain numeric minute. Returns ``None`` on anything unparseable."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if "T" in s:                      # ISO timestamp → keep the time component
        s = s.split("T", 1)[1]
    elif " " in s and ":" in s:       # "YYYY-MM-DD HH:MM:SS" → keep the clock
        s = s.split(" ")[-1]
    if ":" in s:
        parts = s.split(":")
        try:
            return float(int(parts[0]) * 60 + int(parts[1]))
        except (ValueError, IndexError):
            return None
    try:                              # already a numeric minute
        return float(s)
    except ValueError:
        return None


def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        text = str(val).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def _parse_file(path: Path) -> list[dict[str, Any]]:
    """Parse one normalized count file into observed records. Records outside the
    Toronto bbox or missing a time/volume are dropped (mirrors loader hygiene)."""
    columns, rows = _read_rows(path)
    if not rows:
        return []
    lat_col = _find_col(columns, ("latitude", "lat"))
    lng_col = _find_col(columns, ("longitude", "long", "lng"))
    time_col = _find_col(columns, ("time_start", "start_time", "time", "bin", "minute"))
    vol_col = _find_col(columns, ("volume", "count", "peds", "pedestrian", "total"))
    mode_col = _find_col(columns, ("mode",))
    loc_col = _find_col(columns, ("location", "intersection", "name"))
    if not (lat_col and lng_col and time_col and vol_col):
        return []
    recs: list[dict[str, Any]] = []
    for row in rows:
        lat, lng = _coord(row, lat_col), _coord(row, lng_col)
        if lat is None or lng is None or not in_toronto_bbox(lat, lng):
            continue
        minute = _parse_minute(row.get(time_col))
        volume = _parse_float(row.get(vol_col))
        if minute is None or volume is None or volume < 0:
            continue
        recs.append(
            {
                "location": str(row.get(loc_col, "")).strip() if loc_col else "",
                "lat": lat,
                "lng": lng,
                "minute": minute,
                "mode": (str(row.get(mode_col, "")).strip().lower() if mode_col else "all"),
                "volume": volume,
            }
        )
    return recs


def load_counts(data_dir: Path | None = None, key: str = "tmc") -> list[dict[str, Any]]:
    """Load every ``{key}__*.csv|json`` count file under ``data_dir`` into a flat list
    of ``{location, lat, lng, minute, mode, volume}`` records. Empty (not an error)
    when the directory or files are absent — the offline-safe boundary."""
    data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
    out: list[dict[str, Any]] = []
    if not data_dir.exists():
        return out
    for path in sorted([*data_dir.glob(f"{key}__*.csv"), *data_dir.glob(f"{key}__*.json")]):
        try:
            out.extend(_parse_file(path))
        except Exception:  # noqa: BLE001 — a bad slice must not break the load
            continue
    return out


def load_station_values(
    data_dir: Path | None = None, key: str = "ttc_boardings", value_col: str = "boardings"
) -> list[dict[str, Any]]:
    """Load **static** per-location values (lat/lng + a single value column, no time axis)
    from ``{key}__*.csv|json`` — e.g. real TTC daily station boardings. The non-temporal
    twin of :func:`load_counts`: returns ``{location, lat, lng, value}`` records. Rows
    outside the Toronto bbox or missing coords/value are dropped (loader hygiene). Empty
    (not an error) when files are absent — the offline-safe boundary."""
    data_dir = Path(data_dir) if data_dir is not None else settings.data_dir
    out: list[dict[str, Any]] = []
    if not data_dir.exists():
        return out
    for path in sorted([*data_dir.glob(f"{key}__*.csv"), *data_dir.glob(f"{key}__*.json")]):
        try:
            columns, rows = _read_rows(path)
            if not rows:
                continue
            lat_col = _find_col(columns, ("latitude", "lat"))
            lng_col = _find_col(columns, ("longitude", "long", "lng"))
            val_col = _find_col(columns, (value_col, "value", "volume", "count", "total"))
            loc_col = _find_col(columns, ("location", "station", "name"))
            if not (lat_col and lng_col and val_col):
                continue
            for row in rows:
                lat, lng = _coord(row, lat_col), _coord(row, lng_col)
                if lat is None or lng is None or not in_toronto_bbox(lat, lng):
                    continue
                value = _parse_float(row.get(val_col))
                if value is None or value < 0:
                    continue
                out.append({
                    "location": str(row.get(loc_col, "")).strip() if loc_col else "",
                    "lat": lat,
                    "lng": lng,
                    "value": value,
                })
        except Exception:  # noqa: BLE001 — a bad slice must not break the load
            continue
    return out
