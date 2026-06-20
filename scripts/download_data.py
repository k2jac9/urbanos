"""Pre-download Toronto open datasets into DATA_DIR.

RUN THIS BEFORE THE HACKATHON. The venue Wi-Fi and live CKAN API are unreliable
during judging — cache everything locally so the demo never depends on the network.

Usage:
    python scripts/download_data.py            # all registered datasets
    python scripts/download_data.py permits    # one dataset by registry key
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from urbanos.risk.config import settings  # noqa: E402
from urbanos.risk.ingest.ckan import CKANClient  # noqa: E402
from urbanos.risk.ingest.datasets import REGISTRY  # noqa: E402


def download(keys: list[str]) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    with CKANClient() as ckan:
        for key in keys:
            ds = REGISTRY[key]
            print(f"[{key}] {ds.title} ({ds.cadence}, geo={ds.geo})")
            try:
                resources = ckan.resources(ds.slug)
            except Exception as exc:
                print(f"  ! could not list resources: {exc}")
                continue
            for res in resources:
                url = res.get("url")
                fmt = (res.get("format") or "").lower()
                if not url or fmt not in {"csv", "json", "geojson", "xml"}:
                    continue
                dest = settings.data_dir / f"{key}__{res.get('name', res['id'])}.{fmt}"
                try:
                    # Stream via the hardened client (retry/backoff + redirects).
                    ckan.download_resource(res, dest)
                    print(f"  -> {dest.name}")
                except Exception as exc:
                    print(f"  ! {url}: {exc}")


if __name__ == "__main__":
    requested = sys.argv[1:] or list(REGISTRY)
    unknown = [k for k in requested if k not in REGISTRY]
    if unknown:
        sys.exit(f"unknown dataset key(s): {unknown}; known: {sorted(REGISTRY)}")
    download(requested)
