"""Finance storage: each write of a source is an immutable snapshot, normalised into balances and positions.

The validated document is kept on the snapshot too, so the current state reads back exactly as it was written
(one row per source), while the normalised rows answer questions across time (a holding's units and value over a
year, an account's balance history). Prices are separate: a manual holding with units is revalued from the newest
price, without touching what was written.
"""
import json
import re

from .db import DB, NotFound, check_name, dumps, now
from .portfolio import validate

ISIN = re.compile(r"^[a-z]{2}[a-z0-9]{9}[0-9]$")
SEDOL = re.compile(r"^[0-9b-df-hj-np-tv-z]{6}[0-9]$")
POSITION_COLUMNS = {"id", "name", "status", "settles", "units", "price_p", "value", "cost", "gain", "day_change"}
BALANCE_COLUMNS = {"name", "type", "cash", "stock", "total", "interest_pct", "matures", "in_total", "holdings", "key"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "account"


def _instrument(db: DB, key: str, name: str) -> int:
    r = db.conn.execute("SELECT id FROM fin_instruments WHERE key=?", (key,)).fetchone()
    if r:
        return r["id"]
    cur = db.conn.execute("INSERT INTO fin_instruments (key, isin, sedol, name, created_at) VALUES (?,?,?,?,?)",
                          (key, key.upper() if ISIN.match(key) else None, key.upper() if SEDOL.match(key) else None,
                           name, now()))
    return cur.lastrowid


def write_snapshot(db: DB, source_id: str, data, by: str) -> dict:
    """Validate and store a source's full current state. An identical resubmission adds nothing."""
    check_name("source", source_id)
    doc = validate(data)
    body = dumps(doc)
    with db.tx():
        src = db.conn.execute("SELECT s.current_snapshot_id, n.document FROM fin_sources s "
                              "LEFT JOIN fin_snapshots n ON n.id = s.current_snapshot_id WHERE s.id=?",
                              (source_id,)).fetchone()
        if src and src["document"] == body:
            return {"source": source_id, "snapshot": src["current_snapshot_id"], "changed": False}
        ts = now()
        db.conn.execute("INSERT INTO fin_sources (id, name, kind, status, status_reason, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?) ON CONFLICT (id) DO UPDATE SET name=excluded.name, kind=excluded.kind, "
                        "status=excluded.status, status_reason=excluded.status_reason, updated_at=excluded.updated_at",
                        (source_id, doc["name"], doc["kind"], doc["status"], doc.get("paused_reason"), ts, ts))
        snap = db.conn.execute("INSERT INTO fin_snapshots (source_id, as_of, taken_at, principal, document) "
                               "VALUES (?,?,?,?,?)", (source_id, doc.get("as_of"), ts, by, body)).lastrowid
        n_pos = 0
        for acc in doc["accounts"]:
            key = acc.get("key") or _slug(acc["name"])
            db.conn.execute("INSERT INTO fin_accounts (source_id, key, name, type) VALUES (?,?,?,?) "
                            "ON CONFLICT (source_id, key) DO UPDATE SET name=excluded.name, type=excluded.type",
                            (source_id, key, acc["name"], acc["type"]))
            acc_id = db.conn.execute("SELECT id FROM fin_accounts WHERE source_id=? AND key=?",
                                     (source_id, key)).fetchone()["id"]
            extra = {k: v for k, v in acc.items() if k not in BALANCE_COLUMNS}
            db.conn.execute("INSERT INTO fin_balances VALUES (?,?,?,?,?,?,?,?,?)",
                            (snap, acc_id, acc.get("cash"), acc.get("stock"), acc["total"], acc.get("interest_pct"),
                             acc.get("matures"), int(acc.get("in_total", True) is not False), dumps(extra) if extra else None))
            for h in acc["holdings"]:
                extra = {k: v for k, v in h.items() if k not in POSITION_COLUMNS}
                db.conn.execute(
                    "INSERT INTO fin_positions (snapshot_id, account_id, instrument_id, status, settles_on, units, "
                    "price_p, value, cost, gain, day_change, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (snap, acc_id, _instrument(db, h["id"], h["name"]), h["status"], h.get("settles"), h.get("units"),
                     h.get("price_p"), h["value"], h.get("cost"), h.get("gain"), h.get("day_change"),
                     dumps(extra) if extra else None))
                n_pos += 1
        db.conn.execute("UPDATE fin_sources SET current_snapshot_id=? WHERE id=?", (snap, source_id))
        db.audit(by, "snapshot", "portfolio", source_id, {"snapshot": snap, "accounts": len(doc["accounts"]),
                                                          "positions": n_pos})  # counts only, never amounts
    return {"source": source_id, "snapshot": snap, "changed": True}


def set_status(db: DB, source_id: str, status: str, reason: str | None, by: str):
    """Pause or resume a source (e.g. HL halted) without writing a snapshot."""
    if status not in ("ok", "paused"):
        raise ValueError("status is 'ok' or 'paused'")
    with db.tx():
        n = db.conn.execute("UPDATE fin_sources SET status=?, status_reason=?, updated_at=? WHERE id=?",
                            (status, reason if status == "paused" else None, now(), source_id)).rowcount
        if not n:
            raise NotFound(f"portfolio/{source_id}")
        db.audit(by, "status", "portfolio", source_id, {"status": status, "reason": reason})


