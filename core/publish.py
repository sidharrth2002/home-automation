"""Mirror state into Home Assistant, which carries it to the Hub, the TV and the widget.

Runs on its own thread, following the change feed, so a write never waits on (or fails because of) Home Assistant.
A change marks its publisher dirty; it's published shortly after (a burst of writes becomes one publish), retried
until it lands, and re-published every few minutes because Home Assistant forgets REST-set states on restart.
Live entities (core/live.py: what the services report) are marked one by one as they change.
"""
import json
import logging
import os
import threading
import time
import urllib.request
from datetime import date

from . import finance, live, portfolio, tasks
from .db import DB, NotFound

log = logging.getLogger("core.publish")
REPUBLISH_S = 300
DEBOUNCE_S = 0.5


def post_state(entity: str, state, attrs: dict):
    url = os.environ.get("HA_HTTP", "http://localhost:8123")
    req = urllib.request.Request(f"{url}/api/states/{entity}", method="POST",
                                 data=json.dumps({"state": state, "attributes": attrs}).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['TOKEN']}",
                                          "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).close()


def publish_investments(db: DB, post=post_state):
    sources = finance.current(db)
    if not sources:
        return
    today = date.today().isoformat()
    total, attrs = portfolio.merge(sources, finance.valuations(db), today)
    finance.record_valuation(db, today, total, {
        s["id"]: round(sum(a["total"] or 0 for a in s["data"]["accounts"] if a.get("in_total", True) is not False), 2)
        for s in sources})
    post("sensor.investments", total, attrs)
    log.info("published investments: %d sources, %d accounts, %d holdings",  # no amounts in logs
             len(sources), len(attrs["accounts"]), len(attrs["holdings"]))


def publish_tasks(db: DB, post=post_state):
    s = tasks.summary(db)
    running = s["counts"].get("running", 0)
    post("sensor.core_tasks", running, {"friendly_name": "Background tasks", "icon": "mdi:robot-outline",
                                        "counts": s["counts"], "recent": s["recent"]})


def publish_live(db: DB, entity: str, post=post_state):
    try:
        row = live.get(db, entity)
    except NotFound:  # deleted since it was marked
        return
    post(entity, row["state"], row["attributes"])


PUBLISHERS = {"investments": publish_investments, "tasks": publish_tasks}
TRIGGERS = {"portfolio": "investments", "price": "investments", "task": "tasks"}  # audit entity -> publisher
LIVE = "live:"  # the dirty mark for one live entity is LIVE + its id


class Publisher:
    def __init__(self, db: DB, post=post_state):
        self.db, self.post = db, post
        self.dirty = self.everything()  # everything once at start
        self.wake = threading.Event()
        self.wake.set()
        self.last_ok: dict[str, str] = {}

    def everything(self) -> set[str]:
        return set(PUBLISHERS) | {LIVE + e for e in live.entities(self.db)}

    def live_changed(self, entity: str):
        """A service reported a new state: publish it shortly."""
        self.dirty.add(LIVE + entity)
        self.wake.set()

    def run(self):
        backoff, last_full = 2, time.monotonic()
        while True:
            self.wake.wait(timeout=REPUBLISH_S)
            time.sleep(DEBOUNCE_S)
            self.wake.clear()
            if time.monotonic() - last_full >= REPUBLISH_S:
                self.dirty |= self.everything()
                last_full = time.monotonic()
            for name in sorted(self.dirty):
                self.dirty.discard(name)  # before reading the state: a write during the publish marks it again
                try:
                    if name.startswith(LIVE):
                        publish_live(self.db, name[len(LIVE):], self.post)
                    else:
                        PUBLISHERS[name](self.db, self.post)
                    # one freshness figure for all live entities
                    self.last_ok["live" if name.startswith(LIVE) else name] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    backoff = 2
                except Exception as e:  # Home Assistant down or restarting: dirty again, try again
                    self.dirty.add(name)
                    log.warning("publishing %s failed (%s); retrying in %ds", name, e, backoff)
                    threading.Timer(backoff, self.wake.set).start()
                    backoff = min(backoff * 2, 60)
                    break  # the rest stay marked: no point timing out on each while it's down

    def follow(self):
        seq = self.db.last_seq()
        while True:
            for c in self.db.changes_since(seq, wait=30):
                seq = c["seq"]
                if c["entity"] in TRIGGERS:
                    self.dirty.add(TRIGGERS[c["entity"]])
                    self.wake.set()
