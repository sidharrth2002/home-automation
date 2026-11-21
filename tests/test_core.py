"""The core state service: database, API, portfolio merge and publishing, on a throwaway database (made-up numbers).

Run: .venv/bin/python -m tests.test_core
"""
import tempfile
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from core import finance, portfolio
from core.db import DB
from core.maintenance import Maintenance
from core.publish import Publisher, publish_investments
from core.server import create_app

ADMIN = "admin-token-for-tests-0123456789"
HL = {"name": "HL", "kind": "auto", "accounts": [
    {"name": "ISA", "type": "isa", "cash": 10.0, "holdings": [
        {"name": "World Fund", "id": "b0000001", "value": 600.0, "cost": 500.0, "gain": 100.0, "day_change": 6.0},
        {"name": "Bond Fund", "id": "b0000002", "value": 300.0, "cost": 310.0, "gain": -10.0, "day_change": -1.0}]}]}
BANK = {"name": "Bank", "as_of": "2026-01-10", "accounts": [
    {"name": "GIA", "type": "gia", "cash": 50.0, "holdings": [
        {"name": "US Index Inc", "id": "gb00b0000003", "value": 200.0, "units": 100.0, "cost": 200.0},
        {"name": "Pending Buy", "value": 100.0, "status": "pending", "settles": "2026-01-12"}]},
    {"name": "Saver", "type": "savings", "cash": 400.0, "interest_pct": 5.0, "matures": "2027-01-01"},
    {"name": "Current", "type": "current", "cash": 90.0, "in_total": False}]}


def expect(status, response):
    assert response.status_code == status, (status, response.status_code, response.text)
    return response.json()


def test_api(tmp: Path):
    db = DB(tmp / "core.db")
    api = TestClient(create_app(db, ADMIN))
    admin = {"Authorization": f"Bearer {ADMIN}"}

    expect(200, api.get("/v1/health"))
    expect(401, api.get("/v1/state"))
    expect(401, api.get("/v1/state", headers={"Authorization": "Bearer nope"}))

    # documents: versions, optimistic concurrency, patch, history, delete
    d = expect(200, api.put("/v1/state/settings/tv", json={"apps": ["netflix"]}, headers=admin))
    assert d["version"] == 1 and d["updated_by"] == "services"
    assert expect(200, api.put("/v1/state/settings/tv", json={"apps": ["netflix"]}, headers=admin))["version"] == 1
    expect(409, api.put("/v1/state/settings/tv", json={}, headers={**admin, "If-Match": "7"}))
    d = expect(200, api.patch("/v1/state/settings/tv", json={"dim": True}, headers=admin))
    assert d["data"] == {"apps": ["netflix"], "dim": True} and d["version"] == 2
    d = expect(200, api.patch("/v1/state/settings/tv", json={"dim": None}, headers=admin))
    assert d["data"] == {"apps": ["netflix"]}
    assert [v["version"] for v in expect(200, api.get("/v1/state/settings/tv/versions", headers=admin))["items"]] == [3, 2, 1]
    expect(400, api.put("/v1/state/Bad Name/x", json={}, headers=admin))
    expect(200, api.delete("/v1/state/settings/tv", headers=admin))
    expect(404, api.get("/v1/state/settings/tv", headers=admin))

    # scoped tokens: read everything, write only what the scopes allow
    tok = db.add_principal("finance", ["portfolio/bank*", "doc/finance/*"])
    fin = {"Authorization": f"Bearer {tok}"}
    assert expect(200, api.get("/v1/me", headers=fin))["writes"] == ["portfolio/bank*", "doc/finance/*"]
    expect(200, api.put("/v1/state/finance/plan", json={"note": "x"}, headers=fin))
    expect(403, api.put("/v1/state/settings/x", json={}, headers=fin))
    expect(403, api.put("/v1/portfolio/hl", json=HL, headers=fin))

    # portfolio: snapshots, validation, merge
    expect(200, api.put("/v1/portfolio/hl", json=HL, headers=admin))
    r = expect(200, api.put("/v1/portfolio/bank", json=BANK, headers=fin))
    assert r["changed"]
    assert not expect(200, api.put("/v1/portfolio/bank", json=BANK, headers=fin))["changed"], "identical: no snapshot"
    bad = {**BANK, "accounts": [{"name": "X", "type": "nope"}]}
    expect(422, api.put("/v1/portfolio/bank", json=bad, headers=fin))
    expect(422, api.put("/v1/portfolio/bank", json={"name": "B", "accounts": [{"name": "A", "holdings": [{"name": "h"}]}]},
                        headers=fin))
    p = expect(200, api.get("/v1/portfolio", headers=fin))
    s = p["summary"]
    # HL 10+600+300 = 910; bank GIA 50+200+100 = 350, saver 400; current account left out
    assert p["total"] == 1660.0, p["total"]
    assert s["cash"] == 60.0 and s["day_change"] == 5.0  # uninvested cash only; the saver is its own row
    assert s["invested_cost"] == 1010.0 and s["gain"] == 90.0, (s["invested_cost"], s["gain"])
    assert {a["name"] for a in s["accounts"]} >= {"HL ISA", "Bank GIA", "Bank Saver", "Bank Current"}
    assert next(a for a in s["accounts"] if a["name"] == "Bank Current")["in_total"] is False
    pending = next(h for h in s["holdings"] if h["name"] == "Pending Buy")
    assert pending["status"] == "pending" and pending["sedol"] == "pending-buy" and pending["source"] == "bank"

    # a price revalues a manual holding with units, without touching what was written
    expect(200, api.put("/v1/prices/GB00B0000003", json={"day": "2026-01-11", "price_gbp": 2.5, "source": "test"},
                        headers=admin))
    expect(403, api.put("/v1/prices/gb00b0000003", json={"day": "2026-01-11", "price_gbp": 2.5}, headers=fin))
    bank = expect(200, api.get("/v1/portfolio/bank", headers=fin))
    us = bank["data"]["accounts"][0]["holdings"][0]
    assert us["value"] == 250.0 and us["priced"] == "2026-01-11" and us["gain"] == 50.0
    assert bank["data"]["accounts"][0]["total"] == 400.0
    snap = expect(200, api.get(f"/v1/portfolio/bank/snapshots/{bank['snapshot']}", headers=fin))
    assert snap["data"]["accounts"][0]["holdings"][0]["value"] == 200.0, "the snapshot keeps what was written"
    # an older price than the snapshot doesn't override it
    finance.record_price(db, "gb00b0000003", "US", "2026-01-01", 9.0, "test", "t")
    assert expect(200, api.get("/v1/portfolio/bank", headers=fin))["data"]["accounts"][0]["holdings"][0]["value"] == 250.0

    # pause / resume, delete keeps history
    expect(200, api.patch("/v1/portfolio/hl", json={"status": "paused", "paused_reason": "halted"}, headers=admin))
    s = expect(200, api.get("/v1/portfolio", headers=admin))["summary"]
    assert s["status"] == "paused" and "HL: halted" in s["paused_reason"]
    expect(200, api.patch("/v1/portfolio/hl", json={"status": "ok"}, headers=admin))
    expect(200, api.delete("/v1/portfolio/bank", headers=fin))
    assert [x["id"] for x in expect(200, api.get("/v1/portfolio", headers=admin))["sources"]] == ["hl"]
    assert expect(200, api.get("/v1/portfolio/bank/snapshots", headers=admin))["items"]
    expect(200, api.put("/v1/portfolio/bank", json=BANK, headers=fin))  # back again

    # the audit log and change feed
    trail = expect(200, api.get("/v1/audit?entity=portfolio&key=bank", headers=admin))["items"]
    assert trail[0]["action"] == "snapshot" and trail[0]["principal"] == "finance"
    assert "value" not in str(trail), "the audit log holds counts, not amounts"
    feed = expect(200, api.get("/v1/changes?since=0", headers=admin))
    assert feed["seq"] == db.last_seq() and feed["changes"]
    t0 = time.monotonic()
    assert expect(200, api.get(f"/v1/changes?since={feed['seq']}&wait=0.3", headers=admin))["changes"] == []
    assert time.monotonic() - t0 >= 0.25

    # revoked tokens stop working
    assert db.revoke_principal("finance")
    expect(401, api.get("/v1/me", headers=fin))
    print("core API OK")
    return db


