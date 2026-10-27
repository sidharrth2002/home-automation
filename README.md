# home-automation

Home Assistant (Docker) + a native macOS service that syncs WiZ bulbs to system audio.

- `docker-compose.yml` runs Home Assistant on :8123; config lives in `homeassistant/config/` (git-ignored).
- `music_sync/` captures macOS system audio (via the bundled MIT-licensed [audiotee](https://github.com/makeusabrew/audiotee) binary, macOS 14.2+), detects beats, and drives the bulbs over UDP. Beat detection is ported from `wiz_spotify`'s local-audio mode.
- `discover.py` / `lights.py` are small standalone helpers for finding and poking bulbs.

## Setup
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in TOKEN
docker compose up -d
```
Enable "Allow local communication" in the WiZ app first.

## Music sync
`.venv/bin/python -m music_sync` connects to Home Assistant and creates three controls (Music Sync toggle,
mode dropdown, sensitivity slider) that appear on the default dashboard. Toggle it on while music plays;
the bulbs are restored when you toggle off, after 30s of silence, or on the next run after a crash.
First run triggers a macOS system-audio permission prompt for your terminal.
