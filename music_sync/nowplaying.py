"""What's playing in the Mac's Spotify app, and its album-art palette.

Uses Spotify's AppleScript interface, so no Spotify developer app or login is needed. The script checks
`is running` first so polling never launches Spotify.
"""
import asyncio
import logging
import urllib.request
from collections import OrderedDict

from . import palette

log = logging.getLogger("music_sync.nowplaying")

SCRIPT = """
if application "Spotify" is running then
    tell application "Spotify"
        set t to current track
        return (player state as string) & linefeed & (id of t) & linefeed & (name of t) & linefeed & ¬
            (artist of t) & linefeed & (artwork url of t)
    end tell
end if
return ""
"""


class NowPlaying:
    def __init__(self):
        self.state = "stopped"
        self.track_id = None
        self.title = self.artist = self.art_url = None
        self.palette: list[palette.Swatch] = []
        self._cache: OrderedDict[str, list[palette.Swatch]] = OrderedDict()

    @property
    def label(self):
        return f"{self.title} — {self.artist}" if self.title else "Nothing playing"

    async def poll(self) -> bool:
        """Refresh from Spotify. Returns True if the track or play state changed."""
        proc = await asyncio.create_subprocess_exec("osascript", "-e", SCRIPT, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        parts = out.decode().strip().split("\n")
        if len(parts) < 5:
            changed = self.track_id is not None
            self.state, self.track_id, self.title, self.artist, self.art_url, self.palette = (
                "stopped", None, None, None, None, [])
            return changed
        state, track_id, title, artist, art_url = parts[:5]
        changed = track_id != self.track_id or state != self.state
        self.state = state
        if track_id != self.track_id:
            self.track_id, self.title, self.artist, self.art_url = track_id, title, artist, art_url
            self.palette = await self._palette(art_url)
            log.info("now playing %s (%s)", self.label, " ".join(s.hex for s in self.palette) or "no colour")
        return changed

    async def _palette(self, url):
        if not url:
            return []
        if url in self._cache:
            self._cache.move_to_end(url)
            return self._cache[url]
        try:
            data = await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=5).read())
            swatches = await asyncio.to_thread(palette.extract, data)
        except Exception as e:
            log.warning("could not read album art: %s", e)
            return []
        self._cache[url] = swatches
        if len(self._cache) > 64:
            self._cache.popitem(last=False)
        return swatches

    async def run(self, on_change, interval=2.0):
        while True:
            try:
                if await self.poll():
                    on_change(self)
            except Exception as e:
                log.warning("now-playing poll failed: %s", e)
            await asyncio.sleep(interval)