def test_publish(db: DB):
    posted = []
    publish_investments(db, post=lambda e, s, a: posted.append((e, s, a)))
    entity, state, attrs = posted[-1]
    assert entity == "sensor.investments" and state == 1710.0, state  # the bank fund revalued at 2.5
    assert {"accounts", "holdings", "history", "sources", "day_change", "gain_pct", "status"} <= set(attrs)
    assert attrs["history"][-1][1] == 1710.0 and finance.valuations(db)  # today's total is recorded

    # the publisher follows the feed: a write leads to a publish soon after
    pub = Publisher(db, post=lambda e, s, a: posted.append((e, s, a)))
    pub.dirty.clear()
    threading.Thread(target=pub.run, daemon=True).start()
    threading.Thread(target=pub.follow, daemon=True).start()
    time.sleep(0.3)
    n = len(posted)
    finance.write_snapshot(db, "cash", {"name": "Cash", "accounts": [{"name": "Pot", "cash": 5.0}]}, by="test")
    deadline = time.monotonic() + 5
    while len(posted) == n and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(posted) > n and posted[-1][1] == 1715.0, posted[-1][1]
    print("publish OK")


def test_reopen_and_maintenance(tmp: Path):
    db = DB(tmp / "core.db")  # migrations are idempotent
    assert db.schema_version == 1 and finance.current(db)
    m = Maintenance(db, tmp / "backups")
    m.run_once()
    m.run_once()  # one backup a day
    assert m.status["integrity"] == "ok" and len(list((tmp / "backups").glob("core-*.db"))) == 1
    backup = DB(next((tmp / "backups").glob("core-*.db")))
    assert [s["id"] for s in finance.current(backup)] == [s["id"] for s in finance.current(db)]
    print("maintenance OK")


def test_validate():
    doc = portfolio.validate({"name": "X", "accounts": [{"name": "A", "cash": 1, "holdings": [{"name": "Fund A", "value": 2}]}]})
    acc = doc["accounts"][0]
    assert acc["total"] == 3.0 and acc["holdings"][0]["id"] == "fund-a" and acc["holdings"][0]["status"] == "held"
    assert portfolio.validate({"name": "X", "extra": {"kept": True}})["extra"] == {"kept": True}
    for bad in ({}, {"name": ""}, {"name": "X", "kind": "robot"}, {"name": "X", "accounts": [{"name": "A", "matures": "soon"}]}):
        try:
            portfolio.validate(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    print("validate OK")


def main():
    test_validate()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        db = test_api(tmp)
        test_publish(db)
        test_reopen_and_maintenance(tmp)


if __name__ == "__main__":
    main()
