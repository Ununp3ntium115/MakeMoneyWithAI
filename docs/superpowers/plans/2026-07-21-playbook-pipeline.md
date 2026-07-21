# Playbook Content Pipeline Implementation Plan (Plan A of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `generate_playbooks.py` — the pipeline stage that turns each repo in `repos.csv` into a schema-validated money-making playbook, stores full bodies in Cloudflare KV, and maintains the committed public previews file.

**Architecture:** Single Python module with pure functions (validation, prompt, OpenAI call, KV client, preview writer) orchestrated by `main()`. KV is the source of truth for which playbooks exist; local `playbooks/` is a gitignored working copy; `site/src/data/previews.json` is the only committed output. Sibling plans: Plan B (site + paywall) consumes `previews.json` and the KV value format; Plan C (Threads + CI) invokes this script in the daily workflow.

**Tech Stack:** Python 3.14 (repo `.venv`), `requests` (only runtime dep), `pytest` (dev), OpenAI Chat Completions API, Cloudflare KV REST API.

## Global Constraints

- Working directory for all commands: `/Users/brodynielsen/MakeMoneyWithAI/MakeMoneyWithAI` (the git repo). Python is `.venv/bin/python`, pytest is `.venv/bin/pytest`.
- OpenAI model comes from `OPENAI_MODEL` env, empty-counts-as-unset, default `gpt-5-mini` (matches `fetch_projects.py`).
- Full playbook bodies must NEVER be committed to git (public repo). `playbooks/` is gitignored; only `site/src/data/previews.json` is committed.
- KV slug/key format: `{owner}__{name}` exactly as spelled in `repos.csv` (case preserved).
- Env vars used: `OPENAI_API_KEY`, `OPENAI_MODEL`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CF_KV_NAMESPACE_ID`. All secrets live in the gitignored `.env`, never in code.
- If the KV key listing fails, abort generation (never regenerate blindly).
- One OpenAI retry per playbook on schema failure; a repo that fails twice is skipped and logged, never fails the run.
- Commit messages: short imperative subject, matching existing repo history.

---

### Task 1: Schema validation + test scaffolding

**Files:**
- Create: `generate_playbooks.py`
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_validate.py`
- Create: `requirements.txt`, `requirements-dev.txt`
- Modify: `.gitignore` (append `playbooks/`)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `validate_playbook(obj: dict) -> list[str]` (empty list = valid), `PlaybookError(Exception)`, module constants `DIFFICULTIES`, `CSV_FILE`, `PLAYBOOKS_DIR`, `PREVIEWS_FILE`

- [ ] **Step 1: Scaffolding**

```bash
printf 'requests\n' > requirements.txt
printf 'pytest\n' > requirements-dev.txt
.venv/bin/pip install -q pytest
mkdir -p tests && touch tests/__init__.py
printf 'playbooks/\n' >> .gitignore
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_validate.py`:

```python
import copy
from generate_playbooks import validate_playbook

VALID = {
    "slug": "acme__widget",
    "generated_at": "2026-07-21T00:00:00+00:00",
    "model": "gpt-4.1-mini",
    "summary": "A widget that does things profitably.",
    "who_its_for": "Developers who want widget income.",
    "business_models": [
        {
            "name": "Hosted SaaS",
            "description": "Run it for customers.",
            "difficulty": "medium",
            "startup_cost": "$20-100/mo",
            "revenue_potential": "side-income",
        }
    ],
    "getting_started_steps": ["Clone it", "Deploy it", "Sell it"],
    "cost_estimate": "About $25/mo to run.",
    "risks": ["Competition", "API pricing changes"],
}


def test_valid_playbook_passes():
    assert validate_playbook(VALID) == []


def test_missing_required_field():
    bad = copy.deepcopy(VALID)
    del bad["summary"]
    assert any("summary" in e for e in validate_playbook(bad))


def test_bad_difficulty():
    bad = copy.deepcopy(VALID)
    bad["business_models"][0]["difficulty"] = "impossible"
    assert any("difficulty" in e for e in validate_playbook(bad))


def test_steps_count_bounds():
    bad = copy.deepcopy(VALID)
    bad["getting_started_steps"] = ["only one"]
    assert any("getting_started_steps" in e for e in validate_playbook(bad))


def test_risks_count_bounds():
    bad = copy.deepcopy(VALID)
    bad["risks"] = ["r"] * 6
    assert any("risks" in e for e in validate_playbook(bad))


def test_business_models_bounds():
    bad = copy.deepcopy(VALID)
    bad["business_models"] = []
    assert any("business_models" in e for e in validate_playbook(bad))


def test_non_dict_input():
    assert validate_playbook("nope") != []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_validate.py -q`
