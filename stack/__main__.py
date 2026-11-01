"""Supervises the Mac-side services next to the Home Assistant container (started by `./home up`).

Runs each service as a child process, restarts it with backoff if it dies, and on SIGTERM/SIGINT stops them all
(SIGTERM first, so music sync restores the bulbs, then SIGKILL after a grace period) before exiting.
"""
import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
GRACE_S = 10

log = logging.getLogger("home")


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def services():
    """name -> argv. Presence only runs once it knows which phone to look for."""
    out = {
        "music_sync": [PY, "-m", "music_sync"],
        "netflix": [PY, "-m", "netflix", "--watch"],
    }
    if os.environ.get("PRESENCE_PHONE_MAC"):
        out["presence"] = [PY, "-m", "presence"]
    from investments.__main__ import configured  # Keychain lookup; only run once HL credentials are stored
    if configured():
        out["investments"] = [PY, "-m", "investments", "--watch"]
    return out


class Child:
    def __init__(self, name, argv):
        self.name, self.argv = name, argv
        self.proc: asyncio.subprocess.Process | None = None

    async def run(self, stopping: asyncio.Event):
        backoff = 1
        while not stopping.is_set():
            started = time.monotonic()
            with open(ROOT / f"{self.name}.log", "ab") as out:
                self.proc = await asyncio.create_subprocess_exec(*self.argv, cwd=ROOT, stdout=out, stderr=out)
            log.info("%s started (pid %d)", self.name, self.proc.pid)
            code = await self.proc.wait()
            if stopping.is_set():
                break
            backoff = 1 if time.monotonic() - started > 60 else min(backoff * 2, 60)
            log.warning("%s exited (%s); restarting in %ds", self.name, code, backoff)
            try:
                await asyncio.wait_for(stopping.wait(), backoff)
            except asyncio.TimeoutError:
                pass

    async def stop(self):
        if not self.proc or self.proc.returncode is not None:
            return
        self.proc.terminate()
        try:
            await asyncio.wait_for(self.proc.wait(), GRACE_S)
        except asyncio.TimeoutError:
            log.warning("%s ignored SIGTERM; killing", self.name)
            self.proc.kill()
            await self.proc.wait()
        log.info("%s stopped", self.name)


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        loop.add_signal_handler(sig, stopping.set)

    children = [Child(name, argv) for name, argv in services().items()]
    tasks = [asyncio.create_task(c.run(stopping)) for c in children]
    log.info("supervising %s", ", ".join(c.name for c in children))
    await stopping.wait()
    log.info("shutting down")
    await asyncio.gather(*(c.stop() for c in children))
    await asyncio.gather(*tasks, return_exceptions=True)
    log.info("all services stopped")


if __name__ == "__main__":
    asyncio.run(main())
