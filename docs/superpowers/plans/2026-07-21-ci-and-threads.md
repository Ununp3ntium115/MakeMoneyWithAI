# CI + Threads Marketing Implementation Plan (Plan C of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the daily pipeline (data → playbooks → KV → site build → deploy) into one GitHub Actions workflow, and add outbound Threads posting that announces newly-added repos on the product's *own* account.

**Scope boundary (read first):** The Threads integration in this plan is **outbound broadcast only** — it publishes posts about the product's own new list entries to the account owner's own feed. It does NOT read, search, follow, like, or message any other account, and it takes no input from other users' posts. Anything beyond "publish our own update to our own timeline" is out of scope and must not be added.

**Architecture:** `post_to_threads.py` is a standalone daily step that diffs `repos.csv` against a KV-stored set of already-announced slugs, publishes up to 3 new ones via the two-step Threads publish API, and records them. `threads_auth.py` is a one-time local helper that puts a long-lived token in KV. The GitHub workflow chains the existing `fetch_projects.py`, `generate_playbooks.py` (Plan A), the site build/deploy (Plan B), and the Threads step, with the Threads step never able to fail the run.

**Tech Stack:** Python 3.14 (`.venv`), `requests`, `pytest`, Threads Graph API (`graph.threads.net`), Cloudflare KV REST API (reusing Plan A's `kv_*` helpers), GitHub Actions.

## Global Constraints

- Working directory: `/Users/brodynielsen/MakeMoneyWithAI/MakeMoneyWithAI`. Python `.venv/bin/python`, tests `.venv/bin/pytest`.
- Reuse Plan A's KV helpers from `generate_playbooks.py` (`kv_list_keys` is not enough — add `kv_get`/`kv_put` for single string keys in Task 1).
- Threads token lives in KV under `threads:token` as JSON `{"access_token": str, "expires_at": epoch_seconds}`. Announced slugs live under `threads:posted` as a JSON array of slug strings.
- Daily post cap: 3. If there are more than 3 un-announced repos, post the 3 highest-star and leave the rest for subsequent days.
- Any Threads or token error logs and exits 0 — the marketing step must never fail the data/site pipeline.
- Token refresh threshold: refresh when it expires within 7 days (Threads `refresh_access_token` requires the token be ≥24h old and unexpired; the 7-day window always satisfies this).
- `THREADS_APP_ID` / `THREADS_APP_SECRET` are used ONLY by the one-time local `threads_auth.py`, never by CI.
- The site owner's Threads user id is stored in KV under `threads:token` alongside the token (`{"access_token","expires_at","user_id"}`).

---

### Task 1: Single-key KV get/put helpers

**Files:**
- Modify: `generate_playbooks.py` (append `kv_get`, `kv_put`)
- Create: `tests/test_kv_single.py`

**Interfaces:**
- Consumes: `_kv_base`, `_kv_headers`, `PlaybookError`, `requests` (Plan A)
- Produces: `kv_get(key: str) -> str | None` (None if the key is absent / 404); `kv_put(key: str, value: str) -> None` (raises `PlaybookError` on failure)

- [ ] **Step 1: Write failing tests**

Create `tests/test_kv_single.py`:

```python
import pytest

import generate_playbooks as gp
from tests.conftest import FakeResponse


@pytest.fixture(autouse=True)
def cf_env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_KV_NAMESPACE_ID", "ns")


def test_kv_get_returns_value(monkeypatch):
    monkeypatch.setattr(gp.requests, "get", lambda *a, **kw: FakeResponse(200, {}).__class__(200, {}) or FakeResponse(200, {}))
    # Simpler: patch with a response whose .text is the stored string.
    r = FakeResponse(200, {})
    r.text = "hello"
    monkeypatch.setattr(gp.requests, "get", lambda *a, **kw: r)
    assert gp.kv_get("k") == "hello"


def test_kv_get_missing_returns_none(monkeypatch):
    monkeypatch.setattr(gp.requests, "get", lambda *a, **kw: FakeResponse(404, {}))
    assert gp.kv_get("k") is None


def test_kv_put_success(monkeypatch):
    monkeypatch.setattr(gp.requests, "put", lambda *a, **kw: FakeResponse(200, {"success": True}))
    gp.kv_put("k", "v")  # no raise


def test_kv_put_failure_raises(monkeypatch):
    monkeypatch.setattr(gp.requests, "put", lambda *a, **kw: FakeResponse(500, {"success": False}))
    with pytest.raises(gp.PlaybookError):
        gp.kv_put("k", "v")
```

- [ ] **Step 2: Run — expect fail.** Run: `.venv/bin/pytest tests/test_kv_single.py -q` → `AttributeError: ... 'kv_get'`.

- [ ] **Step 3: Implement.** Append to `generate_playbooks.py`:

```python
def kv_get(key):
    """Return the string value at key, or None if it does not exist."""
    response = requests.get(f"{_kv_base()}/values/{key}", headers=_kv_headers())
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PlaybookError(f"KV get {key} failed: {response.status_code}")
    return response.text


def kv_put(key, value):
    """Write a single string value at key. Raises PlaybookError on failure."""
    response = requests.put(
        f"{_kv_base()}/values/{key}", headers=_kv_headers(),
        data=value.encode("utf-8"),
    )
    if response.status_code != 200 or not response.json().get("success"):
        raise PlaybookError(f"KV put {key} failed: {response.status_code}")
```

- [ ] **Step 4: Run — expect pass.** Run: `.venv/bin/pytest -q` → 31 passed (27 + 4).

- [ ] **Step 5: Commit.**

```bash
git add generate_playbooks.py tests/test_kv_single.py
git commit -m "Add single-key KV get/put helpers"
```

---

### Task 2: Threads posting module (TDD, API mocked)

**Files:**
- Create: `post_to_threads.py`
- Create: `tests/test_threads.py`

**Interfaces:**
- Consumes: `kv_get`, `kv_put`, `CSV_FILE`, `slug_for` (Plan A)
- Produces:
  - `format_post(repo: dict) -> str` — the post text (name, stars, blurb, playbook link).
  - `unposted_repos(rows: list[dict], posted: set[str], limit: int = 3) -> list[dict]` — highest-star repos whose slug isn't in `posted`, capped.
  - `maybe_refresh_token(token: dict, now: int) -> dict` — returns a refreshed token dict if within 7 days of expiry, else the same dict.
  - `publish(user_id: str, access_token: str, text: str) -> None` — two-step create-container → publish.
  - `main(argv=None) -> int` — always returns 0; logs and swallows all Threads errors.

- [ ] **Step 1: Write failing tests**

Create `tests/test_threads.py`:

```python
import pytest

import post_to_threads as pt
from tests.conftest import FakeResponse

ROWS = [
    {"owner": "a", "name": "one", "stars": "300", "url": "https://github.com/a/one", "business_model": "**Sell** it."},
    {"owner": "b", "name": "two", "stars": "200", "url": "https://github.com/b/two", "business_model": "**Rent** it."},
    {"owner": "c", "name": "three", "stars": "100", "url": "https://github.com/c/three", "business_model": "**Host** it."},
    {"owner": "d", "name": "four", "stars": "50", "url": "https://github.com/d/four", "business_model": "**Lease** it."},
]


def test_format_post_includes_name_and_stars():
    text = pt.format_post(ROWS[0])
    assert "a/one" in text and "300" in text


def test_unposted_picks_highest_star_capped():
    picked = pt.unposted_repos(ROWS, posted={"a__one"}, limit=3)
    assert [pt_slug(r) for r in picked] == ["b__two", "c__three", "d__four"][:3]


def pt_slug(r):
    return f"{r['owner']}__{r['name']}"


def test_unposted_empty_when_all_posted():
    assert pt.unposted_repos(ROWS, posted={"a__one", "b__two", "c__three", "d__four"}) == []


def test_maybe_refresh_within_window(monkeypatch):
    calls = []
    monkeypatch.setattr(pt.requests, "get",
                        lambda *a, **kw: calls.append(1) or FakeResponse(200, {"access_token": "NEW", "expires_in": 5000000}))
    token = {"access_token": "OLD", "expires_at": 1000 + 6 * 86400, "user_id": "u"}
    refreshed = pt.maybe_refresh_token(token, now=1000)
    assert refreshed["access_token"] == "NEW" and len(calls) == 1


def test_maybe_refresh_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(pt.requests, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not refresh")))
    token = {"access_token": "OLD", "expires_at": 1000 + 30 * 86400, "user_id": "u"}
    assert pt.maybe_refresh_token(token, now=1000)["access_token"] == "OLD"


def test_main_swallows_errors_and_returns_zero(monkeypatch):
    monkeypatch.setattr(pt, "kv_get", lambda k: (_ for _ in ()).throw(RuntimeError("kv down")))
    assert pt.main([]) == 0
```

- [ ] **Step 2: Run — expect fail.** Run: `.venv/bin/pytest tests/test_threads.py -q` → `ModuleNotFoundError: post_to_threads`.

- [ ] **Step 3: Implement.** Create `post_to_threads.py`:

```python
"""Announce newly-added repos on the product's own Threads feed (outbound only)."""
import csv
import json
import os

import requests

from generate_playbooks import CSV_FILE, kv_get, kv_put, slug_for

THREADS_API = "https://graph.threads.net"
POSTED_KEY = "threads:posted"
TOKEN_KEY = "threads:token"
DAILY_CAP = 3
REFRESH_WITHIN = 7 * 86400


def format_post(repo):
    blurb = repo["business_model"].replace("**", "")
    slug = slug_for(repo["owner"], repo["name"])
    site = os.getenv("SITE_URL", "https://makemoneywithai.pages.dev")
    return (f"New on Make Money With AI: {repo['owner']}/{repo['name']} "
            f"(☆{repo['stars']})\n\n{blurb}\n\n{site}/projects/{slug}")


def unposted_repos(rows, posted, limit=DAILY_CAP):
    fresh = [r for r in rows if slug_for(r["owner"], r["name"]) not in posted]
    fresh.sort(key=lambda r: int(r["stars"]), reverse=True)
    return fresh[:limit]


def maybe_refresh_token(token, now):
    if token["expires_at"] - now > REFRESH_WITHIN:
        return token
    resp = requests.get(f"{THREADS_API}/refresh_access_token",
                        params={"grant_type": "th_refresh_token", "access_token": token["access_token"]})
    if resp.status_code != 200:
        raise RuntimeError(f"token refresh failed: {resp.status_code}")
    data = resp.json()
    return {"access_token": data["access_token"],
            "expires_at": now + int(data["expires_in"]),
            "user_id": token["user_id"]}


def publish(user_id, access_token, text):
    create = requests.post(f"{THREADS_API}/{user_id}/threads",
                           params={"media_type": "TEXT", "text": text, "access_token": access_token})
    if create.status_code != 200:
        raise RuntimeError(f"create container failed: {create.status_code} {create.text[:200]}")
    creation_id = create.json()["id"]
    pub = requests.post(f"{THREADS_API}/{user_id}/threads_publish",
                        params={"creation_id": creation_id, "access_token": access_token})
    if pub.status_code != 200:
        raise RuntimeError(f"publish failed: {pub.status_code} {pub.text[:200]}")


def _now():
    import time
    return int(time.time())


def main(argv=None):
    try:
        raw_token = kv_get(TOKEN_KEY)
        if not raw_token:
            print("No Threads token in KV - run threads_auth.py once. Skipping.")
            return 0
        token = maybe_refresh_token(json.loads(raw_token), _now())
        kv_put(TOKEN_KEY, json.dumps(token))

        with open(CSV_FILE, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        posted = set(json.loads(kv_get(POSTED_KEY) or "[]"))
        todo = unposted_repos(rows, posted)
        if not todo:
            print("No new repos to announce.")
            return 0

        for repo in todo:
            publish(token["user_id"], token["access_token"], format_post(repo))
            posted.add(slug_for(repo["owner"], repo["name"]))
            print(f"Posted {slug_for(repo['owner'], repo['name'])}")
        kv_put(POSTED_KEY, json.dumps(sorted(posted)))
    except Exception as e:  # marketing must never fail the pipeline
        print(f"Threads posting skipped ({type(e).__name__}: {e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run — expect pass.** Run: `.venv/bin/pytest -q` → 38 passed (31 + 7).

- [ ] **Step 5: Commit.**

```bash
git add post_to_threads.py tests/test_threads.py
git commit -m "Add outbound Threads announcement module (own feed only)"
```

---

### Task 3: One-time Threads OAuth helper

**Files:**
- Create: `threads_auth.py`
- Modify: `CLAUDE.md` (document the one-time auth + the new pipeline steps)

**Interfaces:**
- Consumes: `kv_put` (Plan A)
- Produces: a CLI that, given a redirect `code`, exchanges it for a short-lived token, upgrades to long-lived, fetches the user id, and writes `{access_token, expires_at, user_id}` to KV under `threads:token`.

- [ ] **Step 1: Implement** `threads_auth.py`:

```python
"""One-time local helper: put a long-lived Threads token into Cloudflare KV.

Usage:
  1. Open the authorization URL this prints, approve, copy the `code` param.
  2. Re-run with:  python threads_auth.py <code>
Requires THREADS_APP_ID, THREADS_APP_SECRET, THREADS_REDIRECT_URI in env.
"""
import json
import os
import sys
import time

import requests

from generate_playbooks import kv_put

THREADS_API = "https://graph.threads.net"
AUTH_URL = "https://threads.net/oauth/authorize"


def auth_url():
    return (f"{AUTH_URL}?client_id={os.environ['THREADS_APP_ID']}"
            f"&redirect_uri={os.environ['THREADS_REDIRECT_URI']}"
            f"&scope=threads_basic,threads_content_publish&response_type=code")


def exchange(code):
    short = requests.post(f"{THREADS_API}/oauth/access_token", data={
        "client_id": os.environ["THREADS_APP_ID"],
        "client_secret": os.environ["THREADS_APP_SECRET"],
        "grant_type": "authorization_code",
        "redirect_uri": os.environ["THREADS_REDIRECT_URI"],
        "code": code,
    })
    short.raise_for_status()
    short_token = short.json()["access_token"]
    user_id = str(short.json()["user_id"])

    long = requests.get(f"{THREADS_API}/access_token", params={
        "grant_type": "th_exchange_token",
        "client_secret": os.environ["THREADS_APP_SECRET"],
        "access_token": short_token,
    })
    long.raise_for_status()
    data = long.json()
    return {"access_token": data["access_token"],
            "expires_at": int(time.time()) + int(data["expires_in"]),
            "user_id": user_id}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("Open this URL, approve, then re-run with the `code` you get back:\n")
        print(auth_url())
        return 0
    token = exchange(argv[0])
    kv_put("threads:token", json.dumps(token))
    print(f"Stored long-lived token for user {token['user_id']} (expires_at {token['expires_at']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Manual sanity (no live call needed).** Run: `python threads_auth.py` with dummy env and confirm it prints an auth URL:

```bash
THREADS_APP_ID=x THREADS_REDIRECT_URI=https://example.com .venv/bin/python threads_auth.py | head -2
```

Expected: prints the instructions and a `https://threads.net/oauth/authorize?...` URL.

- [ ] **Step 3: Document** in `CLAUDE.md` (append to Commands):

```markdown
python threads_auth.py                  # one-time: print Threads auth URL; re-run with the code to store a token in KV
python post_to_threads.py               # announce up to 3 new repos on the product's own Threads feed
```

- [ ] **Step 4: Commit.**

```bash
git add threads_auth.py CLAUDE.md
git commit -m "Add one-time Threads OAuth helper and docs"
```

---

### Task 4: Unified daily workflow

**Blocked on user-supplied CI secrets** for the deploy + KV steps (`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CF_KV_NAMESPACE_ID`, plus existing `OPENAI_API_KEY`). The workflow can be committed now; it will only fully succeed once secrets exist and the GitHub Actions billing lock is cleared.

**Files:**
- Modify: `.github/workflows/fetch-ai-projects.yml`

**Interfaces:**
- Consumes: `fetch_projects.py`, `generate_playbooks.py`, `post_to_threads.py`, `site/` build (Plan B).

- [ ] **Step 1: Replace the single-step job** with the full chain. Key steps (append after the existing "Fetch AI projects" step, before the git commit step):

```yaml
      - name: Generate playbooks
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          OPENAI_MODEL: ${{ vars.OPENAI_MODEL }}
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          CF_KV_NAMESPACE_ID: ${{ secrets.CF_KV_NAMESPACE_ID }}
        run: python generate_playbooks.py

      - name: Build site
        run: cd site && corepack enable && pnpm install --frozen-lockfile=false && pnpm build

      - name: Deploy to Cloudflare Pages
        uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy site/dist --project-name=makemoneywithai

      - name: Announce new repos on Threads
        continue-on-error: true
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          CF_KV_NAMESPACE_ID: ${{ secrets.CF_KV_NAMESPACE_ID }}
          SITE_URL: ${{ vars.SITE_URL }}
        run: python post_to_threads.py
```

Keep the existing commit step, adding `site/src/data/previews.json` to its `git add` line. Update the "Install dependencies" step to also set up Node/pnpm (`actions/setup-node@v4` with `node-version: 20`).

- [ ] **Step 2: Lint the YAML locally.**

```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/fetch-ai-projects.yml')); print('yaml ok')"
```

Expected: `yaml ok` (install pyyaml into the venv first if needed: `.venv/bin/pip install -q pyyaml`).

- [ ] **Step 3: Commit.**

```bash
git add .github/workflows/fetch-ai-projects.yml
git commit -m "CI: chain playbooks, site build/deploy, and Threads announce into daily run"
```

- [ ] **Step 4: (When secrets + billing ready)** add the CI secrets in the fork's Settings → Secrets, enable Actions on the fork, and trigger a manual run: `gh workflow run "Fetch AI Projects" --repo Ununp3ntium115/MakeMoneyWithAI`. Confirm the run reaches the deploy step and the site updates.

---

## Plan Self-Review (completed)

- **Spec coverage:** daily chain data→playbooks→KV→build→deploy→Threads (Task 4); Threads token in KV via one-time local OAuth (Task 3); long-lived exchange + 7-day refresh (Tasks 2, 3); ≤3 posts/day, highest-star first (Task 2); posting never fails the run (Task 2 `main` + `continue-on-error`); outbound-own-feed-only boundary (scope note + `publish` only calls `/{user_id}/threads*`). No reading/following/messaging endpoints appear anywhere.
- **Placeholders:** none — full code for each module; workflow YAML is concrete.
- **Type consistency:** `kv_get`/`kv_put`, `format_post`, `unposted_repos`, `maybe_refresh_token`, `publish`, `main`, `slug_for` signatures match across tasks and tests. Token dict shape `{access_token, expires_at, user_id}` is consistent across Tasks 2 and 3.