Expected: FAIL / errors with `ModuleNotFoundError: No module named 'generate_playbooks'`

- [ ] **Step 4: Write minimal implementation**

Create `generate_playbooks.py`:

```python
"""Generate money-making playbooks for repos in repos.csv.

Full bodies go to Cloudflare KV (never committed - public repo);
public previews go to site/src/data/previews.json (committed).
"""
import os

import requests  # used by later tasks

CSV_FILE = "repos.csv"
PLAYBOOKS_DIR = "playbooks"
PREVIEWS_FILE = "site/src/data/previews.json"
DIFFICULTIES = {"low", "medium", "high"}

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-5-mini"
CF_API = "https://api.cloudflare.com/client/v4"


class PlaybookError(Exception):
    """A playbook could not be generated or validated."""


_STRING_FIELDS = ["slug", "generated_at", "model", "summary", "who_its_for", "cost_estimate"]
_BM_FIELDS = ["name", "description", "difficulty", "startup_cost", "revenue_potential"]


def validate_playbook(obj):
    """Return a list of problems; empty list means the playbook is valid."""
    if not isinstance(obj, dict):
        return ["playbook is not an object"]
    errors = []
    for field in _STRING_FIELDS:
        if not isinstance(obj.get(field), str) or not obj.get(field).strip():
            errors.append(f"{field}: missing or not a non-empty string")

    bms = obj.get("business_models")
    if not isinstance(bms, list) or not 1 <= len(bms) <= 5:
        errors.append("business_models: must be a list of 1-5 items")
    else:
        for i, bm in enumerate(bms):
            if not isinstance(bm, dict):
                errors.append(f"business_models[{i}]: not an object")
                continue
            for field in _BM_FIELDS:
                if not isinstance(bm.get(field), str) or not bm.get(field).strip():
                    errors.append(f"business_models[{i}].{field}: missing or empty")
            if bm.get("difficulty") not in DIFFICULTIES:
                errors.append(f"business_models[{i}].difficulty: must be one of {sorted(DIFFICULTIES)}")

    steps = obj.get("getting_started_steps")
    if not isinstance(steps, list) or not 3 <= len(steps) <= 7 or not all(
        isinstance(s, str) and s.strip() for s in steps
    ):
        errors.append("getting_started_steps: must be a list of 3-7 non-empty strings")

    risks = obj.get("risks")
    if not isinstance(risks, list) or not 2 <= len(risks) <= 5 or not all(
        isinstance(r, str) and r.strip() for r in risks
    ):
        errors.append("risks: must be a list of 2-5 non-empty strings")

    return errors
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_validate.py -q`
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add generate_playbooks.py tests/ requirements.txt requirements-dev.txt .gitignore
git commit -m "Add playbook schema validation and test scaffolding"
```

---

### Task 2: Prompt, OpenAI call, and retry logic

**Files:**
- Modify: `generate_playbooks.py` (append functions)
- Create: `tests/conftest.py`
- Create: `tests/test_generate.py`

**Interfaces:**
- Consumes: `validate_playbook`, `PlaybookError`, `OPENAI_API_URL`, `OPENAI_MODEL` (Task 1)
- Produces: `slug_for(owner: str, name: str) -> str`; `build_prompt(repo: dict) -> str` (repo keys: `owner`, `name`, `stars`, `url`, `business_model`); `call_openai(prompt: str) -> dict` (parsed JSON); `generate_playbook(repo: dict) -> dict` (validated playbook with `slug`, `generated_at`, `model` stamped; raises `PlaybookError` after 2 failed attempts)

- [ ] **Step 1: Write the shared fake-response fixture**

Create `tests/conftest.py`:

```python
import json


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def openai_chat_payload(content_obj):
    """Wrap an object the way the Chat Completions API returns it."""
    return {"choices": [{"message": {"content": json.dumps(content_obj)}}]}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_generate.py`:

```python
import copy

import pytest

import generate_playbooks as gp
from tests.conftest import FakeResponse, openai_chat_payload
from tests.test_validate import VALID

REPO = {
    "owner": "acme",
    "name": "widget",
    "stars": "12345",
    "url": "https://github.com/acme/widget",
    "business_model": "Sell **widgets** as a service.",
}


