"""Push the version-controlled HA config in this folder to Home Assistant: helpers, template sensors,
scripts, automations and the dashboard (in that order, so automations never reference missing entities).

Run: .venv/bin/python -m homeassistant.apply
"""
import asyncio
import json
import os
import urllib.request
from pathlib import Path

from music_sync.service import HA, HA_HTTP, load_env

ROOT = Path(__file__).resolve().parent
DASHBOARD = "home-hub"
TEMPLATE_FIELDS = ("state", "unit_of_measurement", "device_class", "state_class")


def rest(token, path, body=None, method="POST"):
    req = urllib.request.Request(f"{HA_HTTP}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


def apply_template(token, spec, existing_entries):
    """Create a template sensor helper, or update its options if one with this name exists."""
    fields = {k: spec[k] for k in TEMPLATE_FIELDS if k in spec}
    entry = existing_entries.get(spec["name"])
    if entry:
        flow = rest(token, "/api/config/config_entries/options/flow", {"handler": entry["entry_id"]})
        result = rest(token, f"/api/config/config_entries/options/flow/{flow['flow_id']}", fields)
        action = "updated"
    else:
        flow = rest(token, "/api/config/config_entries/flow", {"handler": "template"})
        flow = rest(token, f"/api/config/config_entries/flow/{flow['flow_id']}", {"next_step_id": "sensor"})
        result = rest(token, f"/api/config/config_entries/flow/{flow['flow_id']}", {"name": spec["name"], **fields})
        action = "created"
    if result.get("type") != "create_entry":
        raise RuntimeError(f"template {spec['name']!r} not {action}: {result.get('errors') or result}")
    print(f"template: {spec['name']} ({action})")


async def main():
    load_env()
    token = os.environ["TOKEN"]
    ha = await HA.connect(token)
    pump = asyncio.create_task(_drain(ha))

    states = {s["entity_id"] for s in await ha.call(type="get_states")}
    for helper in json.loads((ROOT / "helpers.json").read_text()):
        if helper["entity_id"] not in states:
            await ha.call(type=f"{helper['entity_id'].split('.')[0]}/create", **helper["create"])
            print(f"helper: {helper['entity_id']} (created)")

    entries = {e["title"]: e for e in rest(token, "/api/config/config_entries/entry?domain=template", method="GET")}
    for f in sorted((ROOT / "templates").glob("*.json")):
        apply_template(token, json.loads(f.read_text()), entries)

    for kind in ("script", "automation"):
        for f in sorted((ROOT / f"{kind}s").glob("*.json")):
            rest(token, f"/api/config/{kind}/config/{f.stem}", json.loads(f.read_text()))
            print(f"{kind}: {f.stem}")

    existing = {d["url_path"] for d in await ha.call(type="lovelace/dashboards/list")}
    if DASHBOARD not in existing:
        await ha.call(type="lovelace/dashboards/create", url_path=DASHBOARD, title="Home",
                      icon="mdi:home-variant", show_in_sidebar=True, require_admin=False, mode="storage")
    await ha.call(type="lovelace/config/save", url_path=DASHBOARD,
                  config=json.loads((ROOT / "dashboards" / "home.json").read_text()))
    print(f"dashboard: {HA_HTTP}/{DASHBOARD}/home")
    pump.cancel()
    await ha.ws.close()


async def _drain(ha):
    async for _ in ha.events():
        pass


if __name__ == "__main__":
    asyncio.run(main())
