"""Fall asleep to music: a Spotify playlist on the TV, the room winding down, the music fading out, then off.

Home Assistant's `home_sleep` event drives it (script.sleep_timer_start / _cancel / _extend, which the Hub, the TV
app and the phone call):

- start {playlist, name, minutes}: the TV on if it's off; the playlist on the TV through Spotify Connect; the Sleep
  lights (music sync off, a warm glow stepping down to dark); and the TV's own sleep timer set a couple of minutes
  later than ours over adb, so the TV still turns itself off if this machine or Spotify isn't there at the end
- the last FADE_S: the TV's Spotify volume eases down to nothing (no sudden silence to wake you)
- the end: music paused, the volume put back for next time, the TV and the lights off
- cancel: the timer stops, the music carries on at its volume; extend {minutes}: more time (the fade restarts)

It reports sensor.sleep_timer (on/off; ends_at, minutes, playlist, image) and sensor.spotify_playlists (your
playlists for the pickers) through core. A running timer survives a restart of this service (data/sleep.json).
Run by ./home up.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import telemetry

import websockets

from core import client as core
from music_sync.service import HA, load_env

from . import spotify

log = logging.getLogger("sleep")
ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "sleep.json"
EVENT = "home_sleep"
TIMER = "sensor.sleep_timer"
PLAYLISTS = "sensor.spotify_playlists"
TV = "media_player.smart_tv_pro"
ROOM_LIGHTS = ["light.wiz_rgbw_tunable_624d4e", "light.wiz_rgbw_tunable_4b472c", "light.tv_backlight", "light.desk_lamp"]
FADE_S = 600  # the music fades out over the last 10 minutes
TICK_S = 15
TV_BACKUP_MIN = 2  # the TV's own timer runs this much longer than ours
PLAYLISTS_EVERY_S = 1800
DEVICE_WAIT_S = 60


def fade_volume(start: int, remaining_s: float) -> int:
    """The volume with `remaining_s` to go: full until the fade, then down in a straight line to 0."""
    if remaining_s >= FADE_S:
        return start
    return max(0, round(start * max(0.0, remaining_s) / FADE_S))


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class Sleeper:
    """The running timer (or none). The outside world comes in as callables, so tests can fake it."""

    def __init__(self, ha_service, tv_state, adb_timer, report, now=time.time, sp=spotify):
        self.ha_service, self.tv_state, self.adb_timer, self.report, self.now, self.sp = \
            ha_service, tv_state, adb_timer, report, now, sp
        self.t: dict | None = None  # {ends, minutes, uri, name, image, device, volume, applied}

    # ── what the UIs see ──
    def publish(self, error: str | None = None):
        t = self.t
        attrs = {"friendly_name": "Sleep timer", "icon": "mdi:bed-clock"}
        if t:
            attrs.update(ends_at=iso(t["ends"]), minutes=t["minutes"], playlist=t["name"], image=t.get("image"),
                         uri=t["uri"])
        if error:
            attrs["error"] = error
        self.report(TIMER, "on" if t else "off", attrs)

    def save(self):
        STATE.parent.mkdir(parents=True, exist_ok=True)
        if self.t:
            STATE.write_text(json.dumps(self.t))
        else:
            STATE.unlink(missing_ok=True)

    def resume(self):
        """After a restart: carry on with a timer that hasn't run out."""
        try:
            t = json.loads(STATE.read_text())
        except (OSError, ValueError):
            return
        if t.get("ends", 0) > self.now():
            self.t = t
            log.info("resuming the sleep timer: %d min left", (t["ends"] - self.now()) // 60)
        else:
            STATE.unlink(missing_ok=True)

    # ── commands ──
    async def start(self, uri: str, name: str, minutes: int, playlists: list[dict]):
        minutes = max(5, min(180, int(minutes)))
        if self.t:  # a new start replaces the running one (its volume first)
            await self._restore_volume()
        image = next((p.get("image") for p in playlists if p["uri"] == uri), None)
        name = name or next((p["name"] for p in playlists if p["uri"] == uri), "Spotify")
        # "on" before the TV wakes, so the TV's bias lighting stays out of the way
        self.t = {"ends": self.now() + minutes * 60, "minutes": minutes, "uri": uri, "name": name, "image": image,
                  "device": None, "volume": None, "applied": None}
        self.publish()
        if (await self.tv_state()) != "on":
            await self.ha_service("media_player", "turn_on", TV)
        device = await self._wait_for_tv()
        if not device:
            self.t = None
            self.save()
            self.publish("The TV didn't show up in Spotify. Is the TV on, and Spotify signed in on it?")
            return
        self.t["device"], self.t["volume"] = device["id"], device.get("volume_percent") or 30
        await asyncio.to_thread(self.sp.play, device["id"], uri)
        await self.ha_service("script", "turn_on", "script.sleep_lights")
        await self._tv_backup(minutes)
        self.save()
        self.publish()
        log.info("sleep timer: %s for %d min", name, minutes)

    async def cancel(self):
        if not self.t:
            return self.publish()
        await self._restore_volume()
        await self.adb_timer(-1)
        self.t = None
        self.save()
        self.publish()
        log.info("sleep timer cancelled")

    async def extend(self, minutes: int):
        if not self.t:
            return self.publish()
        self.t["ends"] = max(self.t["ends"], self.now()) + max(1, int(minutes)) * 60
        self.t["minutes"] += int(minutes)
        await self._restore_volume()  # the fade starts again from the top
        await self._tv_backup((self.t["ends"] - self.now()) / 60)
        self.save()
        self.publish()

    async def tick(self):
        """Every TICK_S: fade, or finish."""
        if not self.t or not self.t.get("device"):
            return
        left = self.t["ends"] - self.now()
        if left <= 0:
            return await self.finish()
        want = fade_volume(self.t["volume"], left)
        applied = self.t.get("applied")
        if want != (applied if applied is not None else self.t["volume"]) and \
                (applied is None or abs(want - applied) >= 2 or want == 0):
            await asyncio.to_thread(self.sp.volume, self.t["device"], want)
            self.t["applied"] = want
            self.save()

    async def finish(self):
        t = self.t
        log.info("sleep timer done: pausing and turning everything off")
        try:
            await asyncio.to_thread(self.sp.pause, t["device"])
            await asyncio.sleep(1)
            await asyncio.to_thread(self.sp.volume, t["device"], t["volume"])  # back to normal for next time
        except OSError as e:
            log.warning("couldn't pause or reset Spotify: %s", e)
        await self.ha_service("media_player", "turn_off", TV)
        await self.ha_service("script", "turn_off", "script.sleep_lights")  # a timer shorter than the wind-down
        await self.ha_service("light", "turn_off", ROOM_LIGHTS)
        await asyncio.sleep(10)  # "on" until the TV is off, so its bias lighting doesn't put the lights back on
        self.t = None
        self.save()
        self.publish()

    # ── helpers ──
    async def _wait_for_tv(self):
        deadline = self.now() + DEVICE_WAIT_S
        while True:
            try:
                device = await asyncio.to_thread(self.sp.tv_device)
                if device:
                    return device
            except OSError as e:
                log.debug("Spotify devices: %s", e)
            if self.now() >= deadline:
                return None
            await asyncio.sleep(3)

    async def _restore_volume(self):
        t = self.t
        if t and t.get("device") and t.get("applied") is not None and t["applied"] != t["volume"]:
            try:
                await asyncio.to_thread(self.sp.volume, t["device"], t["volume"])
            except OSError as e:
                log.warning("couldn't put the volume back: %s", e)
        if t:
            t["applied"] = None

    async def _tv_backup(self, minutes_left: float):
        await self.adb_timer(int(minutes_left + 0.999) + TV_BACKUP_MIN)


# ── the TV's own timer, over adb (as the Home Button watchdog reaches the TV) ──
async def set_tv_timer(minutes: int):
    """The TCL TV's sleep timer: global tcl_app_power_off_time_delay, in minutes; -1 cancels it. Its own service
    (com.tcl.shutdowndialog) watches the setting and starts the countdown at once."""
    from home_button.__main__ import serial, shell

    def go():
        s = serial()
        if not s:
            return log.warning("TV not reachable over adb: no backup sleep timer on the TV")
        shell(s, "settings", "put", "global", "tcl_app_power_off_time_delay", str(minutes))
    try:
        await asyncio.to_thread(go)
    except OSError as e:
        log.warning("couldn't set the TV's sleep timer: %s", e)


async def refresh_playlists(cache: list):
    try:
        found = await asyncio.to_thread(spotify.playlists)
    except OSError as e:
        return log.warning("couldn't read the Spotify playlists: %s", e)
    cache[:] = found
    try:
        await asyncio.to_thread(core.report, PLAYLISTS, len(found),
                                {"friendly_name": "Spotify playlists", "icon": "mdi:playlist-music", "playlists": found})
    except OSError as e:
        log.warning("couldn't report the playlists: %s", e)


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    telemetry.setup("sleep")
    token = os.environ["TOKEN"]
    playlists: list[dict] = []
    ha_ref: dict = {}

    async def ha_service(domain, service, entity_id):
        if ha_ref.get("ha"):
            await ha_ref["ha"].service(domain, service, entity_id)

    async def tv_state():
        try:
            for s in await ha_ref["ha"].call(type="get_states"):
                if s["entity_id"] == TV:
                    return s["state"]
        except (KeyError, RuntimeError, asyncio.TimeoutError):
            pass
        return None

    await asyncio.to_thread(core.ready, 120)  # started alongside the core

    def report_now(entity, state, attrs):
        try:
            core.report(entity, state, attrs)
        except OSError as e:
            log.warning("couldn't report %s: %s", entity, e)

    def report(entity, state, attrs):  # from async code: off the event loop, never blocking it
        asyncio.get_running_loop().run_in_executor(None, report_now, entity, state, attrs)
    sleeper = Sleeper(ha_service, tv_state, set_tv_timer, report)
    sleeper.resume()

    async def background():
        last = 0.0
        while True:
            if time.time() - last > PLAYLISTS_EVERY_S:
                await refresh_playlists(playlists)
                last = time.time()
            try:
                await sleeper.tick()
            except Exception:
                log.exception("sleep timer tick failed")
            await asyncio.sleep(TICK_S)

    async def handle(data: dict):
        action = data.get("action")
        try:
            if action == "start" and data.get("playlist"):
                if not playlists:
                    await refresh_playlists(playlists)
                await sleeper.start(data["playlist"], data.get("name") or "", int(data.get("minutes") or 45), playlists)
            elif action == "cancel":
                await sleeper.cancel()
            elif action == "extend":
                await sleeper.extend(int(data.get("minutes") or 15))
        except spotify.SpotifyError as e:
            log.warning("sleep timer: %s", e)
            sleeper.t = None
            sleeper.save()
            sleeper.publish("Spotify wouldn't start it" + (" (Premium needed)" if e.status == 403 else f": {e}"))

    asyncio.create_task(background())
    backoff = 1
    while True:
        try:
            ha = await HA.connect(token)
            ha_ref["ha"] = ha
            pump = asyncio.create_task(_listen(ha, handle))
            await ha.call(type="subscribe_events", event_type=EVENT)
            sleeper.publish()
            log.info("listening for %s", EVENT)
            backoff = 1
            await pump
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
            log.warning("Home Assistant connection lost (%s); retrying in %ds", e, backoff)
        ha_ref.pop("ha", None)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


async def _listen(ha: HA, handle):
    async for event in ha.events():
        if event.get("event_type") == EVENT:
            asyncio.create_task(handle(event.get("data") or {}))  # never block the pump: handlers call HA themselves


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["login"]:  # once: this service's own Spotify sign-in (see sleep/spotify.py)
        load_env()
        spotify.login()
    else:
        asyncio.run(main())
