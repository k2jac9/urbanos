#!/usr/bin/env bash
# Rebuild the offline downtown-Toronto vector basemap (static/toronto.pmtiles).
#
# Pulls only the bbox region from the Protomaps daily build via HTTP range requests
# (~6 MB), so it's ToS-clean OSM-derived data, not a bulk tile scrape. Re-run to
# refresh the basemap or widen the area. Requires the `pmtiles` CLI:
#   https://github.com/protomaps/go-pmtiles/releases
set -euo pipefail

BUILD="${BUILD:-https://build.protomaps.com/20251201.pmtiles}"   # pick a recent daily build
BBOX="${BBOX:--79.43,43.62,-79.34,43.69}"                        # downtown Toronto
OUT="${OUT:-src/urbanos/risk/api/static/toronto.pmtiles}"
MAXZOOM="${MAXZOOM:-15}"

pmtiles extract "$BUILD" "$OUT" --bbox="$BBOX" --maxzoom="$MAXZOOM"
echo "Wrote $OUT"
pmtiles show "$OUT" | head -8
