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

## Dashboard, scripts and automations
Home Assistant config that matters is kept here as JSON and pushed with
`.venv/bin/python -m homeassistant.apply`:

- `homeassistant/dashboards/home.json` — the **Home** dashboard (`/home-hub`): a sections view with scene
  buttons, light tiles (brightness + colour temperature), music-sync controls and the TV.
- `homeassistant/scripts/` — Party, Chill, Movie and All off.
- `homeassistant/automations/` — TV bias lighting.

Edit the JSON and re-run apply rather than editing in the UI, so the repo stays the source of truth.

## Music sync
`.venv/bin/python -m music_sync` connects to Home Assistant and creates its controls, which appear on the
default dashboard:

| Entity | What it does |
| --- | --- |
| `input_boolean.music_sync` | On/off. Bulbs are restored when it goes off, after 30s of silence, or on the next run after a crash. |
| `input_select.music_sync_mode` | `auto`, `calm`, `party` (chase + strobe on drops), `tv` (see below), `classic` (the original wiz_spotify algorithm). |
| `input_number.music_sync_sensitivity` | Onset threshold. Raise if lights trigger on noise, lower if they miss beats. |
| `input_number.music_sync_latency` | Fires beats this many ms early to cancel bulb lag. Go negative for Bluetooth speakers. |
| `sensor.music_sync_tempo` | Detected BPM (and whether the beat grid is locked). |

How it works (`music_sync/analysis.py`, `music_sync/show.py`): 23 ms STFT hops; spectral-flux onsets in
bass/mid/high bands with adaptive thresholds; autocorrelation tempo + comb-filter beat phase + kick PLL, so
locked beats are *predicted* and sent early; hue from a chroma vector on the circle of fifths (it follows
the key); per-band AGC; breakdown→drop detection. Bulbs alternate roles (beat vs. snare/hat sparkle) and
get different hues; updates are rate-limited per bulb and skip no-op changes.

### TV mode
`tv` is bias lighting rather than a show: warm white (2200–2700K, warmer on bass-heavy scenes), 15% brightness,
swelling by at most 8 points over ~3s in loud scenes and settling over ~8s. No RGB colour, beats or flashes.
It listens to the room through the Mac's microphone, so it follows whatever the TV plays from any app
(Netflix, the TV's Spotify, YouTube…). Audio stays in memory; nothing is recorded. It never times out on
silence, since quiet scenes are normal.

The TCL TV is paired through HA's Android TV Remote integration (`media_player.smart_tv_pro`). The
`TV bias lighting` automation (`homeassistant/automations/tv_bias_lighting.json`, pushed by `homeassistant.apply`) switches to `tv` mode when the TV turns on, if music sync
isn't already running, and turns it off (restoring the bulbs) when the TV turns off.

`.venv/bin/python -m tests.test_analysis` checks the pipeline against a synthetic 128 BPM track.
First run triggers macOS system-audio (and, for TV mode, microphone) permission prompts.
