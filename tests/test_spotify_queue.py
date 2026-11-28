"""Spotify's queue for the Hub: reading it, add, skip-to and search, against a fake Spotify.

Run: .venv/bin/python -m tests.test_spotify_queue
"""
import asyncio
from unittest import mock

import spotify_queue.__main__ as sq
from sleep import spotify


class FakeSpotify:
    def __init__(self):
        self.calls = []
        self.up = [{"name": f"Song {i}", "artist": "A", "image": None, "uri": f"spotify:track:{i}"} for i in range(30)]

    def queue(self):
        return {"name": "Now", "artist": "A", "image": None, "uri": "spotify:track:now"}, self.up

    def add_to_queue(self, uri): self.calls.append(("add", uri))
    def next_track(self): self.calls.append(("next",))
    def search(self, q): return [{"name": q, "artist": "B", "image": None, "uri": "spotify:track:s"}]


def run():
    album = {"uri": "spotify:track:1", "name": "Alright", "artists": [{"name": "Gracie Abrams"}, {"name": "X"}],
             "album": {"images": [{"url": "big", "width": 640}, {"url": "small", "width": 64}]}}
    assert spotify.track(album) == {"name": "Alright", "artist": "Gracie Abrams, X", "image": "small", "uri": "spotify:track:1"}
    episode = {"uri": "spotify:episode:1", "name": "Ep", "show": {"name": "Pod", "images": [{"url": "p"}]}}
    assert spotify.track(episode)["artist"] == "Pod" and spotify.track(episode)["image"] == "p"
    assert spotify.track(None) is None and spotify.track({"name": "no uri"}) is None

    reports = []
    sp = FakeSpotify()
    q = sq.Queue(lambda e, s, a: reports.append((e, s, a)), sp=sp)

    async def scenario():
        with mock.patch("asyncio.sleep", new=lambda *_: real_sleep(0)):
            await q.refresh()
            assert reports[-1][0] == sq.QUEUE and reports[-1][1] == "30" and len(reports[-1][2]["queue"]) == sq.SHOWN
            assert q.playing
            await q.refresh()
            assert len(reports) == 1, "an unchanged queue isn't sent again"

            await q.handle({"action": "add", "uri": "spotify:track:9"})
            assert sp.calls == [("add", "spotify:track:9")]
            await q.handle({"action": "add", "uri": "https://evil"})
            assert len(sp.calls) == 1, "only Spotify URIs"

            sp.calls.clear()
            await q.handle({"action": "skip", "index": "2"})
            assert sp.calls == [("next",)] * 3, "the third one up: next three times"
            sp.calls.clear()
            await q.handle({"action": "skip", "index": 500})
            assert len(sp.calls) == sq.MAX_SKIP, "never more than the shown queue"

            await q.handle({"action": "search", "q": "  gracie  "})
            assert reports[-1][0] == sq.SEARCH and reports[-1][1] == "gracie" and reports[-1][2]["results"][0]["name"] == "gracie"
            await q.handle({"action": "clear"})
            assert reports[-1] == (sq.SEARCH, "", {"results": []})

            def broken():
                raise spotify.SpotifyError(401, "no token")
            sp.queue = broken
            await q.refresh()  # logged, nothing reported, no crash
            assert reports[-1][0] == sq.SEARCH
    real_sleep = asyncio.sleep
    asyncio.run(scenario())
    print("spotify queue OK")


if __name__ == "__main__":
    run()
