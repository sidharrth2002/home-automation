"""Feed and installer for the iPhone home-screen widget (a Scriptable script, see widget/home.js).

  python -m widget --watch    the service (run by ./home up): every 20s write the feed the widget reads
  python -m widget url        print the feed URLs
  python -m widget hooks      print the tap-target (webhook) URLs, e.g. for building Shortcuts buttons
  python -m widget install    write the ready-to-paste widget script to data/widget/Home.js (--copy: also to the clipboard)

Tapping a light on the widget calls a Home Assistant webhook: a secret, LAN-only address (derived from the same
key) that triggers one automation, which does exactly one thing: toggle that lamp (or turn everything off). The
phone never holds a Home Assistant token.

The feed is deliberately boring: whether each light is on and its colour, what's playing, the TV, home/away and
the weather. No finances, no calendar. It's a JSON file under Home Assistant's /local/ folder, whose name is a
random secret, so the phone needs no Home Assistant token and nothing else on the network can guess it. Anyone
who has the URL can read those few facts, so treat it like a password and don't commit it (it lives in data/,
which is git-ignored).
"""
import hashlib
import hmac
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
# What a tap on the widget can do. Each name is a webhook in the `widget_actions` automation (see automation_config).
LIGHT_ACTIONS = {"tv1": LIGHTS[0][0], "desk": LIGHTS[1][0], "tv2": LIGHTS[2][0]}
ACTIONS = (*LIGHT_ACTIONS, "off", "ping")  # "ping" does nothing visible; it tests the path without touching a light
PHONE_ACTIONS = ACTIONS  # the phone uses "ping" for its setup check
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
    action_of = {eid: act for act, eid in LIGHT_ACTIONS.items()}
    for eid, name in LIGHTS:
        state, a = get(eid)
        on = state == "on"
        lights.append({"name": name, "action": action_of[eid], "on": on, "reachable": state not in (None, "unavailable"),
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


def action_id(name: str) -> str:
    """The webhook id for an action: unguessable, and different for each action and each key."""
    return "widget-" + hmac.new(key().encode(), f"action:{name}".encode(), hashlib.sha256).hexdigest()[:32]


def automation_config() -> dict:
    """The one Home Assistant automation behind the widget's tap targets. Built here, not stored in the repo, because the
    webhook ids are secrets (homeassistant.apply pushes it)."""
    branch = lambda name, *sequence: {"conditions": [{"condition": "trigger", "id": name}], "sequence": list(sequence)}
    return {
        "id": "widget_actions", "alias": "Widget actions", "mode": "queued", "max": 10,
        "description": "Tap targets for the iPhone widget: toggle a lamp, or everything off. Webhooks, LAN only.",
        "triggers": [{"trigger": "webhook", "webhook_id": action_id(a), "allowed_methods": ["POST"], "local_only": True, "id": a}
                     for a in ACTIONS],
        "actions": [{"choose": [
            *[branch(a, {"action": "light.toggle", "target": {"entity_id": eid}}) for a, eid in LIGHT_ACTIONS.items()],
            branch("off", {"action": "script.turn_on", "target": {"entity_id": "script.all_off"}}),
            branch("ping", {"event": "widget_ping"}),
        ]}],
    }


def action_bases() -> list[str]:
    name = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True).stdout.strip()
    return [f"http://{h}:8123" for h in [lan_ip()] + ([f"{name}.local"] if name else [])]


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
    actions = {"ids": {a: action_id(a) for a in PHONE_ACTIONS}, "bases": action_bases()}
    script = TEMPLATE.read_text().replace('"__FEED_URLS__"', json.dumps(feed_urls())) \
        .replace('"__ACTIONS__"', json.dumps(actions)) \
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
    elif cmd == "hooks":
        for a in ACTIONS:
            print(f"{a:5} POST {action_bases()[0]}/api/webhook/{action_id(a)}")
    elif cmd == "install":
        path = install(copy="--copy" in sys.argv)
        print(f"Wrote {path}" + ("\nCopied to the clipboard; paste it into a new Scriptable script." if "--copy" in sys.argv else ""))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
