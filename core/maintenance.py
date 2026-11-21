"""Housekeeping for the state database, on its own thread: a daily backup (the last BACKUPS_KEPT are kept), an
integrity check, and SQLite's optimise and WAL checkpoint. Results go in `status`, which /v1/health reports.
"""
import logging
import sqlite3
import time
from datetime import date
from pathlib import Path

from .db import DB, now

log = logging.getLogger("core.maintenance")
EVERY_S = 3600
BACKUPS_KEPT = 14


class Maintenance:
    def __init__(self, db: DB, backups: Path):
        self.db, self.backups = db, backups
        self.status = {"last_run": None, "last_backup": None, "integrity": None}

    def backup(self) -> Path | None:
        self.backups.mkdir(parents=True, exist_ok=True)
        out = self.backups / f"core-{date.today().isoformat()}.db"
        if out.exists():
            return None  # one a day
        tmp = out.with_suffix(".tmp")
        dest = sqlite3.connect(str(tmp))
        try:
            with self.db.lock:
                self.db.conn.backup(dest)
        finally:
            dest.close()
        tmp.rename(out)
        for old in sorted(self.backups.glob("core-*.db"))[:-BACKUPS_KEPT]:
            old.unlink()
        return out

    def run_once(self):
        made = self.backup()
        if made:
            self.status["last_backup"] = made.name
            log.info("backed up the state database")
        with self.db.lock:
            result = self.db.conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.db.conn.execute("PRAGMA optimize")
            self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.status.update(integrity=result, last_run=now())
        if result != "ok":
            log.error("state database integrity check failed: %s", result)

    def run(self):
        while True:
            try:
                self.run_once()
            except Exception:
                log.exception("maintenance failed")
            time.sleep(EVERY_S)
