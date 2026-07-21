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
