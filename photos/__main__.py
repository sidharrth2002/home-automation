"""Photos for the Hub and the TV screensaver, picked from OneDrive through Microsoft's API.

  python -m photos --watch             the service (run by ./home up)
  python -m photos once                index, look at a batch, pick and publish now
  python -m photos learn-me <photo>    your reference face, from a photo of you
  python -m photos status

How it picks without downloading the library:
1. Index. Graph's delta listing of PHOTOS_DIRS gives every photo's metadata (when, which camera, focal length, size).
   Nothing is downloaded, and after the first run only changes are fetched.
2. Filter on metadata: real camera photos only (no screenshots or saved images), big enough. A short focal length
   marks the front camera: a selfie, which is kept only if there are other people in it.
3. Look, a batch at a time (ANALYSE_PER_RUN): fetch the ~800px thumbnail (~150 KB) and find faces on this machine
   (photos/faces.py). "With people" means two or more faces big enough to be the subject; ones with you in rank
   highest. Results are cached, so the whole library gets looked at once, over a few days.
4. Pick about PHOTOS_PER_SET: people first, you highest, at most two from any one day, a share from this month in
   past years.
5. Show: download the original of just those (full resolution), re-encode as JPEG with no metadata (no location
   leaves the Mac; browsers can't show HEIC anyway), add a pre-blurred background, and serve them under random
   names. sensor.photo_frame lists them for the Hub. Each set avoids the photos in the one before.

PHOTOS_DIRS in .env: OneDrive folders to use, separated by ";" (default "Pictures/Camera Roll").
Everything it keeps (index, models, your face embedding, the served copies) is git-ignored.
"""
import io
import json
import logging
import os
import random
import secrets
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps
from pillow_heif import register_heif_opener

from .faces import Faces
from .graph import Graph

register_heif_opener()  # iPhone originals are HEIC
log = logging.getLogger("photos")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "photos"
INDEX = DATA / "index.json"
OUT = ROOT / "homeassistant" / "config" / "www" / "photos"
SENSOR = "sensor.photo_frame"
HA_HTTP = os.environ.get("HA_HTTP", "http://localhost:8123")
EXTENSIONS = (".jpg", ".jpeg", ".heic", ".png")
PHOTOS_PER_SET = 40
FETCHERS = 6  # downloads at once; Graph is happy with a handful
ANALYSE_PER_RUN = 150  # thumbnails looked at per refresh (~150 KB each)
SAME_MONTH_SHARE = 0.4
MAX_PER_DAY = 2
FRONT_CAMERA_MM = 3.5  # phone front cameras are ~2-3 mm; main cameras ~4-7 mm (selfies are fine, but not alone)
MIN_SIDE = 1200
REFRESH_S = 4 * 3600


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def folder_names() -> list[str]:
    return [n.strip().strip("/") for n in os.environ.get("PHOTOS_DIRS", "Pictures/Camera Roll").split(";") if n.strip()]


# ── 1. index ─────────────────────────────────────────────────────
def load_index() -> dict:
    return json.loads(INDEX.read_text()) if INDEX.exists() else {"items": {}, "delta": {}}


def save_index(index: dict):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(index))
    tmp.chmod(0o600)
    tmp.replace(INDEX)


def record(item: dict) -> dict | None:
    """The metadata worth keeping for one Graph item, or None if it isn't a photo."""
    if "file" not in item or not item.get("name", "").lower().endswith(EXTENSIONS):
        return None
    photo, image = item.get("photo") or {}, item.get("image") or {}
    return {"name": item["name"], "folder": (item.get("parentReference") or {}).get("path", ""),
            "taken": photo.get("takenDateTime"), "make": photo.get("cameraMake"), "focal": photo.get("focalLength"),
            "w": image.get("width"), "h": image.get("height"), "size": item.get("size"), "look": None}


def update_index(graph: Graph, index: dict) -> int:
    changed = 0
    for folder in folder_names():
        link = index["delta"].get(folder)
        items = graph.delta(folder, link)
        while True:
            try:
                item = next(items)
            except StopIteration as done:
                index["delta"][folder] = done.value
                break
            if item.get("deleted"):
                changed += index["items"].pop(item["id"], None) is not None
                continue
            rec = record(item)
            if rec:
                old = index["items"].get(item["id"])
                if old and old.get("size") == rec["size"]:
                    rec["look"] = old.get("look")  # same file: keep what we already know about it
                index["items"][item["id"]] = rec
                changed += 1
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
def look_at_batch(graph: Graph, faces: Faces, index: dict, today: date, budget: int = ANALYSE_PER_RUN, rng=random) -> int:
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

    looked = 0
    batch = (same_month + others)[:budget]
    with ThreadPoolExecutor(FETCHERS) as pool:  # downloads in parallel; the face models stay on this thread
        for (item_id, rec), jpeg in zip(batch, pool.map(fetch, (i for i, _ in batch))):
            rec["look"] = faces.analyse(jpeg) if jpeg else {"ok": False}
            looked += jpeg is not None
    return looked


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
    body = {"state": len(entries), "attributes": {"friendly_name": "Photo frame", "icon": "mdi:image-multiple",
                                                   "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                                                   "photos": entries}}
    req = urllib.request.Request(f"{HA_HTTP}/api/states/{SENSOR}", method="POST", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['TOKEN']}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).close()


def show(graph: Graph, index: dict, chosen: list[str], today: date) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    old = set(OUT.glob("*.jpg"))
    def make(item_id):  # download, convert and save in the worker, so only a few full-size images are in memory
        rec = index["items"][item_id]
        try:
            made = prepare(graph.original(item_id))
        except Exception as e:
            log.debug("couldn't fetch %s: %s", rec["name"], e)
            return None
        if not made or made[0].height > made[0].width:  # landscape only (in case the metadata disagreed)
            return None
        im, bg = made
        name = secrets.token_urlsafe(18)
        im.save(OUT / f"{name}.jpg", quality=92, optimize=True, progressive=True, subsampling=0)
        bg.save(OUT / f"{name}-bg.jpg", quality=70)
        return {"src": f"/local/photos/{name}.jpg", "bg": f"/local/photos/{name}-bg.jpg",
                "label": label(taken(rec), today), "portrait": False,
                "people": (rec.get("look") or {}).get("faces", 0) >= 2}

    with ThreadPoolExecutor(FETCHERS) as pool:
        made = list(pool.map(make, chosen))
    entries = [e for e in made if e]
    index["shown"] = [i for i, e in zip(chosen, made) if e]
    if entries:
        publish(entries)
        time.sleep(120)  # let a slideshow that's mid-photo finish with the old set
        for f in old:
            f.unlink(missing_ok=True)
    return len(entries)


def refresh(graph: Graph, faces: Faces):
    today = date.today()
    index = load_index()
    changed = update_index(graph, index)
    save_index(index)
    looked = look_at_batch(graph, faces, index, today)
    save_index(index)
    shown = show(graph, index, pick(index, today), today)
    save_index(index)  # remembers what's on screen, for the next set
    log.info("index: %d photos (%d changed); looked at %d; showing %d", len(index["items"]), changed, looked, shown)


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
        refresh(Graph(), Faces())
    elif cmd == "--watch":
        graph, faces = Graph(), Faces()
        while True:
            try:
                refresh(graph, faces)
            except Exception:
                log.exception("photo refresh failed")
            time.sleep(REFRESH_S)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
