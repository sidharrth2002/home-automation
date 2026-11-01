"""Publish Netflix history to Home Assistant as sensors for the dashboard.

  python -m netflix [path/to/export.csv] [--watch]

Without a path it uses the newest Netflix export in ~/Downloads or data/netflix/. With --watch it
re-checks every 5 minutes, so dropping in a newer export updates the dashboard (and re-publishes after
a Home Assistant restart, since REST-created sensors aren't persisted).
"""
import json
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from music_sync.service import HA_HTTP, load_env

from .history import continue_watching, parse, relative

log = logging.getLogger("netflix")
ROOT = Path(__file__).resolve().parent.parent
SEARCH = [Path.home() / "Downloads", ROOT / "data" / "netflix"]
PATTERNS = ["NetflixViewingHistory*.csv", "ViewingActivity*.csv"]


def newest_export():
    found = [p for d in SEARCH if d.exists() for pat in PATTERNS for p in d.rglob(pat)]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def post(entity_id, state, attrs):
    req = urllib.request.Request(
        f"{HA_HTTP}/api/states/{entity_id}", method="POST",
        data=json.dumps({"state": str(state)[:255], "attributes": attrs}).encode(),
        headers={"Authorization": f"Bearer {os.environ['TOKEN']}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).close()


def publish(path: Path):
    today = datetime.now()
    h = parse(path, profile=os.environ.get("NETFLIX_PROFILE") or None, today=today)
    recent = [{"title": v.label, "show": v.show, "when": relative(v.when, today), "movie": v.is_movie}
              for v in h.views[:10]]
    cont = []
    for v, n in continue_watching(h):
        item = {"show": v.show, "next_after": f"{v.season}: {v.episode}", "when": relative(v.when, today),
                "episodes_watched": n}
        if v.position_s:
            item["stopped_at"] = f"{v.position_s // 3600}:{v.position_s % 3600 // 60:02d}:{v.position_s % 60:02d}" \
                if v.position_s >= 3600 else f"{v.position_s // 60}:{v.position_s % 60:02d}"
        cont.append(item)
    last = h.views[0] if h.views else None
    common = {"icon": "mdi:netflix", "source": h.source, "export_file": path.name,
              "export_date": datetime.fromtimestamp(path.stat().st_mtime).strftime("%-d %b %Y")}
    post("sensor.netflix_last_watched", last.label if last else "Nothing yet",
         {**common, "friendly_name": "Netflix last watched", "when": relative(last.when, today) if last else None,
          "recent": recent})
    post("sensor.netflix_continue_watching", len(cont),
         {**common, "friendly_name": "Netflix continue watching", "unit_of_measurement": "shows", "shows": cont})
    post("sensor.netflix_episodes_this_week", h.stats["episodes_7d"],
         {**common, "friendly_name": "Netflix episodes this week", "unit_of_measurement": "episodes", **h.stats})
    log.info("published %d views from %s (%s)", len(h.views), path.name, h.source)


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = [a for a in sys.argv[1:] if a != "--watch"]
    watch = "--watch" in sys.argv
    while True:
        path = Path(args[0]) if args else newest_export()
        if path:
            try:
                publish(path)
            except Exception as e:
                log.warning("could not publish %s: %s", path, e)
        else:
            log.info("no Netflix export found in %s", ", ".join(str(d) for d in SEARCH))
        if not watch:
            return
        time.sleep(300)


if __name__ == "__main__":
    main()
