"""Load pre-downloaded Toronto open-data files into a CivicGraph.

Reads the files produced by scripts/download_data.py (named `<key>__*.csv|json`)
and attaches each row to its address node. Schemas vary across datasets, so column
resolution is heuristic with light per-dataset hints — it degrades gracefully when
a column is missing rather than failing the whole load. If DATA_DIR is empty the
graph simply stays empty and the API still boots (offline-safe).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd

from ..agents.verify import classify_inspection
from ..config import settings
from ..graph.builder import CivicGraph, in_toronto_bbox, normalize_address
from .datasets import REGISTRY

_log = logging.getLogger(__name__)

# Real enforcement outcomes (OutcomeDesc) that mark a visit SEVERE even when its
# inspectionStatus is Pass/Conditional Pass — these are court/closure actions, not
# routine line-items, so they should dominate the routine status signal (#3b).
_CONVICTION_KEYWORDS = ("conviction", "closed", "closure", "order", "suspend", "fined")

# Severity rank for collapsing a multi-row visit to its worst line item.
_SEVERITY_RANK = {"pass": 0, "minor": 1, "severe": 2}
_RANK_TO_OUTCOME = {0: "Pass", 1: "Conditional Pass", 2: "Fail"}

# Registry key -> graph node kind.
KIND_BY_KEY: dict[str, str] = {
    "permits": "permit",
    "permits_cleared": "permit",
    "dinesafe": "inspection",
    "311": "request",
    "licences": "licence",
}

# Which graph attribute the ComplianceAgent reads, by kind, and the source-column
# keywords that map to it (first matching column wins, case-insensitive substring).
_STATE_ATTR: dict[str, tuple[str, tuple[str, ...]]] = {
    "permit": ("status", ("status",)),
    "inspection": ("outcome", ("status", "outcome", "result", "severity")),
    "request": ("status", ("status",)),
    "licence": ("status", ("status",)),
}

_ADDRESS_PART_KEYWORDS = (
    ("num", ("street_num", "st_num", "street number", "streetnum")),
    ("name", ("street_name", "st_name", "street name", "streetname")),
    ("type", ("street_type", "st_type", "street type")),
    ("dir", ("street_dir", "direction")),
)

_ROW_LIMIT = 5000  # cap per file for a snappy demo on the GX10


def _norm_header(col: Any) -> str:
    """Lowercase + strip a header for matching, tolerating BOM, NBSP, stray
    surrounding whitespace and embedded newlines from real-world CSV exports.
    The original column name is what we look up rows by, so this only affects
    matching — never the row-key used to read a value."""
    return (
        str(col)
        .replace("﻿", "")  # UTF-8 BOM pandas can leave on the first header
        .replace("\xa0", " ")  # non-breaking space
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
        .lower()
    )


def _find_col(columns: list[str], keywords: tuple[str, ...]) -> str | None:
    """First column whose normalized name contains any keyword. Returns the
    *original* column name so row lookups by the unmodified header still work."""
    for col in columns:
        low = _norm_header(col)
        if any(kw in low for kw in keywords):
            return col
    return None


def _resolve_plan(columns: list[str], kind: str) -> dict[str, Any]:
    """Decide once per file how to read address / id / state from its columns."""
    single = _find_col(columns, ("address",))
    parts = {tag: _find_col(columns, kws) for tag, kws in _ADDRESS_PART_KEYWORDS}
    id_col = _find_col(columns, ("_id", "permit_num", "licence", "license", "id"))
    state_attr, state_kws = _STATE_ATTR.get(kind, ("status", ("status",)))
    return {
        "address_single": single,
        "address_parts": [parts[t] for t in ("num", "name", "type", "dir") if parts[t]],
        "id_col": id_col,
        "state_attr": state_attr,
        "state_col": _find_col(columns, state_kws),
        # A date column makes each evidence row traceable to a real, dated record (#5)
        # AND lets us collapse same-day line-items into one visit (#3 de-dup).
        "date_col": _find_col(columns, ("date", "issued", "inspection_date", "_dt")),
        # Real enforcement outcome (DineSafe OutcomeDesc), used additively to escalate
        # a visit to SEVERE on a conviction/order/closure keyword (#3b).
        "outcome_desc_col": _find_col(columns, ("outcomedesc", "outcome desc")),
        # Establishment id — the de-dup key for collapsing ONE premises' deficiency
        # line-items (estId+date) WITHOUT fusing distinct vendors that share a building
        # (e.g. 7 food stands at Rogers Centre, same address+date) (#3).
        "est_id_col": _find_col(columns, ("estid", "establishment id", "establishmentid")),
        "lat_col": _find_col(columns, ("latitude", "lat")),
        "lng_col": _find_col(columns, ("longitude", "long", "lng")),
    }


def _clean_value(val: Any) -> str:
    """Collapse any whitespace (incl. embedded newlines/tabs from multiline CSV
    cells) to single spaces and strip. Empty / missing becomes ''."""
    if val is None:
        return ""
    return " ".join(str(val).split())


# Whole-token placeholders that leak into single-field source addresses when an
# upstream join stringified a null unit/component (e.g. "142 Parliament St None
# M5A 2Z1" or "...nan..."). Matched case-insensitively but only as a *whole*
# whitespace-delimited token, so real street names (Annette, Nanton, …) and
# genuine units ("Unit-6") are never touched.
_NULL_ADDRESS_TOKENS = frozenset({"none", "nan", "null", "n/a", "na"})


def _clean_address(val: Any) -> str:
    """Clean an address field and drop stringified-null placeholder tokens
    ("None"/"nan"/…) that leaked in from an upstream join, collapsing the
    resulting double spaces. Keeps every real component intact."""
    cleaned = _clean_value(val)
    if not cleaned:
        return ""
    tokens = [t for t in cleaned.split(" ") if t.lower() not in _NULL_ADDRESS_TOKENS]
    return " ".join(tokens)


def _address(row: dict[str, Any], plan: dict[str, Any]) -> str | None:
    if plan["address_single"]:
        val = _clean_address(row.get(plan["address_single"]))
        return val or None
    if plan["address_parts"]:
        parts = [_clean_address(row.get(c)) for c in plan["address_parts"]]
        joined = " ".join(p for p in parts if p)
        return joined or None
    return None


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("records", [])
        else:
            rows = []
        # Keep only dict rows (a stray scalar/list entry shouldn't break the load).
        rows = [r for r in rows[:_ROW_LIMIT] if isinstance(r, dict)]
        columns = list(rows[0].keys()) if rows else []
        return columns, rows
    return _read_csv_rows(path)


# Which engine read the last CSV: "cudf-polars" (RAPIDS GPU), "polars" (CPU), or
# "pandas" (fallback). Reflects what ACTUALLY ran — for the `make gpu-check` proof.
DF_BACKEND: str = "pandas"


def _gpu_df_enabled() -> bool:
    """The cuDF GPU dataframe engine is opt-in: ``URBANOS_GPU_DF=1`` on a box with
    Polars' GPU engine (``cudf-polars``) installed. Off by default so the demo venv /
    CI are untouched; the GPU engine helps at ingest scale (full city datasets), not
    the small committed demo slice."""
    return os.environ.get("URBANOS_GPU_DF", "").strip().lower() in {"1", "true", "yes"}


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Read a CSV as all-string rows (nulls → "").

    Prefers **Polars** — with the **RAPIDS cuDF GPU engine** when enabled+installed —
    and falls back to **pandas** when Polars is absent (so the live demo venv keeps
    working until Polars is installed). All three paths return the IDENTICAL
    ``(columns, rows)``; this is a drop-in ingest accelerator, never a behaviour
    change (golden two-index numbers are unaffected — see tests)."""
    global DF_BACKEND
    # Escape hatch to force the pandas path (parity testing / emergencies).
    if os.environ.get("URBANOS_DF_BACKEND", "").strip().lower() == "pandas":
        DF_BACKEND = "pandas"
        return _read_csv_rows_pandas(path)
    try:
        import polars as pl
    except Exception:
        DF_BACKEND = "pandas"
        return _read_csv_rows_pandas(path)
    try:
        # Lazy scan so the cuDF GPU engine (when enabled) can accelerate the query;
        # infer_schema_length=0 ⇒ every column stays a string, matching pandas dtype=str.
        lf = pl.scan_csv(
            path, infer_schema_length=0, ignore_errors=True, truncate_ragged_lines=True
        ).head(_ROW_LIMIT)
        if _gpu_df_enabled():
            try:
                df = lf.collect(engine="gpu")
                DF_BACKEND = "cudf-polars"
            except Exception as exc:  # GPU engine/cudf-polars missing → Polars CPU
                _log.warning("cuDF GPU engine unavailable, using Polars CPU: %s", exc)
                df = lf.collect()
                DF_BACKEND = "polars"
        else:
            df = lf.collect()
            DF_BACKEND = "polars"
        df = df.fill_null("")
        return df.columns, df.to_dicts()
    except Exception as exc:  # any Polars read problem → pandas, never fail the load
        _log.warning("Polars read failed for %s, using pandas: %s", path, exc)
        DF_BACKEND = "pandas"
        return _read_csv_rows_pandas(path)


