"""Live entity state: what the services report (now playing, presence, the photo frame, ...), kept by the core and
mirrored into Home Assistant by the publisher.

Only the latest value per entity is kept, with no history or audit entry: these change often and some are large
(the photo list). A write that changes nothing is a no-op, so services can report on every loop.
"""
import json
import re

from .db import DB, NotFound, dumps, now

ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]{1,100}$")


def check(entity: str):
    if not ENTITY.match(entity):
        raise ValueError(f"bad entity id {entity!r} (like sensor.now_playing)")


def put(db: DB, entity: str, state, attributes: dict, by: str) -> bool:
    """Set an entity's state. Returns whether it changed."""
    check(entity)
    s, a = dumps(state), dumps(attributes or {})
    with db.tx():
        old = db.conn.execute("SELECT state, attrs FROM live WHERE entity=?", (entity,)).fetchone()
        if old and old["state"] == s and old["attrs"] == a:
            return False
        db.conn.execute("INSERT INTO live (entity, state, attrs, updated_by, updated_at) VALUES (?,?,?,?,?) "
                        "ON CONFLICT (entity) DO UPDATE SET state=excluded.state, attrs=excluded.attrs, "
                        "updated_by=excluded.updated_by, updated_at=excluded.updated_at", (entity, s, a, by, now()))
    return True


def _row(r) -> dict:
    return {"entity": r["entity"], "state": json.loads(r["state"]), "attributes": json.loads(r["attrs"]),
            "updated_by": r["updated_by"], "updated_at": r["updated_at"]}


def get(db: DB, entity: str) -> dict:
    r = db.q1("SELECT * FROM live WHERE entity=?", (entity,))
    if not r:
        raise NotFound(f"entity {entity}")
    return _row(r)


def listing(db: DB, attributes: bool = False) -> list[dict]:
    rows = [_row(r) for r in db.q("SELECT * FROM live ORDER BY entity")]
    return rows if attributes else [{k: v for k, v in r.items() if k != "attributes"} for r in rows]


def entities(db: DB) -> list[str]:
    return [r[0] for r in db.q("SELECT entity FROM live")]


def delete(db: DB, entity: str):
    with db.tx():
        if not db.conn.execute("DELETE FROM live WHERE entity=?", (entity,)).rowcount:
            raise NotFound(f"entity {entity}")
