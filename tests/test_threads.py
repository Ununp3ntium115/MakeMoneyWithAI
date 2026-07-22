import pytest

import post_to_threads as pt
from tests.conftest import FakeResponse

ROWS = [
    {"owner": "a", "name": "one", "stars": "300", "url": "https://github.com/a/one", "business_model": "**Sell** it."},
    {"owner": "b", "name": "two", "stars": "200", "url": "https://github.com/b/two", "business_model": "**Rent** it."},
    {"owner": "c", "name": "three", "stars": "100", "url": "https://github.com/c/three", "business_model": "**Host** it."},
    {"owner": "d", "name": "four", "stars": "50", "url": "https://github.com/d/four", "business_model": "**Lease** it."},
]


def slug(r):
    return f"{r['owner']}__{r['name']}"


def test_format_post_includes_name_and_stars():
    text = pt.format_post(ROWS[0])
    assert "a/one" in text and "300" in text
    assert "**" not in text  # markdown stripped for plain-text feed


def test_unposted_picks_highest_star_capped():
    picked = pt.unposted_repos(ROWS, posted={"a__one"}, limit=3)
    assert [slug(r) for r in picked] == ["b__two", "c__three", "d__four"]


def test_unposted_empty_when_all_posted():
    assert pt.unposted_repos(ROWS, posted={"a__one", "b__two", "c__three", "d__four"}) == []


def test_maybe_refresh_within_window(monkeypatch):
    calls = []
    monkeypatch.setattr(pt.requests, "get",
                        lambda *a, **kw: calls.append(1) or FakeResponse(200, {"access_token": "NEW", "expires_in": 5000000}))
    token = {"access_token": "OLD", "expires_at": 1000 + 6 * 86400, "user_id": "u"}
    refreshed = pt.maybe_refresh_token(token, now=1000)
    assert refreshed["access_token"] == "NEW" and len(calls) == 1


def test_maybe_refresh_skips_when_fresh():
    token = {"access_token": "OLD", "expires_at": 1000 + 30 * 86400, "user_id": "u"}
    # No requests.get patched — if it tried to call out, it would fail the network.
    assert pt.maybe_refresh_token(token, now=1000)["access_token"] == "OLD"


def test_publish_calls_own_feed_endpoints_only(monkeypatch):
    urls = []

    def fake_post(url, params=None):
        urls.append(url)
        return FakeResponse(200, {"id": "container1"})

    monkeypatch.setattr(pt.requests, "post", fake_post)
    pt.publish("u123", "tok", "hello")
    assert urls == [f"{pt.THREADS_API}/u123/threads", f"{pt.THREADS_API}/u123/threads_publish"]


def test_main_swallows_errors_and_returns_zero(monkeypatch):
    def boom(_k):
        raise RuntimeError("kv down")
    monkeypatch.setattr(pt, "kv_get", boom)
    assert pt.main([]) == 0


def test_main_skips_when_no_token(monkeypatch):
    monkeypatch.setattr(pt, "kv_get", lambda k: None)
    assert pt.main([]) == 0
