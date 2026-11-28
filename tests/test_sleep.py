"""The music sleep timer: start, the fade, extend, cancel and the end, against fake Spotify, HA and adb.

Run: .venv/bin/python -m tests.test_sleep
"""
import asyncio
import tempfile
from pathlib import Path
from unittest import mock

import sleep.__main__ as sl


class FakeSpotify:
    def __init__(self, tv=True):
        self.calls, self.tv = [], tv

    def tv_device(self):
        return {"id": "tv1", "name": "Living room TV", "type": "TV", "volume_percent": 40} if self.tv else None

    def play(self, d, uri): self.calls.append(("play", d, uri))
    def pause(self, d): self.calls.append(("pause", d))
    def volume(self, d, v): self.calls.append(("volume", d, v))


def run():
    assert sl.fade_volume(40, 3600) == 40 and sl.fade_volume(40, sl.FADE_S) == 40
    assert sl.fade_volume(40, sl.FADE_S / 2) == 20 and sl.fade_volume(40, 0) == 0 and sl.fade_volume(40, -5) == 0

    with tempfile.TemporaryDirectory() as d:
        sl.STATE = Path(d) / "sleep.json"
        clock = [1000.0]
        ha, adb, reports = [], [], []
        sp = FakeSpotify()

        async def ha_service(domain, service, entity):
            ha.append((domain, service, entity))

        async def tv_off():
            return "off"

        async def adb_timer(m):
            adb.append(m)

        s = sl.Sleeper(ha_service, tv_off, adb_timer, lambda e, st, a: reports.append((e, st, a)),
                       now=lambda: clock[0], sp=sp)
        playlists = [{"name": "Night", "uri": "spotify:playlist:1", "image": "https://i/1.jpg"}]

        real_sleep = asyncio.sleep

        async def scenario():
            with mock.patch("asyncio.sleep", new=lambda *_: real_sleep(0)):
                await s.start("spotify:playlist:1", "", 30, playlists)
                assert reports[0][1] == "on", "on before the TV wakes (the bias lighting reads it)"
                assert ("media_player", "turn_on", sl.TV) in ha, "the TV is woken"
                assert ("play", "tv1", "spotify:playlist:1") in sp.calls
                assert ("script", "turn_on", "script.sleep_lights") in ha
                assert adb[-1] == 32, "the TV's own timer as a backup, a little later"
                assert reports[-1][2]["playlist"] == "Night" and reports[-1][2]["image"] == "https://i/1.jpg"
                assert sl.STATE.exists(), "survives a restart"

                clock[0] += 10 * 60  # 20 min left: no fade yet
                await s.tick()
                assert not [c for c in sp.calls if c[0] == "volume"]
                clock[0] += 15 * 60  # 5 min left: halfway down
                await s.tick()
                assert sp.calls[-1] == ("volume", "tv1", 20)
                clock[0] += 10  # tiny steps aren't sent
                await s.tick()
                assert sp.calls[-1] == ("volume", "tv1", 20)

                await s.extend(15)
                assert sp.calls[-1] == ("volume", "tv1", 40), "more time: the volume back up, the fade later"
                assert adb[-1] == 22 and s.t["minutes"] == 45

                clock[0] += 30 * 60  # past the end
                await s.tick()
                assert ("pause", "tv1") in sp.calls and sp.calls[-1] == ("volume", "tv1", 40), "paused, volume reset"
                assert ("media_player", "turn_off", sl.TV) in ha and ("light", "turn_off", sl.ROOM_LIGHTS) in ha
                assert s.t is None and reports[-1][1] == "off" and not sl.STATE.exists()

                # cancel: the music carries on; the TV's backup timer is cleared
                await s.start("spotify:playlist:1", "Night", 45, playlists)
                await s.cancel()
                assert adb[-1] == -1 and s.t is None and reports[-1][1] == "off"
                assert sp.calls[-1][0] == "play", "cancel doesn't pause the music"

                # the TV never appears in Spotify: a clear message, nothing left running
                s.sp = FakeSpotify(tv=False)
                with mock.patch.object(sl, "DEVICE_WAIT_S", 0):
                    await s.start("spotify:playlist:1", "Night", 30, playlists)
                assert s.t is None and reports[-1][1] == "off" and "didn't show up" in reports[-1][2]["error"]

                # a restart mid-timer resumes it
                s.sp = sp
                await s.start("spotify:playlist:1", "Night", 30, playlists)
                again = sl.Sleeper(ha_service, tv_off, adb_timer, lambda *a: None, now=lambda: clock[0], sp=sp)
                again.resume()
                assert again.t and again.t["uri"] == "spotify:playlist:1"
        asyncio.run(scenario())

    assert sl.spotify.cover([{"url": "big", "width": 640}, {"url": "mid", "width": 300}, {"url": "tiny", "width": 60}]) == "mid"
    assert sl.spotify.cover([{"url": "mosaic", "width": None}]) == "mosaic" and sl.spotify.cover([]) is None
    print("sleep timer OK")


if __name__ == "__main__":
    run()
