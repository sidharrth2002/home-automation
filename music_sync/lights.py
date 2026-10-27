"""Robust WiZ output for beat sync.

- Bulbs are tracked by MAC and (re)discovered on the LAN, so DHCP changes don't break us.
- Beats are sent as fire-and-forget UDP setPilot datagrams (no waiting on replies), at most
  MAX_HZ per bulb, always latest-wins so a slow bulb never builds a backlog.
- A heartbeat marks bulbs unhealthy/healthy and re-resolves their IP when they stop answering.
- The pre-sync state of every bulb is saved to disk, so it can be restored even after a crash.
"""
import asyncio
import json
import logging
import os
import socket
import time
from pathlib import Path

from pywizlight import PilotBuilder, discovery, wizlight

from .engine import Beat

log = logging.getLogger("music_sync.lights")

WIZ_PORT = 38899
MAX_HZ = 15
HEARTBEAT_S = 20
STATE_FILE = Path(__file__).resolve().parent.parent / ".music_sync_saved_state.json"


def _broadcast_addr() -> str:
    """Best-effort /24 broadcast for the active interface."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        return ".".join(ip.split(".")[:3] + ["255"])
    except OSError:
        return "255.255.255.255"


class Bulb:
    def __init__(self, mac: str, ip: str):
        self.mac, self.ip = mac, ip
        self.healthy = True
        self.pending: dict | None = None
        self.last_sent = 0.0
        self.saved: dict | None = None


class _Sink(asyncio.DatagramProtocol):
    """Ignore bulb replies; we only care that sends don't raise."""

    def error_received(self, exc):
        log.debug("udp error: %s", exc)


class Lights:
    def __init__(self, extra_ips: list[str] | None = None):
        self.bulbs: dict[str, Bulb] = {}
        self._extra_ips = extra_ips or [i for i in os.environ.get("WIZ_BULB_IPS", "").split(",") if i]
        self._transport: asyncio.DatagramTransport | None = None
        self._tasks: list[asyncio.Task] = []
        self._wake = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------
    async def start(self):
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(_Sink, family=socket.AF_INET, local_addr=("0.0.0.0", 0))
        await self.discover()
        if not self.bulbs:
            raise RuntimeError("No WiZ bulbs found; set WIZ_BULB_IPS or check 'Allow local communication' in the WiZ app")
        await self._save_state()
        self._tasks = [asyncio.create_task(self._sender()), asyncio.create_task(self._heartbeat())]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        await self.restore()
        if self._transport:
            self._transport.close()

    # -- discovery ---------------------------------------------------------
    async def discover(self):
        found = {}
        try:
            for b in await discovery.discover_lights(broadcast_space=_broadcast_addr(), wait_time=3):
                found[await b.getMac()] = b.ip
        except Exception as e:
            log.warning("broadcast discovery failed: %s", e)
        for ip in self._extra_ips:
            try:
                found.setdefault(await wizlight(ip).getMac(), ip)
            except Exception as e:
                log.warning("bulb %s unreachable: %s", ip, e)
        for mac, ip in found.items():
            if mac in self.bulbs:
                if self.bulbs[mac].ip != ip:
                    log.info("bulb %s moved %s -> %s", mac, self.bulbs[mac].ip, ip)
                self.bulbs[mac].ip = ip
                self.bulbs[mac].healthy = True
            else:
                self.bulbs[mac] = Bulb(mac, ip)
                log.info("found bulb %s at %s", mac, ip)

    # -- output ------------------------------------------------------------
    def show(self, beat: Beat):
        """Non-blocking: replace each bulb's pending frame with the newest one."""
        frame = {"state": True, "r": beat.rgb[0], "g": beat.rgb[1], "b": beat.rgb[2],
                 "dimming": max(10, round(beat.brightness * 100 / 255))}
        for bulb in self.bulbs.values():
            bulb.pending = frame
        self._wake.set()

    async def _sender(self):
        min_gap = 1 / MAX_HZ
        while True:
            await self._wake.wait()
            self._wake.clear()
            now = time.monotonic()
            next_due = None
            for bulb in self.bulbs.values():
                if bulb.pending is None:
                    continue
                wait = bulb.last_sent + min_gap - now
                if wait > 0:
                    next_due = wait if next_due is None else min(next_due, wait)
                    continue
                self._send(bulb, bulb.pending)
                bulb.pending, bulb.last_sent = None, now
            if next_due is not None:
                await asyncio.sleep(next_due)
                self._wake.set()

    def _send(self, bulb: Bulb, params: dict):
        msg = json.dumps({"method": "setPilot", "params": params}).encode()
        try:
            self._transport.sendto(msg, (bulb.ip, WIZ_PORT))
        except OSError as e:
            log.warning("send to %s failed: %s", bulb.ip, e)
            bulb.healthy = False

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            lost = False
            for bulb in self.bulbs.values():
                try:
                    await asyncio.wait_for(wizlight(bulb.ip).updateState(), 2)
                    if not bulb.healthy:
                        log.info("bulb %s is back", bulb.mac)
                    bulb.healthy = True
                except Exception:
                    if bulb.healthy:
                        log.warning("bulb %s at %s stopped responding", bulb.mac, bulb.ip)
                    bulb.healthy, lost = False, True
            if lost:
                await self.discover()

    # -- state save / restore ---------------------------------------------
    async def _save_state(self):
        # A leftover file means a previous run died mid-sync; its snapshot is the real "before".
        if STATE_FILE.exists():
            try:
                old = json.loads(STATE_FILE.read_text())
                for mac, st in old.items():
                    if mac in self.bulbs:
                        self.bulbs[mac].saved = st
                log.info("recovered saved light state from a previous unclean exit")
                return
            except (OSError, ValueError):
                log.warning("ignoring unreadable %s", STATE_FILE)
        snap = {}
        for mac, bulb in self.bulbs.items():
            try:
                st = (await wizlight(bulb.ip).updateState())[0]
                bulb.saved = {"on": bool(st.get_state()), "brightness": st.get_brightness(),
                              "rgb": st.get_rgb(), "colortemp": st.get_colortemp()}
                snap[mac] = bulb.saved
            except Exception as e:
                log.warning("could not read state of %s: %s", bulb.ip, e)
        STATE_FILE.write_text(json.dumps(snap))

    async def restore(self):
        for bulb in self.bulbs.values():
            st = bulb.saved
            if not st:
                continue
            try:
                w = wizlight(bulb.ip)
                if not st["on"]:
                    await w.turn_off()
                elif st.get("colortemp"):
                    await w.turn_on(PilotBuilder(colortemp=st["colortemp"], brightness=st["brightness"]))
                elif st.get("rgb") and any(st["rgb"]):
                    await w.turn_on(PilotBuilder(rgb=tuple(st["rgb"]), brightness=st["brightness"]))
                else:
                    await w.turn_on(PilotBuilder(brightness=st["brightness"]))
            except Exception as e:
                log.warning("could not restore %s: %s", bulb.ip, e)
        STATE_FILE.unlink(missing_ok=True)