def llm_body():
    body = copy.deepcopy(VALID)
    for k in ("slug", "generated_at", "model"):
        body.pop(k, None)  # the LLM does not produce these; we stamp them
    return body


def test_slug_for():
    assert gp.slug_for("acme", "widget") == "acme__widget"


def test_build_prompt_mentions_repo():
    prompt = gp.build_prompt(REPO)
    assert "acme/widget" in prompt and "12345" in prompt


def test_generate_playbook_success(monkeypatch):
    monkeypatch.setattr(
        gp.requests, "post",
        lambda *a, **kw: FakeResponse(200, openai_chat_payload(llm_body())),
    )
    pb = gp.generate_playbook(REPO)
    assert pb["slug"] == "acme__widget"
    assert pb["model"] == gp.OPENAI_MODEL
    assert gp.validate_playbook(pb) == []


def test_generate_playbook_retries_once_then_succeeds(monkeypatch):
    calls = []

    def fake_post(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(200, openai_chat_payload({"garbage": True}))
        return FakeResponse(200, openai_chat_payload(llm_body()))

    monkeypatch.setattr(gp.requests, "post", fake_post)
    pb = gp.generate_playbook(REPO)
    assert len(calls) == 2 and pb["slug"] == "acme__widget"


def test_generate_playbook_fails_after_two_attempts(monkeypatch):
    monkeypatch.setattr(
        gp.requests, "post",
        lambda *a, **kw: FakeResponse(200, openai_chat_payload({"garbage": True})),
    )
    with pytest.raises(gp.PlaybookError):
        gp.generate_playbook(REPO)


def test_generate_playbook_http_error(monkeypatch):
    monkeypatch.setattr(
        gp.requests, "post",
        lambda *a, **kw: FakeResponse(500, {"error": "boom"}),
    )
    with pytest.raises(gp.PlaybookError):
        gp.generate_playbook(REPO)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_generate.py -q`
Expected: FAIL with `AttributeError: module 'generate_playbooks' has no attribute 'slug_for'`

- [ ] **Step 4: Implement**

Append to `generate_playbooks.py`:

```python
import json
from datetime import datetime, timezone


def slug_for(owner, name):
    return f"{owner}__{name}"


def build_prompt(repo):
    return f"""You are an AI business consultant. Write a money-making playbook for this open-source project as a single JSON object.

Project: {repo['owner']}/{repo['name']}
Stars: {repo['stars']}
URL: {repo['url']}
What it does: {repo['business_model']}

Return ONLY a JSON object with exactly these fields:
- "summary": 2-3 sentences - what it is and the monetization thesis.
- "who_its_for": 1-2 sentences.
- "business_models": array of 1-5 objects, each with "name", "description",
  "difficulty" (one of "low", "medium", "high"), "startup_cost" (e.g. "$0-100/mo"),
  "revenue_potential" (e.g. "side-income" or "full-business").
- "getting_started_steps": array of 3-7 concrete steps.
- "cost_estimate": one-sentence running-cost summary.
- "risks": array of 2-5 short risk statements.

No markdown, no commentary - JSON only."""


def call_openai(prompt):
    """One Chat Completions call; returns the parsed JSON content object."""
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    response = requests.post(OPENAI_API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise PlaybookError(f"OpenAI API error {response.status_code}: {response.text[:200]}")
    content = response.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise PlaybookError(f"OpenAI returned non-JSON content: {e}")


def generate_playbook(repo):
    """Generate + validate a playbook for one repo. One retry, then PlaybookError."""
    prompt = build_prompt(repo)
    last_errors = None
    for _attempt in range(2):
        try:
            body = call_openai(prompt)
        except PlaybookError as e:
            last_errors = [str(e)]
            continue
        body["slug"] = slug_for(repo["owner"], repo["name"])
        body["generated_at"] = datetime.now(timezone.utc).isoformat()
        body["model"] = OPENAI_MODEL
        errors = validate_playbook(body)
        if not errors:
            return body
        last_errors = errors
    raise PlaybookError(f"{slug_for(repo['owner'], repo['name'])}: {last_errors}")
```

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: `12 passed`

- [ ] **Step 6: Commit**

```bash
git add generate_playbooks.py tests/conftest.py tests/test_generate.py
git commit -m "Add playbook prompt, OpenAI call, and one-retry generation"
```

---

### Task 3: Cloudflare KV client

**Files:**
- Modify: `generate_playbooks.py` (append functions)
- Create: `tests/test_kv.py`

**Interfaces:**
- Consumes: `CF_API` constant (Task 1)
- Produces: `kv_list_keys() -> set[str]` (raises `PlaybookError` on any failure — caller must abort); `kv_bulk_put(items: list[dict]) -> None` where each item is `{"key": str, "value": str}` (raises `PlaybookError` on failure)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kv.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kv.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'kv_list_keys'`

- [ ] **Step 3: Implement**

Append to `generate_playbooks.py`:

```python
def _kv_base():
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    namespace = os.getenv("CF_KV_NAMESPACE_ID")
    if not account or not namespace:
        raise PlaybookError("CLOUDFLARE_ACCOUNT_ID / CF_KV_NAMESPACE_ID not set")
    return f"{CF_API}/accounts/{account}/storage/kv/namespaces/{namespace}"


def _kv_headers():
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not token:
        raise PlaybookError("CLOUDFLARE_API_TOKEN not set")
    return {"Authorization": f"Bearer {token}"}


def kv_list_keys():
    """All key names in the namespace. Raises PlaybookError on any failure."""
    keys, cursor = set(), None
    while True:
        params = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        response = requests.get(f"{_kv_base()}/keys", headers=_kv_headers(), params=params)
        if response.status_code != 200 or not response.json().get("success"):
            raise PlaybookError(f"KV key listing failed: {response.status_code} {response.text[:200]}")
        data = response.json()
        keys.update(k["name"] for k in data["result"])
        cursor = (data.get("result_info") or {}).get("cursor") or None
        if not cursor:
            return keys


def kv_bulk_put(items):
    """Write [{'key':..., 'value':...}] pairs. Raises PlaybookError on failure."""
    if not items:
        return
    response = requests.put(f"{_kv_base()}/bulk", headers=_kv_headers(), json=items)
    if response.status_code != 200 or not response.json().get("success"):
        raise PlaybookError(f"KV bulk put failed: {response.status_code} {response.text[:200]}")
```

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: `16 passed`

- [ ] **Step 5: Commit**

```bash
git add generate_playbooks.py tests/test_kv.py
git commit -m "Add Cloudflare KV client (paginated list, bulk put)"
```

---

### Task 4: Preview extraction and previews.json writer

**Files:**
- Modify: `generate_playbooks.py` (append functions)
- Create: `tests/test_previews.py`

**Interfaces:**
- Consumes: `PREVIEWS_FILE` constant (Task 1); playbook shape (Task 2)
- Produces: `extract_preview(playbook: dict) -> dict` with keys `slug`, `summary`, `who_its_for`, `first_business_model` (one business-model object); `update_previews(new_previews: list[dict], path: str = PREVIEWS_FILE) -> None` (merge by slug into existing file, sorted by slug, create parent dirs)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_previews.py`:

```python
import json

import generate_playbooks as gp
from tests.test_validate import VALID


def test_extract_preview_shape():
    preview = gp.extract_preview(VALID)
    assert preview == {
        "slug": "acme__widget",
        "summary": VALID["summary"],
        "who_its_for": VALID["who_its_for"],
        "first_business_model": VALID["business_models"][0],
    }


def test_update_previews_creates_and_merges(tmp_path):
    path = str(tmp_path / "data" / "previews.json")
    gp.update_previews([{"slug": "b__two", "summary": "s", "who_its_for": "w",
                         "first_business_model": {}}], path=path)
    gp.update_previews([{"slug": "a__one", "summary": "s", "who_its_for": "w",
                         "first_business_model": {}},
                        {"slug": "b__two", "summary": "UPDATED", "who_its_for": "w",
                         "first_business_model": {}}], path=path)
    data = json.loads(open(path).read())
    assert [p["slug"] for p in data] == ["a__one", "b__two"]
    assert data[1]["summary"] == "UPDATED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_previews.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'extract_preview'`

- [ ] **Step 3: Implement**

Append to `generate_playbooks.py`:

```python
def extract_preview(playbook):
    return {
        "slug": playbook["slug"],
        "summary": playbook["summary"],
        "who_its_for": playbook["who_its_for"],
        "first_business_model": playbook["business_models"][0],
    }


def update_previews(new_previews, path=PREVIEWS_FILE):
    """Merge previews into the committed previews file, keyed by slug."""
    existing = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            existing = {p["slug"]: p for p in json.load(fh)}
    for preview in new_previews:
        existing[preview["slug"]] = preview
    merged = [existing[slug] for slug in sorted(existing)]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=1)
```

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: `18 passed`

- [ ] **Step 5: Commit**

```bash
git add generate_playbooks.py tests/test_previews.py
git commit -m "Add preview extraction and previews.json merge writer"
```

---

### Task 5: main() orchestration and CLI

**Files:**
- Modify: `generate_playbooks.py` (append `main` + `__main__` block)
- Create: `tests/test_main.py`

**Interfaces:**
- Consumes: everything from Tasks 1-4
- Produces: `main(argv: list[str] | None = None) -> int` (0 on success, 1 if KV listing aborted). CLI: `--max N` limits new generations; `--force owner/name` regenerates one repo even if it exists in KV. Plan C's workflow calls `python generate_playbooks.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main.py`:

```python
import copy
import csv
import json

import pytest

import generate_playbooks as gp
from tests.test_generate import llm_body

ROWS = [
    {"id": "1", "owner": "acme", "name": "widget", "stars": "100",
     "url": "https://github.com/acme/widget", "business_model": "b"},
    {"id": "2", "owner": "beta", "name": "gadget", "stars": "200",
     "url": "https://github.com/beta/gadget", "business_model": "b"},
]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    csv_path = tmp_path / "repos.csv"
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ROWS[0]))
        writer.writeheader()
        writer.writerows(ROWS)
    monkeypatch.setattr(gp, "CSV_FILE", str(csv_path))
    monkeypatch.setattr(gp, "PLAYBOOKS_DIR", str(tmp_path / "playbooks"))
    monkeypatch.setattr(gp, "PREVIEWS_FILE", str(tmp_path / "previews.json"))
    return tmp_path


def test_main_generates_only_missing(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: {"acme__widget"})
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))
    monkeypatch.setattr(gp, "generate_playbook",
                        lambda repo: dict(llm_body(), slug=gp.slug_for(repo["owner"], repo["name"]),
                                          generated_at="t", model="m"))
    assert gp.main([]) == 0
    assert [p["key"] for p in puts] == ["beta__gadget"]
    previews = json.load(open(sandbox / "previews.json"))
    assert [p["slug"] for p in previews] == ["beta__gadget"]
    assert (sandbox / "playbooks" / "beta__gadget.json").exists()


def test_main_aborts_when_kv_listing_fails(sandbox, monkeypatch):
    def boom():
        raise gp.PlaybookError("kv down")
    monkeypatch.setattr(gp, "kv_list_keys", boom)
    assert gp.main([]) == 1


def test_main_force_regenerates(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: {"acme__widget", "beta__gadget"})
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))
    monkeypatch.setattr(gp, "generate_playbook",
                        lambda repo: dict(llm_body(), slug=gp.slug_for(repo["owner"], repo["name"]),
                                          generated_at="t", model="m"))
    assert gp.main(["--force", "acme/widget"]) == 0
    assert [p["key"] for p in puts] == ["acme__widget"]


def test_main_skips_failed_repo_and_continues(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: set())
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))

    def flaky(repo):
        if repo["owner"] == "acme":
            raise gp.PlaybookError("nope")
        return dict(llm_body(), slug=gp.slug_for(repo["owner"], repo["name"]),
                    generated_at="t", model="m")

    monkeypatch.setattr(gp, "generate_playbook", flaky)
    assert gp.main([]) == 0
    assert [p["key"] for p in puts] == ["beta__gadget"]


def test_main_respects_max(sandbox, monkeypatch):
    monkeypatch.setattr(gp, "kv_list_keys", lambda: set())
    puts = []
    monkeypatch.setattr(gp, "kv_bulk_put", lambda items: puts.extend(items))
    monkeypatch.setattr(gp, "generate_playbook",
                        lambda repo: dict(llm_body(), slug=gp.slug_for(repo["owner"], repo["name"]),
                                          generated_at="t", model="m"))
    assert gp.main(["--max", "1"]) == 0
    assert len(puts) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_main.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'main'`

- [ ] **Step 3: Implement**

Append to `generate_playbooks.py`:

```python
import argparse
import csv


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate playbooks into KV + previews.json")
    parser.add_argument("--max", type=int, default=None, help="limit number of new playbooks")
    parser.add_argument("--force", action="append", default=[],
                        help="owner/name to regenerate even if present in KV (repeatable)")
    args = parser.parse_args(argv)
    forced = {f.replace("/", "__") for f in args.force}

    with open(CSV_FILE, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    try:
        existing = kv_list_keys()
    except PlaybookError as e:
        print(f"ABORT: {e}")
        return 1

    todo = [r for r in rows
            if slug_for(r["owner"], r["name"]) not in existing
            or slug_for(r["owner"], r["name"]) in forced]
    if args.max is not None:
        todo = todo[: args.max]
    print(f"{len(rows)} repos, {len(existing)} in KV, {len(todo)} to generate")

    os.makedirs(PLAYBOOKS_DIR, exist_ok=True)
    items, previews, failed = [], [], 0
    for repo in todo:
        slug = slug_for(repo["owner"], repo["name"])
        try:
            playbook = generate_playbook(repo)
        except PlaybookError as e:
            print(f"  SKIP {slug}: {e}")
            failed += 1
            continue
        body = json.dumps(playbook, ensure_ascii=False)
        with open(os.path.join(PLAYBOOKS_DIR, f"{slug}.json"), "w", encoding="utf-8") as fh:
            fh.write(body)
        items.append({"key": slug, "value": body})
        previews.append(extract_preview(playbook))
        print(f"  OK   {slug}")

    kv_bulk_put(items)
    update_previews(previews)
    print(f"Done: {len(items)} written to KV, {failed} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: `23 passed`

- [ ] **Step 5: Commit**

```bash
git add generate_playbooks.py tests/test_main.py
git commit -m "Add generate_playbooks orchestration with --max and --force"
```

---

### Task 6: Cloudflare setup + live smoke run (2 repos)

**Blocked on user-supplied credentials.** Requires a Cloudflare account. If `CLOUDFLARE_API_TOKEN` is not available, stop here and report — Tasks 1-5 are complete and fully tested without it.

**Files:**
- Modify: `.env` (append three vars — NEVER committed; verify with `git check-ignore .env`)
- Modify: `CLAUDE.md` (document the new pipeline stage commands)
- Commit: `site/src/data/previews.json` (first two real previews)

**Interfaces:**
- Consumes: `main()` (Task 5)
- Produces: a live KV namespace named `PLAYBOOKS` whose ID is in `.env` as `CF_KV_NAMESPACE_ID`; Plan B binds this same namespace to Pages Functions; Plan C reuses these env names as CI secrets.

- [ ] **Step 1: Create the KV namespace** (user provides `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` in `.env` first)

```bash
set -a && source .env && set +a
curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/storage/kv/namespaces" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"title":"PLAYBOOKS"}'
```

Expected: JSON with `"success": true` and a `result.id` — append `CF_KV_NAMESPACE_ID=<result.id>` to `.env`.

- [ ] **Step 2: Live run limited to 2 repos**

```bash
set -a && source .env && set +a
.venv/bin/python generate_playbooks.py --max 2
```

Expected output shape: `411 repos, 0 in KV, 2 to generate`, two `OK` lines, `Done: 2 written to KV, 0 skipped`.

- [ ] **Step 3: Verify KV and previews**

```bash
set -a && source .env && set +a
curl -s "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/storage/kv/namespaces/$CF_KV_NAMESPACE_ID/keys" \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" | .venv/bin/python -m json.tool | head -20
.venv/bin/python -c "import json; d=json.load(open('site/src/data/previews.json')); print(len(d), [p['slug'] for p in d])"
git check-ignore playbooks/ .env && echo "gitignore OK"
```

Expected: two key names; `2 ['<slug>', '<slug>']`; `gitignore OK`.

- [ ] **Step 4: Document in CLAUDE.md**

Append to the Commands section of `CLAUDE.md`:

```markdown
python generate_playbooks.py --max 2   # generate playbooks for repos missing from KV (test run)
python generate_playbooks.py           # full run; --force owner/name regenerates one
.venv/bin/pytest -q                    # pipeline unit tests
```

- [ ] **Step 5: Commit**

```bash
git add site/src/data/previews.json CLAUDE.md
git commit -m "Add first live playbook previews and pipeline docs"
```

---

## Plan Self-Review (completed)

- **Spec coverage:** schema fields (Task 1), generation + retry + skip policy (Tasks 2, 5), KV as source of truth + abort-on-list-failure (Tasks 3, 5), gitignored `playbooks/` + committed previews (Tasks 1, 4, 6), `--force` (Task 5), cost-bounded test run (Task 6). Site, paywall, Threads, CI are Plans B/C by design.
- **Placeholders:** none — every step has complete code or exact commands.
- **Type consistency:** `slug_for`, `generate_playbook`, `kv_list_keys`, `kv_bulk_put`, `extract_preview`, `update_previews`, `main` signatures match across tasks and tests.
