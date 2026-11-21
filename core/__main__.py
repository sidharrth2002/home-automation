"""The core service: application state in SQLite, an HTTP API to change it, and Home Assistant kept in step.

    python -m core serve                          run it (the supervisor does this)
    python -m core token add <name> <scope>...    a token for a client, e.g. finance 'portfolio/hsbc*' 'doc/finance/*'
    python -m core token list | revoke <name>
    python -m core get <collection> [<key>]       read a document straight from the database

CORE_TOKEN in .env is the admin token the services use. CORE_BIND (default 127.0.0.1) and CORE_PORT (8790) say where
it listens; on a Pi serving other devices, bind to the LAN address. CORE_DB moves the database file.
"""
import json
import logging
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

import telemetry

from music_sync.service import load_env

from . import finance, tasks
from .db import DB, NotFound
from .maintenance import Maintenance
from .publish import Publisher

log = logging.getLogger("core")
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "core"


def migrate_legacy(db: DB):
    """First run: bring in what the investments service used to publish straight to Home Assistant."""
    old = ROOT / "data" / "investments" / "history.json"
    if not finance.valuations(db, 1) and old.exists():
        for day, total in json.loads(old.read_text()).items():
            finance.record_valuation(db, day, total, {"hl": total})
        log.info("migrated the daily totals")
    if db.q1("SELECT 1 FROM fin_sources WHERE id='hl'"):
        return
    try:  # until the next refresh, the last HL snapshot lives only in Home Assistant
        req = urllib.request.Request(f"{os.environ.get('HA_HTTP', 'http://localhost:8123')}/api/states/"
                                     "sensor.investments", headers={"Authorization": f"Bearer {os.environ['TOKEN']}"})
        attrs = json.loads(urllib.request.urlopen(req, timeout=10).read())["attributes"]
    except Exception as e:
        log.warning("no HL snapshot to migrate (%s); it arrives with the next refresh", e)
        return
    if not attrs.get("accounts") or attrs.get("sources"):  # nothing there, or already published by core
        return
    drop = {"sedol", "account", "source", "in_total"}
    accounts = [{"name": a["name"], "type": "isa" if "isa" in a["name"].lower() else "other",
                 "cash": a.get("cash"), "total": a.get("total"), "stock": a.get("stock"),
                 "holdings": [{**{k: v for k, v in h.items() if k not in drop and v is not None}, "id": h["sedol"]}
                              for h in attrs.get("holdings", []) if h.get("account") == a["name"]]}
                for a in attrs["accounts"]]
    doc = {"name": "HL", "kind": "auto", "accounts": accounts, "status": attrs.get("status", "ok"),
           "paused_reason": attrs.get("paused_reason")}
    finance.write_snapshot(db, "hl", {k: v for k, v in doc.items() if v is not None}, by="migration")
    log.info("migrated the last HL snapshot (%d accounts)", len(accounts))


DEFAULT_SCHEDULES = [  # name, kind, title, every_s; created once, then edited over the API
    ("revalue", "revalue", "Revalue hand-written holdings from FT prices", 3600),
    ("photos-look", "photos-look", "Look at a batch of photos", 3600),
    ("premium-bonds", "premium-bonds", "Check Premium Bonds prizes", 86400),
]


def scheduler(db: DB):
    """Queue scheduled tasks when they're due."""
    for name, kind, title, every in DEFAULT_SCHEDULES:
        try:
            tasks.schedules(db, name)
        except NotFound:
            tasks.set_schedule(db, name, kind, title, every, by="core", first_in_s=60)
    while True:
        try:
            tasks.run_due(db)
        except Exception:
            log.exception("scheduler failed")
        time.sleep(20)


def instrument(app, db: DB, publisher: Publisher):
    """Request traces and metrics for the API, and gauges for the queue, the database and publishing."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/v1/health")
    except ImportError:
        pass
    path = Path(db.path)
    telemetry.gauge("home.tasks", lambda: [(n, {"status": s}) for s, n in tasks.summary(db, 0)["counts"].items()],
                    "tasks by status")
    telemetry.gauge("home.core.db_size", lambda: [(path.stat().st_size + (path.with_suffix(".db-wal").stat().st_size
                                                   if path.with_suffix(".db-wal").exists() else 0), {})],
                    "state database size", "By")
    telemetry.gauge("home.publish.age", lambda: [(time.time() - time.mktime(time.strptime(t, "%Y-%m-%dT%H:%M:%S")),
                                                  {"publisher": name}) for name, t in publisher.last_ok.items()],
                    "seconds since each publisher last reached Home Assistant", "s")


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    telemetry.setup("core")
    args = sys.argv[1:] or ["serve"]
    db = DB(os.environ.get("CORE_DB", DATA / "core.db"))
    if args[0] == "serve":
        import uvicorn

        from .server import create_app

        admin = os.environ.get("CORE_TOKEN", "")
        if len(admin) < 24:
            raise SystemExit("CORE_TOKEN missing or too short in .env "
                             "(python -c 'import secrets; print(secrets.token_urlsafe(32))')")
        migrate_legacy(db)
        publisher, maintenance = Publisher(db), Maintenance(db, DATA / "backups")
        for target, name in ((publisher.run, "publish"), (publisher.follow, "follow"), (maintenance.run, "maintenance"),
                             (lambda: scheduler(db), "scheduler")):
            threading.Thread(target=target, daemon=True, name=name).start()
        app = create_app(db, admin, health=lambda: {"maintenance": maintenance.status, "published": publisher.last_ok},
                         on_live=publisher.live_changed)
        instrument(app, db, publisher)
        host, port = os.environ.get("CORE_BIND", "127.0.0.1"), int(os.environ.get("CORE_PORT", "8790"))
        log.info("core API on http://%s:%d (docs at /docs)", host, port)
        # log_config=None: uvicorn's own logging setup flushes every existing handler under the logging lock, which
        # deadlocks with the telemetry exporter for its 30 s timeout on each start; its loggers use ours instead.
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)
    elif args[:2] == ["token", "add"] and len(args) >= 4:
        token = db.add_principal(args[2], args[3:])
        print(f"token for '{args[2]}' (writes {', '.join(args[3:])}); shown once, keep it safe:\n{token}")
    elif args[:2] == ["token", "list"]:
        for t in db.principals():
            state = f"revoked {t['revoked_at']}" if t["revoked_at"] else f"last used {t['last_used_at'] or 'never'}"
            print(f"{t['name']:<16} {', '.join(t['scopes']):<40} {state}")
    elif args[:2] == ["token", "revoke"] and len(args) == 3:
        print("revoked" if db.revoke_principal(args[2]) else "no such token")
    elif args[0] == "get" and len(args) in (2, 3):
        try:
            out = db.get_doc(*args[1:]) if len(args) == 3 else db.list_docs(args[1])
        except NotFound:
            raise SystemExit("not found")
        print(json.dumps(out, indent=2))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
