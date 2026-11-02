"""Speaks when Home Assistant asks: fire the `home_say` event with {"text": ..., "voice"?, "rate"?, "target"?}.

target "mac" (the default) speaks on the Mac. target "tv" renders the same voice to a WAV file, serves it from
Home Assistant's /local/ folder under a random name, waits for the TV to finish waking, casts it to the TV, then
closes the cast player so the TV goes back to where it was. If the TV doesn't come up, it says it on the Mac instead.

Uses macOS's own text to speech (`say`), so it's instant and needs no cloud service. It picks the most natural
British voice that's installed: the Premium and Enhanced voices (System Settings > Accessibility > Spoken Content >
System voice > Manage Voices) sound far more human than the built-in compact Daniel. ANNOUNCE_VOICE in .env
overrides the choice. The voice list is re-read for every announcement, so a newly downloaded voice is used at once. Announcements
queue rather than talk over each other. Run by ./home up.
"""
import asyncio
import logging
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import wave
from pathlib import Path

import websockets

from music_sync.service import HA, load_env

log = logging.getLogger("announce")
ROOT = Path(__file__).resolve().parent.parent
TV_OUT = ROOT / "homeassistant" / "config" / "www" / "announce"  # served at /local/announce/
TV_REMOTE = "media_player.smart_tv_pro"  # Android TV Remote: knows whether the TV is on
TV_CAST = "media_player.sid_london_room_tv"  # Google Cast: plays the audio
TV_WAIT_S = 45  # how long to wait for the TV to wake before giving up and using the Mac
TV_SETTLE_S = 4  # after the TV reports "on", give Cast a moment to be ready
CAST_PLAYER = "Default Media Receiver"
EVENT = "home_say"
MAX_CHARS = 300
RATE_RANGE = (90, 300)  # words per minute; say's default is about 175
# Most natural first. Premium voices are Apple's neural ones; Enhanced are the larger classic voices.
PREFERRED = ("Jamie (Premium)", "Daniel (Enhanced)", "Oliver (Premium)", "Oliver (Enhanced)", "Serena (Premium)",
             "Kate (Enhanced)", "Daniel")


def pick_voice(voices: set[str]) -> str | None:
    wanted = os.environ.get("ANNOUNCE_VOICE")
    if wanted in voices:
        return wanted
    return next((v for v in PREFERRED if v in voices), None)


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


def render_command(data: dict, voices: set[str], default_voice: str, path: Path) -> list[str] | None:
    """The same as command(), but writing 16-bit WAV to `path` instead of playing it (Cast devices play WAV)."""
    cmd = command(data, voices, default_voice)
    if not cmd:
        return None
    return cmd[:-2] + ["-o", str(path), "--file-format=WAVE", "--data-format=LEI16@24000", "--", cmd[-1]]


def tv_ready(states: dict) -> bool:
    """The TV is on and its Cast receiver is reachable."""
    return states.get(TV_REMOTE) == "on" and states.get(TV_CAST) not in (None, "unavailable")


def lan_ip() -> str:
    """The Mac's address on the home network, which is how the TV fetches the audio."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks the outbound interface
            return s.getsockname()[0]
    except OSError:
        return "localhost"


async def states(ha: HA) -> dict:
    return {s["entity_id"]: s for s in await ha.call(type="get_states")}


async def speak_on_tv(ha: HA, data: dict, voices: set[str], default_voice: str, lock: asyncio.Lock):
    TV_OUT.mkdir(parents=True, exist_ok=True)
    path = TV_OUT / f"{secrets.token_urlsafe(16)}.wav"
    try:
        cmd = render_command(data, voices, default_voice, path)
        if not cmd:
            return
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        if await proc.wait() or not path.exists():
            raise RuntimeError("couldn't render the audio")
        with wave.open(str(path)) as w:
            seconds = w.getnframes() / w.getframerate()

        deadline = time.monotonic() + TV_WAIT_S
        while not tv_ready({k: v["state"] for k, v in (await states(ha)).items()}):
            if time.monotonic() > deadline:
                raise TimeoutError("the TV didn't come on")
            await asyncio.sleep(1)
        await asyncio.sleep(TV_SETTLE_S)

        url = f"http://{lan_ip()}:8123/local/announce/{path.name}"
        await ha.call(type="call_service", domain="media_player", service="play_media", target={"entity_id": TV_CAST},
                      service_data={"media_content_id": url, "media_content_type": "music"})
        log.info("speaking on the TV (%.1fs)", seconds)
        await asyncio.sleep(seconds + 2.5)
        # Close the cast player we opened, so the TV goes back to its home screen. Only if it's still ours.
        cast = (await states(ha)).get(TV_CAST, {})
        if cast.get("attributes", {}).get("app_name") == CAST_PLAYER:
            await ha.call(type="call_service", domain="media_player", service="turn_off", target={"entity_id": TV_CAST})
    except Exception as e:
        log.warning("couldn't speak on the TV (%s); saying it on the Mac", e)
        mac = command(data, voices, default_voice)
        if mac and voices:
            await speak(mac, lock)
    finally:
        asyncio.get_running_loop().call_later(120, lambda: path.unlink(missing_ok=True))


def clean_old_audio(max_age_s=600):
    for f in TV_OUT.glob("*.wav") if TV_OUT.exists() else []:
        if time.time() - f.stat().st_mtime > max_age_s:
            f.unlink(missing_ok=True)


async def speak(cmd: list[str], lock: asyncio.Lock):
    async with lock:  # one announcement at a time
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()


async def listen(ha: HA, lock: asyncio.Lock):
    async for event in ha.events():
        if event.get("event_type") != EVENT:
            continue
        voices = installed_voices()  # cheap, and picks up a voice downloaded since the service started
        default_voice = pick_voice(voices)
        data = event.get("data") or {}
        cmd = command(data, voices, default_voice)
        if not cmd:
            continue
        if not voices:
            log.warning("asked to speak, but this machine has no `say` command")
            continue
        if data.get("target") == "tv":
            log.info("speaking %d characters on the TV", len(cmd[-1]))
            asyncio.create_task(speak_on_tv(ha, data, voices, default_voice, lock))
        else:
            log.info("speaking %d characters", len(cmd[-1]))
            asyncio.create_task(speak(cmd, lock))


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = os.environ["TOKEN"]
    log.info("voice: %s", pick_voice(installed_voices()) or "system default")
    clean_old_audio()
    lock, backoff = asyncio.Lock(), 1
    while True:
        try:
            ha = await HA.connect(token)
            pump = asyncio.create_task(listen(ha, lock))
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
