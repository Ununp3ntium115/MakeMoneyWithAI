"""Announce newly-added repos on the product's OWN Threads feed (outbound only).

This module only publishes posts to the account owner's own timeline. It does
NOT read, search, follow, like, or message any other account. The only Threads
endpoints it calls are the owner's own /{user_id}/threads and
/{user_id}/threads_publish. Keep it that way.
"""
import csv
import json
import os
import time

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
    """Two-step publish to the owner's OWN feed: create container, then publish."""
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
