"""The core state service: database, API, portfolio merge and publishing, on a throwaway database (made-up numbers).

Run: .venv/bin/python -m tests.test_core
"""
import tempfile
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

import json
import os
import stat
import urllib.error

from core import finance, live, portfolio, tasks, worker
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
    assert db.schema_version == 4 and finance.current(db)
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


def test_tasks(tmp: Path):
    db = DB(tmp / "tasks.db")
    api = TestClient(create_app(db, ADMIN))
    admin = {"Authorization": f"Bearer {ADMIN}"}
    t = expect(200, api.post("/v1/tasks", json={"kind": "agent", "title": "Look into X", "input": {"prompt": "x"}},
                             headers=admin))
    assert t["status"] == "queued" and t["created_by"] == "services"
    reader = {"Authorization": f"Bearer {db.add_principal('reader', ['doc/notes/*'])}"}
    expect(403, api.post("/v1/tasks", json={"kind": "agent", "title": "no"}, headers=reader))
    expect(403, api.post("/v1/tasks/claim", json={"worker": "w", "kinds": ["agent"]}, headers=reader))

    # claim, heartbeat, progress, finish
    c = expect(200, api.post("/v1/tasks/claim", json={"worker": "w1", "kinds": ["agent"]}, headers=admin))["task"]
    assert c["id"] == t["id"] and c["status"] == "running" and c["attempts"] == 1
    assert expect(200, api.post("/v1/tasks/claim", json={"worker": "w2", "kinds": ["agent"]}, headers=admin))["task"] is None
    hb = expect(200, api.post(f"/v1/tasks/{c['id']}/heartbeat", json={"worker": "w1", "progress": 0.5, "message": "half",
                                                                     "events": ["did a thing"]}, headers=admin))
    assert hb == {"cancel": False}
    assert expect(200, api.post(f"/v1/tasks/{c['id']}/heartbeat", json={"worker": "other"}, headers=admin))["cancel"]
    done = expect(200, api.post(f"/v1/tasks/{c['id']}/finish", json={"worker": "w1", "result": {"ok": 1}}, headers=admin))
    assert done["status"] == "done" and done["result"] == {"ok": 1} and done["progress"] == 1
    assert any("did a thing" in e["message"] for e in expect(200, api.get(f"/v1/tasks/{c['id']}", headers=admin))["events"])

    # failure retries with backoff, then fails for good; cancelling; a dead worker's lease is taken over
    f = tasks.create(db, "agent", "flaky", max_attempts=2)
    tasks.claim(db, ["agent"], "w")
    tasks.finish(db, f["id"], "w", error="boom")
    assert tasks.get(db, f["id"])["status"] == "queued" and tasks.get(db, f["id"])["run_after"] > tasks.now()
    db.conn.execute("UPDATE tasks SET run_after=? WHERE id=?", ("2000-01-01", f["id"]))
    tasks.claim(db, ["agent"], "w")
    tasks.finish(db, f["id"], "w", error="boom again")
    assert tasks.get(db, f["id"])["status"] == "failed"
    q = tasks.create(db, "agent", "never mind")
    assert expect(200, api.post(f"/v1/tasks/{q['id']}/cancel", headers=admin))["status"] == "cancelled"
    r = tasks.create(db, "agent", "long one", max_attempts=2)
    tasks.claim(db, ["agent"], "dies")
    assert tasks.cancel(db, r["id"], "me")["cancel_requested"]
    assert tasks.heartbeat(db, r["id"], "dies") == {"cancel": True}
    db.conn.execute("UPDATE tasks SET lease_until=? WHERE id=?", ("2000-01-01", r["id"]))
    assert tasks.claim(db, ["agent"], "w3")["worker"] == "w3", "an expired lease is taken over"

    # schedules: due ones are queued once, and not again while the last is still pending
    tasks.set_schedule(db, "tick", "revalue", "Tick", 3600)
    assert tasks.run_due(db) == 1 and tasks.run_due(db) == 0
    db.conn.execute("UPDATE schedules SET next_run='2000-01-01'")
    assert tasks.run_due(db) == 0, "the previous one is still queued"
    s = tasks.summary(db)
    assert s["counts"]["failed"] == 1 and all(x["title"] != "Tick" or x["status"] != "queued" for x in s["recent"])
    print("tasks OK")


