"""Photos for the Hub and the TV screensaver, picked from OneDrive through Microsoft's API.

  python -m photos --watch             the service (run by ./home up)
  python -m photos once                index, pick and publish now
  python -m photos look                look at a batch now (normally the hourly `photos-look` task)
  python -m photos learn-me <photo>    your reference face, from a photo of you
  python -m photos status

How it picks without downloading the library:
1. Index. Graph's delta listing of PHOTOS_DIRS gives every photo's metadata (when, which camera, focal length, size).
   Nothing is downloaded, and after the first run only changes are fetched.
2. Filter on metadata: real camera photos only (no screenshots or saved images), big enough. A short focal length
   marks the front camera: a selfie, which is kept only if there are other people in it.
3. Look, a batch at a time (ANALYSE_PER_RUN): fetch the ~800px thumbnail (~150 KB) and find faces on this machine
   (photos/faces.py). "With people" means two or more faces big enough to be the subject; ones with you in rank
   highest. This is a background task (`photos-look`, hourly, run by the core's task worker), and results are kept
   in the core, so the whole library gets looked at once, over a few days.
4. Pick about PHOTOS_PER_SET: people first, you highest, at most two from any one day, a share from this month in
   past years.
5. Show: download the original of just those (full resolution), re-encode as JPEG with no metadata (no location
   leaves the Mac; browsers can't show HEIC anyway), add a pre-blurred background, and serve them under random
   names. sensor.photo_frame lists them for the Hub. Each set avoids the photos in the one before.

PHOTOS_DIRS in .env: OneDrive folders to use, separated by ";" (default "Pictures/Camera Roll").
The index (metadata, what was found, what was shown) lives in the core's database (/v1/media/onedrive); the face
models, your face embedding and the served copies stay on disk. All of it is git-ignored.
"""
import io
import json
import logging
import os
import random
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import telemetry

from PIL import Image, ImageFilter, ImageOps
from pillow_heif import register_heif_opener

from core import client as core

from . import guest
from .faces import Faces
from .graph import Graph

register_heif_opener()  # iPhone originals are HEIC
log = logging.getLogger("photos")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "photos"
INDEX = DATA / "index.json"  # before the index moved into the core; migrated once, then set aside
PUBLISHED = DATA / "published.json"  # the set on screen, to put back when Home Assistant restarts and forgets it
OUT = ROOT / "homeassistant" / "config" / "www" / "photos"
GUEST_OUT = ROOT / "homeassistant" / "config" / "www" / "photos-guest"
SENSOR = "sensor.photo_frame"
SOURCE = "onedrive"  # the core's media source
ANALYSER = "faces"   # the core's name for what faces.py finds
CORE_FIELDS = {"name": "name", "folder": "folder", "taken": "taken_at", "make": "camera", "focal": "focal_mm",
               "w": "width", "h": "height", "size": "bytes"}  # this module's record -> the core's media columns
HA_HTTP = os.environ.get("HA_HTTP", "http://localhost:8123")
EXTENSIONS = (".jpg", ".jpeg", ".heic", ".png")
PHOTOS_PER_SET = 40
TV_COVER = (2080, 1170)  # the TV's copy: covers 1920x1080 through the slow zoom (the TV can't decode 24 MP smoothly)
FETCHERS = 6  # downloads at once; Graph is happy with a handful
ANALYSE_PER_RUN = 150  # thumbnails looked at per hourly task (~150 KB each)
SAME_MONTH_SHARE = 0.4
MAX_PER_DAY = 2
FRONT_CAMERA_MM = 3.5  # phone front cameras are ~2-3 mm; main cameras ~4-7 mm (selfies are fine, but not alone)
MIN_SIDE = 1200
REFRESH_S = 4 * 3600
CHECK_S = 2  # how often to check the frame shows the right set (guest mode, or HA forgot it on restart)
FRAME_LOCK = threading.Lock()  # the sync thread and a refresh both post the set


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def folder_names() -> list[str]:
    return [n.strip().strip("/") for n in os.environ.get("PHOTOS_DIRS", "Pictures/Camera Roll").split(";") if n.strip()]


