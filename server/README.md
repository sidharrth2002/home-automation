# The home server

The always-on half of the home, on a small Linux box (a mini PC on Debian 13; any Debian-based machine works, a
Raspberry Pi included): Home Assistant, core and its worker, the widget feed, photos, presence, investments, the
cabinet strip, the TV's Home button watchdog and telemetry run here, under systemd, so they come back by themselves
after a reboot or a power cut. The Mac runs only what needs a Mac (music sync hears its audio, announcements use its
voices) and talks to this server over the home network. From outside, the Hub is at a subdomain of your own domain
through a Cloudflare Tunnel: no ports opened on the router.

```
            internet ── Cloudflare ══ tunnel (outbound only) ══╗
                                                               ║
   phone / laptop ─── home Wi-Fi ───┬──────────────────────────╨───────┐
                                    │             the server             │
   Mac (when it's on):              │  Home Assistant, core, widget,     │
     music sync, announcements ─────┤  photos, presence, investments,    │
                                    │  strip (Bluetooth), Home button    │
   TV, bulbs, strip ────────────────┤  watchdog (adb), telemetry         │
                                    └────────────────────────────────────┘
```

The order matters: the box is tested before the home depends on it, and the Mac keeps running everything until the
very last step.

## 1. Before wiping anything (while it can still go back)

1. **First boot, as it came**: plug in a screen, keyboard and Ethernet, and let Windows start once. Power, fan and SSD
   work: nothing is dead on arrival.
2. **A Debian test stick, on the Mac.** Download the *live* image (debian.org → Live images → amd64 → the
   `-xfce.iso`), then:
   ```sh
   diskutil list                              # find the USB stick, e.g. /dev/disk4 (check the size!)
   diskutil unmountDisk /dev/diskN
   sudo dd if=~/Downloads/debian-live-13*-amd64-xfce.iso of=/dev/rdiskN bs=4m status=progress
   ```
   `dd` overwrites whatever disk it's given, so check the number twice.
3. **Boot the stick without installing**: power on and tap the boot-menu key (F7 on most of these boxes; else F11,
   F12 or Esc; Del opens the BIOS). In the live desktop: is there Wi-Fi, and a Bluetooth icon? In a terminal,
   `ls /sys/class/bluetooth` should list `hci0`. If Bluetooth is missing here, it's a firmware or hardware question
   to settle before wiping Windows (a ~£10 USB Bluetooth adapter is the fallback).
4. **In the BIOS** (Del at power-on): find *Restore on AC Power Loss* (or *AC Power Recovery*, *State after G3*) and
   set it to **Power On**, so the box starts by itself after a power cut. Leave Secure Boot as it is (Debian
   supports it).

## 2. Install Debian 13

1. Write the **netinst** image (debian.org → the amd64 `netinst` iso) to the stick the same way, and boot it.
2. In the installer (the plain *Install*, not graphical, is fine):
   - hostname: e.g. `homeserver`; domain: blank
   - **root password: leave it empty**, so your user gets `sudo`
   - your name, username and password
   - disk: *Guided – use entire disk* (this removes Windows), all files in one partition
   - software selection: untick the desktop environments; tick **SSH server** and **standard system utilities**
3. After the reboot, give it a **fixed address**: a DHCP reservation on the router for its Ethernet. The TV app and
   the phone widget use that IP.
4. From the Mac: `ssh-copy-id <user>@homeserver.local`, then `ssh <user>@homeserver.local`.

## 3. Set it up and test it (the Mac still runs the home)

On the server:

```sh
git clone https://github.com/sidharrth2002/home-automation.git && cd home-automation
server/setup                     # packages, firmware, Docker, .venv, security updates, systemd (it lists the data
                                 # still missing: that comes in step 4)
# log out and in again once (new groups: docker, bluetooth)
server/check-hardware --stress 60    # memory layout, disk health, network, Bluetooth, video, then an hour at full
                                     # load watching temperatures and checking the memory for errors
```

Anything marked *check* gets looked at before going further. One memory module means single channel: a matching
second one (DDR4 SO-DIMM, same speed) doubles memory speed, which matters for local AI.

## 4. Move the home onto it

On the Mac:

```sh
./home down                                       # Home Assistant stops here, so its database copies whole
server/move-from-mac <user>@homeserver.local      # copies .env, data/, HA's config, rclone, the adb key
```

On the server:

```sh
server/setup                                      # again: now it adds the server's .env keys and HA's proxy setting
server/check-hardware                             # now with .env: does Bluetooth see the strip?
./home up                                         # starts it all, and at every boot from now on
.venv/bin/python -m investments setup             # HL / Trading 212 details (the Mac's stay in its Keychain)
```