def test_agent_runner(tmp: Path):
    """run_agent against a fake `claude` that streams JSON like the real one: events, files, result, cancel."""
    fake = tmp / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text("""#!/usr/bin/env python3
import json, sys, time
args = sys.argv[1:]
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "WebSearch",
                  "input": {"query": "quiet cafes"}}]}}), flush=True)
open("result.md", "w").write("# Found")
if "slow" in args[1]:
    time.sleep(30)
allowed = args[args.index("--allowedTools") + 1:args.index("--disallowedTools")]
denied = args[args.index("--disallowedTools") + 1:]
print(json.dumps({"type": "result", "result": "All done: " + " ".join(allowed) + " | denied: " + " ".join(denied),
                  "is_error": False, "num_turns": 2, "total_cost_usd": 0.01}), flush=True)
""")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    old_path, old_ws = os.environ["PATH"], worker.WORKSPACES
    os.environ["PATH"], worker.WORKSPACES = f"{fake.parent}:{old_path}", tmp / "tasks"
    try:
        data = tmp / "sheets"
        data.mkdir()
        ctx = worker.Context({"id": 7, "kind": "agent", "input": {"prompt": "find cafes", "dirs": [str(data)]}}, "w")
        res = worker.run_agent(ctx)
        assert res["files"] == ["result.md"] and res["turns"] == 2 and "All done" in res["summary"]
        allowed, denied = res["summary"].split(" | denied: ")
        assert f"Read(/{data.resolve()}/**)" in allowed and "Bash" not in allowed, "tools are scoped"
        assert "Bash(rclone:*)" in denied and "CloudStorage" in denied, "OneDrive is never touched"
        assert any("WebSearch: quiet cafes" in line for line in ctx._lines)
        os.environ["CORE_TOKEN"] = "secret-for-test"
        assert "CORE_TOKEN" not in worker.agent_env() and "PATH" in worker.agent_env(), "agents don't get secrets"
        try:
            worker.run_agent(worker.Context({"id": 8, "kind": "agent", "input": {"prompt": "x", "dirs": ["/nope"]}}, "w"))
            raise AssertionError("a missing folder should fail")
        except ValueError:
            pass
        slow = worker.Context({"id": 9, "kind": "agent", "input": {"prompt": "slow"}}, "w")
        threading.Timer(1.5, slow.cancelled.set).start()
        t0 = time.monotonic()
        assert worker.run_agent(slow) is None and time.monotonic() - t0 < 15, "cancel stops the agent"
    finally:
        os.environ["PATH"], worker.WORKSPACES = old_path, old_ws
    print("agent runner OK")


def test_live(tmp: Path):
    """Services report entity state; the core keeps the latest and the publisher mirrors it."""
    db = DB(tmp / "core.db")
    assert db.schema_version >= 3
    changed = []
    api = TestClient(create_app(db, ADMIN, on_live=changed.append))
    admin = {"Authorization": f"Bearer {ADMIN}"}
    body = {"state": "on", "attributes": {"friendly_name": "Someone home", "phone_last_seen_s": 12}}
    assert expect(200, api.put("/v1/live/binary_sensor.someone_home", json=body, headers=admin))["changed"]
    assert not expect(200, api.put("/v1/live/binary_sensor.someone_home", json=body, headers=admin))["changed"]
    assert changed == ["binary_sensor.someone_home"]  # an unchanged report doesn't republish
    got = expect(200, api.get("/v1/live/binary_sensor.someone_home", headers=admin))
    assert got["state"] == "on" and got["attributes"]["phone_last_seen_s"] == 12 and got["updated_by"] == "services"
    expect(200, api.put("/v1/live/sensor.photo_frame", json={"state": 3, "attributes": {"photos": [1, 2, 3]}},
                        headers=admin))
    listed = expect(200, api.get("/v1/live", headers=admin))["entities"]
    assert [e["entity"] for e in listed] == ["binary_sensor.someone_home", "sensor.photo_frame"]
    assert "attributes" not in listed[0] and expect(200, api.get("/v1/live/sensor.photo_frame", headers=admin))["state"] == 3
    expect(400, api.put("/v1/live/Not An Entity", json=body, headers=admin))
    expect(404, api.get("/v1/live/sensor.nothing", headers=admin))

    # scopes: a token for one entity can't write another
    token = db.add_principal("presence", ["live/binary_sensor.*"])
    scoped = {"Authorization": f"Bearer {token}"}
    expect(200, api.put("/v1/live/binary_sensor.someone_home", json={"state": "off"}, headers=scoped))
    expect(403, api.put("/v1/live/sensor.photo_frame", json={"state": 0}, headers=scoped))

    # the publisher sends every live entity at start, then each change, and survives Home Assistant being down
    posted, down = [], threading.Event()

    def post(e, s, a):
        if down.is_set():
            raise OSError("Home Assistant is down")
        if e == "sensor.aaa_refused":  # sorts first: a permanent refusal mustn't hold up the rest
            raise urllib.error.HTTPError("http://ha", 400, "Bad Request", None, None)
        posted.append((e, s))
    live.put(db, "sensor.aaa_refused", "x" * 300, {}, "test")
    pub = Publisher(db, post=post)
    assert {"live:binary_sensor.someone_home", "live:sensor.photo_frame"} <= pub.dirty
    threading.Thread(target=pub.run, daemon=True).start()

    def wait_for(item):
        deadline = time.monotonic() + 8
        while item not in posted and time.monotonic() < deadline:
            time.sleep(0.05)
        assert item in posted, posted
    wait_for(("binary_sensor.someone_home", "off"))
    wait_for(("sensor.photo_frame", 3))
    down.set()
    live.put(db, "sensor.photo_frame", 4, {}, "test")
    pub.live_changed("sensor.photo_frame")
    time.sleep(1)
    assert ("sensor.photo_frame", 4) not in posted and "live:sensor.photo_frame" in pub.dirty  # kept for a retry
    down.clear()
    wait_for(("sensor.photo_frame", 4))  # the retry (2 s backoff) lands
    expect(200, api.delete("/v1/live/sensor.photo_frame", headers=admin))
    expect(404, api.delete("/v1/live/sensor.photo_frame", headers=admin))
    print("live OK")


