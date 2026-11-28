# The home server (Raspberry Pi)

The always-on half of the home: Home Assistant, core and its worker, the widget feed, photos, presence, investments,
the cabinet strip, the TV's Home button watchdog and telemetry run here, under systemd, so they come back by
themselves after a reboot or a power cut. The Mac runs only what needs a Mac (music sync hears its audio,
announcements use its voices) and talks to this server over the home network. From outside, the Hub is at a
subdomain of your own domain through a Cloudflare Tunnel: no ports opened on the router.

```
            internet ── Cloudflare ══ tunnel (outbound only) ══╗
                                                               ║
   phone / laptop ─── home Wi-Fi ───┬──────────────────────────╨───────┐
                                    │            Raspberry Pi            │
   Mac (when it's on):              │  Home Assistant, core, widget,     │
     music sync, announcements ─────┤  photos, presence, investments,    │
                                    │  strip (Bluetooth), Home button    │
   TV, bulbs, strip ────────────────┤  watchdog (adb), telemetry         │
                                    └────────────────────────────────────┘
```

## 1. The Pi

1. With Raspberry Pi Imager on the Mac: **Raspberry Pi OS Lite (64-bit)**. In its settings: a hostname (e.g.
   `homepi`), your username, SSH on (with your Mac's public key), and Wi-Fi if it won't be on Ethernet.
2. Boot it; then from the Mac, `ssh <user>@homepi.local`.
3. Give it a fixed address: a DHCP reservation on the router. The TV app and the phone widget use that IP.
4. The SSD (Home Assistant's database writes wear out SD cards): easiest before step 2. Fit the M.2 HAT+ and the
   drive, boot from the SD card, flash the same OS onto the SSD (`sudo apt install rpi-imager`, or Imager on the Mac
   with a USB NVMe adapter), set NVMe first in `sudo raspi-config` → Advanced → Boot Order, and take the card out.

## 2. Move the home onto it

On the Mac:

```sh
./home down                              # Home Assistant stops here, so its database copies whole
pi/move-from-mac <user>@homepi.local     # clones the repo there, copies .env, data/, HA's config, rclone, adb key
```

On the Pi:

```sh
cd ~/home-automation
pi/setup                                 # packages, Docker, .venv, the server's .env keys, systemd
# log out and in again once (new groups: docker, bluetooth)
./home up                                # starts it all, and at every boot from now on
.venv/bin/python -m investments setup    # HL / Trading 212 details (the Mac's stay in its Keychain)
```

Back on the Mac:

```sh
pi/use-server homepi.local               # the Mac: music sync + announcements only, against the Pi
tv-app/deploy --no-open                  # the TV app, rebuilt for the Pi's address
.venv/bin/python -m widget install --copy   # the phone widget, pointed at the Pi (paste into Scriptable)
```

`pi/use-server --undo` puts the Mac back to running everything (its data is still there).

## 3. From anywhere: home.<your domain>

A Cloudflare Tunnel needs the domain's DNS on Cloudflare (the free plan is enough). If the domain already serves a
website from elsewhere (e.g. Vercel), it keeps working as long as its records come across.

1. **Cloudflare account** → Add a domain → yours → Free. It scans the existing records: compare them with the
   current DNS (`dig +short A <domain>`, `dig +short CNAME www.<domain>`) and check any MX/TXT records for email
   came across. Records for a host like Vercel stay **DNS only** (grey cloud), as Vercel asks.
2. **At the registrar** (e.g. GoDaddy → the domain → Nameservers → *I'll use my own*) → the two Cloudflare gives
   you. It takes minutes to a few hours; the site stays up throughout.
3. **Cloudflare** → Zero Trust → Networks → Tunnels → Create (cloudflared) → name it `home` → copy the token.
   Public hostname: `home.<your domain>` → Service `HTTP` → `localhost:8123`.
4. **On the Pi**, in `.env`:
   ```
   TUNNEL_TOKEN=<the token>
   COMPOSE_PROFILES=tunnel
   PUBLIC_URL=https://home.<your domain>
   ```
   then `./home up`. `pi/setup` already told Home Assistant to trust the tunnel (`http: trusted_proxies`).
5. **Lock it down**: Home Assistant is now on the internet, behind its own login. In your HA profile turn on
   **multi-factor authentication**. Optionally put **Cloudflare Access** (Zero Trust → Access → Applications) in
   front of the Hub's pages for a second sign-in, but leave `/api/webhook/*` and `/local/widget/*` outside it so the
   phone's shortcuts and widget keep working.
6. Add `PUBLIC_URL` to the Mac's `.env` too and run `widget install --copy` again: the widget then falls back to it
   when the phone is away from home.

Never commit the token, the Pi's address or anything from `.env`: the repo is public.

## Day to day

| | |
|---|---|
| `./home status` / `up` / `down` / `reload` | same as on the Mac; on the Pi they drive systemd (`home-stack`) |
| `./home logs backlight` | a service's log |
| `journalctl -u home-stack -e` | the supervisor itself |
| `pi/setup --check` | what's missing, without changing anything |
| `git pull && ./home reload` | ship a change to the server |
