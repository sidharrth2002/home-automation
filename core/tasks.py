"""Background tasks: a durable queue in the state database, worked by `python -m core.worker` over the API.

A task is claimed with a lease that the worker renews while it runs; if the worker dies, the lease runs out and the
task is claimed again (up to max_attempts, with exponential backoff between failures). Cancelling sets a flag the
worker sees on its next heartbeat. Progress and log lines go to `task_events`. Schedules enqueue a task every
`every_s` seconds, skipping a turn while the previous one is still queued or running (the dedupe key).
"""
import json
from datetime import datetime, timedelta, timezone

from .db import DB, NotFound, check_name, dumps, now

LEASE_S = 90
DONE = ("done", "failed", "cancelled")
EVENTS_KEPT = 500  # per task


def _at(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _task(r, events: list | None = None) -> dict:
    t = dict(r)
    for k in ("input", "result"):
        t[k] = json.loads(t[k]) if t[k] else None
    t["cancel_requested"] = bool(t["cancel_requested"])
    if events is not None:
        t["events"] = events
    return t


def create(db: DB, kind: str, title: str, input=None, by: str = "services", priority: int = 0, delay_s: float = 0,
           max_attempts: int = 3, dedupe: str | None = None) -> dict | None:
    """Queue a task. With `dedupe`, nothing is queued while one with the same key is queued or running."""
    check_name("task kind", kind)
    with db.tx():
        if dedupe and db.conn.execute("SELECT 1 FROM tasks WHERE dedupe=? AND status IN ('queued', 'running')",
                                      (dedupe,)).fetchone():
            return None
        ts = now()
        tid = db.conn.execute(
            "INSERT INTO tasks (kind, title, input, dedupe, priority, max_attempts, run_after, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (kind, title[:200], None if input is None else dumps(input), dedupe, priority, max_attempts,
             _at(delay_s), by, ts)).lastrowid
        db.audit(by, "create", "task", str(tid), {"kind": kind})
    return get(db, tid)


def get(db: DB, task_id: int, events: int = 0) -> dict:
    r = db.q1("SELECT * FROM tasks WHERE id=?", (task_id,))
    if not r:
        raise NotFound(f"task {task_id}")
    ev = None
    if events:
        ev = [dict(e) for e in reversed(db.q("SELECT ts, level, message FROM task_events WHERE task_id=? "
                                             "ORDER BY id DESC LIMIT ?", (task_id, events)))]
    return _task(r, ev)


