<p align="center"><img src="docs/icon.png" width="112" alt=""></p>

<h1 align="center">home-automation</h1>

<p align="center">
The setup that runs my room in London: three WiZ bulbs, a TCL Google TV and a Mac, glued together with Home
Assistant and a few Python services.
</p>

<p align="center">
<img src="https://img.shields.io/badge/home%20assistant-docker-18BCF2?logo=homeassistant&logoColor=white" alt="">
<img src="https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white" alt="">
<img src="https://img.shields.io/badge/macOS-14.2%2B-111?logo=apple&logoColor=white" alt="">
</p>

<p align="center"><img src="docs/hub.png" width="880" alt="The Hub dashboard"></p>

That's the Hub, the dashboard I actually use. The orbs are the bulbs in whatever colour they are right now,
and the background picks up colour from the lights and the album art.

## What's in here

- **Music sync.** The two lamps by the TV follow whatever is playing. It does proper beat tracking (onsets,
  tempo, a beat grid it can predict ahead of time), so the lights land on the kick instead of lagging behind
  it. Colours come from the album cover, or from the key of the song if the cover is black and white. It
  listens to the Mac directly, or through the mic when the music is coming out of the TV.
- **TV mode.** When the TV comes on, the same lamps switch to dim warm light that drifts a little with loud
  scenes. I wanted something I wouldn't notice while watching, so there's no colour and nothing flashes. If
  the TV is playing Spotify it goes back to the music show.
- **Desk lamp.** The third bulb sets its own colour temperature and brightness from the sun, cloud cover and
  rain, and gets warmer and dimmer in the evening. These lamps are the only lights in the room, so it stays
  fairly low. If I change it by hand it leaves it alone for two hours.
- **The Hub.** Plain HTML/JS on Home Assistant's websocket API, no build step. Lights, now playing with
  controls, the week's calendar (iCloud), my investments, the desk lamp, a remote for the TV and a health
  card that shows what's running and how fresh the data is.
