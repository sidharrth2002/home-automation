"""Read-only Trading 212 client: cash balance and the interest it pays on uninvested cash.

Uses Trading 212's official public API (https://docs.trading212.com/api), HTTP Basic with an API key + secret.
Only GET requests are ever made, so even a key with trading permissions couldn't be used to place an order from
here; the setup still asks you to create a read-only key.

If the key is rejected (401/403) nothing retries: a halt file stops the service until `python -m investments
t212` succeeds by hand. Rate limits are respected (summary 1 req/5s, history 20 req/min).
"""
import base64
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import requests

from .hl import DATA, UA, save_json

BASE = "https://live.trading212.com/api/v0"
HALT = DATA / "T212_HALTED"
INTEREST_FILE = DATA / "t212_interest.json"
LAST_FILE = DATA / "t212_last.json"  # last balances, kept locally so bin/check-commit can recognise them
INTEREST_TYPES = ("INTEREST_ON_FREE_CASH", "LENDING_INTEREST")
EPOCH = date(1970, 1, 1)
PAGE_PAUSE_S = 3.2  # 20 requests a minute is the history limit
MAX_PAGES = 80


class Rejected(RuntimeError):
    """The key was refused or lacks a permission; retrying can't help."""


def halted_reason():
    return HALT.read_text().strip() if HALT.exists() else None


def halt(reason):
    DATA.mkdir(parents=True, exist_ok=True)
    HALT.write_text(f"{datetime.now():%Y-%m-%d %H:%M} {reason}\n")
    raise Rejected(reason)


class T212:
    def __init__(self, key: str, secret: str):
        key, secret = (key or "").strip(), (secret or "").strip()
        if len(key) < 8 or len(secret) < 8 or any(c.isspace() for c in key + secret):
            raise ValueError("that doesn't look like a Trading 212 API key and secret")
        token = base64.b64encode(f"{key}:{secret}".encode()).decode()
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Basic {token}", "User-Agent": UA})

    def _get(self, url, params=None):
        """GET with one polite wait on 429; a refused key halts instead of being retried."""
        for attempt in (1, 2):
            r = self.s.get(url if url.startswith("http") else BASE + url, params=params, timeout=30)
            if r.status_code in (401, 403):
                halt(f"Trading 212 refused the key ({r.status_code}): "
                     f"{'wrong key/secret' if r.status_code == 401 else 'the key lacks a permission for ' + url}")
            if r.status_code == 429 and attempt == 1:
                reset = float(r.headers.get("x-ratelimit-reset", 0)) - time.time()
                time.sleep(min(max(reset, 5), 65))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError("rate limited")

    def summary(self):
        j = self._get("/equity/account/summary").json()
        cash = j.get("cash") or {}
        inv = j.get("investments") or {}
        available, in_pies, reserved = (cash.get(k) or 0 for k in ("availableToTrade", "inPies", "reservedForOrders"))
        return {"currency": j.get("currency", "GBP"), "cash": round(available + in_pies + reserved, 2),
                "available": available, "in_pies": in_pies, "reserved": reserved,
                "invested": inv.get("currentValue"), "invested_cost": inv.get("totalCost"),
                "unrealised": inv.get("unrealizedProfitLoss"), "total": j.get("totalValue")}

    def interest(self):
        """Every interest payment, newest first. Walks the history only until it reaches payments it already has."""
        known = {i["ref"]: i for i in json.loads(INTEREST_FILE.read_text())} if INTEREST_FILE.exists() else {}
        newest_known = max((i["date"] for i in known.values()), default=None)
        url, params = "/equity/history/transactions", {"limit": 50}
        newest_first = None
        for page in range(MAX_PAGES):
            j = self._get(url, params).json()
            items = j.get("items") or []
            for it in items:
                if it.get("type") in INTEREST_TYPES and it.get("reference") not in known:
                    known[it["reference"]] = {"ref": it["reference"], "date": it["dateTime"][:10],
                                              "amount": it["amount"], "type": it["type"]}
            if newest_first is None and len(items) > 1:
                newest_first = items[0]["dateTime"] >= items[-1]["dateTime"]
            nxt = j.get("nextPagePath")
            # Interest is paid daily, so once a page lies entirely before the newest payment we already have,
            # (newest-first) there's nothing newer further back. If the order is unknown, walk it all.
            caught_up = (newest_first and newest_known and items
                         and all(i["dateTime"][:10] < newest_known for i in items))
            if not nxt or caught_up:
                break
            url, params = "https://live.trading212.com" + nxt, None
            time.sleep(PAGE_PAUSE_S)
        out = sorted(known.values(), key=lambda i: (i["date"], i["ref"]), reverse=True)
        save_json(INTEREST_FILE, out)
        return out


def summarise(payments, cash, today=None):
    """Interest figures for the dashboard from raw payments: [{date, amount, type}]."""
    today = today or date.today()
    by_day = defaultdict(float)
    for p in payments:
        by_day[p["date"]] += p["amount"]
    days = sorted(by_day)
    total = lambda since: round(sum(v for d, v in by_day.items() if d >= since.isoformat()), 2)
    last = days[-1] if days else None
    last_amount = round(by_day[last], 2) if last else None
    month_start, year_start = today.replace(day=1), today.replace(month=1, day=1)
    last30 = total(today - timedelta(days=30))
    # A daily payment on today's balance, annualised. Only an estimate: the rate changes and the balance moves.
    est_rate = round(by_day[last] * 365 / cash * 100, 2) if last and cash and cash > 0 else None
    daily = [[(date.fromisoformat(d) - EPOCH).days, round(by_day[d], 4)] for d in days if d >= (today - timedelta(days=400)).isoformat()]
    return {"last_date": last, "last_amount": last_amount, "month": total(month_start), "last30": last30,
            "ytd": total(year_start), "all_time": round(sum(by_day.values()), 2), "count": len(days),
            "est_rate_pct": est_rate, "est_month": round(last_amount * 30, 2) if last_amount else None,
            "since": days[0] if days else None, "daily": daily}
