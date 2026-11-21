"""The state database: one SQLite file (WAL), versioned schema, an append-only audit log.

Design (see docs/core.md for the diagram):

- Platform: `schema_migrations` (numbered, applied in order at start), `principals` (API tokens, hashed, revocable,
  each with write scopes), `audit_log` (every change: who, when, what; its seq is also the change feed).
- General app state: `documents` (collection/key -> JSON, versioned, optimistic concurrency) and `document_versions`
  (every past version, including deletions).
- Finance (core/finance.py): sources -> immutable snapshots -> balances and positions, plus instruments, prices and
  daily valuations. A snapshot is never edited; history is the snapshots.

- Tasks (core/tasks.py): a durable queue of background work with leases, retries, cancellation, events and schedules.

Planned (as a later migration): media metadata and analysis results for the photos (the image bytes stay on disk,
named by content hash).

The SQL sticks to what SQLite and Postgres share (TEXT ISO timestamps, JSON in TEXT) so it can move later.
"""
import hashlib
import json
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")  # collection, key, source and token names

MIGRATIONS = [
    # 1: the whole first schema
    """
    CREATE TABLE principals (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, token_hash TEXT NOT NULL UNIQUE,
        scopes TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT, last_used_at TEXT);
    CREATE TABLE audit_log (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, principal TEXT NOT NULL,
        action TEXT NOT NULL, entity TEXT NOT NULL, key TEXT NOT NULL, detail TEXT);
    CREATE INDEX audit_entity ON audit_log (entity, key, seq);

    CREATE TABLE documents (
        collection TEXT NOT NULL, key TEXT NOT NULL, data TEXT NOT NULL, version INTEGER NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL,
        PRIMARY KEY (collection, key));
    CREATE TABLE document_versions (
        collection TEXT NOT NULL, key TEXT NOT NULL, version INTEGER NOT NULL, data TEXT,
        ts TEXT NOT NULL, principal TEXT NOT NULL, PRIMARY KEY (collection, key, version));

    CREATE TABLE fin_sources (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('auto', 'manual')),
        status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'paused')), status_reason TEXT,
        current_snapshot_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE fin_accounts (
        id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES fin_sources (id), key TEXT NOT NULL,
        name TEXT NOT NULL, type TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'GBP', UNIQUE (source_id, key));
    CREATE TABLE fin_instruments (
        id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, isin TEXT UNIQUE, sedol TEXT, name TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE TABLE fin_snapshots (
        id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES fin_sources (id), as_of TEXT,
        taken_at TEXT NOT NULL, principal TEXT NOT NULL, document TEXT NOT NULL);
    CREATE INDEX fin_snapshots_source ON fin_snapshots (source_id, id);
    CREATE TABLE fin_balances (
        snapshot_id INTEGER NOT NULL REFERENCES fin_snapshots (id), account_id INTEGER NOT NULL REFERENCES fin_accounts (id),
        cash REAL, stock REAL, total REAL, interest_pct REAL, matures_on TEXT, in_total INTEGER NOT NULL DEFAULT 1,
        meta TEXT, PRIMARY KEY (snapshot_id, account_id));
    CREATE TABLE fin_positions (
        id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL REFERENCES fin_snapshots (id),
        account_id INTEGER NOT NULL REFERENCES fin_accounts (id), instrument_id INTEGER NOT NULL REFERENCES fin_instruments (id),
        status TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'pending')), settles_on TEXT,
        units REAL, price_p REAL, value REAL NOT NULL, cost REAL, gain REAL, day_change REAL, meta TEXT);
    CREATE INDEX fin_positions_snapshot ON fin_positions (snapshot_id);
    CREATE INDEX fin_positions_instrument ON fin_positions (instrument_id, snapshot_id);
    CREATE TABLE fin_prices (
        instrument_id INTEGER NOT NULL REFERENCES fin_instruments (id), day TEXT NOT NULL, price_gbp REAL NOT NULL,
        source TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (instrument_id, day, source));
    CREATE TABLE fin_valuations (
        day TEXT PRIMARY KEY, total REAL NOT NULL, by_source TEXT NOT NULL, computed_at TEXT NOT NULL);

    """,
    # 2: background tasks (core/tasks.py)
    """
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, input TEXT, dedupe TEXT,
        status TEXT NOT NULL DEFAULT 'queued'
            CHECK (status IN ('queued', 'running', 'done', 'failed', 'cancelled')),
        priority INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
        run_after TEXT NOT NULL, worker TEXT, lease_until TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
        progress REAL, message TEXT, result TEXT, error TEXT, created_by TEXT NOT NULL,
        created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
    CREATE INDEX tasks_ready ON tasks (status, run_after, priority);
    CREATE UNIQUE INDEX tasks_dedupe ON tasks (dedupe) WHERE status IN ('queued', 'running');
    CREATE TABLE task_events (
        id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks (id), ts TEXT NOT NULL,
        level TEXT NOT NULL, message TEXT NOT NULL);
    CREATE INDEX task_events_task ON task_events (task_id, id);
    CREATE TABLE schedules (
        name TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, input TEXT, every_s INTEGER NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1, next_run TEXT NOT NULL, last_task_id INTEGER);
    """,
]