Back on the Mac:

```sh
server/use-server homeserver.local                # the Mac: music sync + announcements only, against the server
tv-app/deploy --no-open                           # the TV app, rebuilt for the server's address
.venv/bin/python -m widget install --copy         # the phone widget, pointed at the server (paste into Scriptable)
```

`server/use-server --undo` puts the Mac back to running everything (its data is still there).

## 5. From anywhere: home.<your domain>

A Cloudflare Tunnel needs the domain's DNS on Cloudflare (the free plan is enough). If the domain already serves a
website from elsewhere (e.g. Vercel), it keeps working as long as its records come across.

1. **Cloudflare account** → Add a domain → yours → Free. It scans the existing records: compare them with the
   current DNS (`dig +short A <domain>`, `dig +short CNAME www.<domain>`) and check any MX/TXT records for email
   came across. Records for a host like Vercel stay **DNS only** (grey cloud), as Vercel asks.
2. **At the registrar** (e.g. GoDaddy → the domain → Nameservers → *I'll use my own*) → the two Cloudflare gives
   you. It takes minutes to a few hours; the site stays up throughout.
3. **Cloudflare** → Zero Trust (Free plan) → Networks → Tunnels → Create (cloudflared) → name it `home` → Docker →
   copy the token (after `--token`). Then the tunnel → Add a route → **Published application**: subdomain (e.g.
   `home-server`), your domain, service URL **`http://homeassistant:8123`**. That one address works on both machines:
   on the Mac it's Home Assistant's container, on the server docker-compose.server.yml maps it to this machine.
4. **The token goes in `.env`** (the home-automation one: never a tracked file), without it showing on screen:
   `printf 'TUNNEL_TOKEN=%s\n' "$(pbpaste)" >> .env`, plus `COMPOSE_PROFILES=tunnel` and
   `PUBLIC_URL=https://<subdomain>.<your domain>`, then `./home up`. Home Assistant must trust the tunnel: its web
   settings live in `homeassistant/config/.storage/http` (a YAML `http:` section is ignored once it has migrated), and
   `server/setup` adds `use_x_forwarded_for` and the trusted proxies there (with Home Assistant stopped). Without it,
   every request through the tunnel gets **400**.
   The tunnel can start on the Mac first (it did, 2026-11-28) and simply move: `server/move-from-mac` copies `.env`
   with the token, and `server/use-server` stops it on the Mac.
5. **Lock it down**: Home Assistant is now on the internet, behind its own login. In your HA profile turn on
   **multi-factor authentication**. Optionally put **Cloudflare Access** (Zero Trust → Access → Applications) in
   front of the Hub's pages for a second sign-in, but leave `/api/webhook/*` and `/local/widget/*` outside it so the
   phone's shortcuts and widget keep working.
6. Add `PUBLIC_URL` to the Mac's `.env` too and run `widget install --copy` again: the widget then falls back to it
   when the phone is away from home.

Never commit the token, the server's address or anything from `.env`: the repo is public.

## 6. Claude and the home state (MCP)

The home-state MCP runs on the server next to the core (`home_mcp --http`, port 8792, supervised like the rest).
Every request must carry a core token (`Authorization: Bearer ...`); the core then applies that token's scopes, so a
token made with `python -m core token add <name> <scopes>` limits what that client can touch.

- **Claude Desktop (Mac)**: `server/use-server` already points its home-state tools at the server's core
  (`bin/install-mcp`); quit and reopen Desktop.
- **Claude Code (Mac)**: the home-state skill follows too (`~/.config/home-core/url`). For the MCP itself:
  `claude mcp add --transport http home-state http://<server IP>:8792/mcp --header "Authorization: Bearer $(cat ~/.config/home-core/token)"`
- **From anywhere**: add a second public hostname to the tunnel, `mcp.<your domain>` → `HTTP` → `localhost:8792`,
  and use `https://mcp.<your domain>/mcp` with the same header. Give each device its own token, so one can be
  revoked (`python -m core token revoke <name>`) without touching the others.
- claude.ai's custom connectors (and so the phone app) need OAuth sign-in, which this doesn't do yet: it's the next
  step if the phone should reach the home state.

## Day to day

| | |
|---|---|
| `./home status` / `up` / `down` / `reload` | same as on the Mac; on the server they drive systemd (`home-stack`) |
| `./home logs backlight` | a service's log |
| `journalctl -u home-stack -e` | the supervisor itself |
| `server/setup --check` | what's missing, without changing anything |
| `server/check-hardware` | the hardware, again (e.g. after adding memory) |
| `git pull && ./home reload` | ship a change to the server |
