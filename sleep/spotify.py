"""Spotify's Web API, with a sign-in of the sleep service's own.

`python -m sleep login` (once, on the Mac: it opens the browser) authorises the same Spotify developer app Home
Assistant uses (SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in .env) with a redirect to http://127.0.0.1:8798/callback,
and keeps the token in data/secrets/spotify.json (0600, never in the repo; server/move-from-mac copies it). This
service refreshes it itself. Until then it borrows the token Home Assistant's Spotify integration saved, but that
one goes stale whenever the integration's polling fails (Spotify changed its responses under it, 2026-11), so the
own sign-in is the one to rely on. Playback control needs Premium (Spotify's rule); reading playlists doesn't.
"""
import base64
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "homeassistant" / "config" / ".storage" / "core.config_entries"
OWN = ROOT / "data" / "secrets" / "spotify.json"
API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
REDIRECT = "http://127.0.0.1:8798/callback"
SCOPES = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative"


class SpotifyError(OSError):
    def __init__(self, status, message):
        super().__init__(f"Spotify {status}: {message}")
        self.status = status


def _client() -> tuple[str, str]:
    cid, secret = os.environ.get("SPOTIFY_CLIENT_ID", ""), os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if not cid or not secret:
        raise SpotifyError(401, "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET aren't in .env")
    return cid, secret


def _accounts(form: dict) -> dict:
    """POST to Spotify's token endpoint with the app's own credentials."""
    cid, secret = _client()
    req = urllib.request.Request(ACCOUNTS + "/api/token", method="POST", data=urllib.parse.urlencode(form).encode(),
                                 headers={"Authorization": "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode(),
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SpotifyError(e.code, e.read()[:200].decode(errors="replace")) from None


def _save(tok: dict):
    OWN.parent.mkdir(parents=True, exist_ok=True)
    OWN.parent.chmod(0o700)
    tmp = OWN.with_suffix(".tmp")
    tmp.touch(mode=0o600)
    tmp.chmod(0o600)
    tmp.write_text(json.dumps(tok))
    tmp.replace(OWN)


def _own_token() -> str | None:
    """This service's own token, refreshed when it's within a minute of expiring. None without a sign-in."""
    try:
        tok = json.loads(OWN.read_text())
    except (OSError, ValueError):
        return None
    if tok.get("expires_at", 0) < time.time() + 60:
        new = _accounts({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        tok = {"access_token": new["access_token"], "expires_at": time.time() + new.get("expires_in", 3600),
               # Spotify sometimes sends a new refresh token; otherwise the old one stays good
               "refresh_token": new.get("refresh_token") or tok["refresh_token"]}
        _save(tok)
    return tok["access_token"]


def _borrowed_token() -> str | None:
    """Home Assistant's Spotify token, while it's fresh (its integration refreshes it as it polls)."""
    try:
        entries = json.loads(ENTRIES.read_text())["data"]["entries"]
    except (OSError, ValueError, KeyError):
        return None
    entry = next((e for e in entries if e.get("domain") == "spotify"), None)
    tok = (entry or {}).get("data", {}).get("token", {})
    if not tok.get("access_token") or tok.get("expires_at", 0) < time.time() + 30:
        return None
    return tok["access_token"]


def token() -> str | None:
    """The token to use: our own sign-in, else Home Assistant's while it's fresh."""
    return _own_token() or _borrowed_token()


def login():
    """Sign in once in the browser (on the Mac). The redirect lands on a tiny local server, which hands back the
    code; the token is saved to data/secrets/spotify.json."""
    import http.server
    import webbrowser
    _client()
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = q.get("state", [""])[0] == state and "code" in q
            if ok:
                got["code"] = q["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<p style='font:16px system-ui;margin:3em'>"
                              + ("Signed in. You can close this tab." if ok else "That didn't work: try again.")
                              + "</p>").encode())

    server = http.server.HTTPServer(("127.0.0.1", 8798), Callback)
    url = ACCOUNTS + "/authorize?" + urllib.parse.urlencode({
        "client_id": _client()[0], "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES, "state": state})
    print("Opening Spotify in the browser; approve, and come back here.")
    webbrowser.open(url)
    deadline = time.time() + 300
    while "code" not in got and time.time() < deadline:
        server.timeout = 5
        server.handle_request()
    server.server_close()
    if "code" not in got:
        raise SystemExit("no sign-in within 5 minutes; run it again")
    t = _accounts({"grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT})
    _save({"access_token": t["access_token"], "refresh_token": t["refresh_token"],
           "expires_at": time.time() + t.get("expires_in", 3600)})
    me = call("GET", "/me")
    print(f"Signed in ({me.get('product')} account). The sleep service uses this sign-in from now on.")


def call(method: str, path: str, body=None, query: dict | None = None):
    tok = token()
    if not tok:
        raise SpotifyError(401, "no fresh token from Home Assistant's Spotify integration")
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {tok}",
                                                               "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {}).get("message", e.reason)
        except ValueError:
            msg = e.reason
        raise SpotifyError(e.code, msg) from None


def cover(images: list) -> str | None:
    """The smallest picture that's still sharp on the TV (Spotify lists them largest first)."""
    sized = [i for i in images or [] if i.get("url")]
    good = [i for i in sized if (i.get("width") or 640) >= 200]
    pick = (good or sized)[-1:] if (good or sized) else []
    return pick[0]["url"] if pick else None


def playlists() -> list[dict]:
    """The user's playlists in their own order: name, URI and a cover."""
    out, offset = [], 0
    while True:
        page = call("GET", "/me/playlists", query={"limit": 50, "offset": offset}) or {}
        for p in page.get("items") or []:
            if p and p.get("uri"):
                out.append({"name": p.get("name") or "Untitled", "uri": p["uri"], "image": cover(p.get("images"))})
        offset += 50
        if not page.get("next") or offset >= 500:
            return out


def tv_device() -> dict | None:
    """The TV as a Spotify Connect device: SPOTIFY_TV_DEVICE by name if set, else the one of type TV."""
    devices = (call("GET", "/me/player/devices") or {}).get("devices", [])
    want = os.environ.get("SPOTIFY_TV_DEVICE")
    return next((d for d in devices if (d.get("name") == want if want else d.get("type") == "TV")), None)


def play(device_id: str, uri: str):
    call("PUT", "/me/player/play", {"context_uri": uri}, {"device_id": device_id})


def pause(device_id: str):
    call("PUT", "/me/player/pause", query={"device_id": device_id})


def volume(device_id: str, percent: int):
    call("PUT", "/me/player/volume", query={"volume_percent": max(0, min(100, int(percent))), "device_id": device_id})