# ── 1. index (kept in the core: /v1/media/onedrive) ─────────────
def to_core(item_id: str, rec: dict) -> dict:
    return {"id": item_id, **{c: rec.get(k) for k, c in CORE_FIELDS.items()}}


def from_core(item: dict) -> dict:
    return {**{k: item.get(c) for k, c in CORE_FIELDS.items()}, "look": item.get("analysis")}


def load_index(analysed: bool | None = None) -> dict:
    """The library from the core: {"items": {id: record}, "shown": [ids on screen now]}. `analysed` keeps only the
    photos already looked at (True) or not yet (False)."""
    items, after = {}, ""
    while after is not None:
        q = {"analyser": ANALYSER, "after": after} | ({} if analysed is None else {"analysed": str(analysed).lower()})
        page = core.call("GET", f"/v1/media/{SOURCE}/items?{urllib.parse.urlencode(q)}", timeout=60)
        items.update((it["id"], from_core(it)) for it in page["items"])
        after = page["next"]
    return {"items": items, "shown": core.call("GET", f"/v1/media/{SOURCE}")["last_shown"]}


def save_looks(looks: dict[str, dict]):
    core.call("PUT", f"/v1/media/{SOURCE}/analysis/{ANALYSER}", {"results": looks}, timeout=60)


def migrate():
    """Once: move the old JSON index (data/photos/index.json) into the core, then set it aside."""
    if not INDEX.exists() or core.call("GET", f"/v1/media/{SOURCE}")["items"]:
        return
    old = json.loads(INDEX.read_text())
    ids = list(old["items"])
    for i in range(0, len(ids), 2000):
        core.call("PUT", f"/v1/media/{SOURCE}/items",
                  {"items": [to_core(k, old["items"][k]) for k in ids[i:i + 2000]]}, timeout=120)
    looks = [(k, r["look"]) for k, r in old["items"].items() if r.get("look") is not None]
    for i in range(0, len(looks), 2000):
        save_looks(dict(looks[i:i + 2000]))
    for folder, link in old.get("delta", {}).items():  # last: until it's saved, the next listing starts over
        core.call("PUT", f"/v1/media/{SOURCE}/items", {"cursor": {"key": folder, "value": link}})
    if old.get("shown"):
        core.call("POST", f"/v1/media/{SOURCE}/shown", {"ids": old["shown"]})
    INDEX.rename(INDEX.with_suffix(".json.migrated"))
    log.info("moved the photo index into the core: %d photos, %d looked at", len(ids), len(looks))


def record(item: dict) -> dict | None:
    """The metadata worth keeping for one Graph item, or None if it isn't a photo."""
    if "file" not in item or not item.get("name", "").lower().endswith(EXTENSIONS):
        return None
    photo, image = item.get("photo") or {}, item.get("image") or {}
    return {"name": item["name"], "folder": (item.get("parentReference") or {}).get("path", ""),
            "taken": photo.get("takenDateTime"), "make": photo.get("cameraMake"), "focal": photo.get("focalLength"),
            "w": image.get("width"), "h": image.get("height"), "size": item.get("size"), "look": None}


def update_index(graph: Graph) -> int:
    """Send the library's changes since the last listing to the core (which drops what it knew about a photo whose
    file changed). The listing's cursor is saved with the last batch, so an interrupted run starts over safely."""
    cursors = core.call("GET", f"/v1/media/{SOURCE}")["cursors"]
    changed = 0
    for folder in folder_names():
        found, gone = [], []
        listing = graph.delta(folder, cursors.get(folder))
        while True:
            try:
                item = next(listing)
            except StopIteration as done:
                link = done.value
                break
            if item.get("deleted"):
                gone.append(item["id"])
            elif rec := record(item):
                found.append(to_core(item["id"], rec))
            if len(found) + len(gone) >= 2000:
                changed += core.call("PUT", f"/v1/media/{SOURCE}/items", {"items": found, "deleted": gone},
                                     timeout=120)["changed"]
                found, gone = [], []
        changed += core.call("PUT", f"/v1/media/{SOURCE}/items", {"items": found, "deleted": gone,
                                                                   "cursor": {"key": folder, "value": link}},
                             timeout=120)["changed"]
    return changed


