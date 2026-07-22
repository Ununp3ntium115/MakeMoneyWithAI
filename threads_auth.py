"""One-time local helper: put a long-lived Threads token into Cloudflare KV.

Outbound-only: the resulting token can publish to the owner's OWN Threads feed
(scopes threads_basic, threads_content_publish). It cannot read, follow, or
message any other account.

Usage:
  1. python threads_auth.py            # prints the authorization URL
  2. Open it, approve, copy the `code` from the redirect URL (strip a trailing #_)
  3. python threads_auth.py <code>     # exchanges the code, stores the token in KV

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
    """Exchange an auth code for a long-lived token + user id."""
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
