"""Make the TV app its own long-lived Home Assistant token (once; tv-app/deploy keeps it in data/tv/token, git-ignored).

It's a separate token from the services' so it can be revoked on its own (Home Assistant: your profile > Security >
Long-lived access tokens > "Home TV app"). Prints the token on stdout, nothing else.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from music_sync.service import load_env  # noqa: E402


async def main():
    load_env()
    url = os.environ.get("HA_HTTP", "http://localhost:8123").replace("http", "ws", 1) + "/api/websocket"
    async with websockets.connect(url) as ws:
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "access_token": os.environ["TOKEN"]}))
        if json.loads(await ws.recv())["type"] != "auth_ok":
            sys.exit("Home Assistant refused the token in .env")
        await ws.send(json.dumps({"id": 1, "type": "auth/long_lived_access_token", "client_name": "Home TV app", "lifespan": 3650}))
        r = json.loads(await ws.recv())
        if not r.get("success"):
            sys.exit(f"couldn't make a token: {r.get('error')}")
        print(r["result"])

asyncio.run(main())
