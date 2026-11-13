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
    print("backlight OK")


if __name__ == "__main__":
    run()