- **Investments.** Holdings from Hargreaves Lansdown, which has no API, so it logs in like the website does
  (written so it can't lock the account, more on that below), plus the interest on my cash at Trading 212
  through its official API. Values are blurred on the dashboard until I tap to show them.
- **iPhone widget.** A Scriptable widget in the same neon style: the three bulbs as glowing orbs, what's
  playing with its album art, the TV, home/away and the weather, in small, medium, large and lock screen sizes.
- **Talking to it.** Claude can control everything through Home Assistant's MCP server, so "turn the TV lamps
  blue" or "lights out" just works.
- **Away mode.** If my phone hasn't been on the Wi-Fi for a while and the Mac is idle, everything turns off.

## How it fits together

```mermaid
flowchart LR
    subgraph Mac
        direction TB
        audio["system audio<br/>(audiotee)"]
        mic["microphone"]
        spotify["Spotify app<br/>(AppleScript)"]
        sync["music_sync"]
        side["presence,<br/>investments"]
        sup(["./home"])
        audio --> sync
        mic --> sync
        spotify --> sync
        sup -.-> sync & side
    end

    ha["Home Assistant<br/>(Docker)"]
    bulbs(("WiZ bulbs"))
    tv["TCL TV"]
    hub["Hub"]
    phone["iPhone widget"]
    claude["Claude"]
    icloud["iCloud"]
    hl["Hargreaves<br/>Lansdown"]
    t212["Trading 212<br/>(official API)"]
    ft["FT<br/>(fund prices)"]

    sync -- UDP --> bulbs
    sync <-- websocket --> ha
    side -- REST --> ha
    hl -. read-only .-> side
    t212 -. read-only .-> side
    ft -.-> side
    ha -- desk lamp --> bulbs
    ha <--> tv
    icloud -- CalDAV --> ha
    hub <-- websocket --> ha
    ha -. JSON feed .-> phone
    claude -- MCP --> ha
```

Home Assistant runs in Docker. The audio side can't, because it needs Core Audio and the mic, so those
services run natively on the Mac under a small supervisor, and `./home` starts and stops the lot together.

## Running it

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                       # TOKEN = a Home Assistant long-lived token
./home up
.venv/bin/python -m homeassistant.apply    # pushes helpers, automations, dashboards and the Hub
```

The Hub is at `http://localhost:8123/hub-live`, or full screen at `/local/hub/index.html` (it has a manifest
and icon, so it can go on a phone's home screen). Turn on *Allow local communication* in the WiZ app first.
The first run will ask for system audio, microphone and Spotify automation permissions.

```sh
./home up | down | restart | status       # down restores the bulbs before stopping anything
./home logs music_sync
bin/ha states light                       # quick look at anything in HA
bin/ha call script.turn_on script.party_mode
```

<p align="center"><img src="docs/hub-phone.png" width="280" alt="The Hub on a phone"></p>

## Notes

<details>
<summary><b>Music sync</b></summary>
<br>

`python -m music_sync` connects to Home Assistant and creates its own controls:

| Entity | |
| --- | --- |
| `input_boolean.music_sync` | On/off. The bulbs go back to how they were when it stops, after 30s of silence, or on the next run after a crash. |
| `input_select.music_sync_mode` | `auto`, `calm`, `party` (chases, strobes on drops), `tv`, `classic` (the original wiz_spotify algorithm). |
| `input_select.music_sync_colours` | `Album art` or `Music key`. |
| `input_number.music_sync_sensitivity` | Onset threshold. Up if it reacts to noise, down if it misses beats. |
| `input_number.music_sync_latency` | Sends beats this many ms early to cover bulb lag. Negative for Bluetooth speakers. |
| `sensor.music_sync_tempo` | Detected BPM and whether the beat grid is locked. |
| `sensor.music_sync_now_playing` | Track, cover, palette and playback position. |

The analysis (`analysis.py`, `show.py`) works on 23 ms STFT hops: spectral-flux onsets in three bands with
adaptive thresholds, tempo from autocorrelation, beat phase from a comb filter plus a PLL that nudges the
grid towards detected kicks. Once it's locked, beats are predicted and sent early. Hue comes from a chroma
vector mapped onto the circle of fifths, so it follows the key. There's per-band AGC and a simple
breakdown-then-drop detector. Each bulb is rate limited and identical updates are skipped.

Where it listens: `tv` mode always uses the mic. The other modes use the Mac's audio, but if that's silent for
3s while the TV is on they switch to the mic (with a slow gain stage, since a laptop across the room hears
the TV at about -55 dBFS) and switch back after 1.5s of sustained Mac audio. I couldn't use Spotify's own
state for this because the Mac app reports "playing" while it's acting as a remote for the TV.

Album colours: `nowplaying.py` asks Spotify over AppleScript what's playing (no developer account, and it
won't launch Spotify if it's closed). `palette.py` runs k-means on the cover, merges near-duplicate hues,
throws out black/grey/white and keeps up to four colours. Bulbs rotate through them every bar, two bars or
beat depending on the mode.

`script.music_command` does play/pause/next/previous on the Mac's Spotify if it's open, otherwise on the TV.

System audio comes from the bundled [audiotee](https://github.com/makeusabrew/audiotee) binary (MIT, macOS
14.2+). Nothing is recorded; audio only lives in memory.

</details>

<details>
<summary><b>TV mode</b></summary>
<br>

Warm white between 2200 and 2700K at 15%. Loud scenes can push it up by at most 8 points over about 3
seconds, and it settles back over about 8. No RGB, no beats. It listens to the room, so it works with every
app, and it never times out on quiet scenes.

The TV is paired through HA's Android TV Remote integration (`media_player.smart_tv_pro`). The *TV bias
lighting* automation starts it when the TV turns on, unless music sync is already running or I'm out, and
stops it when the TV turns off. It only fires on a real off→on change, otherwise every HA restart would
trigger it.

</details>

<details>
<summary><b>Desk lamp</b></summary>
<br>

This one lives entirely in Home Assistant (`homeassistant/templates/`, `automations/desk_lamp_*.json`).

