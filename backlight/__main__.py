"""The backlight service: makes the Bluetooth strip behind the cabinet a normal light in Home Assistant.

Home Assistant runs in Docker, which can't reach the Mac's Bluetooth, so this holds the connection instead. The
light, `light.tv_backlight`, is a template light (homeassistant/templates/tv_backlight.json) whose state lives in four
helpers: on/off, level (0-255), hue and saturation. This watches them and sends changes to the strip, so the Hub,
voice, Claude, scenes and automations all control it like any other light.

Music sync drives it directly while a show runs: it sends frames to UDP 127.0.0.1:BACKLIGHT_PORT (see
`backlight.live`). The latest intent wins: a show that starts takes the strip, even if it was switched off before, but
switching it off during a show takes it out of that show (switching it on again puts it back). When frames stop (or
music sync says it's done) the strip goes back to whatever Home
Assistant says. Run by ./home up.
"""
import asyncio
import json
import logging
import os
import time

import telemetry

import websockets

from music_sync.service import HA, load_env

from . import PORT
from .strip import FreshStart, Strip, frame_rgb, hs_to_rgb

log = logging.getLogger("backlight")
ON = "input_boolean.tv_backlight"
LEVEL = "input_number.tv_backlight_level"
HUE = "input_number.tv_backlight_hue"
SAT = "input_number.tv_backlight_saturation"
WATCHED = (ON, LEVEL, HUE, SAT)
LIVE_TIMEOUT_S = 2.0  # no frames for this long: music sync has stopped (or died), go back to Home Assistant's state


class Backlight:
    def __init__(self):
        self.strip = Strip()
        self.ha_state = {ON: "off", LEVEL: "128", HUE: "30", SAT: "70"}
        self.live_at = 0.0
        self.show_since = 0.0  # when the current show started
        self.left_show = False  # switched off during this show: stays off and out of it

    @property
    def live(self):
        return time.monotonic() - self.live_at < LIVE_TIMEOUT_S

    def apply_ha(self):
        if self.live and not self.left_show:
            return
        try:
            level = float(self.ha_state[LEVEL])
            rgb = hs_to_rgb(float(self.ha_state[HUE]), float(self.ha_state[SAT]))
        except ValueError:
            return
        on = self.ha_state[ON] == "on" and level > 0
        self.strip.set(on, rgb, max(1, round(level / 255 * 100)))

    def on_frame(self, frame: dict | None):
        if frame is None:  # music sync is done with it
            self.live_at = 0.0
            self.left_show = False
            self.apply_ha()
            return
        if not self.live:  # a new show: a newer intent than any earlier switch-off
            self.show_since = time.monotonic()
            self.left_show = False
        self.live_at = time.monotonic()
        if self.left_show:
            return
        rgb = frame_rgb(frame)
        self.strip.set(any(rgb), rgb, 100)

    def on_ha_change(self, entity: str, state: str):
        """A change to one of the strip's helpers. Switching it off during a show takes it out of the show (the latest
        intent wins); switching it on puts it back."""
        was = self.ha_state.get(entity)
        self.ha_state[entity] = state
        if entity == ON and self.live and state != was:
            self.left_show = state == "off"
            if not self.left_show:
                return  # back in the show: the next frame sets it
        self.apply_ha()

    async def expire_live(self):
        while True:
            await asyncio.sleep(0.5)
            if self.live_at and not self.live:
                log.info("music sync went quiet; back to Home Assistant's state")
                self.live_at = 0.0
                self.left_show = False
                self.apply_ha()

    async def follow_ha(self, token):
        backoff = 1
        while True:
            try:
                ha = await HA.connect(token)
                pump = asyncio.create_task(self._pump(ha))
                await ha.call(type="subscribe_events", event_type="state_changed")
                for s in await ha.call(type="get_states"):
                    if s["entity_id"] in WATCHED:
                        self.ha_state[s["entity_id"]] = s["state"]
                self.apply_ha()
                log.info("following Home Assistant")
                backoff = 1
                await pump
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
                log.warning("Home Assistant connection lost (%s); retrying in %ds", e, backoff)
            except Exception:
                log.exception("backlight error; reconnecting in %ds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _pump(self, ha):
        async for event in ha.events():
            data = event["data"]
            if data.get("entity_id") in WATCHED and data.get("new_state"):
                self.on_ha_change(data["entity_id"], data["new_state"]["state"])


class _Frames(asyncio.DatagramProtocol):
    def __init__(self, backlight: Backlight):
        self.backlight = backlight

    def datagram_received(self, data, addr):
        try:
            self.backlight.on_frame(json.loads(data))
        except (ValueError, KeyError, TypeError):
            pass


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    telemetry.setup("backlight")
    backlight = Backlight()
    loop = asyncio.get_running_loop()
    await loop.create_datagram_endpoint(lambda: _Frames(backlight), local_addr=("127.0.0.1", PORT))
    try:
        await asyncio.gather(backlight.strip.run(), backlight.follow_ha(os.environ["TOKEN"]), backlight.expire_live())
    except FreshStart as e:
        log.warning("strip: %s; exiting so the supervisor starts a fresh process", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