# ── 2. filter on metadata ────────────────────────────────────────
def worth_a_look(rec: dict) -> bool:
    """A real camera photo (not a screenshot or a saved image), big enough for a TV."""
    if not rec.get("make") or "screenshot" in rec["name"].lower() or "screenshots" in rec.get("folder", "").lower():
        return False
    return min(rec.get("w") or 0, rec.get("h") or 0) >= MIN_SIDE


def selfie(rec: dict) -> bool:
    return rec.get("focal") is not None and rec["focal"] < FRONT_CAMERA_MM


def taken(rec: dict) -> date | None:
    try:
        return datetime.fromisoformat(rec["taken"].replace("Z", "+00:00")).date() if rec.get("taken") else None
    except ValueError:
        return None


# ── 3. look at a batch ───────────────────────────────────────────
def look_at_batch(graph: Graph, faces: Faces, index: dict, today: date, budget: int = ANALYSE_PER_RUN, rng=random,
                  save=lambda looks: None, progress=lambda fraction, message: None, cancelled=lambda: False) -> int:
    """Look at up to `budget` photos not yet looked at (this month in past years first), saving as it goes."""
    pending = [(i, r) for i, r in index["items"].items() if r.get("look") is None and worth_a_look(r)]
    same_month = [p for p in pending if (d := taken(p[1])) and d.month == today.month and d.year < today.year]
    others = [p for p in pending if p not in same_month]
    rng.shuffle(same_month)
    rng.shuffle(others)
    def fetch(item_id):
        try:
            return graph.thumbnail(item_id, "large")
        except Exception as e:  # one bad thumbnail shouldn't stop the batch
            log.debug("couldn't fetch %s: %s", item_id, e)
            return None

    looked, looks = 0, {}
    batch = (same_month + others)[:budget]
    with ThreadPoolExecutor(FETCHERS) as pool:  # downloads in parallel; the face models stay on this thread
        for n, ((item_id, rec), jpeg) in enumerate(zip(batch, pool.map(fetch, (i for i, _ in batch))), 1):
            if cancelled():
                break
            rec["look"] = looks[item_id] = faces.analyse(jpeg) if jpeg else {"ok": False}
            looked += jpeg is not None
            if len(looks) >= 25:
                save(looks)
                looks = {}
            progress(n / len(batch), f"looked at {n} of {len(batch)}")
    if looks:
        save(looks)
    return looked


def look(budget: int = ANALYSE_PER_RUN, progress=lambda fraction, message: None, cancelled=lambda: False) -> dict:
    """One batch, as a background task (the worker's `photos-look`, scheduled hourly)."""
    index = load_index(analysed=False)
    looked = look_at_batch(Graph(), Faces(), index, date.today(), budget, save=save_looks, progress=progress,
                           cancelled=cancelled)
    remaining = sum(1 for r in index["items"].values() if r.get("look") is None and worth_a_look(r))
    log.info("looked at %d photos; %d still to look at", looked, remaining)
    return {"looked": looked, "remaining": remaining}


# ── 4. pick ──────────────────────────────────────────────────────
def score(rec: dict) -> float:
    """How much a photo belongs on the frame: people (with you) first, sharp and well exposed, never a selfie."""
    look = rec.get("look") or {}
    if not look.get("ok") or look["sharpness"] < 60 or not 35 <= look["brightness"] <= 225:
        return 0.0
    if not look.get("landscape"):
        return 0.0  # landscape only: portrait photos look lost on a TV
    faces = look["faces"]
    if selfie(rec) and faces < 2:
        return 0.0  # a selfie on my own; selfies with other people are welcome
    if faces == 1 and look["largest_face"] > 0.06:
        return 0.0  # one big face: a close-up portrait, not "with people"
    s = 0.2  # a decent photo with no one in it: only used to fill a set while the library is still being looked at
    if faces >= 2:
        s = 2.0 + min(faces, 6) * 0.15
    if look.get("me") and faces >= 2:
        s += 3.0
    return s


