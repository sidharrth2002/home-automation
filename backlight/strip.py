"""The TV backlight strip: a Bluetooth LED controller of the MELK / ELK-BLEDOM family (sold with "Lotus Lamp X" and
similar apps). One colour for the whole strip.

Its protocol is 9-byte commands written to characteristic FFF3, `7e .. .. .. .. .. .. .. ef`, with no reply:
power, brightness (0-100) and colour (r, g, b). Writes go out without waiting for an acknowledgement, at most MAX_HZ,
latest wins, so a slow radio never builds a backlog. The controller accepts one connection at a time: while this holds
it, the phone app can't connect (close the app if this can't find it).
"""
import asyncio
import colorsys
import logging
import math
import os
import time

from bleak import BleakClient, BleakScanner

log = logging.getLogger("backlight.strip")
WRITE = "0000fff3-0000-1000-8000-00805f9b34fb"
NAME_PREFIX = os.environ.get("BACKLIGHT_NAME", "MELK")
MAX_HZ = 20
SCAN_S = 15


def power(on: bool) -> bytes:
    return bytes([0x7e, 0x00, 0x04, 0xf0 if on else 0x00, 0x00, 0x01 if on else 0x00, 0xff, 0x00, 0xef])


def brightness(pct: int) -> bytes:
    return bytes([0x7e, 0x00, 0x01, max(0, min(100, round(pct))), 0x00, 0x00, 0x00, 0x00, 0xef])


def colour(r: int, g: int, b: int) -> bytes:
    return bytes([0x7e, 0x00, 0x05, 0x03, *(max(0, min(255, round(c))) for c in (r, g, b)), 0x00, 0xef])


def hs_to_rgb(hue: float, sat: float) -> tuple[int, int, int]:
    """Home Assistant's hue (0-360) and saturation (0-100), at full value; brightness is set separately."""
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360, max(0.0, min(1.0, sat / 100)), 1.0)
    return round(r * 255), round(g * 255), round(b * 255)


def kelvin_to_rgb(k: float) -> tuple[int, int, int]:
    """Approximate colour of white light at a colour temperature (Tanner Helland's fit), for music sync's TV mode."""
    t = max(1000, min(40000, k)) / 100
    r = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255 if t >= 66 else 0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    return tuple(max(0, min(255, round(c))) for c in (r, g, b))


def frame_rgb(frame: dict) -> tuple[int, int, int]:
    """A music sync frame (WiZ setPilot params: r/g/b or temp, plus dimming 0-100) as one scaled colour."""
    if frame.get("state") is False:
        return 0, 0, 0
    rgb = kelvin_to_rgb(frame["temp"]) if "temp" in frame else (frame.get("r", 0), frame.get("g", 0), frame.get("b", 0))
    dim = frame.get("dimming", 100) / 100
    return tuple(round(c * dim) for c in rgb)


class Strip:
    """Keeps a connection open and sends the newest wanted state: (on, (r, g, b), brightness %)."""

    def __init__(self):
        self.client: BleakClient | None = None
        self.wanted: tuple | None = None
        self.sent: tuple | None = None  # what the strip has been told; None after a (re)connect
        self.connected = asyncio.Event()
        self._wake = asyncio.Event()

    def set(self, on: bool, rgb=(255, 255, 255), pct: int = 100):
        self.wanted = (bool(on), tuple(rgb), int(pct))
        self._wake.set()

    async def run(self):
        backoff = 2
        while True:
            try:
                await self._connect()
                backoff = 2
                await self._send_loop()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("strip: %s; retrying in %ds", e or type(e).__name__, backoff)
            self.connected.clear()
            if self.client:
                try:
                    await self.client.disconnect()
                except Exception:
                    pass
            self.client = None
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _connect(self):
        dev = await BleakScanner.find_device_by_filter(
            lambda d, a: (d.name or a.local_name or "").startswith(NAME_PREFIX), timeout=SCAN_S)
        if not dev:
            raise ConnectionError(f"no {NAME_PREFIX}* strip in range (is its phone app connected to it?)")
        self.client = BleakClient(dev, timeout=20, disconnected_callback=lambda _: self._wake.set())
        await self.client.connect()
        self.sent = None
        self.connected.set()
        log.info("connected to %s", dev.name)

    async def _send_loop(self):
        gap = 1 / MAX_HZ
        last = 0.0
        while True:
            await self._wake.wait()
            self._wake.clear()
            if not self.client.is_connected:
                raise ConnectionError("disconnected")
            if self.wanted is None or self.wanted == self.sent:
                continue
            wait = last + gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            want = self.wanted
            on, rgb, pct = want
            old = self.sent
            if not on:
                await self._write(power(False))
            else:
                if old is None or not old[0]:
                    await self._write(power(True))
                if old is None or old[2] != pct or not old[0]:
                    await self._write(brightness(pct))
                if old is None or old[1] != rgb or not old[0]:
                    await self._write(colour(*rgb))
            self.sent, last = want, time.monotonic()
            if self.wanted != want:
                self._wake.set()

    async def _write(self, data: bytes):
        await self.client.write_gatt_char(WRITE, data, response=False)
