"""Build a small committed REAL slice of Toronto active road restrictions (demo_data/).

Produces ``demo_data/road_restrictions__downtown.csv`` — the geocoded "where the road network is
currently disrupted" field the Urban-OS RoadDisruption display lens lifts onto the substrate
(ADR-0037). Each row of the City "Road Restrictions (Version 3)" feed is a real active closure /
restriction at a ``Latitude``/``Longitude`` with a road class. Counting road-class-weighted
restrictions near each substrate node gives a real, static **disruption density** — distinct from
the crush and from the historical KSI danger field.

What it does (real values, only reshaped):
- Streams the Road Restrictions CSV (note: the file's FIRST line is a title — the real header is
  the SECOND line, handled below).
- Keeps the downtown bbox (matches ``fetch_tmc.py`` / ``fetch_ksi.py`` / the offline PMTiles
  basemap) and weights each restriction by road class (Major Arterial 3 / Minor Arterial or
  Collector 2 / else 1) so a closure on a big egress road reads hotter than a side street — the
  relative *shape* is the claim, not any single count.
- Writes a tidy slice (one row per kept restriction), most-severe first so an MAX_OUT cap keeps
  the strongest signal.

Offline-safe: any network/parse failure prints a note and exits 0 (the adapter's synthetic
fallback covers dev/CI). The raw CSV is never committed — only the small normalized slice.

    python scripts/fetch_road_restrictions.py
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "demo_data"

_DATASET = "road-restrictions"
_RESOURCE_CSV = "58d5be90-b8cd-46a9-8671-4deeffd833d4"   # "Road Restrictions (Version 3) - CSV"
_RESOURCE_SHOW = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/api/3/action/resource_show"
)
# Downtown bbox — matches fetch_tmc.py / fetch_ksi.py / the offline PMTiles basemap.
BBOX = dict(min_lat=43.62, max_lat=43.69, min_lon=-79.43, max_lon=-79.34)
MAX_OUT = 1500


def _severity(road_class: str) -> int:
    """Road-class weight (Major Arterial 3 / Minor Arterial or Collector 2 / else 1) — a closure
    on a bigger egress road matters more to the crowd than a side street."""
    rc = (road_class or "").strip().lower()
    if "major" in rc:
        return 3
    if "minor" in rc or "collector" in rc:
        return 2
    return 1


def _resource_url(rid: str) -> str:
    resp = httpx.get(_RESOURCE_SHOW, params={"id": rid}, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()["result"]["url"]


def _collect(text: str) -> list[dict]:
    """The Road Restrictions CSV opens with a one-line TITLE; the real header is line 2. Skip the
    title, then DictReader the rest. Keep downtown rows with a parseable lat/lng. One bad row is
    skipped, never fatal."""
    lines = text.splitlines()
    # Drop the leading title line(s) until we reach the real header (the one with Latitude).
    start = 0
    for i, ln in enumerate(lines[:5]):
        if "latitude" in ln.lower() and "longitude" in ln.lower():
            start = i
            break
    reader = csv.DictReader(lines[start:])
    rows: list[dict] = []
    for r in reader:
        try:
            lat = float(r.get("Latitude") or "")
            lng = float(r.get("Longitude") or "")
        except (TypeError, ValueError):
            continue
        if not (BBOX["min_lat"] <= lat <= BBOX["max_lat"]
                and BBOX["min_lon"] <= lng <= BBOX["max_lon"]):
            continue
        rows.append({
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "severity": _severity(r.get("RoadClass", "")),
            "road_class": (r.get("RoadClass") or "").strip() or "Unknown",
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        url = _resource_url(_RESOURCE_CSV)
        text = httpx.get(url, timeout=120, follow_redirects=True).content.decode(
            "utf-8-sig", errors="replace"
        )
        rows = _collect(text)
    except Exception as exc:  # noqa: BLE001 — offline-safe: never fail the chained target
        print(f"fetch_road_restrictions: skipped (no network / API error: {exc}). "
              "The synthetic road-disruption fallback covers dev/CI.")
        return 0
    if not rows:
        print("fetch_road_restrictions: no downtown rows; leaving any existing slice in place.")
        return 0
    rows.sort(key=lambda r: -r["severity"])
    rows = rows[:MAX_OUT]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "road_restrictions__downtown.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["lat", "lng", "severity", "road_class"])
        w.writeheader()
        w.writerows(rows)
    majors = sum(1 for r in rows if r["severity"] == 3)
    print(f"road_restrictions: {len(rows)} downtown active restrictions ({majors} major-arterial) "
          f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
