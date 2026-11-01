"""Is anyone home? Publishes binary_sensor.someone_home to Home Assistant.

Home means either:
- the phone was seen on the home Wi-Fi in the last PRESENCE_AWAY_AFTER_MIN minutes (default 15). Phones
  sleep their Wi-Fi and ignore most probes, so a single miss means nothing; any sign of life counts: a ping
  reply, or the iPhone sync port (62078) accepting *or refusing* a connection. The phone's IP is looked up
  from its Wi-Fi MAC every cycle, so DHCP changes don't matter; or
- the Mac's keyboard/mouse was used in the last PRESENCE_MAC_ACTIVE_MIN minutes (default 10), which covers
  a flat or forgotten phone.

  python -m presence          # needs PRESENCE_PHONE_MAC in .env (Settings > Wi-Fi > (i) > Wi-Fi Address)
"""
import errno
import json
import logging
import os
import re
import socket
import subprocess
import time
import urllib.request

from music_sync.service import HA_HTTP, load_env

log = logging.getLogger("presence")
SENSOR = "binary_sensor.someone_home"
PROBE_EVERY_S = 20


def norm_mac(mac):
    return ":".join(f"{int(p, 16):02x}" for p in re.split("[:-]", mac.strip()))


def ip_for_mac(mac):
    out = subprocess.run(["arp", "-an"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        m = re.search(r"\(([\d.]+)\) at ([0-9a-f:]+)", line)
        if m and norm_mac(m.group(2)) == mac:
            return m.group(1)
    return None


def alive(ip):
    if subprocess.run(["ping", "-c", "1", "-t", "1", ip], capture_output=True).returncode == 0:
        return "ping"
    with socket.socket() as s:
        s.settimeout(1.5)
        code = s.connect_ex((ip, 62078))
    if code == 0:
        return "port open"
    if code == errno.ECONNREFUSED:  # a refusal still proves the phone is there
        return "port refused"
    return None


def mac_idle_s():
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 1e9 if m else float("inf")


def publish(state, attrs):
    req = urllib.request.Request(
        f"{HA_HTTP}/api/states/{SENSOR}", method="POST",
        data=json.dumps({"state": "on" if state else "off", "attributes": {
            "friendly_name": "Someone home", "device_class": "presence", **attrs}}).encode(),
        headers={"Authorization": f"Bearer {os.environ['TOKEN']}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).close()


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    macs = [norm_mac(m) for m in os.environ.get("PRESENCE_PHONE_MAC", "").split(",") if m.strip()]
    if not macs:
        raise SystemExit("set PRESENCE_PHONE_MAC in .env (phone: Settings > Wi-Fi > (i) > Wi-Fi Address)")
    away_after = float(os.environ.get("PRESENCE_AWAY_AFTER_MIN", 15)) * 60
    mac_active = float(os.environ.get("PRESENCE_MAC_ACTIVE_MIN", 10)) * 60
    last_ip = {m: None for m in macs}
    last_seen = time.time()  # assume home at startup rather than switching everything off on a restart
    how = "startup"
    home = None
    while True:
        for mac in macs:
            last_ip[mac] = ip_for_mac(mac) or last_ip[mac]
            if last_ip[mac] and (sign := alive(last_ip[mac])):
                last_seen, how = time.time(), sign
        idle = mac_idle_s()
        since = time.time() - last_seen
        now_home = since < away_after or idle < mac_active
        reason = "phone" if since < away_after else "mac in use" if idle < mac_active else "phone gone"
        if now_home != home:
            log.info("%s (%s; phone last seen %.0fs ago via %s, mac idle %.0fs)",
                     "HOME" if now_home else "AWAY", reason, since, how, idle)
            home = now_home
        try:
            publish(now_home, {"reason": reason, "phone_last_seen_s": round(since), "phone_seen_via": how,
                               "phone_ip": next((ip for ip in last_ip.values() if ip), None),
                               "mac_idle_min": round(idle / 60, 1)})
        except OSError as e:
            log.warning("could not publish presence: %s", e)
        time.sleep(PROBE_EVERY_S)


if __name__ == "__main__":
    main()
