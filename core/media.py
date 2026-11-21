"""Media: a library's metadata (one row per item, from a `source` such as onedrive), what each analyser found in
each item, and what was shown when.

The files themselves stay where they are (OneDrive); only metadata and results live here. Analysers run
progressively (a background task looks at a batch an hour) and their results are kept per analyser, so a new kind
of analysis can be added later without touching the old ones. An item whose file changes (a different size) loses
its results and is looked at again. Selection policy (what's worth a look, what gets shown) is the client's.
"""
import json

from .db import DB, check_name, dumps, now

FIELDS = ("name", "folder", "taken_at", "camera", "focal_mm", "width", "height", "bytes")
PAGE = 5000


def _id(db: DB, source: str, source_id: str) -> int | None:
    r = db.conn.execute("SELECT id FROM media WHERE source=? AND source_id=?", (source, source_id)).fetchone()
    return r[0] if r else None


def upsert(db: DB, source: str, items: list[dict], deleted: list[str] = (), cursor: dict | None = None,
           by: str = "services") -> int:
    """Add or update items (each {"id", name, ...FIELDS}), remove deleted ones, and save the listing cursor, in one
    transaction. Returns how many changed."""
    check_name("media source", source)
    changed, ts = 0, now()
    cols = ", ".join(FIELDS)
    with db.tx():
        for it in items:
            sid, vals = str(it["id"]), tuple(it.get(f) for f in FIELDS)
            old = db.conn.execute(f"SELECT id, {cols} FROM media WHERE source=? AND source_id=?", (source, sid)).fetchone()
            if old is None:
                db.conn.execute(f"INSERT INTO media (source, source_id, {cols}, updated_at) VALUES (?,?,{','.join('?' * len(FIELDS))},?)",
                                (source, sid, *vals, ts))
            elif tuple(old[f] for f in FIELDS) != vals:
                db.conn.execute(f"UPDATE media SET {', '.join(f'{f}=?' for f in FIELDS)}, updated_at=? WHERE id=?",
                                (*vals, ts, old["id"]))
                if old["bytes"] != it.get("bytes"):  # a different file: what was found in the old one no longer holds
                    db.conn.execute("DELETE FROM media_analysis WHERE media_id=?", (old["id"],))
            else:
                continue
            changed += 1
        gone = 0
        for sid in deleted:
            gone += db.conn.execute("DELETE FROM media WHERE source=? AND source_id=?", (source, str(sid))).rowcount
        if cursor:
            db.conn.execute("INSERT INTO media_cursors (source, key, value) VALUES (?,?,?) ON CONFLICT (source, key) "
                            "DO UPDATE SET value=excluded.value", (source, cursor["key"], cursor["value"]))
        if changed or gone:
            db.audit(by, "index", "media", source, {"changed": changed, "deleted": gone})
    return changed + gone


def record_analysis(db: DB, source: str, analyser: str, results: dict[str, dict], by: str = "services") -> int:
    """Results by source id. Items no longer in the library are skipped. Returns how many were recorded."""
    check_name("analyser", analyser)
    ts, n = now(), 0
    with db.tx():
        for sid, result in results.items():
            mid = _id(db, source, str(sid))
            if mid is None:
                continue
            db.conn.execute("INSERT INTO media_analysis (media_id, analyser, result, analysed_at) VALUES (?,?,?,?) "
                            "ON CONFLICT (media_id, analyser) DO UPDATE SET result=excluded.result, "
                            "analysed_at=excluded.analysed_at", (mid, analyser, dumps(result), ts))
            n += 1
        if n:
            db.audit(by, "analyse", "media", source, {"analyser": analyser, "count": n})
    return n


def record_shown(db: DB, source: str, source_ids: list[str], by: str = "services") -> int:
    """A set went on screen."""
    ts, n = now(), 0
    with db.tx():
        for sid in source_ids:
            mid = _id(db, source, str(sid))
            if mid is not None:
                n += db.conn.execute("INSERT OR IGNORE INTO media_shown (shown_at, media_id) VALUES (?,?)",
                                     (ts, mid)).rowcount
        db.audit(by, "show", "media", source, {"count": n})
    return n


def items(db: DB, source: str, analyser: str | None = None, analysed: bool | None = None, after: str = "",
          limit: int = PAGE) -> tuple[list[dict], str | None]:
    """A page of items in source-id order, each with `analysis` (that analyser's result, or None) when one is named;
    `analysed` keeps only those with (True) or without (False) a result. Returns (items, the next page's `after`)."""
    cols = ", ".join(f"m.{f}" for f in FIELDS)
    join, where, args = "", ["m.source = ?", "m.source_id > ?"], [source, after]
    if analyser:
        join = "LEFT JOIN media_analysis a ON a.media_id = m.id AND a.analyser = ?"
        args.insert(0, analyser)
        if analysed is not None:
            where.append("a.result IS NOT NULL" if analysed else "a.result IS NULL")
    rows = db.q(f"SELECT m.source_id, {cols}{', a.result' if analyser else ''} FROM media m {join} "
                f"WHERE {' AND '.join(where)} ORDER BY m.source_id LIMIT ?", (*args, limit))
    out = []
    for r in rows:
        it = {"id": r["source_id"], **{f: r[f] for f in FIELDS}}
        if analyser:
            it["analysis"] = json.loads(r["result"]) if r["result"] else None
        out.append(it)
    return out, (out[-1]["id"] if len(out) == limit else None)


def summary(db: DB, source: str) -> dict:
    """Counts, the listing cursors, and the set shown last."""
    last = db.q1("SELECT MAX(s.shown_at) FROM media_shown s JOIN media m ON m.id = s.media_id WHERE m.source=?",
                 (source,))[0]
    return {
        "items": db.q1("SELECT COUNT(*) FROM media WHERE source=?", (source,))[0],
        "analysed": {r[0]: r[1] for r in db.q("SELECT a.analyser, COUNT(*) FROM media_analysis a JOIN media m "
                                              "ON m.id = a.media_id WHERE m.source=? GROUP BY a.analyser", (source,))},
        "cursors": {r[0]: r[1] for r in db.q("SELECT key, value FROM media_cursors WHERE source=?", (source,))},
        "last_shown": [r[0] for r in db.q("SELECT m.source_id FROM media_shown s JOIN media m ON m.id = s.media_id "
                                          "WHERE m.source=? AND s.shown_at=?", (source, last))] if last else [],
        "last_shown_at": last,
    }
