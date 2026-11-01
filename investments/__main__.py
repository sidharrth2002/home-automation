"""Hargreaves Lansdown holdings -> Home Assistant (`sensor.investments`), for the Hub.

  python -m investments setup     store HL credentials in the macOS Keychain (asked for interactively)
  python -m investments login     log in once by hand, fetch and publish; also clears a halt after a failure
  python -m investments status
  python -m investments --watch   the service (run by ./home up): refresh hourly 07:00-22:00, otherwise every 4h

Safety (HL locks the account after a few bad logins): one login attempt at a time, never retried; any failure
halts automatic logins until `login` succeeds by hand; at most MAX_AUTO_LOGINS automatic logins a day.
"""
import getpass
import json
import logging
import os
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

import keyring

from .hl import DATA, HL, Credentials, Halted, halted_reason, save_json, _halt

log = logging.getLogger("investments")
ROOT = Path(__file__).resolve().parent.parent
KEYCHAIN = "home-automation.hargreaves-lansdown"
FIELDS = ("username", "dob", "password", "secure_number")
SENSOR = "sensor.investments"
HISTORY = DATA / "history.json"
LOGINS = DATA / "auto_logins.json"
MAX_AUTO_LOGINS = 8
HA_HTTP = os.environ.get("HA_HTTP", "http://localhost:8123")


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def configured():
    try:
        return bool(keyring.get_password(KEYCHAIN, "username"))
    except Exception:
        return False


def credentials():
    values = {f: keyring.get_password(KEYCHAIN, f) for f in FIELDS}
    missing = [f for f, v in values.items() if not v]
    if missing:
        raise SystemExit(f"missing from Keychain: {', '.join(missing)} — run: python -m investments setup")
    return Credentials.checked(**values)


def setup():
    print("Stored in the macOS Keychain (item '%s'), never in files or git.\n" % KEYCHAIN)
    username = input("HL username: ").strip()
    dob = input("Date of birth (DD/MM/YYYY): ").strip()
    password = getpass.getpass("Password (hidden): ")
    password2 = getpass.getpass("Password again: ")
    if password != password2:
        raise SystemExit("passwords don't match; nothing saved")
    secure = getpass.getpass("6-digit secure number (hidden): ")
    creds = Credentials.checked(username, dob, password, secure)  # raises on anything malformed
    for f in FIELDS:
        keyring.set_password(KEYCHAIN, f, getattr(creds, f))
    print("Saved. Now run: python -m investments login")


# ── publishing ───────────────────────────────────────────────────
def post(state, attrs):
    req = urllib.request.Request(f"{HA_HTTP}/api/states/{SENSOR}", method="POST",
                                 data=json.dumps({"state": state, "attributes": attrs}).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['TOKEN']}",
                                          "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).close()


BASE_ATTRS = {"friendly_name": "Investments", "icon": "mdi:chart-line", "unit_of_measurement": "GBP"}


def publish(accounts):
    total = round(sum(a["total"] or 0 for a in accounts), 2)
    holdings = sorted((h for a in accounts for h in a["holdings"]), key=lambda h: -(h["value"] or 0))
    cost = sum(h["cost"] or 0 for h in holdings)
    gain = sum(h["gain"] or 0 for h in holdings)

    history = json.loads(HISTORY.read_text()) if HISTORY.exists() else {}
    today = date.today().isoformat()
    history[today] = total
    history = dict(sorted(history.items())[-400:])
    save_json(HISTORY, history)
    previous = [v for d, v in history.items() if d < today]
    day_change = round(total - previous[-1], 2) if previous else None

    post(total, {**BASE_ATTRS, "status": "ok", "updated": datetime.now().isoformat(timespec="seconds"),
                 "cash": round(sum(a["cash"] or 0 for a in accounts), 2),
                 "invested_cost": round(cost, 2), "gain": round(gain, 2),
                 "gain_pct": round(gain / cost * 100, 2) if cost else None, "day_change": day_change,
                 "accounts": [{k: a[k] for k in ("name", "total", "stock", "cash")} for a in accounts],
                 "holdings": [{k: h[k] for k in ("name", "account", "value", "cost", "gain", "gain_pct", "units",
                                                 "price_p", "unit_type")} for h in holdings],
                 "history": [[d, v] for d, v in list(history.items())[-180:]]})
    log.info("published £%.2f across %d accounts, %d holdings", total, len(accounts), len(holdings))


def publish_paused(reason):
    try:
        last = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"{HA_HTTP}/api/states/{SENSOR}", headers={"Authorization": f"Bearer {os.environ['TOKEN']}"}),
            timeout=10).read())
        state, attrs = last["state"], last["attributes"]
    except Exception:
        state, attrs = "unknown", dict(BASE_ATTRS)
    post(state, {**attrs, "status": "paused", "paused_reason": reason})


# ── running ──────────────────────────────────────────────────────
def count_auto_login():
    """Cap automatic logins per day, so no bug can ever turn into a stream of attempts."""
    counts = json.loads(LOGINS.read_text()) if LOGINS.exists() else {}
    today = date.today().isoformat()
    counts = {today: counts.get(today, 0) + 1}
    save_json(LOGINS, counts)
    if counts[today] > MAX_AUTO_LOGINS:
        _halt(f"more than {MAX_AUTO_LOGINS} automatic logins today; something is off, so pausing")


def refresh(hl: HL, *, manual=False):
    if not hl.logged_in():
        if not manual:
            count_auto_login()
        log.info("logging in")
        creds = credentials()
        try:
            hl.login(creds, manual=manual)
        except Halted:
            raise
        except Exception as e:  # e.g. the connection dropped mid-login: it may have counted, so don't go again
            _halt(f"login interrupted ({type(e).__name__}: {e}); not retrying automatically")
        if not hl.logged_in():
            _halt("logged in but the portfolio still isn't readable; pausing rather than logging in again")
    publish(hl.snapshot())


def next_delay():
    h = datetime.now().hour
    return 3600 if 7 <= h < 22 else 4 * 3600


def watch():
    hl = HL()
    while True:
        reason = halted_reason()
        if reason:
            log.warning("paused: %s", reason)
            publish_paused(reason)
            while halted_reason():  # wait for a successful manual `login`
                time.sleep(60)
            continue
        if not configured():
            time.sleep(600)
            continue
        try:
            refresh(hl)
        except Halted as e:
            log.error("halted: %s", e)
            continue
        except Exception as e:  # network or parsing trouble: not a login attempt, just try later
            log.warning("refresh failed: %s", e)
        time.sleep(next_delay())


def main():
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "setup":
        setup()
    elif cmd == "login":
        reason = halted_reason()
        if reason:
            print(f"Previously halted: {reason}\nCheck the details (python -m investments setup) before going on.")
            if input("Try one login now? [y/N] ").strip().lower() != "y":
                return
        refresh(HL(), manual=True)
        print("Logged in and published. Automatic refreshes are on.")
    elif cmd == "status":
        print("credentials:", "in Keychain" if configured() else "not set (python -m investments setup)")
        print("halted:", halted_reason() or "no")
    elif cmd == "--watch":
        watch()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
