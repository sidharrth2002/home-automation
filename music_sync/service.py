"""Bridges Home Assistant UI controls to the music-sync pipeline.

Creates helpers in HA (a toggle, a mode dropdown, sensitivity and latency sliders) and a tempo sensor,
then watches the helpers over the websocket API. Turning the toggle on starts audio capture + bulb
output; turning it off (or 30s of silence) stops it and restores the bulbs.
"""
import asyncio
import json
import logging
import os
import signal
import time
import urllib.request
from pathlib import Path

import numpy as np
import websockets

from . import capture
from .analysis import HOP, Analyzer
from .engine import BeatEngine
from .lights import Lights
from .show import Show

log = logging.getLogger("music_sync")

HA_URL = os.environ.get("HA_URL", "ws://localhost:8123/api/websocket")
HA_HTTP = os.environ.get("HA_HTTP", "http://localhost:8123")
SWITCH = "input_boolean.music_sync"
MODE = "input_select.music_sync_mode"
SENSITIVITY = "input_number.music_sync_sensitivity"
LATENCY = "input_number.music_sync_latency"
TEMPO_SENSOR = "sensor.music_sync_tempo"
WATCHED = (SWITCH, MODE, SENSITIVITY, LATENCY)
MODES = ("auto", "calm", "party", "tv", "classic")
SILENCE_RMS = 0.005
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
        self.mode = "auto"
        self.sensitivity = 1.35
        self.latency_ms = 60.0
        self.session: asyncio.Task | None = None
        self.ha: HA | None = None
        self.token = ""
        self._bg: set[asyncio.Task] = set()

    async def ensure_helpers(self):
        states = {s["entity_id"]: s for s in await self.ha.call(type="get_states")}
        if SWITCH not in states:
            await self.ha.call(type="input_boolean/create", name="Music Sync", icon="mdi:music")
        if MODE not in states:
            await self.ha.call(type="input_select/create", name="Music Sync Mode", icon="mdi:tune",
                               options=list(MODES), initial="auto")
        elif states[MODE]["attributes"].get("options") != list(MODES):
            await self.ha.call(type="input_select/update", input_select_id=MODE.split(".")[1],
                               name="Music Sync Mode", icon="mdi:tune", options=list(MODES))
        if SENSITIVITY not in states:
            await self.ha.call(type="input_number/create", name="Music Sync Sensitivity", icon="mdi:sine-wave",
                               min=1.0, max=2.5, step=0.05, mode="slider", initial=1.35)
        if LATENCY not in states:
            await self.ha.call(type="input_number/create", name="Music Sync Latency", icon="mdi:timer-sync",
                               min=-200, max=300, step=10, mode="slider", unit_of_measurement="ms", initial=60)
        states = {s["entity_id"]: s for s in await self.ha.call(type="get_states")}
        for eid in WATCHED:
            self.apply(eid, states[eid]["state"])
        self.publish_status()

    def apply(self, entity_id, state):
        if entity_id == MODE and state in MODES:
            self.mode = state
        elif entity_id in (SENSITIVITY, LATENCY):
            try:
                value = float(state)
            except ValueError:
                return
            if entity_id == SENSITIVITY:
                self.sensitivity = value
            else:
                self.latency_ms = value
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
            analyzer, show = Analyzer(), Show(len(lights.bulbs))
            classic, classic_buf = BeatEngine(), []
            last_status = time.monotonic()
            log.info("music sync started with %d bulbs", len(lights.bulbs))
            done = False
            while not done:
                # TV mode listens to the room (whatever the TV plays, from any app); the rest tap the Mac.
                use_mic = self.mode == "tv"
                source = capture.mic_hops(HOP) if use_mic else capture.hops(HOP)
                log.info("listening to %s", "the microphone" if use_mic else "system audio")
                last_sound = time.monotonic()
                try:
                    async for samples in source:
                        if (self.mode == "tv") != use_mic:
                            break  # switched between TV and Mac audio; reopen the right source
                        now = time.monotonic()
                        if self._step(samples, now, analyzer, show, classic, classic_buf, lights) >= SILENCE_RMS:
                            last_sound = now
                        elif not use_mic and now - last_sound > SILENCE_STOP_S:
                            # TV scenes go quiet all the time, so only Mac-audio sessions time out.
                            log.info("no audio for %ds, stopping", SILENCE_STOP_S)
                            done = True
                        if now - last_status > 2:
                            last_status = now
                            self.publish_status(analyzer.tempo)
                        if done:
                            break
                    else:
                        done = True  # the capture source ended
                finally:
                    await source.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("music sync failed")
        finally:
            await asyncio.shield(lights.stop())
            log.info("music sync stopped, lights restored")
            self.publish_status()
            if self.ha:
                try:
                    await self.ha.service("input_boolean", "turn_off", SWITCH)
                except Exception:
                    pass

    def _step(self, samples, now, analyzer, show, classic, classic_buf, lights):
        """Analyse one hop and drive the bulbs. Returns the hop's RMS."""
        show.mode, show.latency_ms = self.mode, self.latency_ms
        analyzer.sensitivity = self.sensitivity
        analyzer.hue_tau = show.profile["hue_tau"]
        frame = analyzer.process(samples, now)
        if self.mode == "classic":
            # The original wiz_spotify algorithm, fed ~140 ms windows like it was designed for.
            classic_buf.append(samples)
            if len(classic_buf) >= 6:
                classic.sensitivity = self.sensitivity
                beat, _ = classic.process(np.concatenate(classic_buf), capture.SAMPLE_RATE, now * 1000)
                classic_buf.clear()
                if beat:
                    lights.show(beat)
        else:
            lights.render(show.update(frame, analyzer.tempo, now))
        return frame.rms

    def publish_status(self, tempo=None):
        """Mirror the detected tempo into HA as a sensor (REST, since the websocket API can't set states)."""
        locked = bool(tempo and tempo.locked)
        body = {"state": round(tempo.bpm) if locked else "unknown",
                "attributes": {"friendly_name": "Music Sync Tempo", "unit_of_measurement": "BPM",
                               "icon": "mdi:metronome", "locked": locked,
                               "confidence": round(tempo.confidence, 2) if tempo else 0.0}}
        task = asyncio.create_task(asyncio.to_thread(self._post_state, TEMPO_SENSOR, body))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def _post_state(self, entity_id, body):
        req = urllib.request.Request(f"{HA_HTTP}/api/states/{entity_id}", data=json.dumps(body).encode(),
                                     method="POST", headers={"Authorization": f"Bearer {self.token}",
                                                             "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=3).close()
        except OSError as e:
            log.debug("could not publish %s: %s", entity_id, e)

    async def run(self, token):
        self.token = token
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
            if eid in WATCHED and data.get("new_state"):
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
