"""Build small, committed REAL-data slices for the demo (demo_data/).

Produces three slices that share addresses so the demo shows genuine cross-dataset
fusion on the map:
  - dinesafe__downtown.csv  (food-safety inspections, drives risk + map pins/coords)
  - licences__downtown.csv  (business licences at the SAME addresses → linked records)
  - permits__downtown.csv   (active building permits at the SAME addresses → also risk)

Both are filtered to the downtown bbox that matches the offline PMTiles basemap,
kept small for the repo, and preserve the real column schema. Re-run to refresh.

    python scripts/build_demo_slice.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from urbanos.risk.graph.builder import normalize_address  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "demo_data"
BBOX = dict(min_lon=-79.43, min_lat=43.62, max_lon=-79.34, max_lat=43.69)
DINESAFE_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "b6b4f3fb-2e2c-47e7-931d-b87d22806948/resource/"
    "af0f5b8a-4b73-4a50-8781-65e949792b40/download/dinesafe.csv"
)
LICENCES_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "57b2285f-4f80-45fb-ae3e-41a02c3a137f/resource/"
    "54bddc5e-92d9-4102-89c1-43e82f8f4d2d/download/business-licences-data.csv"
)
PERMITS_URL = (
    "https://ckan0.cf.opendata.inter.prod-toronto.ca/dataset/"
    "108c2bd1-6945-46f6-af92-02f5658ee7f7/resource/"
    "dfce3b7b-4f17-4a9d-9155-5e390a5ffa97/download/building-permits-active-permits.csv"
)
MAX_DINESAFE = 250
MAX_LICENCES = 200
MAX_PERMITS = 200


def _ensure(path: Path, url: str) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url.rsplit('/', 1)[-1]} → {path} …")
        path.write_bytes(httpx.get(url, timeout=180, follow_redirects=True).content)
    return path


def build_dinesafe() -> set[str]:
    df = pd.read_csv(_ensure(RAW / "dinesafe__real.csv", DINESAFE_URL), dtype=str).fillna("")
    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["lon"] = pd.to_numeric(df["longitude"], errors="coerce")
    downtown = df[
        df["lat"].between(BBOX["min_lat"], BBOX["max_lat"])
        & df["lon"].between(BBOX["min_lon"], BBOX["max_lon"])
        & (df["address"] != "")
    ]
    at_risk = downtown[downtown["inspectionStatus"] != "Pass"]
    passing = downtown[downtown["inspectionStatus"] == "Pass"]
    keep = pd.concat([at_risk.head(MAX_DINESAFE // 2), passing.head(MAX_DINESAFE // 2)])
    keep = keep.drop(columns=["lat", "lon"]).head(MAX_DINESAFE)
    OUT.mkdir(parents=True, exist_ok=True)
    keep.to_csv(OUT / "dinesafe__downtown.csv", index=False)
    keys = {normalize_address(a) for a in keep["address"]}
    print(f"dinesafe: {len(keep)} rows, {len(keys)} addresses")
    return keys


def build_licences(addr_keys: set[str]) -> None:
    df = pd.read_csv(_ensure(RAW / "licences__real.csv", LICENCES_URL), dtype=str).fillna("")
    df["key"] = df["Licence Address Line 1"].map(normalize_address)
    keep = df[df["key"].isin(addr_keys)].drop(columns=["key"]).head(MAX_LICENCES)
    keep.to_csv(OUT / "licences__downtown.csv", index=False)
    print(f"licences: {len(keep)} rows linking to {keep['Licence Address Line 1'].nunique()} addresses")


def build_permits(addr_keys: set[str]) -> None:
    df = pd.read_csv(_ensure(RAW / "permits__real.csv", PERMITS_URL), dtype=str).fillna("")
    composite = (
        df["STREET_NUM"] + " " + df["STREET_NAME"] + " "
        + df["STREET_TYPE"] + " " + df["STREET_DIRECTION"]
    )
    df["key"] = composite.map(normalize_address)
    matched = df[df["key"].isin(addr_keys)]
    n_addr = matched["key"].nunique()
    matched.drop(columns=["key"]).head(MAX_PERMITS).to_csv(OUT / "permits__downtown.csv", index=False)
    print(f"permits: {min(len(matched), MAX_PERMITS)} rows linking to {n_addr} addresses")


def main() -> None:
    keys = build_dinesafe()
    build_licences(keys)
    build_permits(keys)


if __name__ == "__main__":
    main()
