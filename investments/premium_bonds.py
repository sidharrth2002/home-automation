"""Premium Bonds: has the holder number won anything? (the worker's `premium-bonds` task, scheduled daily)

Uses NS&I's public "have I won" checker, the same one the website's form posts to: the holder number only, never a
sign-in, never the account pages. Draws are on the first working day of the month and NS&I says results are up
within a few days, so the daily task does nothing (no request) until REVEAL_DAYS after this month's draw, then
checks once and records the month; unclaimed prizes are checked every UNCLAIMED_EVERY_DAYS. A failure is recorded
and tried again at the next daily run: no retries against NS&I.

PREMIUM_BOND_HOLDER in .env is the holder number. It goes to NS&I and nowhere else: not the logs, the core, the
sensor or the task result. Results go into the core document finance/premium_bonds and sensor.premium_bonds,
alongside the holding the finance session wrote into portfolio/nsandi (read, never changed). Amounts never go in
the logs; a win also raises a Home Assistant notification (silent, no voice on the TV).
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from core import client as core

log = logging.getLogger("investments.premium_bonds")
ENDPOINT = "https://www.nsandi.com/premium-bonds-have-i-won-ajax"
ENV = "PREMIUM_BOND_HOLDER"
DOC = ("finance", "premium_bonds")
SENSOR = "sensor.premium_bonds"
REVEAL_DAYS = 3
UNCLAIMED_EVERY_DAYS = 30
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")


class NotConfigured(RuntimeError):
    pass


class InvalidHolder(ValueError):
    pass


# ── when ─────────────────────────────────────────────────────────
def _easter(year: int) -> date:
    """Easter Sunday (the anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _holidays(year: int) -> set[date]:
    """The England bank holidays that can fall at the start of a month (the only ones that move a draw)."""
    easter = _easter(year)
    may = date(year, 5, 1)
    return {date(year, 1, 1), easter - timedelta(days=2), easter + timedelta(days=1),
            may + timedelta(days=(7 - may.weekday()) % 7)}  # early May: the first Monday


def draw_date(year: int, month: int) -> date:
    """The first working day of the month."""
    d, off = date(year, month, 1), _holidays(year)
    while d.weekday() >= 5 or d in off:
        d += timedelta(days=1)
    return d


def london_today() -> date:
    return datetime.now(ZoneInfo("Europe/London")).date()


def next_check(today: date) -> date:
    """When the next month's (or this month's, if still to come) results get checked."""
    this = draw_date(today.year, today.month) + timedelta(days=REVEAL_DAYS)
    if today < this:
        return this
    nxt = date(today.year + today.month // 12, today.month % 12 + 1, 1)
    return draw_date(nxt.year, nxt.month) + timedelta(days=REVEAL_DAYS)


# ── NS&I ─────────────────────────────────────────────────────────
def _post(fields: dict, timeout: float = 20) -> dict:
    req = urllib.request.Request(ENDPOINT, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"User-Agent": "Mozilla/5.0 (home-automation premium bond check)",
                                          "Accept": "application/json",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ask(holder: str, period: str, post=_post) -> dict:
    """One check: period is "this_month", "last_six_month" or "unclaimed_prize". Returns {won, header, prizes}
    (each prize {prize, date}; bond numbers are left out)."""
    body = post({"field_premium_bond_period": period, "field_premium_bond_number": holder})
    if body.get("holder_number") == "is invalid":
        raise InvalidHolder("NS&I says the holder number is invalid: check PREMIUM_BOND_HOLDER in .env")
    if "status" not in body:
        raise ValueError(f"unexpected reply from NS&I (keys: {', '.join(sorted(body)) or 'none'})")
    prizes = [{"prize": int(float(e["prize"])), "date": e.get("date")} for e in body.get("history") or []
              if e.get("bond_number") not in (None, "", "0")]
    return {"won": "no" not in str(body["status"]).lower(), "header": str(body.get("header") or ""), "prizes": prizes}


def _for_month(result: dict, draw: date) -> bool:
    """False if the reply names a different month: NS&I hasn't put this month's results up yet."""
    text = result["header"].lower()
    named = [i + 1 for i, m in enumerate(MONTHS) if m in text]
    return not named or draw.month in named


# ── the task ─────────────────────────────────────────────────────
def holding() -> float | None:
    """The Premium Bonds total in portfolio/nsandi (written by the finance session), if it's there."""
    try:
        src = core.call("GET", "/v1/portfolio/nsandi")
    except core.CoreError as e:
        if e.status == 404:
            return None
        raise
    totals = [a.get("total") or 0 for a in src["data"].get("accounts", []) if "premium" in a.get("name", "").lower()]
    return round(sum(totals), 2) if totals else None


def load() -> dict:
    try:
        return core.get(*DOC)["data"]
    except core.CoreError as e:
        if e.status != 404:
            raise
        return {"draws": {}, "unclaimed": None}


def notify(title: str, message: str):
    """A Home Assistant notification: shows in HA and the app, makes no sound in the room."""
    req = urllib.request.Request(f"{os.environ.get('HA_HTTP', 'http://localhost:8123')}/api/services/"
                                 "persistent_notification/create", method="POST",
                                 data=json.dumps({"title": title, "message": message,
                                                  "notification_id": "premium_bonds"}).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['TOKEN']}",
                                          "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).close()


def report(doc: dict, today: date):
    draws = doc.get("draws") or {}
    last = max(draws) if draws else None
    this_year = [p for m, d in draws.items() if m.startswith(str(today.year)) for p in d.get("prizes", [])]
    unclaimed = (doc.get("unclaimed") or {}).get("prizes") or []
    state = ("won" if draws[last]["won"] else "no win") if last else "waiting"
    if doc.get("last_error") and last != draw_date(today.year, today.month).strftime("%Y-%m"):
        state = "error"
    core.report(SENSOR, state, {
        "friendly_name": "Premium Bonds", "icon": "mdi:trophy-outline", "holding": holding(),
        "last_draw": last, "last_checked": doc.get("last_checked"), "won_this_year": len(this_year),
        "won_this_year_total": sum(p["prize"] for p in this_year), "unclaimed": len(unclaimed),
        "unclaimed_total": sum(p["prize"] for p in unclaimed), "next_check": next_check(today).isoformat(),
        "last_error": doc.get("last_error")})


def check(today: date | None = None, ask=ask, notify=notify) -> dict:
    """The daily task. Asks NS&I only when a result is due; never raises for NS&I trouble (recorded instead), so
    the task queue doesn't retry against NS&I."""
    holder = os.environ.get(ENV, "").strip()
    if not holder:
        raise NotConfigured(f"set {ENV} in .env to your Premium Bonds holder number (NS&I app or letters)")
    today = today or london_today()
    draw = draw_date(today.year, today.month)
    month = draw.strftime("%Y-%m")
    doc = load()
    doc.setdefault("draws", {})
    last_unclaimed = (doc.get("unclaimed") or {}).get("checked_on")
    due_draw = today >= draw + timedelta(days=REVEAL_DAYS) and month not in doc["draws"]
    due_unclaimed = not last_unclaimed or (today - date.fromisoformat(last_unclaimed)).days >= UNCLAIMED_EVERY_DAYS
    if not (due_draw or due_unclaimed):
        return {"checked": False, "draw": month, "next_check": next_check(today).isoformat()}

    stamp, errors, outcome = datetime.now().astimezone().isoformat(timespec="seconds"), [], {"checked": True}
    if due_draw:
        try:
            r = ask(holder, "this_month")
            if _for_month(r, draw):
                doc["draws"][month] = {"checked_at": stamp, "won": r["won"], "prizes": r["prizes"]}
                outcome.update(draw=month, won=r["won"])
            else:
                outcome.update(draw=month, published=False)  # tomorrow's run asks again
        except Exception as e:  # NS&I down, changed, or the number refused: try again tomorrow
            errors.append(f"this month: {e if isinstance(e, InvalidHolder) else type(e).__name__}")
    if due_unclaimed:
        try:
            u = ask(holder, "unclaimed_prize")
            doc["unclaimed"] = {"checked_on": today.isoformat(), "prizes": u["prizes"] if u["won"] else []}
            outcome["unclaimed"] = len(doc["unclaimed"]["prizes"])
        except Exception as e:
            errors.append(f"unclaimed: {e if isinstance(e, InvalidHolder) else type(e).__name__}")
    doc["last_checked"] = stamp
    doc["last_error"] = "; ".join(errors) or None
    core.put(*DOC, doc)
    report(doc, today)
    if outcome.get("won"):
        total = sum(p["prize"] for p in doc["draws"][month]["prizes"])
        log.info("premium bonds: a prize in the %s draw", month)  # no amounts in logs
        try:
            notify("Premium Bonds win", f"You won £{total:,} in the {draw:%B %Y} draw.")
        except OSError as e:
            log.warning("couldn't raise the notification: %s", e)
    if errors:
        log.warning("premium bonds check: %s (next try tomorrow)", "; ".join(errors))
        outcome["error"] = doc["last_error"]
    return outcome


if __name__ == "__main__":
    from music_sync.service import load_env
    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(check())
