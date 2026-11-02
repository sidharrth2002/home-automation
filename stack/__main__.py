"""Supervises the Mac-side services next to the Home Assistant container (started by `./home up`).

Runs each service as a child process, restarts it with backoff if it dies, and on SIGTERM/SIGINT stops them all
(SIGTERM first, so music sync restores the bulbs, then SIGKILL after a grace period) before exiting.

It also reports on them: every minute, and whenever a service changes state, it publishes `sensor.system_health`
(each service's state, uptime and restarts, plus the host's load and free disk) for the Hub's health card.
"""
import asyncio
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
GRACE_S = 10
HEALTH_SENSOR = "sensor.system_health"
HEARTBEAT_S = 60

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
    out = {"music_sync": [PY, "-m", "music_sync"], "widget": [PY, "-m", "widget", "--watch"],
           "announce": [PY, "-m", "announce"]}
    if os.environ.get("PRESENCE_PHONE_MAC"):
        out["presence"] = [PY, "-m", "presence"]
    from investments.__main__ import any_configured  # Keychain lookup; only run once credentials are stored
    if any_configured():
        out["investments"] = [PY, "-m", "investments", "--watch"]
    if shutil.which("rclone") and "[onedrive]" in rclone_config():  # photos, once OneDrive is signed in
        out["photos"] = [PY, "-m", "photos", "--watch"]
    return out


def rclone_config() -> str:
    try:
        return subprocess.run(["rclone", "config", "show"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


class Child:
    def __init__(self, name, argv):
        self.name, self.argv = name, argv
        self.proc: asyncio.subprocess.Process | None = None
        self.state = "starting"  # starting | running | restarting | stopped
        self.started_at: float | None = None
        self.restarts = 0
        self.last_exit: int | None = None

    async def run(self, stopping: asyncio.Event, changed: asyncio.Event):
        backoff = 1
        while not stopping.is_set():
            started = time.monotonic()
            with open(ROOT / f"{self.name}.log", "ab") as out:
                self.proc = await asyncio.create_subprocess_exec(*self.argv, cwd=ROOT, stdout=out, stderr=out)
            self.state, self.started_at = "running", time.time()
            changed.set()
            log.info("%s started (pid %d)", self.name, self.proc.pid)
            code = await self.proc.wait()
            self.last_exit = code
            if stopping.is_set():
                break
            self.state = "restarting"
            self.restarts += 1
            changed.set()
            backoff = 1 if time.monotonic() - started > 60 else min(backoff * 2, 60)
            log.warning("%s exited (%s); restarting in %ds", self.name, code, backoff)
            try:
                await asyncio.wait_for(stopping.wait(), backoff)
            except asyncio.TimeoutError:
                pass
        self.state = "stopped"

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


# ── health reporting ─────────────────────────────────────────────
def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def snapshot(children, started_at, *, stopped=False):
    """(state, attributes) for sensor.system_health. Timestamps are UTC so any browser reads them correctly."""
    services = {c.name: {"state": "stopped" if stopped else c.state,
                         "pid": c.proc.pid if c.proc and c.proc.returncode is None else None,
                         "since": iso(c.started_at) if c.started_at else None,
                         "restarts": c.restarts, "last_exit": c.last_exit} for c in children}
    try:
        disk = shutil.disk_usage(ROOT)
        host = {"disk_free_pct": round(disk.free / disk.total * 100, 1)}
    except OSError:
        host = {}
    try:
        host["load1"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    host.update(cores=os.cpu_count(), platform=platform.system())
    state = "stopped" if stopped else ("ok" if all(c.state == "running" for c in children) else "degraded")
    return state, {"friendly_name": "System health", "icon": "mdi:heart-pulse", "updated": iso(time.time()),
                   "supervisor_since": iso(started_at), "services": services, "host": host}


def post(state, attrs):
    token = os.environ.get("TOKEN")
    if not token:
        return
    req = urllib.request.Request(f"{os.environ.get('HA_HTTP', 'http://localhost:8123')}/api/states/{HEALTH_SENSOR}",
                                 method="POST", data=json.dumps({"state": state, "attributes": attrs}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5).close()
    except OSError as e:  # Home Assistant restarting or down: the next heartbeat will get through
        log.debug("health not published: %s", e)


async def report(children, started_at, changed: asyncio.Event):
    while True:
        changed.clear()  # before the snapshot: a change that lands while it's being sent must trigger another report
        await asyncio.to_thread(post, *snapshot(children, started_at))
        try:
            await asyncio.wait_for(changed.wait(), HEARTBEAT_S)
            await asyncio.sleep(1)  # let a burst of restarts settle into one update
        except asyncio.TimeoutError:
            pass


async def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stopping, changed = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        loop.add_signal_handler(sig, stopping.set)

    started_at = time.time()
    children = [Child(name, argv) for name, argv in services().items()]
    tasks = [asyncio.create_task(c.run(stopping, changed)) for c in children]
    reporter = asyncio.create_task(report(children, started_at, changed))
    log.info("supervising %s", ", ".join(c.name for c in children))
    await stopping.wait()
    log.info("shutting down")
    reporter.cancel()
    await asyncio.gather(*(c.stop() for c in children))
    await asyncio.gather(*tasks, return_exceptions=True)
    await asyncio.to_thread(post, *snapshot(children, started_at, stopped=True))  # so the Hub says "stopped"
    log.info("all services stopped")


if __name__ == "__main__":
    asyncio.run(main())
