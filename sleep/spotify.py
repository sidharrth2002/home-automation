"""Spotify's Web API with the sign-in Home Assistant's Spotify integration already holds.

Home Assistant keeps that token fresh (it refreshes it while it polls), so this only ever reads it from
homeassistant/config/.storage/core.config_entries and never refreshes it itself: two parties refreshing one token
would fight. Playback control needs Premium (Spotify's rule); reading playlists doesn't.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRIES = ROOT / "homeassistant" / "config" / ".storage" / "core.config_entries"
API = "https://api.spotify.com/v1"


class SpotifyError(OSError):
    def __init__(self, status, message):
        super().__init__(f"Spotify {status}: {message}")
        self.status = status


def token() -> str | None:
    """The current access token, or None while there isn't a fresh one (Home Assistant is down or mid-refresh)."""
    try:
        entries = json.loads(ENTRIES.read_text())["data"]["entries"]
    except (OSError, ValueError, KeyError):
        return None
    entry = next((e for e in entries if e.get("domain") == "spotify"), None)
    tok = (entry or {}).get("data", {}).get("token", {})
    if not tok.get("access_token") or tok.get("expires_at", 0) < time.time() + 30:
        return None
    return tok["access_token"]


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
