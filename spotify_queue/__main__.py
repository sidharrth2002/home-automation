"""Spotify's queue for the Hub and the TV app: what's up next, jump to a track in it, search and add a song.

It reports sensor.spotify_queue (state: how many are up next; now, queue: name, artist, image, uri) through core,
fresh within a moment of a track change (a trigger on the now-playing sensor) and every POLL_S anyway, and
sensor.spotify_search (state: the query; results) after a search. Home Assistant's `home_spotify` event drives the
rest (script.spotify_queue, with an action):

- add {uri}: onto the end of your queue (before the rest of the playlist)
- skip {index}: jump to that track in Up next (Spotify has no "play this one", so: next, that many times)
- search {q}: the top tracks, into sensor.spotify_search; clear: empty it again

Spotify's API can't remove or reorder queued tracks, so neither can this. It uses the sleep timer's Spotify
sign-in (sleep/spotify.py). Run by ./home up.
"""
import asyncio
import logging
import os

import telemetry

import websockets

from core import client as core
from music_sync.service import HA, load_env
from sleep import spotify

log = logging.getLogger("spotify_queue")
EVENT = "home_spotify"
QUEUE = "sensor.spotify_queue"
SEARCH = "sensor.spotify_search"
NOW = "sensor.music_sync_now_playing"
POLL_S = 20
IDLE_POLL_S = 120  # nothing playing: look less often
SHOWN = 20  # Spotify sends about this many anyway
MAX_SKIP = 20


class Queue:
    """The queue as last read, and the actions on it. Spotify and the reporting come in as arguments, for tests."""

    def __init__(self, report, sp=spotify):
        self.report, self.sp = report, sp
        self.last = None  # what was reported, so an unchanged queue isn't sent again
        self.playing = False

    async def refresh(self):
        try:
            now, up = await asyncio.to_thread(self.sp.queue)
        except spotify.SpotifyError as e:
            return log.warning("couldn't read the Spotify queue: %s", e)
        self.playing = now is not None
        attrs = {"now": now, "queue": up[:SHOWN]}
        if attrs != self.last:
            self.last = attrs
            self.report(QUEUE, str(len(up)), attrs)

    async def handle(self, data: dict):
        action = data.get("action")
        try:
            if action == "add" and str(data.get("uri", "")).startswith("spotify:"):
                await asyncio.to_thread(self.sp.add_to_queue, data["uri"])
            elif action == "skip":
                for _ in range(min(int(data.get("index") or 0), MAX_SKIP - 1) + 1):
                    await asyncio.to_thread(self.sp.next_track)
                    await asyncio.sleep(0.25)  # one at a time, or Spotify drops some
            elif action == "search" and str(data.get("q", "")).strip():
                q = str(data["q"]).strip()[:100]
                self.report(SEARCH, q[:250], {"results": await asyncio.to_thread(self.sp.search, q)})
                return
            elif action == "clear":
                self.report(SEARCH, "", {"results": []})
                return
            else:
                return
        except spotify.SpotifyError as e:
            log.warning("spotify queue %s: %s", action, e)
            return
        await asyncio.sleep(0.8)  # Spotify's queue catches up a moment after a change
        await self.refresh()


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    telemetry.setup("spotify_queue")
    token = os.environ["TOKEN"]
    await asyncio.to_thread(core.ready, 120)  # started alongside the core

    def report_now(entity, state, attrs):
        try:
            core.report(entity, state, attrs)
        except OSError as e:
            log.warning("couldn't report %s: %s", entity, e)

    def report(entity, state, attrs):  # from async code: off the event loop, never blocking it
        asyncio.get_running_loop().run_in_executor(None, report_now, entity, state, attrs)
    q = Queue(report)
    wake = asyncio.Event()

    async def poll():
        while True:
            await q.refresh()
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), POLL_S if q.playing else IDLE_POLL_S)
            except asyncio.TimeoutError:
                pass

    async def listen(ha: HA):
        async for event in ha.events():
            if event.get("event_type") == EVENT:
                asyncio.create_task(q.handle(event.get("data") or {}))
            elif "variables" in event:  # the track changed: read the queue again in a moment
                await asyncio.sleep(1)
                wake.set()

    asyncio.create_task(poll())
    backoff = 1
    while True:
        try:
            ha = await HA.connect(token)
            pump = asyncio.create_task(listen(ha))
            await ha.call(type="subscribe_events", event_type=EVENT)
            await ha.call(type="subscribe_trigger", trigger={"platform": "state", "entity_id": NOW})
            log.info("listening for %s", EVENT)
            backoff = 1
            await pump
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
            log.warning("Home Assistant connection lost (%s); retrying in %ds", e, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    asyncio.run(main())
