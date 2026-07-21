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
