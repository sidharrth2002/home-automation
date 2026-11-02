"""Speaks on the Mac when Home Assistant asks: fire the `home_say` event with {"text": ..., "voice"?, "rate"?}.

Uses macOS's own text to speech (`say`), so it's instant and needs no cloud service. The default voice is Daniel
(British English); set ANNOUNCE_VOICE in .env for another installed voice (`say -v '?'` lists them). Announcements
queue rather than talk over each other. Run by ./home up.
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess

import websockets

from music_sync.service import HA, load_env

log = logging.getLogger("announce")
EVENT = "home_say"
MAX_CHARS = 300
RATE_RANGE = (90, 300)  # words per minute; say's default is about 175


def installed_voices() -> set[str]:
    if not shutil.which("say"):
        return set()
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return {m.group(1).strip() for m in (re.match(r"^(.+?)\s{2,}[a-z]{2}_[A-Z0-9]{2,}", line) for line in out.splitlines()) if m}


def command(data: dict, voices: set[str], default_voice: str) -> list[str] | None:
    """The `say` command for an event, or None if there's nothing to say. Text is passed as an argument after `--`
    (never through a shell), so nothing in it can be read as an option."""
    text = " ".join(str(data.get("text") or "").split())[:MAX_CHARS]
    if not text:
        return None
    voice = data.get("voice") or default_voice
    cmd = ["say"]
    if voice in voices:
        cmd += ["-v", voice]
    try:
        rate = int(data["rate"]) if data.get("rate") is not None else None
    except (TypeError, ValueError):
        rate = None
    if rate is not None:
        cmd += ["-r", str(max(RATE_RANGE[0], min(RATE_RANGE[1], rate)))]
    return cmd + ["--", text]


async def speak(cmd: list[str], lock: asyncio.Lock):
    async with lock:  # one announcement at a time
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()


async def listen(ha: HA, lock: asyncio.Lock, voices: set[str], default_voice: str):
    async for event in ha.events():
        if event.get("event_type") != EVENT:
            continue
        cmd = command(event.get("data") or {}, voices, default_voice)
        if not cmd:
            continue
        if not voices:
            log.warning("asked to speak, but this machine has no `say` command")
            continue
        log.info("speaking %d characters", len(cmd[-1]))
        asyncio.create_task(speak(cmd, lock))


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ["TOKEN"]
    voices = installed_voices()
    default_voice = os.environ.get("ANNOUNCE_VOICE", "Daniel")
    if default_voice not in voices:
        log.warning("voice %r isn't installed; using the system default", default_voice)
    lock, backoff = asyncio.Lock(), 1
    while True:
        try:
            ha = await HA.connect(token)
            pump = asyncio.create_task(listen(ha, lock, voices, default_voice))
            await ha.call(type="subscribe_events", event_type=EVENT)
            log.info("listening for %s", EVENT)
            backoff = 1
            await pump
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as e:
            log.warning("Home Assistant connection lost (%s); retrying in %ds", e, backoff)
        except Exception:
            log.exception("announce error; reconnecting in %ds", backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    asyncio.run(main())
