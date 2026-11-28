"""Hargreaves Lansdown and Trading 212 -> the core state service, which publishes `sensor.investments` for the Hub.

  python -m investments setup     store HL credentials in the macOS Keychain (asked for interactively)
  python -m investments login     log in once by hand, fetch and publish; also clears a halt after a failure
  python -m investments setup-t212  store a Trading 212 API key + secret in the Keychain (read-only key)
  python -m investments t212      connect to Trading 212 once by hand and publish; also clears a halt
  python -m investments status
  python -m investments --watch   the service (run by ./home up): Hargreaves Lansdown hourly 07:00-22:00 (else every
                                  4h), Trading 212 every 30 min (else every 2h)

Safety (HL locks the account after a few bad logins): one login attempt at a time; any failure halts automatic
logins until `login` succeeds by hand, except a login the network cut off, which gets ONE automatic retry 30 min
later (hl.take_retry); at most MAX_AUTO_LOGINS automatic logins a day.
"""
import getpass
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import telemetry

import keyring
import keyring.backend

from core import client as core

from .hl import DATA, HL, Credentials, Halted, NotSent, halted_reason, recovered, save_json, take_retry, _halt
from .prices import Prices, compact
from . import t212 as t212mod

log = logging.getLogger("investments")
ROOT = Path(__file__).resolve().parent.parent
KEYCHAIN = "home-automation.hargreaves-lansdown"
FIELDS = ("username", "dob", "password", "secure_number")
SENSOR = "sensor.investments"
T212_KEYCHAIN = "home-automation.trading212"
T212_SENSOR = "sensor.trading212"
LOGINS = DATA / "auto_logins.json"
MAX_AUTO_LOGINS = 8
SECRETS = ROOT / "data" / "secrets" / "keyring.json"


class FileKeyring(keyring.backend.KeyringBackend):
    """The server (Linux, no desktop keychain): credentials in one JSON file only this user can read, under data/
    (never in the repo). The Mac keeps using its Keychain."""
    priority = 1

    def _all(self) -> dict:
        return json.loads(SECRETS.read_text()) if SECRETS.exists() else {}

    def get_password(self, service, username):
        return self._all().get(service, {}).get(username)

    @staticmethod
    def _write(values: dict):
        SECRETS.parent.mkdir(parents=True, exist_ok=True)
        SECRETS.parent.chmod(0o700)
        tmp = SECRETS.with_suffix(".tmp")
        tmp.touch(mode=0o600)
        tmp.chmod(0o600)  # before anything is written to it
        tmp.write_text(json.dumps(values))
        tmp.replace(SECRETS)

    def set_password(self, service, username, password):
        values = self._all()
        values.setdefault(service, {})[username] = password
        self._write(values)

    def delete_password(self, service, username):
        values = self._all()
        values.get(service, {}).pop(username, None)
        self._write(values)


if sys.platform != "darwin":
    keyring.set_keyring(FileKeyring())


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
def post(state, attrs, entity):
    """Through the core, which mirrors it into Home Assistant."""
    core.report(entity, state, attrs)


HOLDING_FIELDS = ("name", "value", "cost", "gain", "gain_pct", "units", "price_p", "unit_type", "day_change",
                  "day_change_pct", "yield_pct", "stock_type")


def publish(accounts):
    """The HL snapshot -> the core state service (portfolio/hl), which merges every source into sensor.investments."""
    doc = {"name": "HL", "kind": "auto", "as_of": date.today().isoformat(), "status": "ok", "accounts": [
        {"name": a["name"], "type": "isa" if "isa" in a["name"].lower() else "other",
         **{k: a[k] for k in ("cash", "stock", "total") if a.get(k) is not None},
         "holdings": [{**{k: h[k] for k in HOLDING_FIELDS if h.get(k) is not None}, "id": h["id"].lower()}
                      for h in a["holdings"]]} for a in accounts]}
    result = core.put_source("hl", doc)
    log.info("sent HL to core: %d accounts, %d holdings (%s)", len(accounts),  # no amounts in logs
             sum(len(a["holdings"]) for a in accounts), "new snapshot" if result.get("changed") else "unchanged")


_published_series = {}  # sedol -> date last published, so each fund's history is posted once a day


def post_series(holding_id: str, name: str, series_pence):
    """sensor.investment_<id>: a fund's price history in pence, which the Hub's charts read (once a day per fund)."""
    post(round(series_pence[-1][1], 2), {"friendly_name": name, "icon": "mdi:chart-line", "sedol": holding_id,
                                         "unit_of_measurement": "GBX", "source": "FT", "series": compact(series_pence)},
         entity=f"sensor.investment_{holding_id.lower()}")
    _published_series[holding_id] = date.today().isoformat()


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
        post_series(sedol, h["name"], series)
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
    # The balance also goes into the central portfolio, as a cash account (sensor.trading212 keeps the interest).
    core.put_source("t212", {"name": "Trading 212", "kind": "auto", "as_of": date.today().isoformat(),
                             "accounts": [{"name": "Cash", "type": "cash", "cash": summary["cash"],
                                           "total": summary["total"]}]})
    log.info("published Trading 212 (%d interest payments)", interest["count"])  # no amounts in logs


