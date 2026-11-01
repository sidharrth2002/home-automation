"""Hargreaves Lansdown holdings -> Home Assistant (`sensor.investments`), for the Hub.

  python -m investments setup     store HL credentials in the macOS Keychain (asked for interactively)
  python -m investments login     log in once by hand, fetch and publish; also clears a halt after a failure
  python -m investments setup-t212  store a Trading 212 API key + secret in the Keychain (read-only key)
  python -m investments t212      connect to Trading 212 once by hand and publish; also clears a halt
  python -m investments status
  python -m investments --watch   the service (run by ./home up): Hargreaves Lansdown hourly 07:00-22:00 (else every
                                  4h), Trading 212 every 30 min (else every 2h)

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
from .prices import Prices, compact
from . import t212 as t212mod

log = logging.getLogger("investments")
ROOT = Path(__file__).resolve().parent.parent
KEYCHAIN = "home-automation.hargreaves-lansdown"
FIELDS = ("username", "dob", "password", "secure_number")
SENSOR = "sensor.investments"
T212_KEYCHAIN = "home-automation.trading212"
T212_SENSOR = "sensor.trading212"
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


def t212_configured():
    try:
        return bool(keyring.get_password(T212_KEYCHAIN, "key"))
    except Exception:
        return False


def any_configured():
    return configured() or t212_configured()


def credentials():
    values = {f: keyring.get_password(KEYCHAIN, f) for f in FIELDS}
    missing = [f for f, v in values.items() if not v]
    if missing:
        raise SystemExit(f"missing from Keychain: {', '.join(missing)} — run: python -m investments setup")
    return Credentials.from_stored(**values)


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


def setup_t212():
    print("Create a READ-ONLY key in the Trading 212 app (Settings > API): tick account data and history only,")
    print("leave anything that places orders unticked. Stored in the macOS Keychain, never in files or git.\n")
    key = getpass.getpass("API key (hidden): ")
    secret = getpass.getpass("API secret (hidden): ")
    t212mod.T212(key, secret)  # local sanity check only; nothing is sent
    keyring.set_password(T212_KEYCHAIN, "key", key.strip())
    keyring.set_password(T212_KEYCHAIN, "secret", secret.strip())
    print("Saved. Now run: python -m investments t212")


# ── publishing ───────────────────────────────────────────────────
def post(state, attrs, entity=SENSOR):
    req = urllib.request.Request(f"{HA_HTTP}/api/states/{entity}", method="POST",
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
    # HL's own day change per holding is better than diffing our snapshots (which miss days the Mac was off).
    day_changes = [h["day_change"] for h in holdings if h.get("day_change") is not None]
    previous = [v for d, v in history.items() if d < today]
    day_change = round(sum(day_changes), 2) if day_changes else (round(total - previous[-1], 2) if previous else None)
    stock = sum(h["value"] or 0 for h in holdings)

    post(total, {**BASE_ATTRS, "status": "ok", "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                 "cash": round(sum(a["cash"] or 0 for a in accounts), 2),
                 "invested_cost": round(cost, 2), "gain": round(gain, 2),
                 "gain_pct": round(gain / cost * 100, 2) if cost else None, "day_change": day_change,
                 "day_change_pct": round(day_change / (stock - day_change) * 100, 2) if day_change and stock else None,
                 "accounts": [{k: a[k] for k in ("name", "total", "stock", "cash")} for a in accounts],
                 "holdings": [{**{k: h.get(k) for k in ("name", "account", "value", "cost", "gain", "gain_pct",
                                                       "units", "price_p", "unit_type", "day_change", "day_change_pct",
                                                       "yield_pct", "stock_type")}, "sedol": h["id"]}
                              for h in holdings],
                 "history": [[d, v] for d, v in list(history.items())[-180:]]})
    log.info("published £%.2f across %d accounts, %d holdings", total, len(accounts), len(holdings))


_published_series = {}  # sedol -> date last published, so each fund's history is posted once a day


def publish_prices(accounts, prices: Prices):
    """One sensor per fund with its price history (sensor.investment_<sedol>), for the Hub's detail charts."""
    today = date.today().isoformat()
    for h in (h for a in accounts for h in a["holdings"]):
        sedol = h["id"]
        if _published_series.get(sedol) == today:
            continue
        try:
            series = prices.history(sedol, h["name"])
        except Exception as e:  # FT down or changed: charts just go stale, nothing else depends on this
            log.warning("price history for %s failed: %s", h["name"], e)
            continue
        if not series:
            continue
        # FT quotes some funds in pounds and some in pence; HL always shows pence. Match HL's units.
        if h.get("price_p") and 50 < h["price_p"] / series[-1][1] < 200:
            series = [(d, p * 100) for d, p in series]
        post(round(series[-1][1], 2), {"friendly_name": h["name"], "icon": "mdi:chart-line", "sedol": sedol,
                                       "unit_of_measurement": "GBX", "source": "FT", "series": compact(series)},
             entity=f"sensor.investment_{sedol.lower()}")
        _published_series[sedol] = today
    log.info("price history published for %d funds", len(_published_series))