def delete_source(db: DB, source_id: str, by: str):
    """Stop showing a source. Its snapshots stay, for the record."""
    with db.tx():
        n = db.conn.execute("UPDATE fin_sources SET current_snapshot_id=NULL, updated_at=? WHERE id=? AND "
                            "current_snapshot_id IS NOT NULL", (now(), source_id)).rowcount
        if not n:
            raise NotFound(f"portfolio/{source_id}")
        db.audit(by, "delete", "portfolio", source_id)


def latest_prices(db: DB, keys: list[str]) -> dict[str, tuple[str, float]]:
    """instrument key -> (day, price in GBP) for the newest price of each."""
    if not keys:
        return {}
    marks = ",".join("?" * len(keys))
    rows = db.q(f"SELECT i.key, p.day, p.price_gbp FROM fin_prices p JOIN fin_instruments i ON i.id = p.instrument_id "
                f"WHERE i.key IN ({marks}) AND p.day = (SELECT MAX(day) FROM fin_prices WHERE instrument_id = p.instrument_id)",
                keys)
    return {r["key"]: (r["day"], r["price_gbp"]) for r in rows}


def current(db: DB) -> list[dict]:
    """Each live source as {id, updated, snapshot, data}; manual holdings with units revalued at the newest price."""
    rows = db.q("SELECT s.id, s.status, s.status_reason, s.updated_at, n.id AS snapshot, n.taken_at, n.document "
                "FROM fin_sources s JOIN fin_snapshots n ON n.id = s.current_snapshot_id ORDER BY s.id")
    out = [{"id": r["id"], "updated": r["updated_at"], "snapshot": r["snapshot"], "taken_at": r["taken_at"],
            "data": {**json.loads(r["document"]), "status": r["status"],
                     **({"paused_reason": r["status_reason"]} if r["status_reason"] else {})}} for r in rows]
    priceable = [(src, acc, h) for src in out if src["data"]["kind"] == "manual"
                 for acc in src["data"]["accounts"] for h in acc["holdings"]
                 if h.get("units") and h["status"] == "held"]
    prices = latest_prices(db, sorted({h["id"] for _, _, h in priceable}))
    for src, acc, h in priceable:
        day, gbp = prices.get(h["id"], (None, None))
        written = (src["data"].get("as_of") or src["taken_at"])[:10]
        if day is None or day < written:
            continue  # what was written is newer than any price we have
        value = round(h["units"] * gbp, 2)
        acc["total"] = round(acc["total"] + value - h["value"], 2)
        h.update(value=value, price_p=round(gbp * 100, 4), priced=day)
        if h.get("cost") is not None:
            h["gain"] = round(value - h["cost"], 2)
            h["gain_pct"] = round(h["gain"] / h["cost"] * 100, 2) if h["cost"] else None
    return out


def priceable(db: DB) -> list[dict]:
    """Manual holdings that a price would revalue: key, name and the price (GBP) implied by what was written."""
    seen = {}
    for src in current(db):
        if src["data"]["kind"] != "manual":
            continue
        for acc in src["data"]["accounts"]:
            for h in acc["holdings"]:
                if h.get("units") and h["status"] == "held":
                    seen.setdefault(h["id"], {"key": h["id"], "name": h["name"], "implied_gbp": h["value"] / h["units"]})
    return list(seen.values())


def record_price(db: DB, key: str, name: str, day: str, price_gbp: float, source: str, by: str):
    with db.tx():
        inst = _instrument(db, key, name)
        r = db.conn.execute("SELECT price_gbp FROM fin_prices WHERE instrument_id=? AND day=? AND source=?",
                            (inst, day, source)).fetchone()
        if r and abs(r["price_gbp"] - price_gbp) < 1e-9:
            return
        db.conn.execute("INSERT INTO fin_prices VALUES (?,?,?,?,?) ON CONFLICT (instrument_id, day, source) DO UPDATE "
                        "SET price_gbp=excluded.price_gbp, fetched_at=excluded.fetched_at",
                        (inst, day, price_gbp, source, now()))
        db.audit(by, "price", "price", key, {"day": day, "source": source})


def record_valuation(db: DB, day: str, total: float, by_source: dict):
    with db.tx():
        db.conn.execute("INSERT INTO fin_valuations VALUES (?,?,?,?) ON CONFLICT (day) DO UPDATE SET "
                        "total=excluded.total, by_source=excluded.by_source, computed_at=excluded.computed_at",
                        (day, total, dumps(by_source), now()))


def valuations(db: DB, limit: int = 400) -> dict[str, float]:
    return {r["day"]: r["total"] for r in reversed(db.q("SELECT day, total FROM fin_valuations ORDER BY day DESC LIMIT ?",
                                                         (limit,)))}


def snapshots(db: DB, source_id: str, limit: int = 50) -> list[dict]:
    return [dict(r) for r in db.q("SELECT id, as_of, taken_at, principal FROM fin_snapshots WHERE source_id=? "
                                  "ORDER BY id DESC LIMIT ?", (source_id, limit))]


def snapshot(db: DB, snapshot_id: int) -> dict:
    r = db.q1("SELECT id, source_id, as_of, taken_at, principal, document FROM fin_snapshots WHERE id=?", (snapshot_id,))
    if not r:
        raise NotFound(f"snapshot {snapshot_id}")
    return {**{k: r[k] for k in ("id", "source_id", "as_of", "taken_at", "principal")}, "data": json.loads(r["document"])}