def pick(index: dict, today: date, n: int = PHOTOS_PER_SET, rng=random) -> list[str]:
    scored = [(i, r, score(r)) for i, r in index["items"].items()]
    scored = [x for x in scored if x[2] > 0]
    # weighted random, so the set changes each time but good photos come round more often
    order = sorted(scored, key=lambda x: rng.random() ** (1 / x[2]), reverse=True)
    last = set(index.get("shown", []))  # the set on screen now goes to the back, so each set is fresh
    order = [x for x in order if x[0] not in last] + [x for x in order if x[0] in last]
    same_month = [x for x in order if (d := taken(x[1])) and d.month == today.month and d.year < today.year]
    chosen, per_day = [], {}

    def take(pool, limit):
        for item_id, rec, _ in pool:
            if len(chosen) >= limit:
                return
            day = taken(rec)
            if item_id in chosen or (day and per_day.get(day, 0) >= MAX_PER_DAY):
                continue
            chosen.append(item_id)
            if day:
                per_day[day] = per_day.get(day, 0) + 1

    take(same_month, int(n * SAME_MONTH_SHARE))
    take(order, n)
    rng.shuffle(chosen)
    return chosen


def label(d: date | None, today: date) -> str:
    if not d:
        return ""
    years = today.year - d.year
    when = d.strftime("%B %Y")
    if d.month == today.month and years > 0:
        return f"{when} · {years} year{'s' if years > 1 else ''} ago"
    return when


