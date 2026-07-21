import pytest

import generate_playbooks as gp
from tests.conftest import FakeResponse


@pytest.fixture(autouse=True)
def cf_env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_KV_NAMESPACE_ID", "ns")


def test_kv_list_keys_paginates(monkeypatch):
    pages = [
        FakeResponse(200, {
            "success": True,
            "result": [{"name": "a__one"}, {"name": "b__two"}],
            "result_info": {"cursor": "next-page"},
        }),
        FakeResponse(200, {
            "success": True,
            "result": [{"name": "c__three"}],
            "result_info": {"cursor": ""},
        }),
    ]
    calls = []

    def fake_get(url, headers=None, params=None):
        calls.append(params or {})
        return pages[len(calls) - 1]

    monkeypatch.setattr(gp.requests, "get", fake_get)
    assert gp.kv_list_keys() == {"a__one", "b__two", "c__three"}
    assert len(calls) == 2 and calls[1].get("cursor") == "next-page"


def test_kv_list_keys_failure_raises(monkeypatch):
    monkeypatch.setattr(gp.requests, "get", lambda *a, **kw: FakeResponse(500, {"success": False}))
    with pytest.raises(gp.PlaybookError):
        gp.kv_list_keys()


def test_kv_bulk_put_success(monkeypatch):
    seen = {}

    def fake_put(url, headers=None, json=None):
        seen["url"] = url
        seen["body"] = json
        return FakeResponse(200, {"success": True})

    monkeypatch.setattr(gp.requests, "put", fake_put)
    gp.kv_bulk_put([{"key": "a__one", "value": "{}"}])
    assert seen["url"].endswith("/bulk") and seen["body"][0]["key"] == "a__one"


def test_kv_bulk_put_failure_raises(monkeypatch):
    monkeypatch.setattr(gp.requests, "put", lambda *a, **kw: FakeResponse(403, {"success": False}))
    with pytest.raises(gp.PlaybookError):
        gp.kv_bulk_put([{"key": "a", "value": "b"}])
