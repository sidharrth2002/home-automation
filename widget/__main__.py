"""Feed and installer for the iPhone home-screen widget (a Scriptable script, see widget/home.js).

  python -m widget --watch    the service (run by ./home up): every 20s write the feed the widget reads
  python -m widget url        print the feed URLs
  python -m widget install    write the ready-to-paste widget script to data/widget/Home.js (--copy: also to the clipboard)

The feed is deliberately boring: whether each light is on and its colour, what's playing, the TV, home/away and
the weather. No finances, no calendar. It's a JSON file under Home Assistant's /local/ folder, whose name is a
random secret, so the phone needs no Home Assistant token and nothing else on the network can guess it. Anyone
who has the URL can read those few facts, so treat it like a password and don't commit it (it lives in data/,
which is git-ignored).
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "widget"
KEY_FILE = DATA / "key"
OUT_DIR = ROOT / "homeassistant" / "config" / "www" / "widget"
TEMPLATE = Path(__file__).resolve().parent / "home.js"
INSTALLED = DATA / "Home.js"
HA_HTTP = os.environ.get("HA_HTTP", "http://localhost:8123")
EVERY_S = 20

# What the widget may know about. Adding an entity here is how it ends up on a lock screen, so keep it short.
LIGHTS = (("light.wiz_rgbw_tunable_624d4e", "TV 1"), ("light.desk_lamp", "Desk"), ("light.wiz_rgbw_tunable_4b472c", "TV 2"))
SYNC, MODE, NOW = "input_boolean.music_sync", "input_select.music_sync_mode", "sensor.music_sync_now_playing"
TV, HOME, WEATHER, HEALTH = "media_player.smart_tv_pro", "binary_sensor.someone_home", "weather.forecast_home", "sensor.system_health"


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def key() -> str:
    """The feed's secret name, created on first use."""
    if not KEY_FILE.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(secrets.token_urlsafe(24))
        KEY_FILE.chmod(0o600)
    return KEY_FILE.read_text().strip()


def build(states: list[dict]) -> dict:
    """The feed from Home Assistant's states. Only the entities listed above are ever read."""
    by_id = {s["entity_id"]: s for s in states}

    def get(eid):
        s = by_id.get(eid)
        return (s["state"], s.get("attributes", {})) if s else (None, {})

    lights = []
    for eid, name in LIGHTS:
        state, a = get(eid)
        on = state == "on"
        lights.append({"name": name, "on": on, "reachable": state not in (None, "unavailable"),
                       "pct": round((a.get("brightness") or 0) / 255 * 100) if on else 0,
                       "rgb": a.get("rgb_color") if on else None})
    now_state, now = get(NOW)
    title, _, artist = (now_state or "").partition(" — ")
    tv_state, tv = get(TV)
    w_state, w = get(WEATHER)
    return {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "lights": lights,
        "sync": {"on": get(SYNC)[0] == "on", "mode": get(MODE)[0]},
        "music": {"title": title if now_state and title != "Nothing playing" else None, "artist": artist or None,
                  "playing": now.get("player_state") == "playing", "art": now.get("entity_picture"),
                  "palette": now.get("palette") or []},
        "tv": {"state": tv_state, "app": tv.get("app_id")},
        "home": {"on": True, "off": False}.get(get(HOME)[0]),
        "weather": {"state": w_state, "temp": w.get("temperature")} if w_state else None,
        "health": get(HEALTH)[0],
    }


def fetch_states():
    req = urllib.request.Request(f"{HA_HTTP}/api/states", headers={"Authorization": f"Bearer {os.environ['TOKEN']}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def write_feed(feed: dict):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{key()}.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(feed, separators=(",", ":")))
    tmp.replace(target)  # atomic: the phone never reads half a file


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outbound interface
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def feed_urls() -> list[str]:
    """The IP address first, then the Mac's .local name in case the address changes."""
    name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
    hosts = [lan_ip()] + ([f"{name}.local"] if name else [])
    return [f"http://{h}:8123/local/widget/{key()}.json" for h in hosts]


def install(copy=False) -> Path:
    script = TEMPLATE.read_text().replace('"__FEED_URLS__"', json.dumps(feed_urls())) \
        .replace("__HUB_URL__", f"http://{lan_ip()}:8123/local/hub/index.html")
    DATA.mkdir(parents=True, exist_ok=True)
    INSTALLED.write_text(script)
    INSTALLED.chmod(0o600)
    if copy:
        subprocess.run(["pbcopy"], input=script, text=True, check=True)
    return INSTALLED


def watch():
    load_env()
    last_error = None
    while True:
        try:
            write_feed(build(fetch_states()))
            last_error = None
        except Exception as e:  # Home Assistant restarting: the feed just goes a little stale
            if str(e) != last_error:
                print(f"widget feed not updated: {e}", flush=True)
                last_error = str(e)
        time.sleep(EVERY_S)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "url"
    if cmd == "--watch":
        watch()
    elif cmd == "url":
        print("\n".join(feed_urls()))
    elif cmd == "install":
        path = install(copy="--copy" in sys.argv)
        print(f"Wrote {path}" + ("\nCopied to the clipboard; paste it into a new Scriptable script." if "--copy" in sys.argv else ""))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
