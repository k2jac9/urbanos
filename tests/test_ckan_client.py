"""Hermetic tests for the hardened CKAN client — retries, catalog search, datastore
pagination, resource selection, streaming download. No network: an httpx.MockTransport
serves canned responses (and simulates transient failures) so CI stays offline.
"""
from __future__ import annotations

import httpx
import pytest

from urbanos.risk.ingest.ckan import CKANClient


def _client(handler, **kw) -> CKANClient:
    # backoff=0.0 so retry loops don't actually sleep during tests.
    return CKANClient(
        base_url="https://ckan.test", backoff=0.0,
        transport=httpx.MockTransport(handler), **kw,
    )


def _ok(result):
    return httpx.Response(200, json={"success": True, "result": result})


# --- catalog discovery ------------------------------------------------------
def test_search_parses_results():
    def handler(req):
        return _ok({"count": 1, "results": [
            {"name": "ttc-routes-and-schedules", "title": "TTC Routes",
             "formats": ["ZIP"], "id": "abc"},
        ]})
    hits = _client(handler).search("ttc")
    assert hits == [{"name": "ttc-routes-and-schedules", "title": "TTC Routes",
                     "formats": ["ZIP"], "id": "abc"}]


# --- retry / backoff --------------------------------------------------------
def test_action_retries_transient_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:                       # fail the first two attempts
            raise httpx.ConnectError("boom", request=req)
        return _ok({"ok": True})
    out = _client(handler, retries=3)._action("package_show", id="x")
    assert out == {"ok": True}
    assert calls["n"] == 3


def test_action_retries_on_retryable_status():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)           # transient server error → retry
        return _ok({"ok": True})
    assert _client(handler, retries=2)._action("package_show", id="x") == {"ok": True}
    assert calls["n"] == 2


def test_action_raises_after_exhausting_retries():
    def handler(req):
        raise httpx.ConnectError("down", request=req)
    with pytest.raises(httpx.ConnectError):
        _client(handler, retries=2)._action("package_show", id="x")


def test_action_raises_on_ckan_failure_body():
    def handler(req):
        return httpx.Response(200, json={"success": False, "error": {"message": "nope"}})
    with pytest.raises(RuntimeError, match="failed"):
        _client(handler)._action("package_show", id="x")


# --- datastore pagination ---------------------------------------------------
def test_datastore_iter_paginates_to_completion_and_respects_max_rows():
    data = [{"i": i} for i in range(7)]

    def handler(req):
        off = int(req.url.params.get("offset", 0))
        lim = int(req.url.params.get("limit", 100))
        return _ok({"records": data[off:off + lim], "total": len(data)})
    cli = _client(handler)
    assert list(cli.datastore_iter("res", page_size=3)) == data         # all 7, 3 pages
    assert list(cli.datastore_iter("res", page_size=3, max_rows=4)) == data[:4]


def test_datastore_iter_stops_on_empty_page():
    def handler(req):
        return _ok({"records": [], "total": 0})
    assert list(_client(handler).datastore_iter("res")) == []


# --- resource selection -----------------------------------------------------
def test_find_resource_by_format_and_name():
    def handler(req):
        return _ok({"resources": [
            {"format": "XLSX", "name": "readme", "id": "1"},
            {"format": "ZIP", "name": "2024 data", "id": "2"},
            {"format": "ZIP", "name": "2025 data", "id": "3"},
        ]})
    cli = _client(handler)
    assert cli.find_resource("s", formats=("zip",))["id"] == "2"
    assert cli.find_resource("s", formats=("zip",), name_contains="2025")["id"] == "3"
    assert cli.find_resource("s", formats=("csv",)) is None


# --- streaming download -----------------------------------------------------
def test_download_resource_streams_to_file(tmp_path):
    def handler(req):
        return httpx.Response(200, content=b"hello world")
    dest = tmp_path / "sub" / "out.bin"
    out = _client(handler).download_resource("https://ckan.test/f.bin", dest)
    assert out == dest and dest.read_bytes() == b"hello world"


def test_download_resource_enforces_max_bytes(tmp_path):
    def handler(req):
        return httpx.Response(200, content=b"x" * 100)
    with pytest.raises(ValueError, match="max_bytes"):
        _client(handler).download_resource(
            "https://ckan.test/big.bin", tmp_path / "big.bin", max_bytes=10, chunk=4
        )


def test_download_resource_requires_url(tmp_path):
    with pytest.raises(ValueError, match="no url"):
        _client(lambda req: httpx.Response(200)).download_resource({}, tmp_path / "x")