def publish_t212_paused(reason):
    try:
        last = core.live(T212_SENSOR)
        state, attrs = last["state"], last["attributes"]
    except Exception:
        state, attrs = "unknown", {"friendly_name": "Trading 212", "icon": "mdi:piggy-bank", "unit_of_measurement": "GBP"}
    post(state, {**attrs, "status": "paused", "paused_reason": reason}, entity=T212_SENSOR)


def publish_paused(reason) -> bool:
    try:
        core.call("PATCH", "/v1/portfolio/hl", {"status": "paused", "paused_reason": reason})
        return True
    except core.CoreError as e:
        log.warning("couldn't mark HL paused in core: %s", e)
        return e.status == 404  # no HL snapshot yet: nothing to mark
    except OSError as e:  # core not up yet: try again next round
        log.warning("couldn't reach core to mark HL paused: %s", e)
        return False


def revalue(prices: Prices) -> int:
    """Today's price for each manual holding core can revalue (units + an ISIN), from FT. Only public fund ids are
    sent to FT. FT quotes some funds in pence: the price implied by what was written tells which. Also publishes each
    one's price history (in pence, like HL's) for the Hub's charts. Run hourly by the core task worker (schedule
    "revalue"). Returns how many prices were recorded."""
    recorded = 0
    for h in core.call("GET", "/v1/portfolio/priceable")["items"]:
        if not re.fullmatch(r"[a-z]{2}[0-9a-z]{10}", h["key"].lower()):  # only ISINs can be looked up reliably
            continue
        try:
            series = prices.history(h["key"].upper(), h["name"])
        except Exception as e:
            log.warning("no price for %s: %s", h["name"], e)
            continue
        if not series:
            continue
        day, price = series[-1]
        ratio = price / h["implied_gbp"]
        gbp = price / 100 if 50 < ratio < 200 else price if 0.5 < ratio < 2 else None
        if gbp is None:  # neither pounds nor pence: wrong fund, or a typo in what was written
            log.warning("price for %s doesn't match what was written (x%.2f); skipped", h["name"], ratio)
            continue
        core.call("PUT", f"/v1/prices/{h['key']}", {"day": day.isoformat(), "price_gbp": gbp, "source": "FT",
                                                     "name": h["name"]})
        recorded += 1
        if _published_series.get(h["key"]) != date.today().isoformat():  # the history too, for the Hub's charts
            try:
                post_series(h["key"], h["name"], series if gbp != price else [(d, p * 100) for d, p in series])
            except OSError as e:
                log.warning("price history for %s not published: %s", h["name"], e)
    return recorded


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
        except (Halted, NotSent):  # NotSent: the login page was unusable and nothing went to HL; try next round
            raise
        except Exception as e:  # e.g. the connection dropped mid-login: it may have counted, so not straight away
            _halt(f"login interrupted ({type(e).__name__}: {e}); one automatic try in 30 min, unless that was it",
                  retry_once=True)
        if not hl.logged_in():
            _halt("logged in but the portfolio still isn't readable; pausing rather than logging in again")
    accounts = hl.snapshot()
    publish(accounts)
    publish_prices(accounts, Prices())
    recovered()


def next_delay():
    h = datetime.now().hour
    return 3600 if 7 <= h < 22 else 4 * 3600


def t212_delay():
    return 1800 if 7 <= datetime.now().hour < 22 else 2 * 3600


def core_ready() -> bool:
    """Is the core API up? Checked before each refresh, so a restart race doesn't cost an hour's refresh."""
    try:
        core.call("GET", "/v1/health", timeout=3)
        return True
    except Exception:
        return False


def watch():
    """Two independent sources on their own timers: a problem with one never delays or unblocks the other."""
    hl = HL()
    due = {"hl": 0.0, "t212": 0.0}
    paused = {}  # source -> halt reason already published, so a halt is announced once, not every tick
    while True:
        now = time.time()
        if (configured() and now >= due["hl"]) or (t212_configured() and now >= due["t212"]):
            if not core_ready():  # nothing to publish to yet: look again shortly, without touching HL
                due = {k: max(v, now + 30) for k, v in due.items()}
                time.sleep(15)
                continue
        if configured() and now >= due["hl"]:
            reason = halted_reason()
            if reason and take_retry():  # a login the network cut off: its one automatic try
                log.warning("Hargreaves Lansdown: trying one automatic login after: %s", reason)
                reason = None
            if reason:  # wait for a successful manual `login`; checking again in a minute
                due["hl"] = now + 60
                if paused.get("hl") != reason:
                    log.warning("Hargreaves Lansdown paused: %s", reason)
                    if publish_paused(reason):
                        paused["hl"] = reason
            else:
                paused.pop("hl", None)
                due["hl"] = now + next_delay()
                try:
                    refresh(hl)
                except Halted as e:
                    log.error("Hargreaves Lansdown halted: %s", e)
                    due["hl"] = now + 60
                except NotSent as e:
                    log.warning("Hargreaves Lansdown login skipped: %s", e)
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
    telemetry.setup("investments")
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
