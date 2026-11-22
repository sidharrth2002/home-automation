"""Keeps the TV's Home button on the Hub: puts the TV app's Home button service back when Android drops it.

The Hub's Home button is an accessibility service in the TV app (tv-app/home). When the TV runs out of memory it kills
processes right down to the one on screen, that service's included; killed twice in quick succession, Android files
it under "crashed services" and stops binding it, so Home goes to Google TV until the service is switched off and on
again. This looks every CHECK_S over adb and, if the service is switched on but not bound, switches it off and on (the
same settings `tv-app/home on` writes). With the service switched off (`tv-app/home off`) it leaves things alone, and
with the TV off or unreachable it waits. Run by ./home up.
"""
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import telemetry

from music_sync.service import load_env

log = logging.getLogger("home_button")
ROOT = Path(__file__).resolve().parent.parent
SVC = "com.sid.home/com.sid.home.HomeButtonService"
LABEL = "label=Hub Home button"  # how dumpsys lists it once bound (android:label in the TV app's manifest)
CHECK_S = 30
ADB = str(Path(os.environ.get("ANDROID_HOME", Path.home() / "Library/Android/sdk")) / "platform-tools/adb")


def listed(dump: str, label: str) -> str:
    """The `Bound services:{...}` style list from `dumpsys accessibility`, as text ('' if it's not there)."""
    m = re.search(label + r" services:\{(.*?)\}\n", dump + "\n", re.S)
    return m.group(1) if m else ""


def needs_fix(dump: str) -> bool:
    """Switched on, but crashed or not bound (and not on its way): Home isn't reaching the Hub."""
    if "HomeButtonService" not in listed(dump, "Enabled"):
        return False
    if "HomeButtonService" in listed(dump, "Crashed"):
        return True
    return LABEL not in listed(dump, "Bound") and "HomeButtonService" not in listed(dump, "Binding")


def serial() -> str | None:
    """The TV's adb serial: a live connection, else whatever tv-app/adb.sh finds (it looks the port up over Bonjour)."""
    host = os.environ.get("TV_HOST", "")
    try:
        out = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].startswith(host + ":") and parts[1] == "device":
                return parts[0]
        found = subprocess.run(["bash", "-c", "source ./adb.sh >/dev/null && echo $SERIAL"], cwd=ROOT / "tv-app",
                               capture_output=True, text=True, timeout=30)
        return (found.stdout.strip() or None) if found.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def shell(s: str, *args: str) -> str:
    return subprocess.run([ADB, "-s", s, "shell", *args], capture_output=True, text=True, timeout=20).stdout.strip()


def rebind(s: str):
    """Off and on again: taking it out of the enabled list clears Android's crashed mark, putting it back binds it."""
    now = shell(s, "settings", "get", "secure", "enabled_accessibility_services")
    rest = ":".join(x for x in now.split(":") if x and x != "null" and "HomeButtonService" not in x)
    if rest:
        shell(s, "settings", "put", "secure", "enabled_accessibility_services", rest)
    else:
        shell(s, "settings", "delete", "secure", "enabled_accessibility_services")
    time.sleep(1)
    shell(s, "settings", "put", "secure", "enabled_accessibility_services", f"{rest}:{SVC}" if rest else SVC)
    shell(s, "settings", "put", "secure", "accessibility_enabled", "1")


def check():
    s = serial()
    if not s:
        return
    try:
        if needs_fix(shell(s, "dumpsys", "accessibility")):
            log.warning("Home button service dropped by the TV; switching it back on")
            rebind(s)
            time.sleep(10)  # binding takes a few seconds on a busy TV
            if needs_fix(shell(s, "dumpsys", "accessibility")):
                log.warning("Home button service still not bound; trying again in %ds", CHECK_S)
            else:
                log.info("Home button service back")
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("TV not reachable: %s", e)


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    telemetry.setup("home_button")
    log.info("watching the TV's Home button service")
    while True:
        check()
        time.sleep(CHECK_S)


if __name__ == "__main__":
    main()