def _read_csv_rows_pandas(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    df = pd.read_csv(path, dtype=str, nrows=_ROW_LIMIT).fillna("")
    return list(df.columns), df.to_dict("records")


def _has_conviction(text: Any) -> bool:
    """True if an OutcomeDesc names a court/closure/order enforcement action (#3b)."""
    low = str(text or "").lower()
    return any(kw in low for kw in _CONVICTION_KEYWORDS)


def load_file(graph: CivicGraph, key: str, path: Path) -> int:
    kind = KIND_BY_KEY.get(key, key)
    columns, rows = _read_rows(path)
    if not rows:
        return 0
    plan = _resolve_plan(columns, kind)
    # Inspection visits are line-itemised in DineSafe (one CSV row per deficiency),
    # so a single dated visit shows up as N rows. When a usable date column exists,
    # collapse rows of ONE visit into ONE record (#3) keyed by (estId, date) — or
    # (address, date) when there's no estId; with no date column we fall back to
    # per-row so other feeds/fixtures are unaffected.
    if kind == "inspection" and plan["date_col"]:
        return _load_inspection_visits(graph, key, kind, plan, rows)
    added = 0
    for i, row in enumerate(rows):
        address = _address(row, plan)
        if not address:
            continue
        record_id = str(row.get(plan["id_col"], f"{key}-{i}")) if plan["id_col"] else f"{key}-{i}"
        attrs: dict[str, Any] = {"dataset": key}
        if plan["state_col"]:
            attrs[plan["state_attr"]] = row.get(plan["state_col"])
        if plan["date_col"]:
            date_val = str(row.get(plan["date_col"], "")).strip()
            if date_val:
                attrs["date"] = date_val
        lat, lng = _coords(row, plan["lat_col"], plan["lng_col"])
        graph.add_record(kind, record_id, address, lat=lat, lng=lng, **attrs)
        added += 1
    return added


def _load_inspection_visits(graph: CivicGraph, key: str, kind: str,
                            plan: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    """Group inspection rows into one visit each, keyed by (estId, date) — falling
    back to (normalized address, date) when there is no establishment-id column.

    Keying on estId collapses ONE premises' deficiency line-items while keeping
    DISTINCT establishments that share a building (and date) separate — e.g. the
    seven food vendors at 1 Blue Jays Way (Rogers Centre) inspected the same day are
    seven visits, not one. The collapsed record keeps the WORST severity across its
    line-items (so the score sees one visit, not N deficiencies), records
    `deficiency_count` for display, and is escalated to SEVERE if any line-item's
    OutcomeDesc names a conviction/order/closure (#3b — additive on top of
    inspectionStatus, which stays the primary signal)."""
    est_col = plan["est_id_col"]
    # Preserve first-seen order so evidence/ids stay stable across loads.
    visits: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for i, row in enumerate(rows):
        address = _address(row, plan)
        if not address:
            continue
        date_val = str(row.get(plan["date_col"], "")).strip()
        # estId, when present, scopes the group to a single establishment so distinct
        # vendors at a shared address+date never fuse; else fall back to the address.
        est_val = str(row.get(est_col, "")).strip() if est_col else ""
        gkey = ((f"est:{est_val}" if est_val else normalize_address(address)), date_val)
        outcome = row.get(plan["state_col"]) if plan["state_col"] else None
        sev = classify_inspection(outcome)
        if plan["outcome_desc_col"] and _has_conviction(row.get(plan["outcome_desc_col"])):
            sev = "severe"
            outcome = "Conviction"
        row_lat, row_lng = _coords(row, plan["lat_col"], plan["lng_col"])
        if gkey not in visits:
            order.append(gkey)
            record_id = (str(row.get(plan["id_col"])) if plan["id_col"] else f"{key}-{i}")
            visits[gkey] = {
                "address": address, "record_id": record_id, "date": date_val,
                "rank": _SEVERITY_RANK[sev], "outcome": outcome,
                "deficiency_count": 1,
                "lat": row_lat, "lng": row_lng,
            }
            continue
        v = visits[gkey]
        v["deficiency_count"] += 1
        if _SEVERITY_RANK[sev] > v["rank"]:
            v["rank"], v["outcome"] = _SEVERITY_RANK[sev], outcome
        if v["lat"] is None:
            v["lat"], v["lng"] = row_lat, row_lng
    for gkey in order:
        v = visits[gkey]
        attrs: dict[str, Any] = {"dataset": key, "deficiency_count": v["deficiency_count"]}
        if v["outcome"] is not None:
            attrs[plan["state_attr"]] = v["outcome"]
        if v["date"]:
            attrs["date"] = v["date"]
        graph.add_record(kind, v["record_id"], v["address"], lat=v["lat"], lng=v["lng"], **attrs)
    return len(order)


def _coords(row: dict[str, Any], lat_col: str | None,
            lng_col: str | None) -> tuple[float | None, float | None]:
    """Parse a row's lat/lng pair, swallowing missing/blank/malformed values and
    dropping any pair that falls outside the Toronto bbox (a swapped lat/lng or a
    coordinate from another city → treated as missing, not plotted in the ocean).
    The bbox is defined once in graph.builder.in_toronto_bbox (single source)."""
    lat = _coord(row, lat_col)
    lng = _coord(row, lng_col)
    if lat is None or lng is None:
        return None, None
    if not in_toronto_bbox(lat, lng):
        _log.warning("dropping out-of-Toronto coordinate lat=%s lng=%s", lat, lng)
        return None, None
    return lat, lng


def _coord(row: dict[str, Any], col: str | None) -> float | None:
    """Parse a single lat/lng cell, swallowing missing/blank/malformed values.
    Bbox validation is applied per-pair in `_coords`."""
    if not col:
        return None
    raw = row.get(col)
    if raw is None:
        return None
    try:
        text = str(raw).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def load_into_graph(graph: CivicGraph, data_dir: Path | None = None) -> dict[str, int]:
    """Load every registered dataset found in data_dir. Returns rows-added per key."""
    data_dir = data_dir or settings.data_dir
    summary: dict[str, int] = {}
    if not data_dir.exists():
        return summary
    for key in REGISTRY:
        count = 0
        for path in sorted([*data_dir.glob(f"{key}__*.csv"), *data_dir.glob(f"{key}__*.json")]):
            try:
                count += load_file(graph, key, path)
            except (OSError, ValueError, json.JSONDecodeError,
                    pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
                # A single malformed/unreadable file must not abort the whole load
                # (offline-safe boundary): skip it and keep ingesting the rest — but
                # make a corrupt slice VISIBLE in logs so it isn't a silent "low risk
                # everywhere" demo with no signal.
                _log.warning("skipping %s: %s", path, exc)
                continue
        if count:
            summary[key] = count
    return summary