def refresh_t212():
    """Cash balance + interest history -> sensor.trading212. Read-only; never retried if the key is refused."""
    key, secret = (keyring.get_password(T212_KEYCHAIN, f) for f in ("key", "secret"))
    if not (key and secret):
        raise SystemExit("Trading 212 key missing from Keychain — run: python -m investments setup-t212")
    client = t212mod.T212(key, secret)
    summary = client.summary()
    interest = t212mod.summarise(client.interest(), summary["cash"])
    save_json(t212mod.LAST_FILE, {"cash": summary["cash"], "total": summary["total"], **interest, "daily": None})
    post(summary["cash"], {"friendly_name": "Trading 212", "icon": "mdi:piggy-bank", "unit_of_measurement": "GBP",
                           "status": "ok", "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
                           "currency": summary["currency"], "summary": summary, "interest": interest},
         entity=T212_SENSOR)
    log.info("published Trading 212 (%d interest payments)", interest["count"])  # no amounts in logs


def publish_t212_paused(reason):
    try:
        last = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"{HA_HTTP}/api/states/{T212_SENSOR}", headers={"Authorization": f"Bearer {os.environ['TOKEN']}"}),
            timeout=10).read())
        state, attrs = last["state"], last["attributes"]
    except Exception:
        state, attrs = "unknown", {"friendly_name": "Trading 212", "icon": "mdi:piggy-bank", "unit_of_measurement": "GBP"}
    post(state, {**attrs, "status": "paused", "paused_reason": reason}, entity=T212_SENSOR)


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
    accounts = hl.snapshot()
    publish(accounts)
    publish_prices(accounts, Prices())


def next_delay():
    h = datetime.now().hour
    return 3600 if 7 <= h < 22 else 4 * 3600


def t212_delay():
    return 1800 if 7 <= datetime.now().hour < 22 else 2 * 3600


def watch():
    """Two independent sources on their own timers: a problem with one never delays or unblocks the other."""
    hl = HL()
    due = {"hl": 0.0, "t212": 0.0}
    paused = {}  # source -> halt reason already published, so a halt is announced once, not every tick
    while True:
        now = time.time()
        if configured() and now >= due["hl"]:
            reason = halted_reason()
            if reason:  # wait for a successful manual `login`; checking again in a minute
                due["hl"] = now + 60
                if paused.get("hl") != reason:
                    log.warning("Hargreaves Lansdown paused: %s", reason)
                    publish_paused(reason)
                    paused["hl"] = reason
            else:
                paused.pop("hl", None)
                due["hl"] = now + next_delay()
                try:
                    refresh(hl)
                except Halted as e:
                    log.error("Hargreaves Lansdown halted: %s", e)
                    due["hl"] = now + 60
                except Exception as e:  # network or parsing trouble: not a login attempt, just try later
                    log.warning("refresh failed: %s", e)
        if t212_configured() and now >= due["t212"]:
            reason = t212mod.halted_reason()
            if reason:
                due["t212"] = now + 60
                if paused.get("t212") != reason:
                    log.warning("Trading 212 paused: %s", reason)
                    publish_t212_paused(reason)
                    paused["t212"] = reason
            else:
                paused.pop("t212", None)
                due["t212"] = now + t212_delay()
                try:
                    refresh_t212()
                except t212mod.Rejected as e:
                    log.error("Trading 212 halted: %s", e)
                    due["t212"] = now + 60
                except Exception as e:
                    log.warning("Trading 212 refresh failed: %s", e)
        time.sleep(15)


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
    elif cmd == "setup-t212":
        setup_t212()
    elif cmd == "t212":
        reason = t212mod.halted_reason()
        if reason:
            print(f"Previously halted: {reason}\nCheck the key (python -m investments setup-t212) before going on.")
            if input("Try once now? [y/N] ").strip().lower() != "y":
                return
            t212mod.HALT.unlink(missing_ok=True)
        refresh_t212()
        info = json.loads(t212mod.LAST_FILE.read_text())
        print(f"Connected: cash £{info['cash']:,.2f}, {info['count']} interest payments found"
              f"{', last ' + info['last_date'] if info['last_date'] else ''}. Automatic refreshes are on.")
    elif cmd == "status":
        print("Hargreaves Lansdown:", "in Keychain" if configured() else "not set (python -m investments setup)")
        print("  halted:", halted_reason() or "no")
        print("Trading 212:", "in Keychain" if t212_configured() else "not set (python -m investments setup-t212)")
        print("  halted:", t212mod.halted_reason() or "no")
    elif cmd == "--watch":
        watch()
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
