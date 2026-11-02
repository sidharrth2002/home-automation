"""The iPhone widget's feed: right shape, and nothing outside its whitelist can leak into it."""
import json
import tempfile
from pathlib import Path

from widget import __main__ as w


def states():
    def s(eid, state, **attrs):
        return {"entity_id": eid, "state": state, "attributes": attrs}
    return [
        s("light.wiz_rgbw_tunable_624d4e", "on", brightness=153, rgb_color=[28, 120, 255]),
        s("light.desk_lamp", "on", brightness=26, rgb_color=[255, 167, 87]),
        s("light.wiz_rgbw_tunable_4b472c", "unavailable"),
        s("input_boolean.music_sync", "on"), s("input_select.music_sync_mode", "party"),
        s("sensor.music_sync_now_playing", "No Surprises — Radiohead", player_state="playing", entity_picture="https://i.scdn.co/x",
          palette=["#aabbcc"]),
        s("media_player.smart_tv_pro", "on", app_id="com.netflix.ninja"),
        s("binary_sensor.someone_home", "on"),
        s("weather.forecast_home", "cloudy", temperature=8.2),
        s("sensor.system_health", "ok"),
        # things the widget must never carry, however they got into the state list
        s("sensor.investments", "12345.67", holdings=[{"name": "SECRET FUND"}], cash=1.0),
        s("sensor.trading212", "7777.77", interest={"all_time": 99}),
        s("calendar.work", "on", message="Private meeting"),
        s("sensor.investment_b5zx1m7", "98.76", series=[[1, 2]]),
    ]


def run():
    feed = w.build(states())
    assert [(l["name"], l["on"], l["pct"], l["reachable"]) for l in feed["lights"]] == \
        [("TV 1", True, 60, True), ("Desk", True, 10, True), ("TV 2", False, 0, False)], feed["lights"]
    assert feed["lights"][0]["rgb"] == [28, 120, 255] and feed["lights"][2]["rgb"] is None
    assert feed["music"]["title"] == "No Surprises" and feed["music"]["artist"] == "Radiohead" and feed["music"]["playing"]
    assert feed["sync"] == {"on": True, "mode": "party"} and feed["tv"]["app"] == "com.netflix.ninja"
    assert feed["home"] is True and feed["weather"]["temp"] == 8.2 and feed["health"] == "ok"

    blob = json.dumps(feed).lower()
    for secret in ("secret fund", "12345", "7777", "private meeting", "98.76", "investment", "trading", "calendar"):
        assert secret not in blob, f"{secret!r} leaked into the widget feed"

    # missing entities degrade to nulls instead of crashing the service
    sparse = w.build([])
    assert all(not l["on"] and not l["reachable"] for l in sparse["lights"])
    assert sparse["home"] is None and sparse["weather"] is None and sparse["music"]["title"] is None
    nothing = w.build([{"entity_id": "sensor.music_sync_now_playing", "state": "Nothing playing", "attributes": {}}])
    assert nothing["music"]["title"] is None

    assert [l["action"] for l in feed["lights"]] == ["tv1", "desk", "tv2"], "each bulb carries the action its tap triggers"

    # the tap targets: one automation, webhooks that are local-only, POST-only, secret, and each does exactly one thing
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        w.DATA, w.KEY_FILE = tmp / "data", tmp / "data" / "key"
        auto = w.automation_config()
        triggers = {t["id"]: t for t in auto["triggers"]}
        assert set(triggers) == {"tv1", "desk", "tv2", "off", "ping"}
        assert all(t["trigger"] == "webhook" and t["local_only"] is True and t["allowed_methods"] == ["POST"] for t in triggers.values())
        ids = [t["webhook_id"] for t in triggers.values()]
        assert len(set(ids)) == 5 and all(i.startswith("widget-") and len(i) >= 39 for i in ids), ids
        assert w.key() not in "".join(ids), "the feed's name must not be derivable from the webhook ids"
        assert "ping" not in w.PHONE_ACTIONS, "the test-only action isn't handed to the phone"
        branches = {b["conditions"][0]["id"]: b["sequence"] for b in auto["actions"][0]["choose"]}
        assert branches["desk"] == [{"action": "light.toggle", "target": {"entity_id": "light.desk_lamp"}}]
        assert branches["tv1"][0]["target"]["entity_id"] == "light.wiz_rgbw_tunable_624d4e"
        assert branches["tv2"][0]["target"]["entity_id"] == "light.wiz_rgbw_tunable_4b472c"
        assert branches["off"] == [{"action": "script.turn_on", "target": {"entity_id": "script.all_off"}}]
        assert branches["ping"] == [{"event": "widget_ping"}]
        assert {j["action"] for seq in branches.values() for j in seq if "action" in j} <= {"light.toggle", "script.turn_on"}, \
            "the webhooks must not be able to do anything but toggle lamps or run all_off"
        # a different key gives different ids, so deleting the key revokes every address
        old = ids
        w.KEY_FILE.unlink()
        assert not set(old) & {t["webhook_id"] for t in w.automation_config()["triggers"]}

    # the feed file is written atomically under a secret name, and the key is private
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        w.DATA, w.KEY_FILE, w.OUT_DIR = tmp / "data", tmp / "data" / "key", tmp / "www"
        k = w.key()
        assert len(k) >= 30 and w.key() == k and oct(w.KEY_FILE.stat().st_mode)[-3:] == "600"
        w.write_feed(feed)
        written = list(w.OUT_DIR.iterdir())
        assert [p.name for p in written] == [f"{k}.json"], written
        assert json.loads(written[0].read_text())["lights"][0]["name"] == "TV 1"
    print("widget feed OK")


if __name__ == "__main__":
    run()
