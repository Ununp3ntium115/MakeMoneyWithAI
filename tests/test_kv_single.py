import pytest

import generate_playbooks as gp
from tests.conftest import FakeResponse


@pytest.fixture(autouse=True)
def cf_env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_KV_NAMESPACE_ID", "ns")


def test_kv_get_returns_value(monkeypatch):
    r = FakeResponse(200, {})
    r.text = "hello"
    monkeypatch.setattr(gp.requests, "get", lambda *a, **kw: r)
    assert gp.kv_get("k") == "hello"


def test_kv_get_missing_returns_none(monkeypatch):
    monkeypatch.setattr(gp.requests, "get", lambda *a, **kw: FakeResponse(404, {}))
    assert gp.kv_get("k") is None


def test_kv_get_error_raises(monkeypatch):
    monkeypatch.setattr(gp.requests, "get", lambda *a, **kw: FakeResponse(500, {}))
    with pytest.raises(gp.PlaybookError):
        gp.kv_get("k")


def test_kv_put_success(monkeypatch):
    monkeypatch.setattr(gp.requests, "put", lambda *a, **kw: FakeResponse(200, {"success": True}))
    gp.kv_put("k", "v")  # no raise


def test_kv_put_failure_raises(monkeypatch):
    monkeypatch.setattr(gp.requests, "put", lambda *a, **kw: FakeResponse(500, {"success": False}))
    with pytest.raises(gp.PlaybookError):
        gp.kv_put("k", "v")
