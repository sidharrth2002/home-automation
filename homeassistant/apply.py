"""Push the version-controlled HA config in this folder (scripts, automations, dashboard) to Home Assistant.

Run: .venv/bin/python -m homeassistant.apply
"""
import asyncio
import json
import urllib.request
from pathlib import Path

import websockets

from music_sync.service import HA, HA_HTTP, load_env

ROOT = Path(__file__).resolve().parent
DASHBOARD = "home-hub"


def rest(token, path, body):
    req = urllib.request.Request(f"{HA_HTTP}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


async def main():
    import os
    load_env()
    token = os.environ["TOKEN"]
    for kind in ("script", "automation"):
        for f in sorted((ROOT / f"{kind}s").glob("*.json")):
            rest(token, f"/api/config/{kind}/config/{f.stem}", json.loads(f.read_text()))
            print(f"{kind}: {f.stem}")

    ha = await HA.connect(token)
    pump = asyncio.create_task(_drain(ha))
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