- `sensor.outdoor_daylight` estimates the light coming through the window from the sun's elevation (0 at
  -4°, full at 30°), cloud cover (up to -70%) and rain, fog or snow (another -20%).
- `sensor.desk_lamp_target_colour` is 4000-5200K during the day (cooler when it's overcast, to match the
  light outside), 2700K around sunset, and 2200K from the 21:00-22:30 wind-down until 05:00.
- `sensor.desk_lamp_target_brightness` scales everything to `input_number.desk_lamp_max_brightness`: the full
  value in the dark, less on bright days, 45% of it late at night, and at most 35% of it while the TV is on.

It only adjusts the lamp when it's already on. A manual change that's clearly off target starts
`timer.desk_lamp_manual`, which pauses it for 2 hours. Music sync skips this bulb (`WIZ_EXCLUDE_MACS`).

</details>

<details>
<summary><b>Investments (Hargreaves Lansdown)</b></summary>
<br>

HL doesn't have an API, so `investments/hl.py` logs in the same way the website does and reads the portfolio
pages. It's a port of [hl-api-client-net](https://github.com/jonathanmadeley/hl-api-client-net). HL locks
the account after a few failed logins, so I was careful with this one:

- Credentials are checked locally first: the secure number has to be 6 digits and the date of birth has to
  be unambiguous.
- The password is only submitted if the page asks for exactly three secure-number digits it can identify.
- Any failed, interrupted or unexpected login stops automatic logins completely. Nothing retries. It stays
  stopped until `python -m investments login` works when run by hand.
- At most 8 automatic logins a day, and the session cookie is reused so most refreshes don't log in.

```sh
.venv/bin/python -m investments setup   # prompts for the details and stores them in the macOS Keychain
.venv/bin/python -m investments login   # one login by hand, then fetch and publish
```

After that it refreshes hourly between 07:00 and 22:00 as part of `./home up` and publishes
`sensor.investments`, which isn't exposed to Claude.

Price history for each fund comes from the FT's public fund pages (`investments/prices.py`), looked up by ISIN
(worked out from the SEDOL for UK funds) and fetched once a day into `sensor.investment_<sedol>`. Only fund
identifiers are sent to FT. In the Hub, clicking a holding opens its price chart (1M to 5Y) with my average
cost marked, returns over each period and the position itself. The main chart shows what my current holdings
would have been worth over time, so it ignores deposits. `tests/test_investments.py` runs each of those rules
against a fake HL.

### Trading 212 cash

Trading 212 has an official API, so this one doesn't log in to anything. `investments/t212.py` uses an API
key with read-only permissions (created in the app under Settings > API) and only ever makes GET requests. It
reads the cash balance and the interest paid on uninvested cash, which shows up in the Hub as a card with the
balance, the latest daily payment, an estimated yearly rate and a chart of interest earned.

```sh
.venv/bin/python -m investments setup-t212   # key + secret go into the macOS Keychain
.venv/bin/python -m investments t212         # one supervised connection by hand
```

If Trading 212 ever refuses the key it stops and doesn't retry, the same as the HL side, until `t212` works by
hand. Requests are spaced to stay under its rate limits, and after the first run only new interest payments
are fetched. The key is never written to a file, and `data/` (including the cached interest history) is
git-ignored. It refreshes every 30 minutes during the day. `tests/test_t212.py` runs against a fake API.

</details>

<details>
<summary><b>iPhone widget</b></summary>
<br>

