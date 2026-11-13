"""The TV backlight strip (Bluetooth). `live(frame)` lets music sync drive it through the backlight service."""
import json
import os
import socket

PORT = int(os.environ.get("BACKLIGHT_PORT", "38998"))
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def live(frame: dict | None):
    """Send one music sync frame to the strip (WiZ setPilot params), or None to hand it back to Home Assistant.
    Fire and forget: if the backlight service isn't running, nothing happens."""
    try:
        _sock.sendto(json.dumps(frame).encode(), ("127.0.0.1", PORT))
    except OSError:
        pass
