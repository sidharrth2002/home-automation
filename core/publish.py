"""Mirror state into Home Assistant, which carries it to the Hub, the TV and the widget.

Runs on its own thread, following the change feed, so a write never waits on (or fails because of) Home Assistant.
A change marks its publisher dirty; it's published shortly after (a burst of writes becomes one publish), retried
until it lands, and re-published every few minutes because Home Assistant forgets REST-set states on restart.
"""
import json
import logging
import os
import threading
import time
import urllib.request
from datetime import date

from . import finance, portfolio
from .db import DB

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


PUBLISHERS = {"investments": publish_investments}
TRIGGERS = {"portfolio": "investments", "price": "investments"}  # audit entity -> publisher


class Publisher:
    def __init__(self, db: DB, post=post_state):
        self.db, self.post = db, post
        self.dirty = set(PUBLISHERS)  # everything once at start
        self.wake = threading.Event()
        self.wake.set()
        self.last_ok: dict[str, str] = {}

    def run(self):
        backoff, last_full = 2, time.monotonic()
        while True:
            self.wake.wait(timeout=REPUBLISH_S)
            time.sleep(DEBOUNCE_S)
            self.wake.clear()
            if time.monotonic() - last_full >= REPUBLISH_S:
                self.dirty |= set(PUBLISHERS)
                last_full = time.monotonic()
            for name in sorted(self.dirty):
                self.dirty.discard(name)  # before reading the state: a write during the publish marks it again
                try:
                    PUBLISHERS[name](self.db, self.post)
                    self.last_ok[name] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    backoff = 2
                except Exception as e:  # Home Assistant down or restarting: dirty again, try again
                    self.dirty.add(name)
                    log.warning("publishing %s failed (%s); retrying in %ds", name, e, backoff)
                    threading.Timer(backoff, self.wake.set).start()
                    backoff = min(backoff * 2, 60)

    def follow(self):
        seq = self.db.last_seq()
        while True:
            for c in self.db.changes_since(seq, wait=30):
                seq = c["seq"]
                if c["entity"] in TRIGGERS:
                    self.dirty.add(TRIGGERS[c["entity"]])
                    self.wake.set()
