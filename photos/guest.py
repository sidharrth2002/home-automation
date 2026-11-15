"""Guest mode: generic landscapes instead of my photos, for when someone's visiting.

While `input_boolean.guest_photos` is on, the photo frame shows a set of Wikimedia Commons featured landscape
pictures (high resolution, freely licensed, credited in the label) and none of mine. Any picture with a face in it is
skipped. The set is downloaded once into www/photos-guest and reused.
"""
import html
import json
import logging
import random
import re
import secrets
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

log = logging.getLogger("photos.guest")
SWITCH = "input_boolean.guest_photos"
CATEGORY = "Category:Featured_pictures_of_landscapes"
API = "https://commons.wikimedia.org/w/api.php"
UA = "home-automation-photo-frame/1.0 (https://github.com/sidharrth2002/home-automation)"
WANT = 30
WIDTH = 3840  # Commons scales to this on its side, so downloads stay a sensible size


def _get(url: str, timeout=60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def candidates() -> list[dict]:
    """Wide (not panoramic), large featured landscapes: title, scaled-image URL, credit."""
    query = {"action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": CATEGORY,
             "gcmtype": "file", "gcmlimit": "500", "prop": "imageinfo", "iiprop": "size|url|extmetadata",
             "iiurlwidth": str(WIDTH), "iiextmetadatafilter": "Artist|LicenseShortName"}
    pages, more = {}, {}
    while True:  # with a scaled URL, Commons fills in imageinfo for ~50 files per request
        res = json.loads(_get(f"{API}?{urllib.parse.urlencode({**query, **more})}"))
        for pid, p in res["query"]["pages"].items():
            if "imageinfo" in p:
                pages[pid] = p
        if "continue" not in res or len(pages) >= 300:
            break
        more = res["continue"]
    out = []
    for p in pages.values():
        info = p["imageinfo"][0]
        w, h = info["width"], info["height"]
        if w < 3000 or not 1.4 <= w / h <= 2.2:
            continue
        meta = info.get("extmetadata", {})
        artist = " ".join(re.sub(r"<[^>]+>", "", html.unescape(meta.get("Artist", {}).get("value", ""))).split())
        licence = meta.get("LicenseShortName", {}).get("value", "")
        title = re.sub(r"\.\w+$", "", p["title"].removeprefix("File:")).replace("_", " ")
        credit = " · ".join(x for x in (artist[:40], licence) if x)
        out.append({"title": title, "url": info.get("thumburl") or info["url"], "credit": credit})
    return out


def build(out_dir: Path, faces, prepare, tv_cover) -> list[dict]:
    """Download a guest set (or reuse the one already there). Returns photo-frame entries."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = out_dir / "set.json"
    if saved.exists():
        entries = json.loads(saved.read_text())
        if entries and all((out_dir / Path(e["src"]).name).exists() for e in entries):
            return entries
    pool = candidates()
    random.shuffle(pool)
    entries = []
    for c in pool:
        if len(entries) >= WANT:
            break
        try:
            jpeg = _get(c["url"], timeout=90)
        except OSError as e:
            log.warning("couldn't download %s: %s", c["title"], e)
            continue
        look = faces.analyse(jpeg)
        if not look.get("ok") or look.get("faces", 0) > 0:  # landscapes only: nobody in them
            continue
        made = prepare(jpeg)
        if not made or made[0].height > made[0].width:
            continue
        im, bg = made
        name = secrets.token_urlsafe(12)
        im.save(out_dir / f"{name}.jpg", quality=92, optimize=True, progressive=True)
        scale = max(tv_cover[0] / im.width, tv_cover[1] / im.height)
        im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS).save(
            out_dir / f"{name}-tv.jpg", quality=90, optimize=True, progressive=True)
        bg.save(out_dir / f"{name}-bg.jpg", quality=70)
        label = f"{c['title'][:60]} — {c['credit']}" if c["credit"] else c["title"][:60]
        base = f"/local/{out_dir.name}/{name}"
        entries.append({"src": f"{base}.jpg", "tv": f"{base}-tv.jpg", "bg": f"{base}-bg.jpg", "label": label,
                        "portrait": False, "people": False})
    saved.write_text(json.dumps(entries))
    log.info("guest set: %d landscapes", len(entries))
    return entries
