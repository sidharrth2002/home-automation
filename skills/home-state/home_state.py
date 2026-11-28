#!/usr/bin/env python3
"""Tiny client for the home core API (standard library only).

    home_state.py me | schema
    home_state.py get <path>                       e.g. portfolio, portfolio/hsbc, state/finance/plan, 'audit?entity=portfolio'
    home_state.py put <path> <file.json | ->       replace (a portfolio source: a new snapshot)
    home_state.py patch <path> '<json>'            merge fields
    home_state.py delete <path>
    options: --if-match <version>

Token: $HOME_CORE_TOKEN, else ~/.config/home-core/token. URL: $HOME_CORE_URL, else ~/.config/home-core/url (written
by server/use-server when the core moves to the home server), else http://127.0.0.1:8790.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def token() -> str:
    t = os.environ.get("HOME_CORE_TOKEN")
    if t:
        return t.strip()
    path = Path.home() / ".config" / "home-core" / "token"
    if not path.exists():
        sys.exit(f"no token: put the one from `python -m core token add ...` in {path} (chmod 600)")
    return path.read_text().strip()


def base_url() -> str:
    url_file = Path.home() / ".config" / "home-core" / "url"
    saved = url_file.read_text().strip() if url_file.exists() else ""
    return (os.environ.get("HOME_CORE_URL") or saved or "http://127.0.0.1:8790").rstrip("/")


def call(method: str, path: str, body=None, if_match: str | None = None):
    base = base_url()
    url = f"{base}/{path.lstrip('/')}" if path.startswith("openapi") else f"{base}/v1/{path.lstrip('/')}"
    headers = {"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}
    if if_match:
        headers["If-Match"] = if_match
    req = urllib.request.Request(url, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail", e.reason)
        except ValueError:
            detail = e.reason
        sys.exit(f"{e.code}: {json.dumps(detail) if not isinstance(detail, str) else detail}")
    except urllib.error.URLError as e:
        sys.exit(f"can't reach the core API at {base} ({e.reason}); is the home system running?")


def main(argv):
    if_match = None
    if "--if-match" in argv:
        i = argv.index("--if-match")
        if_match = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    if cmd == "me":
        out = call("GET", "me")
    elif cmd == "schema":
        out = call("GET", "openapi.json")
    elif cmd == "get" and len(args) == 1:
        out = call("GET", args[0])
    elif cmd == "put" and len(args) == 2:
        raw = sys.stdin.read() if args[1] == "-" else Path(args[1]).read_text()
        out = call("PUT", args[0], json.loads(raw), if_match)
    elif cmd == "patch" and len(args) == 2:
        out = call("PATCH", args[0], json.loads(args[1]), if_match)
    elif cmd == "delete" and len(args) == 1:
        out = call("DELETE", args[0], None, if_match)
    else:
        sys.exit(__doc__)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