def test_media(tmp: Path):
    """A library's index, analysis results and shown sets, over the API (made-up items)."""
    db = DB(tmp / "core.db")
    assert db.schema_version == 4
    api = TestClient(create_app(db, ADMIN))
    admin = {"Authorization": f"Bearer {ADMIN}"}
    base = "/v1/media/onedrive"
    item = lambda i, size=100: {"id": f"id{i:03d}", "name": f"IMG_{i}.HEIC", "taken_at": "2024-11-03T12:00:00Z",
                                "camera": "Apple", "focal_mm": 6.8, "width": 4032, "height": 3024, "bytes": size}
    got = expect(200, api.put(f"{base}/items", json={"items": [item(i) for i in range(12)],
                                                     "cursor": {"key": "Pictures", "value": "link-1"}}, headers=admin))
    assert got["changed"] == 12
    assert expect(200, api.put(f"{base}/items", json={"items": [item(0)]}, headers=admin))["changed"] == 0  # unchanged
    looks = {f"id{i:03d}": {"ok": True, "faces": i} for i in range(5)} | {"gone": {"ok": False}}
    assert expect(200, api.put(f"{base}/analysis/faces", json={"results": looks}, headers=admin))["recorded"] == 5

    # pages and filters
    first = expect(200, api.get(f"{base}/items?analyser=faces&limit=5", headers=admin))
    assert [i["id"] for i in first["items"]] == [f"id{i:03d}" for i in range(5)] and first["next"] == "id004"
    assert first["items"][3]["analysis"] == {"ok": True, "faces": 3}
    todo = expect(200, api.get(f"{base}/items?analyser=faces&analysed=false", headers=admin))["items"]
    assert len(todo) == 7 and all(i["analysis"] is None for i in todo)
    assert len(expect(200, api.get(f"{base}/items?analyser=faces&analysed=true", headers=admin))["items"]) == 5

    # a changed file loses its results; a deleted one goes, with them
    expect(200, api.put(f"{base}/items", json={"items": [item(1, size=999)], "deleted": ["id002"]}, headers=admin))
    done = {i["id"] for i in expect(200, api.get(f"{base}/items?analyser=faces&analysed=true", headers=admin))["items"]}
    assert done == {"id000", "id003", "id004"}, done

    expect(200, api.post(f"{base}/shown", json={"ids": ["id000", "id003", "nope"]}, headers=admin))
    s = expect(200, api.get(base, headers=admin))
    assert s["items"] == 11 and s["analysed"] == {"faces": 3} and s["cursors"] == {"Pictures": "link-1"}
    assert sorted(s["last_shown"]) == ["id000", "id003"]

    token = db.add_principal("reader", ["doc/notes/*"])
    expect(403, api.put(f"{base}/items", json={"items": [item(50)]}, headers={"Authorization": f"Bearer {token}"}))
    expect(400, api.put("/v1/media/Bad Source/items", json={"items": []}, headers=admin))
    print("media OK")


def test_telemetry_off():
    """With no endpoint set, telemetry does nothing and the helpers are safe no-ops."""
    import telemetry
    old = os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    try:
        assert telemetry.setup("test") is False
        telemetry.gauge("home.test", lambda: [(1, {})])
        telemetry.meter().create_counter("home.test.count").add(1)
    finally:
        if old:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = old
    print("telemetry OK")


def main():
    test_validate()
    test_telemetry_off()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        db = test_api(tmp)
        test_publish(db)
        test_reopen_and_maintenance(tmp)
        test_tasks(tmp)
        test_agent_runner(tmp)
        test_live(tmp)
        test_media(tmp)


if __name__ == "__main__":
    main()
