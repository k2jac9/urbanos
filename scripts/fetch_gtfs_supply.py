"""Build a small committed REAL slice of TTC transit *supply* (demo_data/).

Produces ``demo_data/transit_supply__downtown.csv`` — real scheduled transit departures per
downtown stop in the evening (17:00-19:00) window, the **supply** signal that pairs with the
demand sources (Bike Share / TTC boardings) for the Urban-OS map (ADR-0032). Where the demand
lenses show *where people want to leave from*, this shows *how much scheduled transit actually
serves each area*.

Source (real, only counted): the TTC GTFS feed (``ttc-routes-and-schedules``). We stream
``stop_times.txt`` and count departures whose scheduled time falls in the evening window, per
stop, then join ``stops.txt`` coordinates and keep the downtown bbox. Pure real data (a count
of scheduled departures); no modelling.

Offline-safe: any network/parse failure prints a note and exits 0 (the adapter's synthetic
fallback covers dev/CI), so ``make demo-data`` never breaks. The raw GTFS ZIP is never
committed — only the small normalized slice. Uses the hardened CKAN client (retry + stream).

    python scripts/fetch_gtfs_supply.py
"""
from __future__ import annotations

import csv
import io
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from urbanos.risk.ingest.ckan import CKANClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_data"
SLUG = "ttc-routes-and-schedules"
# Downtown bbox — matches the other fetchers / the offline PMTiles basemap.
BBOX = dict(min_lat=43.62, max_lat=43.69, min_lon=-79.43, max_lon=-79.34)
WIN_START, WIN_END = 17, 19   # evening window [start, end) in hours (GTFS allows >24h)
MAX_OUT = 5000


def _stop_coords(zf: zipfile.ZipFile) -> dict[str, tuple[float, float]]:
    with zf.open("stops.txt") as fh:
        out: dict[str, tuple[float, float]] = {}
        for s in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
            try:
                out[s["stop_id"]] = (float(s["stop_lat"]), float(s["stop_lon"]))
            except (KeyError, TypeError, ValueError):
                continue
        return out


def _evening_departures(zf: zipfile.ZipFile) -> Counter:
    """Stream stop_times.txt; count scheduled departures in the evening window per stop_id.
    GTFS departure_time can exceed 24h (after-midnight service) — take the hour mod 24."""
    dep: Counter = Counter()
    with zf.open("stop_times.txt") as fh:
        for row in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")):
            t = row.get("departure_time") or ""
            if len(t) >= 2 and t[:2].isdigit():
                if WIN_START <= int(t[:2]) % 24 < WIN_END:
                    sid = row.get("stop_id")
                    if sid:
                        dep[sid] += 1
    return dep


def main() -> int:
    try:
        with CKANClient() as ckan:
            res = ckan.find_resource(SLUG, formats=("zip",))
            if res is None:
                print("fetch_gtfs_supply: no GTFS ZIP found; leaving slice in place.")
                return 0
            with tempfile.TemporaryDirectory() as td:
                zpath = ckan.download_resource(res, Path(td) / "gtfs.zip", max_bytes=80_000_000)
                zf = zipfile.ZipFile(zpath)
                coords = _stop_coords(zf)
                dep = _evening_departures(zf)
                zf.close()
    except Exception as exc:  # noqa: BLE001 — offline-safe: never fail the chained target
        print(f"fetch_gtfs_supply: skipped (no network / API / parse error: {exc}). "
              "The synthetic fallback covers dev/CI.")
        return 0

    rows = []
    for sid, count in dep.most_common():       # busiest stops first (so a cap keeps signal)
        coord = coords.get(sid)
        if coord is None:
            continue
        lat, lng = coord
        if not (BBOX["min_lat"] <= lat <= BBOX["max_lat"]
                and BBOX["min_lon"] <= lng <= BBOX["max_lon"]):
            continue
        rows.append({"location": f"stop_{sid}", "lat": lat, "lng": lng,
                     "mode": "transit", "departures": int(count)})
        if len(rows) >= MAX_OUT:
            break
    if not rows:
        print("fetch_gtfs_supply: no downtown stops returned; leaving any slice in place.")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "transit_supply__downtown.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["location", "lat", "lng", "mode", "departures"])
        w.writeheader()
        w.writerows(rows)
    print(f"transit_supply: {len(rows)} downtown stops (evening 17:00-19:00 departures) -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
