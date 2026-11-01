"""Bridges Home Assistant UI controls to the music-sync pipeline.

Creates helpers in HA (a toggle, mode and colour-source dropdowns, sensitivity and latency sliders) and
tempo / now-playing sensors, then watches the helpers over the websocket API. Turning the toggle on starts audio capture + bulb
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
from .nowplaying import NowPlaying
from .show import Show

log = logging.getLogger("music_sync")

HA_URL = os.environ.get("HA_URL", "ws://localhost:8123/api/websocket")
HA_HTTP = os.environ.get("HA_HTTP", "http://localhost:8123")
SWITCH = "input_boolean.music_sync"
MODE = "input_select.music_sync_mode"
SENSITIVITY = "input_number.music_sync_sensitivity"
LATENCY = "input_number.music_sync_latency"
COLOURS = "input_select.music_sync_colours"
TEMPO_SENSOR = "sensor.music_sync_tempo"
NOW_PLAYING_SENSOR = "sensor.music_sync_now_playing"
COMMAND_EVENT = "music_sync_command"  # fired by the play/pause/skip scripts: {"command": "play_pause"|"next"|"previous"}
TV = os.environ.get("TV_ENTITY", "media_player.smart_tv_pro")
WATCHED = (SWITCH, MODE, SENSITIVITY, LATENCY, COLOURS, TV)
MODES = ("auto", "calm", "party", "tv", "classic")
ALBUM_ART, MUSIC_KEY = "Album art", "Music key"
# TV apps that play music rather than video: TV mode gives these a real (auto) show instead of bias lighting.
TV_MUSIC_APPS = ("com.spotify.tv.android", "com.google.android.youtube.tvmusic", "com.apple.android.music",
                 "com.amazon.music.tv", "deezer.android.tv", "com.aspiro.tidal", "com.soundcloud.android")
SILENCE_RMS = 0.005
SILENCE_STOP_S = 30
TV_FALLBACK_S = 3  # Mac silent this long while the TV is on -> listen to the room instead


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
        """Dispatch results to pending calls and yield subscribed events."""
        async for raw in self.ws:
            m = json.loads(raw)
            if m.get("type") == "result" and m["id"] in self._pending:
                fut = self._pending.pop(m["id"])
                if fut.done():
                    continue  # the caller already timed out
                if m.get("success"):
                    fut.set_result(m.get("result"))
                else:
                    fut.set_exception(RuntimeError(m.get("error")))
            elif m.get("type") == "event":
                yield m["event"]

    async def service(self, domain, service, entity_id, **data):
        return await self.call(type="call_service", domain=domain, service=service,
                               service_data=data, target={"entity_id": entity_id})


class Controller:
    def __init__(self):
        self.mode = "auto"
        self.sensitivity = 1.35
        self.latency_ms = 60.0
        self.colours = ALBUM_ART
        self.tv_app: str | None = None  # foreground app while the TV is on, else None
        self.mac_heard_at = 0.0
        self.now_playing = NowPlaying()
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
        if COLOURS not in states:
            await self.ha.call(type="input_select/create", name="Music Sync Colours", icon="mdi:palette",
                               options=[ALBUM_ART, MUSIC_KEY], initial=ALBUM_ART)
        states = {s["entity_id"]: s for s in await self.ha.call(type="get_states")}
        for eid in WATCHED:
            if eid in states:
                self.apply(eid, states[eid]["state"], states[eid]["attributes"])
        self.publish_status()
        self.publish_now_playing(self.now_playing)

    @property
    def tv_on(self):
        return self.tv_app is not None

    @property
    def show_mode(self):
        """TV mode follows the TV: bias lighting for video, a proper show when a music app is up."""
        if self.mode == "tv" and self.tv_app in TV_MUSIC_APPS:
            return "auto"
        return self.mode

    def want_mic(self):
        """Listen to the room for TV mode, or when the TV is on (and the Mac is silent; see run_session).

        The Mac's Spotify state can't decide this: it reports "playing" while remote-controlling the TV.
        """
        return self.mode == "tv" or self.tv_on

    async def _watch_mac(self):
        """While listening to the room, keep an ear on the Mac so a Mac session can take back over."""
        source = capture.hops(HOP)
        try:
            async for samples in source:
                if float(np.sqrt(np.mean(samples ** 2))) >= SILENCE_RMS:
                    self.mac_heard_at = time.monotonic()
        finally:
            await source.aclose()

    def apply(self, entity_id, state, attrs=None):
        if entity_id == TV:
            self.tv_app = ((attrs or {}).get("app_id") or "") if state not in ("off", "unavailable", "unknown") else None
        elif entity_id == MODE and state in MODES:
            self.mode = state
        elif entity_id == COLOURS and state in (ALBUM_ART, MUSIC_KEY):
            self.colours = state
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
            # TV mode listens to the room (whatever the TV plays, from any app). Other modes tap the Mac, but
            # fall back to the room when the Mac is silent and the TV is on (e.g. Spotify on the TV).
            use_mic = self.mode == "tv"
            while not done:
                source = capture.mic_hops(HOP) if use_mic else capture.hops(HOP)
                log.info("listening to %s", "the microphone" if use_mic else "system audio")
                last_sound = time.monotonic()
                watcher = asyncio.create_task(self._watch_mac()) if use_mic and self.mode != "tv" else None
                try:
                    async for samples in source:
                        now = time.monotonic()
                        mac_live = watcher is not None and now - self.mac_heard_at < 0.5
                        if use_mic and (not self.want_mic() or mac_live):
                            use_mic = False  # TV off, or the Mac started making sound
                            break
                        if not use_mic and self.mode == "tv":
                            use_mic = True
                            break
                        if self._step(samples, now, analyzer, show, classic, classic_buf, lights) >= SILENCE_RMS:
                            last_sound = now
                        elif not use_mic and self.tv_on and now - last_sound > TV_FALLBACK_S:
                            use_mic = True
                            break
                        elif not use_mic and now - last_sound > SILENCE_STOP_S:
                            # Rooms are never silent, so only Mac-audio sessions time out.
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
                    if watcher:
                        watcher.cancel()
                        await asyncio.gather(watcher, return_exceptions=True)
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
        show.mode, show.latency_ms = self.show_mode, self.latency_ms
        # Album colours only while Spotify is actually what's playing; otherwise follow the music's key.
        use_art = self.colours == ALBUM_ART and self.now_playing.state == "playing"
        show.palette = self.now_playing.palette if use_art else []
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

    async def command(self, name):
        """Transport controls: the Mac's Spotify if it's open, otherwise whatever the TV is playing."""
        if name not in ("play_pause", "next", "previous"):
            return
        try:
            if self.now_playing.state in ("playing", "paused") and await self.now_playing.command(name):
                if await self.now_playing.poll():
                    self.publish_now_playing(self.now_playing)
            elif self.tv_on and self.ha:
                service = {"play_pause": "media_play_pause", "next": "media_next_track",
                           "previous": "media_previous_track"}[name]
                await self.ha.service("media_player", service, TV)
        except Exception:
            log.exception("command %s failed", name)

    def publish_status(self, tempo=None):
        """Mirror the detected tempo into HA as a sensor (REST, since the websocket API can't set states)."""
        locked = bool(tempo and tempo.locked)
        body = {"state": round(tempo.bpm) if locked else "unknown",
                "attributes": {"friendly_name": "Music Sync Tempo", "unit_of_measurement": "BPM",
                               "icon": "mdi:metronome", "locked": locked,
                               "confidence": round(tempo.confidence, 2) if tempo else 0.0}}
        self._background(asyncio.to_thread(self._post_state, TEMPO_SENSOR, body))

    def publish_now_playing(self, np_: NowPlaying):
        attrs = {"friendly_name": "Now Playing", "icon": "mdi:spotify", "player_state": np_.state,
                 "palette": [s.hex for s in np_.palette], "media_position": round(np_.position, 1),
                 "media_duration": round(np_.duration, 1), "media_position_updated_at": np_.position_at}
        if np_.art_url:
            attrs["entity_picture"] = np_.art_url
        self._background(asyncio.to_thread(self._post_state, NOW_PLAYING_SENSOR,
                                           {"state": np_.label[:255], "attributes": attrs}))

    def _background(self, coro):
        task = asyncio.create_task(coro)
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
        self._background(self.now_playing.run(self.publish_now_playing))
        backoff = 1
        while True:
            try:
                self.ha = await HA.connect(token)
                pump = asyncio.create_task(self._pump())
                await self.ha.call(type="subscribe_events", event_type="state_changed")
                await self.ha.call(type="subscribe_events", event_type=COMMAND_EVENT)
                await self.ensure_helpers()
                log.info("connected to Home Assistant")
                backoff = 1
                await pump
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
                log.warning("Home Assistant connection lost (%s); retrying in %ds", e, backoff)
            except Exception:
                log.exception("controller error; reconnecting in %ds", backoff)
            self.ha = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _pump(self):
        async for event in self.ha.events():
            data = event["data"]
            if event["event_type"] == COMMAND_EVENT:
                self._background(self.command(data.get("command")))
                continue
            eid = data.get("entity_id")
            if eid in WATCHED and data.get("new_state"):
                self.apply(eid, data["new_state"]["state"], data["new_state"].get("attributes"))


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