def listing(db: DB, status: str | None = None, limit: int = 50) -> list[dict]:
    if status:
        rows = db.q("SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
    else:
        rows = db.q("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
    return [_task(r) for r in rows]


def claim(db: DB, kinds: list[str], worker: str) -> dict | None:
    """The next ready task of these kinds, leased to `worker`. A running task whose lease ran out counts as ready."""
    if not kinds:
        return None
    ts, marks = now(), ",".join("?" * len(kinds))
    with db.tx():
        r = db.conn.execute(
            f"SELECT * FROM tasks WHERE kind IN ({marks}) AND ((status='queued' AND run_after <= ?) OR "
            f"(status='running' AND lease_until < ?)) ORDER BY priority DESC, run_after, id LIMIT 1",
            (*kinds, ts, ts)).fetchone()
        if not r:
            return None
        if r["status"] == "running" and r["attempts"] >= r["max_attempts"]:  # died on its last try
            _end(db, r["id"], "failed", error="the worker stopped responding")
            return None
        db.conn.execute("UPDATE tasks SET status='running', attempts=attempts+1, worker=?, lease_until=?, "
                        "started_at=COALESCE(started_at, ?), message=NULL WHERE id=?", (worker, _at(LEASE_S), ts, r["id"]))
        _event(db, r["id"], "info", f"started by {worker} (attempt {r['attempts'] + 1} of {r['max_attempts']})")
        db.audit(worker, "start", "task", str(r["id"]), {"kind": r["kind"]})
    return get(db, r["id"])


def heartbeat(db: DB, task_id: int, worker: str, progress: float | None = None, message: str | None = None,
              events: list[str] | None = None) -> dict:
    """Renew the lease, record progress and log lines. Returns {"cancel": bool}: the worker should stop if true."""
    with db.tx():
        r = db.conn.execute("SELECT status, worker, cancel_requested FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not r:
            raise NotFound(f"task {task_id}")
        if r["status"] != "running" or r["worker"] != worker:
            return {"cancel": True}  # it was taken over or finished elsewhere
        db.conn.execute("UPDATE tasks SET lease_until=?, progress=COALESCE(?, progress), message=COALESCE(?, message) "
                        "WHERE id=?", (_at(LEASE_S), progress, message, task_id))
        for line in events or []:
            _event(db, task_id, "info", line)
    return {"cancel": bool(r["cancel_requested"])}


def finish(db: DB, task_id: int, worker: str, result=None, error: str | None = None, cancelled: bool = False):
    """The worker is done with it: success, cancelled, or a failure (retried with backoff while attempts remain)."""
    with db.tx():
        r = db.conn.execute("SELECT status, worker, attempts, max_attempts FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not r:
            raise NotFound(f"task {task_id}")
        if r["status"] != "running" or r["worker"] != worker:
            return
        if cancelled:
            _end(db, task_id, "cancelled", by=worker)
        elif error is None:
            _end(db, task_id, "done", result=result, by=worker)
        elif r["attempts"] < r["max_attempts"]:
            retry_s = 60 * 2 ** (r["attempts"] - 1)
            db.conn.execute("UPDATE tasks SET status='queued', worker=NULL, lease_until=NULL, error=?, run_after=? "
                            "WHERE id=?", (error[:4000], _at(retry_s), task_id))
            _event(db, task_id, "error", f"{error[:500]} (retrying in {retry_s // 60} min)")
            db.audit(worker, "retry", "task", str(task_id))
        else:
            _end(db, task_id, "failed", error=error, by=worker)


def cancel(db: DB, task_id: int, by: str) -> dict:
    """A queued task is cancelled at once; a running one when its worker next checks in."""
    with db.tx():
        r = db.conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not r:
            raise NotFound(f"task {task_id}")
        if r["status"] == "queued":
            _end(db, task_id, "cancelled", by=by)
        elif r["status"] == "running":
            db.conn.execute("UPDATE tasks SET cancel_requested=1 WHERE id=?", (task_id,))
            _event(db, task_id, "info", f"cancel requested by {by}")
            db.audit(by, "cancel", "task", str(task_id))
    return get(db, task_id)


def _end(db: DB, task_id: int, status: str, result=None, error: str | None = None, by: str = "core"):
    db.conn.execute("UPDATE tasks SET status=?, result=?, error=?, worker=NULL, lease_until=NULL, finished_at=?, "
                    "progress=CASE WHEN ?='done' THEN 1 ELSE progress END WHERE id=?",
                    (status, None if result is None else dumps(result), error[:4000] if error else None, now(),
                     status, task_id))
    _event(db, task_id, "error" if status == "failed" else "info", status + (f": {error[:500]}" if error else ""))
    db.audit(by, status, "task", str(task_id))


def _event(db: DB, task_id: int, level: str, message: str):
    db.conn.execute("INSERT INTO task_events (task_id, ts, level, message) VALUES (?,?,?,?)",
                    (task_id, now(), level, message[:2000]))
    db.conn.execute("DELETE FROM task_events WHERE task_id=? AND id <= (SELECT id FROM task_events WHERE task_id=? "
                    "ORDER BY id DESC LIMIT 1 OFFSET ?)", (task_id, task_id, EVENTS_KEPT))


# -- schedules ---------------------------------------------------------------------
def set_schedule(db: DB, name: str, kind: str, title: str, every_s: int, input=None, enabled: bool = True,
                 by: str = "services", first_in_s: float = 0) -> dict:
    check_name("schedule", name)
    if every_s < 60:
        raise ValueError("every_s is at least 60")
    with db.tx():
        db.conn.execute("INSERT INTO schedules (name, kind, title, input, every_s, enabled, next_run) VALUES (?,?,?,?,?,?,?) "
                        "ON CONFLICT (name) DO UPDATE SET kind=excluded.kind, title=excluded.title, input=excluded.input, "
                        "every_s=excluded.every_s, enabled=excluded.enabled",
                        (name, kind, title, None if input is None else dumps(input), every_s, int(enabled),
                         _at(first_in_s)))
        db.audit(by, "schedule", "schedule", name, {"kind": kind, "every_s": every_s, "enabled": enabled})
    return schedules(db, name)[0]


def schedules(db: DB, name: str | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM schedules WHERE name=?", (name,)) if name else db.q("SELECT * FROM schedules ORDER BY name")
    if name and not rows:
        raise NotFound(f"schedule {name}")
    return [{**dict(r), "input": json.loads(r["input"]) if r["input"] else None, "enabled": bool(r["enabled"])}
            for r in rows]


def run_due(db: DB) -> int:
    """Queue a task for every enabled schedule that's due. Returns how many were queued."""
    queued = 0
    for s in db.q("SELECT * FROM schedules WHERE enabled=1 AND next_run <= ?", (now(),)):
        t = create(db, s["kind"], s["title"], json.loads(s["input"]) if s["input"] else None, by=f"schedule:{s['name']}",
                   dedupe=f"schedule:{s['name']}")
        with db.tx():
            db.conn.execute("UPDATE schedules SET next_run=?, last_task_id=COALESCE(?, last_task_id) WHERE name=?",
                            (_at(s["every_s"]), t["id"] if t else None, s["name"]))
        queued += t is not None
    return queued


def summary(db: DB, limit: int = 8) -> dict:
    """What the Hub shows: counts and the latest few tasks (no inputs or results, which may be long or private)."""
    counts = {r[0]: r[1] for r in db.q("SELECT status, COUNT(*) FROM tasks GROUP BY status")}
    recent = db.q("SELECT id, kind, title, status, progress, message, created_by, created_at, started_at, finished_at "
                  "FROM tasks WHERE created_by NOT LIKE 'schedule:%' OR status IN ('running', 'failed') "
                  "ORDER BY id DESC LIMIT ?", (limit,))
    return {"counts": counts, "recent": [dict(r) for r in recent]}