class NotFound(KeyError):
    pass


class Conflict(RuntimeError):
    """The document changed since the version the writer read."""


class Forbidden(PermissionError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_name(kind: str, value: str):
    if not isinstance(value, str) or not NAME.match(value):
        raise ValueError(f"bad {kind} {value!r}: lowercase letters, digits, '_', '-', '.'; up to 64")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


class Principal:
    """Who's calling. Every principal reads everything; writes are limited to its scope patterns, matched against
    "<area>/<key>", e.g. "doc/settings/*", "portfolio/hsbc*", or "*" for the services' admin token."""

    def __init__(self, name: str, scopes: list[str]):
        self.name, self.scopes = name, scopes

    def may(self, target: str) -> bool:
        return any(fnmatchcase(target, p) for p in self.scopes)

    def check(self, target: str):
        if not self.may(target):
            raise Forbidden(f"token '{self.name}' may not write {target}")


class DB:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()  # one connection, used by one thread at a time
        self.changed = threading.Condition(self.lock)  # notified on every audit entry (the change feed)
        self._depth = 0
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self._migrate()

    # -- plumbing ----------------------------------------------------------
    def _migrate(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        done = {r[0] for r in self.conn.execute("SELECT version FROM schema_migrations")}
        for version, sql in enumerate(MIGRATIONS, start=1):
            if version in done:
                continue
            with self.tx():
                for stmt in (s.strip() for s in sql.split(";")):
                    if stmt:
                        self.conn.execute(stmt)
                self.conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, now()))

    @property
    def schema_version(self) -> int:
        return self.conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]

    @contextmanager
    def tx(self):
        """A write transaction (nests: only the outermost commits). Notifies change-feed waiters on commit."""
        with self.lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                self.conn.execute("COMMIT")
                self.changed.notify_all()

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def q1(self, sql: str, args=()):
        with self.lock:
            return self.conn.execute(sql, args).fetchone()

    def audit(self, principal: str, action: str, entity: str, key: str, detail=None) -> int:
        """Append to the audit log (inside the caller's transaction). Returns the change's seq."""
        cur = self.conn.execute("INSERT INTO audit_log (ts, principal, action, entity, key, detail) VALUES (?,?,?,?,?,?)",
                                (now(), principal, action, entity, key, None if detail is None else dumps(detail)))
        return cur.lastrowid

    # -- the change feed -----------------------------------------------------
    def last_seq(self) -> int:
        return self.q1("SELECT COALESCE(MAX(seq), 0) FROM audit_log")[0]

    def changes_since(self, seq: int, wait: float = 0, limit: int = 500) -> list[dict]:
        """Audit entries after `seq` (without their detail), waiting up to `wait` s for one if there are none."""
        sql = "SELECT seq, ts, principal, action, entity, key FROM audit_log WHERE seq > ? ORDER BY seq LIMIT ?"
        with self.changed:
            rows = self.conn.execute(sql, (seq, limit)).fetchall()
            if not rows and wait > 0:
                self.changed.wait_for(lambda: self.last_seq() > seq, timeout=wait)
                rows = self.conn.execute(sql, (seq, limit)).fetchall()
        return [dict(r) for r in rows]

    def audit_trail(self, entity: str | None = None, key: str | None = None, limit: int = 100) -> list[dict]:
        where, args = [], []
        if entity:
            where.append("entity = ?"), args.append(entity)
        if key:
            where.append("key = ?"), args.append(key)
        rows = self.q(f"SELECT * FROM audit_log {'WHERE ' + ' AND '.join(where) if where else ''} "
                      "ORDER BY seq DESC LIMIT ?", (*args, limit))
        return [{**dict(r), "detail": json.loads(r["detail"]) if r["detail"] else None} for r in rows]

    # -- principals (API tokens) ----------------------------------------------
    def add_principal(self, name: str, scopes: list[str]) -> str:
        """A new token; returned once, only its hash is kept."""
        check_name("token name", name)
        token = "core_" + secrets.token_urlsafe(32)
        with self.tx():
            if self.conn.execute("SELECT 1 FROM principals WHERE name=? AND revoked_at IS NULL", (name,)).fetchone():
                raise ValueError(f"a token named '{name}' already exists; revoke it first")
            self.conn.execute("DELETE FROM principals WHERE name=?", (name,))  # a revoked one of the same name
            self.conn.execute("INSERT INTO principals (name, token_hash, scopes, created_at) VALUES (?,?,?,?)",
                              (name, _hash(token), dumps(scopes), now()))
            self.audit("admin", "token.add", "principal", name, {"scopes": scopes})
        return token

    def revoke_principal(self, name: str) -> bool:
        with self.tx():
            n = self.conn.execute("UPDATE principals SET revoked_at=? WHERE name=? AND revoked_at IS NULL",
                                  (now(), name)).rowcount
            if n:
                self.audit("admin", "token.revoke", "principal", name)
        return n > 0

    def principals(self) -> list[dict]:
        return [{**dict(r), "scopes": json.loads(r["scopes"])}
                for r in self.q("SELECT name, scopes, created_at, revoked_at, last_used_at FROM principals ORDER BY name")]

    def authenticate(self, token: str, admin_token: str = "") -> Principal | None:
        if not token:
            return None
        if admin_token and secrets.compare_digest(token, admin_token):
            return Principal("services", ["*"])
        r = self.q1("SELECT name, scopes, last_used_at FROM principals WHERE token_hash=? AND revoked_at IS NULL",
                    (_hash(token),))
        if not r:
            return None
        if not r["last_used_at"] or r["last_used_at"][:13] != now()[:13]:  # at most one write an hour per token
            with self.lock:
                self.conn.execute("UPDATE principals SET last_used_at=? WHERE name=?", (now(), r["name"]))
        return Principal(r["name"], json.loads(r["scopes"]))

    # -- general documents -----------------------------------------------------
    @staticmethod
    def _doc(r) -> dict:
        return {"collection": r["collection"], "key": r["key"], "data": json.loads(r["data"]), "version": r["version"],
                "created_at": r["created_at"], "updated_at": r["updated_at"], "updated_by": r["updated_by"]}

    def get_doc(self, collection: str, key: str) -> dict:
        r = self.q1("SELECT * FROM documents WHERE collection=? AND key=?", (collection, key))
        if not r:
            raise NotFound(f"{collection}/{key}")
        return self._doc(r)

    def list_docs(self, collection: str) -> list[dict]:
        return [self._doc(r) for r in self.q("SELECT * FROM documents WHERE collection=? ORDER BY key", (collection,))]

    def collections(self) -> dict[str, int]:
        return {r[0]: r[1] for r in self.q("SELECT collection, COUNT(*) FROM documents GROUP BY collection ORDER BY 1")}

    def put_doc(self, collection: str, key: str, data, by: str, if_version: int | None = None) -> dict:
        check_name("collection", collection)
        check_name("key", key)
        body = dumps(data)
        with self.tx():
            r = self.conn.execute("SELECT version, data, created_at FROM documents WHERE collection=? AND key=?",
                                  (collection, key)).fetchone()
            current = r["version"] if r else 0
            if if_version is not None and if_version != current:
                raise Conflict(f"{collection}/{key} is at version {current}, not {if_version}")
            if r and r["data"] == body:  # unchanged: no new version, nothing in the feed
                return self.get_doc(collection, key)
            version, ts = current + 1, now()
            self.conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?) ON CONFLICT (collection, key) DO UPDATE SET "
                              "data=excluded.data, version=excluded.version, updated_at=excluded.updated_at, "
                              "updated_by=excluded.updated_by",
                              (collection, key, body, version, r["created_at"] if r else ts, ts, by))
            self.conn.execute("INSERT INTO document_versions VALUES (?,?,?,?,?,?)", (collection, key, version, body, ts, by))
            self.audit(by, "put", "doc", f"{collection}/{key}", {"version": version})
        return self.get_doc(collection, key)

    def delete_doc(self, collection: str, key: str, by: str, if_version: int | None = None):
        with self.tx():
            r = self.conn.execute("SELECT version FROM documents WHERE collection=? AND key=?", (collection, key)).fetchone()
            if not r:
                raise NotFound(f"{collection}/{key}")
            if if_version is not None and if_version != r["version"]:
                raise Conflict(f"{collection}/{key} is at version {r['version']}, not {if_version}")
            self.conn.execute("DELETE FROM documents WHERE collection=? AND key=?", (collection, key))
            self.conn.execute("INSERT INTO document_versions VALUES (?,?,?,?,?,?)",
                              (collection, key, r["version"] + 1, None, now(), by))
            self.audit(by, "delete", "doc", f"{collection}/{key}", {"version": r["version"] + 1})

    def doc_versions(self, collection: str, key: str, limit: int = 50) -> list[dict]:
        rows = self.q("SELECT version, data, ts, principal FROM document_versions WHERE collection=? AND key=? "
                      "ORDER BY version DESC LIMIT ?", (collection, key, limit))
        return [{**dict(r), "data": json.loads(r["data"]) if r["data"] else None} for r in rows]
