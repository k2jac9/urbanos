"""Build a small committed REAL slice of Toronto multimodal counts (demo_data/).

Produces ``demo_data/tmc__downtown.csv`` — the time-marginal "density snapshot" the
Urban-OS CongestionNowcast lens calibrates against (docs/research/...). It pulls the
City's Turning-Movement-Count raw table (15-min bins, all modes), filtered to the
downtown bbox **server-side** via the CKAN datastore SQL API (the raw table is huge),
keeps each location's single most-recent count day so every location is a coherent
intraday series, and normalizes the 56-column per-approach schema down to a tidy
``location, lat, lng, date, time_start, mode, volume`` (one row per mode per 15-min
bin). Real column values; only reshaped.

Offline-safe: any network failure prints a note and exits 0 (the adapter's synthetic
fallback covers dev/CI), so ``make demo-data`` never breaks off-box.

    python scripts/fetch_tmc.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_data"

# TMC raw 2020-2029 datastore resource (fields verified via datastore_search).
RESOURCE_ID = "262469c2-abfe-4756-9068-4ea5c7ba1af7"
# This CKAN instance disables datastore_search_sql, so we paginate datastore_search
# and bbox-filter client-side (the table is ~346k rows; we stop once we have enough
# downtown locations).
SEARCH_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/datastore_search"
)
# Downtown bbox — matches build_demo_slice.py / the offline PMTiles basemap.
BBOX = dict(min_lat=43.62, max_lat=43.69, min_lon=-79.43, max_lon=-79.34)
PAGE = 5000        # rows per datastore_search page
MAX_PAGES = 16     # page cap so a cold run stays bounded
ENOUGH_LOCS = 8    # stop early once we have this many downtown locations …
ENOUGH_ROWS = 800  # … and this many downtown rows
MAX_OUT = 5000     # cap on normalized rows written (matches loader _ROW_LIMIT)

# Per-approach source columns grouped into the modes we emit.
_MODE_COLS = {
    "ped": ("n_appr_peds", "s_appr_peds", "e_appr_peds", "w_appr_peds"),
    "bike": ("n_appr_bike", "s_appr_bike", "e_appr_bike", "w_appr_bike"),
    "vehicle": (
        "n_appr_cars_r", "n_appr_cars_t", "n_appr_cars_l",
        "s_appr_cars_r", "s_appr_cars_t", "s_appr_cars_l",
        "e_appr_cars_r", "e_appr_cars_t", "e_appr_cars_l",
        "w_appr_cars_r", "w_appr_cars_t", "w_appr_cars_l",
    ),
}


def _in_bbox(rec: dict) -> bool:
    lat, lng = _num(rec.get("latitude")), _num(rec.get("longitude"))
    return (BBOX["min_lat"] <= lat <= BBOX["max_lat"]
            and BBOX["min_lon"] <= lng <= BBOX["max_lon"])


def _fetch() -> list[dict]:
    """Paginate datastore_search, keeping only downtown rows; stop once we have
    enough downtown locations (or hit the page cap)."""
    out: list[dict] = []
    for page in range(MAX_PAGES):
        resp = httpx.get(
            SEARCH_URL,
            params={"resource_id": RESOURCE_ID, "limit": PAGE, "offset": page * PAGE},
            timeout=180,
            follow_redirects=True,
        )
        resp.raise_for_status()
        recs = resp.json()["result"]["records"]
        if not recs:
            break
        out.extend(r for r in recs if _in_bbox(r))
        locs = len({str(r.get("location_name", "")) for r in out})
        if locs >= ENOUGH_LOCS and len(out) >= ENOUGH_ROWS:
            break
    return out


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _normalize(records: list[dict]) -> list[dict]:
    """Keep each location's most-recent count day, then emit one tidy row per mode
    per 15-min bin (volume = sum over that mode's approach columns)."""
    latest: dict[str, str] = {}
    for r in records:
        loc = str(r.get("location_name", "")).strip()
        date = str(r.get("count_date", "")).strip()
        if loc and date > latest.get(loc, ""):
            latest[loc] = date
    out: list[dict] = []
    for r in records:
        loc = str(r.get("location_name", "")).strip()
        date = str(r.get("count_date", "")).strip()
        if not loc or date != latest.get(loc):
            continue
        for mode, cols in _MODE_COLS.items():
            out.append({
                "location": loc,
                "lat": r.get("latitude"),
                "lng": r.get("longitude"),
                "date": date,
                "time_start": r.get("start_time"),
                "mode": mode,
                "volume": sum(_num(r.get(c)) for c in cols),
            })
    return out[:MAX_OUT]


def main() -> int:
    try:
        records = _fetch()
    except Exception as exc:  # noqa: BLE001 — offline-safe: never fail the chained target
        print(f"fetch_tmc: skipped (no network / API error: {exc}). "
              "The synthetic-count fallback covers dev/CI.")
        return 0
    rows = _normalize(records)
    if not rows:
        print("fetch_tmc: no downtown rows returned; leaving any existing slice in place.")
        return 0
    import csv

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "tmc__downtown.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["location", "lat", "lng", "date",
                                           "time_start", "mode", "volume"])
        w.writeheader()
        w.writerows(rows)
    locs = len({r["location"] for r in rows})
    print(f"tmc: {len(rows)} rows across {locs} downtown locations -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