# ── 5. show ──────────────────────────────────────────────────────
def prepare(jpeg: bytes) -> tuple[Image.Image, Image.Image] | None:
    """Upright pixels only (re-encoding drops every bit of metadata), plus a small blurred background."""
    with Image.open(io.BytesIO(jpeg)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
    if min(im.size) < 400:
        return None
    bg = im.copy()
    bg.thumbnail((480, 480))
    return im, bg.filter(ImageFilter.GaussianBlur(18))


def publish(entries: list[dict]):
    """Remember a new set of mine and put it on screen, unless guest mode is showing landscapes instead."""
    with FRAME_LOCK:
        PUBLISHED.write_text(json.dumps(entries))
        if not guest_on():
            post(entries, guest=False)


def post(entries: list[dict], guest: bool):
    """The set on screen, through the core (which mirrors it into Home Assistant and puts it back after a restart)."""
    core.report(SENSOR, len(entries), {"friendly_name": "Photo frame", "icon": "mdi:image-multiple",
                                       "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                                       "guest": guest, "photos": entries})


def _state(entity_id: str) -> dict | None:
    """An entity's state from Home Assistant; None if it doesn't exist. Raises OSError if HA isn't reachable."""
    req = urllib.request.Request(f"{HA_HTTP}/api/states/{entity_id}", headers={"Authorization": f"Bearer {os.environ['TOKEN']}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def guest_switch() -> bool:
    """Whether guest mode is on. Raises OSError while that can't be known (HA unreachable, or the switch not
    loaded yet after a restart), so the frame isn't swapped on a guess."""
    state = (_state(guest.SWITCH) or {"state": "off"}).get("state")  # never created: off
    if state not in ("on", "off"):
        raise OSError(f"guest switch is {state}")
    return state == "on"


def guest_on() -> bool:
    try:
        return guest_switch()
    except OSError:
        return False


def sync_frame(faces: Faces):
    """Keep the frame showing the right set: landscapes while guest mode is on, otherwise mine."""
    with FRAME_LOCK:  # publish() may be posting a new set of mine from the refresh thread
        try:
            frame, want_guest = core.live(SENSOR), guest_switch()
        except OSError:
            return  # the core or Home Assistant isn't answering: don't swap on a guess; try again next time
        showing_guest = bool(frame and frame["attributes"].get("guest"))
        if frame and showing_guest == want_guest:
            return
        if want_guest:
            entries = guest.build(GUEST_OUT, faces, prepare, TV_COVER)
        elif PUBLISHED.exists():
            entries = [e for e in json.loads(PUBLISHED.read_text()) if (OUT / Path(e["src"]).name).exists()]
        else:
            entries = []
        if entries:
            post(entries, guest=want_guest)
            log.info("photo frame: %d %s", len(entries), "guest landscapes" if want_guest else "of mine")


def keep_in_sync():
    """Check the Guest switch every CHECK_S, on its own thread, so a click shows within seconds even mid-refresh."""
    faces = Faces()  # its own: OpenCV's networks aren't safe to share with the refresh thread
    while True:
        try:
            sync_frame(faces)
        except Exception:
            log.exception("couldn't check the photo frame")
        time.sleep(CHECK_S)


def show(graph: Graph, index: dict, chosen: list[str], today: date) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    old = set(OUT.glob("*.jpg"))
    failed = []
    def make(item_id):  # download, convert and save in the worker, so only a few full-size images are in memory
        rec = index["items"][item_id]
        try:
            made = prepare(graph.original(item_id))
        except Exception as e:
            failed.append(e)
            return None
        if not made or made[0].height > made[0].width:  # landscape only (in case the metadata disagreed)
            return None
        im, bg = made
        name = secrets.token_urlsafe(18)
        im.save(OUT / f"{name}.jpg", quality=92, optimize=True, progressive=True, subsampling=0)
        scale = max(TV_COVER[0] / im.width, TV_COVER[1] / im.height)
        im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS).save(
            OUT / f"{name}-tv.jpg", quality=90, optimize=True, progressive=True, subsampling=0)
        bg.save(OUT / f"{name}-bg.jpg", quality=70)
        return {"src": f"/local/photos/{name}.jpg", "tv": f"/local/photos/{name}-tv.jpg", "bg": f"/local/photos/{name}-bg.jpg",
                "label": label(taken(rec), today), "portrait": False,
                "people": (rec.get("look") or {}).get("faces", 0) >= 2}

    with ThreadPoolExecutor(FETCHERS) as pool:
        made = list(pool.map(make, chosen))
    entries = [e for e in made if e]
    if failed:
        log.warning("couldn't download %d of %d photos (e.g. %s)", len(failed), len(chosen), failed[0])
    if not entries:
        return 0  # keep the set already on screen rather than blank it
    core.call("POST", f"/v1/media/{SOURCE}/shown", {"ids": [i for i, e in zip(chosen, made) if e]})
    publish(entries)
    time.sleep(120)  # let a slideshow that's mid-photo finish with the old set
    for f in old:
        f.unlink(missing_ok=True)
    return len(entries)


def refresh(graph: Graph):
    """List the library's changes and show a new set. Looking at photos is a separate hourly task (look())."""
    today = date.today()
    migrate()
    changed = update_index(graph)
    index = load_index(analysed=True)  # only looked-at photos can score
    shown = show(graph, index, pick(index, today), today)
    log.info("index: %d changed; %d looked at; showing %d", changed, len(index["items"]), shown)


def status():
    index = load_index()
    items = index["items"].values()
    eligible = [r for r in items if worth_a_look(r)]
    looked = [r for r in eligible if r.get("look")]
    people = [r for r in looked if (r["look"] or {}).get("faces", 0) >= 2 and score(r) > 0]
    print(f"photos indexed: {len(index['items'])}; worth a look: {len(eligible)}; looked at: {len(looked)}; "
          f"with people: {len(people)} ({sum(1 for r in people if r['look'].get('me'))} with you)")
    print("reference face:", "set" if (DATA / "me.npy").exists() else "not set (python -m photos learn-me <photo of you>)")


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    telemetry.setup("photos")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "learn-me":
        src = Path(sys.argv[2])
        if src.suffix.lower() == ".heic":  # OpenCV can't read HEIC; macOS can convert it
            jpg = DATA / "me-source.jpg"
            DATA.mkdir(parents=True, exist_ok=True)
            subprocess.run(["sips", "-s", "format", "jpeg", str(src), "--out", str(jpg)], check=True, capture_output=True)
            src = jpg
        ok = Faces().learn_me(src)
        (DATA / "me-source.jpg").unlink(missing_ok=True)
        print("learned your face" if ok else "no face found in that photo")
    elif cmd == "once":
        refresh(Graph())
    elif cmd == "look":
        print(look())
    elif cmd == "--watch":
        graph = Graph()
        core.ready(wait_s=120)  # started alongside the core
        threading.Thread(target=keep_in_sync, daemon=True, name="frame-sync").start()
        while True:
            try:
                refresh(graph)
            except Exception:
                log.exception("photo refresh failed")
            time.sleep(REFRESH_S)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
