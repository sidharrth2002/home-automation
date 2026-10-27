"""Bridges Home Assistant UI controls to the music-sync pipeline.

Creates three helpers in HA (a toggle, a mode dropdown, a sensitivity slider), then watches them over
the websocket API. Turning the toggle on starts audio capture + bulb output; turning it off (or 30s of
silence) stops it and restores the bulbs.
"""
import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

import websockets

from . import capture
from .engine import BeatEngine
from .lights import Lights

log = logging.getLogger("music_sync")

HA_URL = os.environ.get("HA_URL", "ws://localhost:8123/api/websocket")
SWITCH = "input_boolean.music_sync"
MODE = "input_select.music_sync_mode"
SENSITIVITY = "input_number.music_sync_sensitivity"
SILENCE_STOP_S = 30


def load_env():
    path = Path(__file__).resolve().parent.parent / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class HA:
    def __init__(self, ws, token):
        self.ws, self.token, self._id, self._pending = ws, token, 0, {}

    @classmethod
    async def connect(cls, token):
        ws = await websockets.connect(HA_URL, max_size=None)
        await ws.recv()  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        if json.loads(await ws.recv())["type"] != "auth_ok":
            raise RuntimeError("Home Assistant rejected the token")
        return cls(ws, token)

    async def call(self, **msg):
        self._id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        await self.ws.send(json.dumps({"id": self._id, **msg}))
        return await asyncio.wait_for(fut, 10)

    async def events(self):
        """Dispatch results to pending calls and yield state_changed events."""
        async for raw in self.ws:
            m = json.loads(raw)
            if m.get("type") == "result" and m["id"] in self._pending:
                fut = self._pending.pop(m["id"])
                if m.get("success"):
                    fut.set_result(m.get("result"))
                else:
                    fut.set_exception(RuntimeError(m.get("error")))
            elif m.get("type") == "event":
                yield m["event"]["data"]

    async def service(self, domain, service, entity_id, **data):
        return await self.call(type="call_service", domain=domain, service=service,
                               service_data=data, target={"entity_id": entity_id})


class Controller:
    def __init__(self):
        self.engine = BeatEngine()
        self.session: asyncio.Task | None = None
        self.ha: HA | None = None

    async def ensure_helpers(self):
        states = {s["entity_id"]: s for s in await self.ha.call(type="get_states")}
        if SWITCH not in states:
            await self.ha.call(type="input_boolean/create", name="Music Sync", icon="mdi:music")
        if MODE not in states:
            await self.ha.call(type="input_select/create", name="Music Sync Mode", icon="mdi:tune",
                               options=["auto", "calm", "party"], initial="auto")
        if SENSITIVITY not in states:
            await self.ha.call(type="input_number/create", name="Music Sync Sensitivity", icon="mdi:sine-wave",
                               min=1.0, max=2.5, step=0.05, mode="slider", initial=1.35)
        states = {s["entity_id"]: s for s in await self.ha.call(type="get_states")}
        for eid in (SWITCH, MODE, SENSITIVITY):
            self.apply(eid, states[eid]["state"])

    def apply(self, entity_id, state):
        if entity_id == MODE and state in ("auto", "calm", "party"):
            self.engine.mode = state
        elif entity_id == SENSITIVITY:
            try:
                self.engine.sensitivity = float(state)
            except ValueError:
                pass
        elif entity_id == SWITCH:
            running = self.session is not None and not self.session.done()
            if state == "on" and not running:
                self.session = asyncio.create_task(self.run_session())
            elif state == "off" and running:
                self.session.cancel()

    async def run_session(self):
        lights = Lights()
        try:
            await lights.start()
            self.engine.reset()
            last_sound = time.monotonic()
            log.info("music sync started")
            async for pcm in capture.chunks():
                now = time.monotonic()
                beat, rms = self.engine.process(pcm, capture.SAMPLE_RATE, now * 1000)
                if rms >= 0.01:
                    last_sound = now
                if beat:
                    lights.show(beat)
                elif now - last_sound > SILENCE_STOP_S:
                    log.info("no audio for %ds, stopping", SILENCE_STOP_S)
                    break
            else:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("music sync failed")
        finally:
            await asyncio.shield(lights.stop())
            log.info("music sync stopped, lights restored")
            if self.ha:
                try:
                    await self.ha.service("input_boolean", "turn_off", SWITCH)
                except Exception:
                    pass

    async def run(self, token):
        backoff = 1
        while True:
            try:
                self.ha = await HA.connect(token)
                pump = asyncio.create_task(self._pump())
                await self.ha.call(type="subscribe_events", event_type="state_changed")
                await self.ensure_helpers()
                log.info("connected to Home Assistant")
                backoff = 1
                await pump
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
                log.warning("Home Assistant connection lost (%s); retrying in %ds", e, backoff)
            self.ha = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _pump(self):
        async for data in self.ha.events():
            eid = data["entity_id"]
            if eid in (SWITCH, MODE, SENSITIVITY) and data.get("new_state"):
                self.apply(eid, data["new_state"]["state"])


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ.get("TOKEN")
    if not token:
        raise SystemExit("TOKEN missing from .env")
    ctl = Controller()
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()

    def shutdown():
        if ctl.session and not ctl.session.done():
            ctl.session.cancel()
        main_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown)
    try:
        await ctl.run(token)
    except asyncio.CancelledError:
        if ctl.session:
            await asyncio.gather(ctl.session, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