`widget/home.js` is a [Scriptable](https://scriptable.app) widget (free app), so there's nothing to build or sign.
It doesn't talk to Home Assistant and there's no token on the phone. Instead the `widget` service (started by
`./home up`) writes a small JSON feed every 20 seconds to a file under Home Assistant's `/local/` folder whose
name is a random secret. The feed has the three lights (on, brightness, colour), what's playing, the TV, home/away
and the weather, and nothing else: no finances and no calendar. `tests/test_widget.py` checks that nothing outside
that list can get into it.

```sh
.venv/bin/python -m widget install --copy   # fills in the private address and copies the script to the clipboard
```

Then paste it into a new script in Scriptable on the phone (the clipboard carries across with Universal
Clipboard), and add a Scriptable widget to the home or lock screen. Tapping it opens the Hub. Away from home
Wi-Fi it shows the last data it saw, marked with how old it is. The installed script contains the secret address,
so it's written to `data/widget/` (git-ignored) and the copy in the repo only has placeholders. If the address
ever leaks, delete `data/widget/key` and run the install again.

`node tests/widget_smoke.js` runs the script against a strict stand-in for Scriptable's API in every size and a
set of awkward cases (offline, nothing playing, stale data), which catches typos but isn't the same as looking at
it on a phone.

</details>

<details>
<summary><b>Claude</b></summary>
<br>

Home Assistant's MCP server (`/api/mcp`) gives Claude the usual Assist tools: on/off, light colour and
brightness, media controls, scripts and the calendar. `homeassistant/voice.json` controls which entities it
can see and what they're called ("TV lamp 1", "desk light", "lights out" and so on).

```sh
claude mcp add-json -s user home-assistant \
  '{"type":"http","url":"http://localhost:8123/api/mcp","headersHelper":"'"$PWD"'/bin/ha-mcp-headers"}'
```

`bin/ha-mcp-headers` reads the token from `.env` when it's needed, so it isn't stored in Claude's config.

</details>

<details>
<summary><b>Calendar, presence, the TV remote and the health card</b></summary>
<br>

Calendar: iCloud over CalDAV. `homeassistant.apply` adds it once `ICLOUD_USERNAME` and `ICLOUD_APP_PASSWORD`
(an app-specific password) are in `.env`.

TV remote: the Hub's TV card has a D-pad, back/home, play/pause, mute, volume (hold to repeat) and buttons that
launch Netflix, YouTube, Spotify and the other apps. Keys go through `remote.send_command` and apps through
`media_player.play_media` on the Android TV Remote integration. The TV's volume can only be stepped, not set to a
level.

Health card: the supervisor publishes `sensor.system_health` every minute and whenever a service changes
state (per-service state, uptime and restarts, plus load and free disk). The Hub combines that with how recently
each feed refreshed, whether the bulbs, TV, weather and calendar are reachable, and flags anything stale or down.

Presence: `python -m presence` publishes `binary_sensor.someone_home`. I count as home if my phone has been
on the Wi-Fi in the last 15 minutes or the Mac has been used in the last 10. When that flips to away,
everything turns off. If the service isn't running the sensor just doesn't exist, so nothing turns off by
accident. Needs `PRESENCE_PHONE_MAC` in `.env`.

</details>

<details>
<summary><b>Home Assistant config</b></summary>
<br>

The parts of the HA config I care about are JSON files in `homeassistant/`, pushed with
`.venv/bin/python -m homeassistant.apply`. I edit these rather than using the UI so the repo stays in sync.

| | |
| --- | --- |
| `helpers.json` | toggles, timers, sliders |
| `templates/` | daylight and desk lamp target sensors |
| `scripts/` | Party, Chill, Movie, All off, `music_command` |
| `automations/` | TV lighting, desk lamp, manual hold, away |
| `dashboards/home.json` | the standard HA dashboard (`/home-hub`) |
| `voice.json` | what Claude can see and control |

</details>

## Layout

```
home                ./home up | down | status | logs
music_sync/         audio capture, analysis, light show, now playing
investments/        Hargreaves Lansdown client
netflix/            export parser (not currently run; it fed a card I removed)
widget/             the iPhone widget script and the feed behind it
presence/           phone on Wi-Fi -> home/away
stack/              the supervisor behind ./home
homeassistant/      HA config + apply.py
frontend/hub/       the Hub, plus screenshot.py
bin/                audiotee, ha, ha-mcp-headers
tests/
```

Tests: `python -m tests.test_analysis` (a synthetic 128 BPM track: tempo, beat timing, drops, TV mode,
palettes), `tests.test_investments`, `tests.test_t212` and `tests.test_widget`, plus `node tests/widget_smoke.js`.
