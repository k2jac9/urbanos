"""Discover City of Toronto open datasets (open.toronto.ca) from the terminal.

So we *search the catalog* instead of guessing a single slug. Pairs with the
hardened ``urbanos.risk.ingest.ckan.CKANClient`` and ``download_data.py``.

    python scripts/catalog.py search "ttc ridership"     # find datasets by keyword
    python scripts/catalog.py show ttc-routes-and-schedules  # list a dataset's resources

``search`` prints matching dataset slugs (feed one to ``show`` or to
``download_data.py``); ``show`` prints each resource's format / name / whether it is
datastore-queryable, so you know how to pull it. Network tool: a failure prints a
clear message and exits non-zero (unlike the offline-safe fetchers, this is for
interactive discovery, so surfacing the error is the point).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from urbanos.risk.ingest.ckan import CKANClient  # noqa: E402


def _search(query: str, rows: int = 25) -> int:
    with CKANClient() as ckan:
        hits = ckan.search(query, rows=rows)
    if not hits:
        print(f"no datasets match {query!r}.")
        return 0
    print(f"{len(hits)} dataset(s) matching {query!r}:\n")
    for h in hits:
        fmts = ",".join(h.get("formats") or []) or "?"
        print(f"  {h['name']}")
        print(f"      {h.get('title', '')}  [{fmts}]")
    print("\nNext: scripts/catalog.py show <slug>   (or add it to the registry + download_data.py)")
    return 0


def _show(slug: str) -> int:
    with CKANClient() as ckan:
        try:
            resources = ckan.resources(slug)
        except Exception as exc:  # noqa: BLE001
            print(f"could not load {slug!r}: {exc}")
            return 1
    if not resources:
        print(f"{slug}: no resources.")
        return 0
    print(f"{slug} - {len(resources)} resource(s):\n")
    for r in resources:
        ds = "datastore" if r.get("datastore_active") else "file"
        print(f"  [{(r.get('format') or '?'):>7}] {r.get('name', '')}  ({ds})")
        print(f"          id={r.get('id')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] not in {"search", "show"}:
        print(__doc__)
        return 2
    cmd, rest = args[0], args[1:]
    try:
        if cmd == "search":
            return _search(" ".join(rest))
        return _show(rest[0])
    except Exception as exc:  # noqa: BLE001 — discovery tool: surface the failure
        print(f"catalog {cmd} failed (network / API): {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
