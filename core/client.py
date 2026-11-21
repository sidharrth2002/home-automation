"""A small client for the core API, for this repo's services (they use the admin token, CORE_TOKEN in .env)."""
import json
import os
import time
import urllib.error
import urllib.request


class CoreError(OSError):
    """The API refused a call. An OSError, like the connection errors, so `except OSError` covers both."""

    def __init__(self, status, message):
        super().__init__(f"core API {status}: {message}")
        self.status = status


def url() -> str:
    return os.environ.get("CORE_URL") or f"http://127.0.0.1:{os.environ.get('CORE_PORT', '8790')}"


def call(method: str, path: str, body=None, token: str | None = None, if_version: int | None = None, timeout=10):
    headers = {"Authorization": f"Bearer {token or os.environ['CORE_TOKEN']}", "Content-Type": "application/json"}
    if if_version is not None:
        headers["If-Match"] = str(if_version)
    req = urllib.request.Request(url() + path, method=method, headers=headers,
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read()).get("detail", e.reason)
        except ValueError:
            message = e.reason
        raise CoreError(e.code, message) from None


def get(collection: str, doc_id: str) -> dict:
    return call("GET", f"/v1/state/{collection}/{doc_id}")


def put(collection: str, doc_id: str, data) -> dict:
    return call("PUT", f"/v1/state/{collection}/{doc_id}", data)


def patch(collection: str, doc_id: str, fields: dict) -> dict:
    return call("PATCH", f"/v1/state/{collection}/{doc_id}", fields)


def put_source(source: str, doc: dict) -> dict:
    """A portfolio source's full current state (a new snapshot unless it's unchanged)."""
    return call("PUT", f"/v1/portfolio/{source}", doc)


def ready(wait_s: float = 0) -> bool:
    """Is the API up? Waits up to `wait_s` for it (a service starting alongside the core)."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            call("GET", "/v1/health", timeout=3)
            return True
        except Exception:
            if time.monotonic() >= deadline:
                return False
            time.sleep(2)


def report(entity: str, state, attributes: dict, timeout=10) -> bool:
    """A service's entity state, which the core mirrors into Home Assistant. Returns whether it changed."""
    return call("PUT", f"/v1/live/{entity}", {"state": state, "attributes": attributes}, timeout=timeout)["changed"]


def live(entity: str) -> dict | None:
    """An entity's last reported state; None if nothing has reported it."""
    try:
        return call("GET", f"/v1/live/{entity}")
    except CoreError as e:
        if e.status == 404:
            return None
        raise
