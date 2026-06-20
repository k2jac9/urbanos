"""Hardened client for the City of Toronto CKAN open-data API (open.toronto.ca).

One robust, reusable way to reach *any* dataset in the catalog, so fetch scripts
stop hand-rolling pagination/retries and we discover datasets instead of guessing.
Network calls are isolated here so the rest of the app runs against cached/sample
data offline (the venue Wi-Fi is unreliable — pre-download with
``scripts/download_data.py``; discover with ``scripts/catalog.py``).

Capabilities:
- **Resilient transport** — every request retries transient failures (connection
  errors, timeouts, 429/5xx) with exponential backoff, follows redirects.
- **Catalog discovery** — :meth:`package_search` / :meth:`search` over the whole
  gallery (so "did we look?" is a command, not a guess).
- **Bulk rows** — :meth:`datastore_iter` auto-paginates a datastore resource to
  completion (or a row cap), with optional ``filters`` / full-text ``q``.
- **Files** — :meth:`find_resource` picks a resource by format/name;
  :meth:`download_resource` streams it to disk with a size guard (for ZIP/XLSX).

The legacy surface (:meth:`package`, :meth:`resources`, :meth:`datastore_search`)
is preserved for existing callers; it now rides the same retrying transport.
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

# Transport-level failures worth retrying (connection reset, DNS, read timeout, …).
_TRANSIENT = (httpx.TransportError,)
# HTTP statuses worth retrying (rate-limit + transient server errors).
_RETRY_STATUS = {429, 500, 502, 503, 504}


class CKANClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        *,
        retries: int = 3,
        backoff: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.ckan_base_url).rstrip("/")
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))
        self._client = httpx.Client(
            timeout=timeout, follow_redirects=True, transport=transport
        )

    # -- resilient transport ------------------------------------------------
    def _sleep(self, attempt: int) -> None:
        if self.backoff > 0:
            time.sleep(self.backoff * (2 ** attempt))

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """One HTTP call with retry+backoff on transient errors / retryable status."""
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._client.request(method, url, **kwargs)
                if resp.status_code in _RETRY_STATUS and attempt < self.retries:
                    last = httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    self._sleep(attempt)
                    continue
                resp.raise_for_status()
                return resp
            except _TRANSIENT as exc:
                last = exc
                if attempt >= self.retries:
                    break
                self._sleep(attempt)
        assert last is not None
        raise last

    def _action(self, action: str, **params: Any) -> Any:
        """Call a CKAN action API endpoint and return its ``result`` payload."""
        resp = self._request(
            "GET", f"{self.base_url}/api/3/action/{action}", params=params
        )
        body = resp.json()
        if not body.get("success", False):
            raise RuntimeError(f"CKAN action {action} failed: {body.get('error')}")
        return body["result"]

    # -- catalog discovery --------------------------------------------------
    def package_search(self, query: str = "", *, rows: int = 20, start: int = 0) -> dict:
        """Raw ``package_search`` result (``count`` + ``results``) for a query."""
        return self._action("package_search", q=query, rows=rows, start=start)

    def search(self, query: str = "", *, rows: int = 20) -> list[dict[str, Any]]:
        """Discover datasets matching ``query`` — a tidy ``[{name,title,formats,id}]``."""
        res = self.package_search(query, rows=rows)
        return [
            {
                "name": p.get("name"),
                "title": p.get("title"),
                "formats": p.get("formats"),
                "id": p.get("id"),
            }
            for p in res.get("results", [])
        ]

    # -- dataset metadata + resources ---------------------------------------
    def package(self, slug: str) -> dict[str, Any]:
        """Metadata for a dataset, including its downloadable resources."""
        return self._action("package_show", id=slug)

    def resources(self, slug: str) -> list[dict[str, Any]]:
        return self.package(slug).get("resources", [])

    def find_resource(
        self,
        slug: str,
        *,
        formats: tuple[str, ...] | None = None,
        name_contains: str | None = None,
    ) -> dict[str, Any] | None:
        """First resource on ``slug`` matching a format and/or a name substring
        (both case-insensitive). ``None`` when nothing matches."""
        fmts = {f.lower() for f in formats} if formats else None
        needle = name_contains.lower() if name_contains else None
        for res in self.resources(slug):
            if fmts and (res.get("format") or "").lower() not in fmts:
                continue
            if needle and needle not in (res.get("name") or "").lower():
                continue
            return res
        return None

    # -- datastore rows -----------------------------------------------------
    def datastore_search(
        self, resource_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """One page of rows from a datastore-active resource (legacy surface)."""
        result = self._action(
            "datastore_search", id=resource_id, limit=limit, offset=offset
        )
        return result.get("records", [])

    def datastore_iter(
        self,
        resource_id: str,
        *,
        page_size: int = 5000,
        max_rows: int | None = None,
        filters: dict[str, Any] | None = None,
        q: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every row of a datastore resource, paginating to completion (or to
        ``max_rows``). Optional CKAN ``filters`` (exact field matches) and ``q``
        (full-text). The thing every fetch script used to hand-roll."""
        offset = 0
        yielded = 0
        while True:
            params: dict[str, Any] = {
                "id": resource_id,
                "limit": page_size,
                "offset": offset,
            }
            if filters:
                params["filters"] = json.dumps(filters)
            if q:
                params["q"] = q
            result = self._action("datastore_search", **params)
            records = result.get("records", [])
            if not records:
                return
            for rec in records:
                yield rec
                yielded += 1
                if max_rows is not None and yielded >= max_rows:
                    return
            offset += len(records)
            total = result.get("total")
            if total is not None and offset >= int(total):
                return

    # -- files --------------------------------------------------------------
    def download_resource(
        self,
        resource: dict[str, Any] | str,
        dest: str | Path,
        *,
        max_bytes: int | None = None,
        chunk: int = 1 << 16,
    ) -> Path:
        """Stream a resource (a resource dict or a URL) to ``dest`` with retry and an
        optional ``max_bytes`` guard (raises before overrunning — no silent giant
        downloads). Returns the written path."""
        url = resource.get("url") if isinstance(resource, dict) else str(resource)
        if not url:
            raise ValueError("resource has no url")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                written = 0
                with self._client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as fh:
                        for block in resp.iter_bytes(chunk):
                            written += len(block)
                            if max_bytes is not None and written > max_bytes:
                                raise ValueError(
                                    f"resource exceeds max_bytes={max_bytes}"
                                )
                            fh.write(block)
                return dest
            except _TRANSIENT as exc:
                last = exc
                if attempt >= self.retries:
                    break
                self._sleep(attempt)
        assert last is not None
        raise last

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CKANClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
