# CLAUDE.md

Working notes for Claude on this repo. Keep this file current: when a change adds or alters a service, command,
convention, entity or gotcha, update it in the same commit as the change (and README.md for anything user-facing).

## What this is

One room in London run by Home Assistant (Docker, on a Mac) plus a few native macOS Python services: three WiZ
bulbs (two by the TV, one adaptive desk lamp), a TCL Google TV, music-reactive lighting, a custom dashboard (the
Hub), an iPhone widget, an Android TV app, investments (Hargreaves Lansdown, Trading 212) and a speaking "Welcome
home". README.md is the human-facing overview; this file is how to work on it safely.

## The rules that matter most

- **The GitHub repo is public.** Never commit `.env`, `data/`, `homeassistant/config/`, logs, APKs, `.shortcut`
  files, screenshots showing personal data, or anything with money amounts, holdings, fund codes, calendar entries,
  addresses, MACs or secret keys/webhook ids. Stage files by path, read `git status` and the diff before every commit.
  `bin/check-commit` is the pre-commit hook (`ln -sf ../../bin/check-commit .git/hooks/pre-commit`); it blocks the
  obvious cases. Never bypass it with `--no-verify`, and never put real figures in tests, even as "secrets".
- **Commit and push after every change** (the user wants GitHub current). Never rewrite history or force-push
  without the user explicitly asking.
- **Services don't reload themselves.** After editing a service's Python, run `./home reload` and check its live
  output (the sensor it publishes, the widget feed...) before saying it works. Tests run on hand-written fixtures and
  can't see a stale process; this once left the widget's bulb taps silently dead.
- **Hargreaves Lansdown locks the account after a few failed logins.** Never loop or retry logins, never delete
  `data/investments/HALTED` yourself, and leave `python -m investments login` for the user to run. To inspect HL
  pages, reuse the saved session and stop if `HL().logged_in()` is false. `tests/test_investments.py` encodes the rules.
- **Things here are physical.** Lights, the TV and speech happen in the user's room. Test with harmless paths first
  (the `ping` webhook, a neutral phrase), put lamps back exactly as they were after a toggle test, and don't interrupt
  what's playing on the TV unless the user has said it's fine. When the user asks to control the home from chat, just
  do it with `bin/ha`.
- **No Home Assistant token on the phone.** The widget reads a secret-named feed and acts through LAN-only webhooks.

## Layout

```
home                  ./home up | down | restart | reload | status | logs <service>
stack/                supervisor run by ./home: starts, restarts and stops the Mac-side services; publishes sensor.system_health
music_sync/           audio capture -> beat/tempo analysis -> light show; Spotify now-playing and album palettes
announce/             speaks `home_say` events with macOS `say`, on the Mac or cast to the TV
investments/          Hargreaves Lansdown client (hl.py, lockout-safe), FT price history (prices.py), Trading 212 (t212.py)
widget/               iPhone Scriptable widget (home.js) + its feed, webhook actions and signed Shortcuts (__main__.py)
presence/             phone-on-Wi-Fi home/away (needs PRESENCE_PHONE_MAC; not currently running)
netflix/              export parser, no longer run
homeassistant/        HA config as code (helpers, templates, scripts, automations, dashboards, voice.json) + apply.py
frontend/hub/         the Hub: plain HTML/CSS/JS on HA's websocket API, no build step; TV mode for the TV app
tv-app/               Android TV app (a full-screen WebView of the Hub); tv-app/deploy builds and installs it
bin/                  ha (REST CLI), check-commit (pre-commit guard), ha-mcp-headers, audiotee
tests/                python -m tests.<name>; node tests/widget_smoke.js
```

## Commands

```sh
./home up | down | reload | status            # everything / just the Mac-side services
.venv/bin/python -m homeassistant.apply       # push helpers, templates, scripts, automations, dashboards, the Hub
bin/ha states <filter>                        # look at entities
bin/ha call light.turn_on light.desk_lamp brightness_pct=30
.venv/bin/python -m tests.test_analysis       # also: test_investments, test_t212, test_widget, test_announce
node tests/widget_smoke.js                    # widget script against a strict Scriptable stand-in
HARNESS_FEED=<feed.json> WIDGET_JS=data/widget/Home.js node tests/widget_smoke.js   # which taps a fresh draw gets
.venv/bin/python -m widget install --copy     # widget script with the private addresses filled in, to the clipboard
.venv/bin/python -m widget shortcuts          # signed Shortcuts for the lamps (into data/widget/shortcuts/)
tv-app/deploy                                 # build the TV app and install it over adb (TV_HOST in .env)
.venv/bin/python frontend/screenshot.py <out> [selector]   # headless screenshots; HUB_REDACT=1 blurs calendar
```

Edit the JSON under `homeassistant/` and re-run apply rather than changing things in the HA UI; the repo is the
source of truth. The Hub is redeployed by apply (content-hashed, so no stale cache).

## Entities and events worth knowing

- Lights: `light.wiz_rgbw_tunable_624d4e` (TV lamp 1), `light.wiz_rgbw_tunable_4b472c` (TV lamp 2), `light.desk_lamp`.
  WiZ can't do transitions; fades are steps. Music sync never touches the desk lamp (`WIZ_EXCLUDE_MACS`).
- TV: `media_player.smart_tv_pro` (Android TV Remote: power, keys, apps, volume steps only) and
  `media_player.sid_london_room_tv` (Google Cast: playing media, e.g. speech).
- Music sync: `input_boolean.music_sync`, `input_select.music_sync_mode`, `sensor.music_sync_now_playing`.
- Scripts: party/chill/movie/all_off, `music_command` (play/pause/skip), `welcome_home`.
- Events: `home_say` {text, target: mac|tv, voice?, rate?}; `music_sync_command` {command}; `widget_ping`.
- Feeds published by services (REST states, gone after an HA restart until republished): `sensor.investments`,
  `sensor.investment_<sedol>`, `sensor.trading212`, `sensor.system_health`.

## Gotchas

- HA serves `/local/` with month-long caching: cache-bust with a query string or a new file name.
- The Mac's Spotify app says "playing" while it's only remote-controlling the TV; decide by audio, not that state.
- iOS redraws widgets when it likes; a Scriptable tap always opens Scriptable. Shortcuts (from `widget shortcuts`)
  are the way to act without opening an app.
- Timestamps compared in a browser must carry a timezone (UTC or `astimezone()`).
- Casting to the TV takes over whatever is playing; `welcome_home` only speaks on the TV if it was off.
- The compact `say` voices sound robotic; announce picks Premium/Enhanced voices automatically once downloaded.
- Docker Desktop: don't force-kill it; HA sees LAN clients through Docker's NAT, so per-device trust can't work.
- The TV app: Google TV uses *wireless debugging* (random port, announced over Bonjour), not port 5555. Pairing is a
  one-off (`adb pair <tv>:<pairing port> <code>`; the pairing port can be found with `dns-sd -B _adb-tls-pairing._tcp`
  or a port scan of the TV while the pairing screen is open); after that `tv-app/deploy` finds the connect port itself.
  Debug builds allow WebView inspection: `adb forward tcp:9229 localabstract:webview_devtools_remote_<pid>`, then
  CDP on localhost:9229. `adb exec-out screencap -p` screenshots the TV. A screenshot right after launch can show the
  Hub before its scripts run; wait before concluding it's broken.
- `tv-app/app/src/debug/res/` is a git-ignored overlay for personal resources (the launcher banner with the user's
  photo). The committed banner in `src/main` must stay generic. Personal photos (`*.heic`) are git-ignored and blocked
  by the commit guard.
