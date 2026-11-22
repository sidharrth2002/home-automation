"""The backlight strip: its command bytes, colour conversions, and who's in charge (music sync or Home Assistant).

Run: .venv/bin/python -m tests.test_backlight
"""
from backlight import strip
from backlight.__main__ import HUE, LEVEL, ON, SAT, Backlight


class FakeStrip:
    def __init__(self):
        self.wanted = None

    def set(self, on, rgb=(255, 255, 255), pct=100):
        self.wanted = (bool(on), tuple(rgb), int(pct))


def run():
    assert strip.power(True).hex() == "7e0004f00001ff00ef"
    assert strip.power(False).hex() == "7e0004000000ff00ef"
    assert strip.brightness(25).hex() == "7e00011900000000ef"
    assert strip.brightness(150)[3] == 100, "brightness is clamped to 0-100"
    assert strip.colour(255, 120, 30).hex() == "7e000503ff781e00ef"

    assert strip.hs_to_rgb(0, 100) == (255, 0, 0)
    assert strip.hs_to_rgb(120, 0) == (255, 255, 255)
    warm, cool = strip.kelvin_to_rgb(2200), strip.kelvin_to_rgb(6500)
    assert warm[0] == 255 and warm[2] < cool[2], "warm white is red-heavy, cool white has more blue"
    assert strip.frame_rgb({"r": 200, "g": 100, "b": 0, "dimming": 50}) == (100, 50, 0)
    assert strip.frame_rgb({"state": False}) == (0, 0, 0)
    assert strip.frame_rgb({"temp": 2400, "dimming": 10})[0] == 26

    b = Backlight()
    b.strip = FakeStrip()
    b.ha_state.update({ON: "on", LEVEL: "255", HUE: "0", SAT: "100"})
    b.apply_ha()
    assert b.strip.wanted == (True, (255, 0, 0), 100)
    b.on_frame({"r": 0, "g": 0, "b": 255, "dimming": 40})
    assert b.strip.wanted == (True, (0, 0, 102), 100), "music sync frames drive the strip"
    b.ha_state[HUE] = "120"
    b.apply_ha()
    assert b.strip.wanted[1] == (0, 0, 102), "Home Assistant waits while music sync is live"
    b.on_frame(None)
    assert b.strip.wanted == (True, (0, 255, 0), 100), "handed back to Home Assistant's latest state"
    b.ha_state[ON] = "off"
    b.apply_ha()
    assert b.strip.wanted[0] is False
    b.ha_state.update({ON: "on", LEVEL: "1"})
    b.apply_ha()
    assert b.strip.wanted[2] == 1, "the lowest level is still on"

    # the latest intent wins: switched off during a show, the strip leaves it; switched on, it rejoins
    b = Backlight(); b.strip = FakeStrip()
    b.ha_state.update({ON: "off", LEVEL: "200", HUE: "30", SAT: "60"})
    b.on_frame({"r": 255, "g": 0, "b": 0, "dimming": 100})
    assert b.strip.wanted == (True, (255, 0, 0), 100), "a show that starts takes the strip, even if it was off before"
    b.on_ha_change(ON, "on"); b.on_ha_change(ON, "off")
    assert b.strip.wanted[0] is False, "switched off during the show: off now"
    b.on_frame({"r": 0, "g": 255, "b": 0, "dimming": 100})
    assert b.strip.wanted[0] is False, "and the show's next frames don't bring it back"
    b.on_ha_change(LEVEL, "100")
    assert b.strip.wanted[0] is False, "other helper changes keep it off"
    b.on_ha_change(ON, "on")
    b.on_frame({"r": 0, "g": 0, "b": 255, "dimming": 100})
    assert b.strip.wanted == (True, (0, 0, 255), 100), "switched on again: back in the show"
    b.on_ha_change(ON, "off"); b.on_frame(None)
    assert b.strip.wanted[0] is False and not b.left_show, "show over: Home Assistant's state (off), and the slate is clean"
    b.on_frame({"r": 9, "g": 9, "b": 9, "dimming": 100})
    assert b.strip.wanted[0] is True, "a new show later takes it again"
    print("backlight OK")
    keepalive()


def keepalive():
    """With nothing to send, the link is exercised every KEEPALIVE_S, so a quietly dead one is found in the background."""
    import asyncio

    class Client:
        is_connected = True
        def __init__(self): self.writes = []
        async def write_gatt_char(self, char, data, response=False): self.writes.append(bytes(data))

    async def go():
        st = strip.Strip()
        st.client = Client()
        st.set(True, (255, 0, 0), 50)
        old = strip.KEEPALIVE_S
        strip.KEEPALIVE_S = 0.2
        try:
            task = asyncio.create_task(st._send_loop())
            await asyncio.sleep(0.1)
            n = len(st.client.writes)
            assert n == 3, st.client.writes  # power, brightness, colour
            await asyncio.sleep(0.5)
            extra = st.client.writes[n:]
            assert extra and all(w == strip.power(True) for w in extra), "idle: only the unchanged power state, again"
            st.client.is_connected = False
            st._wake.set()
            await asyncio.sleep(0.05)
            assert task.done() and isinstance(task.exception(), ConnectionError), "a dead link ends the loop, to reconnect"
        finally:
            strip.KEEPALIVE_S = old
    asyncio.run(go())
    print("strip keepalive OK")


if __name__ == "__main__":
    run()
