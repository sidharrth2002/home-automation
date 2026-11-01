"""What's playing in the Mac's Spotify app, and its album-art palette.

Uses Spotify's AppleScript interface, so no Spotify developer app or login is needed. The script checks
`is running` first so polling never launches Spotify.
"""
import asyncio
import logging
import time
import urllib.request
from collections import OrderedDict

from . import palette

log = logging.getLogger("music_sync.nowplaying")

SCRIPT = """
if application "Spotify" is running then
    tell application "Spotify"
        set t to current track
        return (player state as string) & linefeed & (id of t) & linefeed & (name of t) & linefeed & ¬
            (artist of t) & linefeed & (artwork url of t) & linefeed & (player position as string) & ¬
            linefeed & (duration of t as string)
    end tell
end if
return ""
"""
COMMANDS = {"play_pause": "playpause", "next": "next track", "previous": "previous track"}
SEEK_TOLERANCE_S = 2.5


class NowPlaying:
    def __init__(self):
        self.state = "stopped"
        self.track_id = None
        self.title = self.artist = self.art_url = None
        self.position = self.duration = 0.0  # seconds
        self.position_at = 0.0  # epoch time `position` was sampled, so UIs can interpolate
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
        if len(parts) < 7:
            changed = self.track_id is not None
            self.state, self.track_id, self.title, self.artist, self.art_url, self.palette = (
                "stopped", None, None, None, None, [])
            self.position = self.duration = 0.0
            return changed
        state, track_id, title, artist, art_url, position, duration = parts[:7]
        now = time.time()
        position, duration = _num(position), _num(duration) / 1000
        expected = self.position + (now - self.position_at if self.state == "playing" else 0)
        seeked = abs(position - expected) > SEEK_TOLERANCE_S
        changed = track_id != self.track_id or state != self.state or seeked
        self.state, self.position, self.duration, self.position_at = state, position, duration, now
        if track_id != self.track_id:
            self.track_id, self.title, self.artist, self.art_url = track_id, title, artist, art_url
            self.palette = await self._palette(art_url)
            log.info("now playing %s (%s)", self.label, " ".join(s.hex for s in self.palette) or "no colour")
        return changed

    async def command(self, name):
        """Play/pause or skip in the Mac's Spotify. Returns False if Spotify isn't running."""
        verb = COMMANDS[name]
        script = f'if application "Spotify" is running then\ntell application "Spotify" to {verb}\nreturn "ok"\nend if'
        proc = await asyncio.create_subprocess_exec("osascript", "-e", script, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate()
        if out.strip() != b"ok":
            return False
        await asyncio.sleep(0.3)
        return True

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


def _num(text):
    try:
        return float(text.replace(",", "."))  # AppleScript formats decimals per the system locale
    except ValueError:
        return 0.0
