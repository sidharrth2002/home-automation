"""The media setup: torrents (qBittorrent) into a library (Jellyfin) that streams to the TV.

  .venv/bin/python -m media setup     once the containers are up (COMPOSE_PROFILES=...,media; ./home up). Safe to
                                      run again: it only fills in what isn't there yet.

What it does:
- the library folders in MEDIA_DIR (default data/media): Movies, Shows, downloads, and .incomplete for files still
  downloading (so Jellyfin never sees half a film)
- qBittorrent: its own password instead of the temporary one it prints at each start; categories "movies" and
  "shows" that move a finished download into Movies or Shows (anything else stays in downloads/); stop seeding at a
  ratio of 1 or after a day; UPnP off (it opens nothing on the router)
- Jellyfin: through its first-run wizard (a user, British metadata, no access from outside the home), and the
  libraries Movies, Shows and Downloads

Passwords are made up here and kept in data/secrets/qbittorrent.json and jellyfin.json (0600). On the TV, sign in to
the Jellyfin app with Quick Connect: it shows a code to approve at http://<this machine>:8096 → your user → Quick
Connect, so the password never has to be typed with the remote.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

from music_sync.service import load_env

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "data" / "secrets"
QBT = "http://127.0.0.1:8090"
JELLYFIN = "http://127.0.0.1:8096"
FOLDERS = ["Movies", "Shows", "downloads", ".incomplete"]
CATEGORIES = {"movies": "/media/Movies", "shows": "/media/Shows"}
LIBRARIES = [("Movies", "movies", "/media/Movies"), ("Shows", "tvshows", "/media/Shows"),
             ("Downloads", "homevideos", "/media/downloads")]
JF_AUTH = 'MediaBrowser Client="home-automation", Device="setup", DeviceId="home-media-setup", Version="1"'


def media_dir() -> Path:
    d = Path(os.environ.get("MEDIA_DIR") or ROOT / "data" / "media").expanduser()
    return d if d.is_absolute() else ROOT / d


def secret(name: str) -> dict | None:
    f = SECRETS / f"{name}.json"
    return json.loads(f.read_text()) if f.exists() else None


def keep(name: str, data: dict):
    SECRETS.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS, 0o700)
    f = SECRETS / f"{name}.json"
    f.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(f, 0o600)


def wait_for(url: str, what: str, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=5):
                return
        except urllib.error.HTTPError:
            return  # it answers, even if not with 200
        except OSError:
            time.sleep(2)
    sys.exit(f"{what} isn't answering at {url}: is COMPOSE_PROFILES set to include media, and ./home up run?")


# ── qBittorrent ──
class Qbt:
    def __init__(self):
        self.http = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def post(self, path: str, form: dict) -> str:
        req = urllib.request.Request(QBT + path, urllib.parse.urlencode(form).encode(), headers={"Referer": QBT, "Origin": QBT})
        with self.http.open(req, timeout=15) as r:
            return r.read().decode()

    def login(self, user: str, password: str) -> bool:
        try:
            return self.post("/api/v2/auth/login", {"username": user, "password": password}).strip() == "Ok."
        except urllib.error.HTTPError:
            return False


def temporary_password() -> str | None:
    """The one qBittorrent prints in its log at each start, until a password is set."""
    logs = subprocess.run(["docker", "logs", "qbittorrent"], capture_output=True, text=True).stdout
    found = re.findall(r"temporary password is provided for this session: (\S+)", logs)
    return found[-1] if found else None


def setup_qbittorrent():
    wait_for(QBT, "qBittorrent")
    qbt, saved = Qbt(), secret("qbittorrent")
    if saved and qbt.login(saved["user"], saved["password"]):
        print("qBittorrent: signed in with the saved password")
    else:
        temp = temporary_password()
        if not temp or not qbt.login("admin", temp):
            sys.exit("qBittorrent: couldn't sign in (no saved password works, and no temporary one in its log). "
                     "Restart it (docker restart qbittorrent) and run this again.")
        saved = {"user": "admin", "password": secrets.token_urlsafe(14)}
        qbt.post("/api/v2/app/setPreferences", {"json": json.dumps({"web_ui_password": saved["password"]})})
        keep("qbittorrent", saved)
        print("qBittorrent: password set (data/secrets/qbittorrent.json)")
    qbt.post("/api/v2/app/setPreferences", {"json": json.dumps({
        "save_path": "/media/downloads", "temp_path_enabled": True, "temp_path": "/media/.incomplete",
        "auto_tmm_enabled": True,  # a category's folder decides where a download ends up
        "max_ratio_enabled": True, "max_ratio": 1.0, "max_seeding_time_enabled": True, "max_seeding_time": 1440,
        "max_ratio_act": 0,  # then stop the torrent (the files stay)
        "upnp": False, "listen_port": 6881, "random_port": False,
    })})
    have = json.loads(qbt.post("/api/v2/torrents/categories", {}) or "{}")
    for name, path in CATEGORIES.items():
        if have.get(name, {}).get("savePath") == path:
            continue  # already right (editing it to the same path is a 409)
        qbt.post("/api/v2/torrents/editCategory" if name in have else "/api/v2/torrents/createCategory",
                 {"category": name, "savePath": path})
    print("qBittorrent: folders, categories (movies, shows) and seeding limits set")


# ── Jellyfin ──
def jf(method: str, path: str, body=None, token: str | None = None):
    auth = JF_AUTH + (f', Token="{token}"' if token else "")
    req = urllib.request.Request(JELLYFIN + path, method=method, headers={"Authorization": auth, "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def setup_jellyfin():
    wait_for(JELLYFIN + "/System/Info/Public", "Jellyfin")
    info = None
    for _ in range(30):  # it answers before the wizard is ready
        try:
            info = jf("GET", "/System/Info/Public")
            break
        except (urllib.error.HTTPError, OSError):
            time.sleep(2)
    if info is None:
        sys.exit("Jellyfin answers but isn't ready: try again in a minute")
    saved = secret("jellyfin")
    if not info.get("StartupWizardCompleted"):
        saved = {"user": os.environ.get("JELLYFIN_USER", "home"), "password": secrets.token_urlsafe(14)}
        jf("POST", "/Startup/Configuration", {"UICulture": "en-GB", "MetadataCountryCode": "GB", "PreferredMetadataLanguage": "en"})
        jf("GET", "/Startup/User")  # makes the first user, before it's named
        jf("POST", "/Startup/User", {"Name": saved["user"], "Password": saved["password"]})
        jf("POST", "/Startup/RemoteAccess", {"EnableRemoteAccess": False, "EnableAutomaticPortMapping": False})
        jf("POST", "/Startup/Complete")
        keep("jellyfin", saved)
        print(f"Jellyfin: set up, user {saved['user']} (password in data/secrets/jellyfin.json)")
    elif not saved:
        sys.exit("Jellyfin was set up by hand: put its user and password in data/secrets/jellyfin.json to go on")
    token = jf("POST", "/Users/AuthenticateByName", {"Username": saved["user"], "Pw": saved["password"]})["AccessToken"]
    have = {f["Name"] for f in jf("GET", "/Library/VirtualFolders", token=token) or []}
    for name, kind, path in LIBRARIES:
        if name not in have:
            q = urllib.parse.urlencode({"name": name, "collectionType": kind, "refreshLibrary": "true"})
            jf("POST", f"/Library/VirtualFolders?{q}", {"LibraryOptions": {"PathInfos": [{"Path": path}]}}, token=token)
            print(f"Jellyfin: library {name} ({path})")
    print("Jellyfin: libraries ready")


def setup():
    load_env()
    lib = media_dir()
    for f in FOLDERS:
        (lib / f).mkdir(parents=True, exist_ok=True)
    print(f"library: {lib}")
    setup_qbittorrent()
    setup_jellyfin()
    print("\nNext: install Jellyfin on the TV (Google Play: \"Jellyfin for Android TV\"), pick this server, and sign in "
          "with Quick Connect. Add torrents at http://<this machine>:8090 (user admin, password in "
          "data/secrets/qbittorrent.json); give a film the category movies, a series shows.")


if __name__ == "__main__":
    if sys.argv[1:] == ["setup"]:
        setup()
    else:
        sys.exit(__doc__)
