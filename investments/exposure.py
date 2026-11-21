"""What each fund holds: its asset allocation and regional weightings, from the FT's public fund pages.

The worker's `exposure` task (daily) fetches the funds that are new or more than REFRESH_DAYS old and stores each in
the core as document fund_exposure/<holding id>; the core weights them by what's held (core/exposure.py) for the
Hub. Only public fund identifiers are sent to the FT, never holdings or amounts.
"""
import logging
import re
import time
from datetime import date

from bs4 import BeautifulSoup

from core import client as core

from .prices import Prices

log = logging.getLogger("investments.exposure")
PAGE = "https://markets.ft.com/data/funds/tearsheet/holdings"
COLLECTION = "fund_exposure"
REFRESH_DAYS = 7
SUPER = ("Americas", "Greater Europe", "Greater Asia")


def _pct(text: str) -> float | None:
    m = re.match(r"^(-?[\d.]+)%$", text.strip())
    return float(m.group(1)) if m else None


def parse(html: str) -> dict:
    """{"asset": {type: pct}, "regions": {super-region: {region: pct}}, "sectors": {sector: pct}} from the page."""
    soup = BeautifulSoup(html, "html.parser")
    out = {"asset": {}, "regions": {}, "sectors": {}}
    for table in soup.find_all("table"):
        head = [th.get_text(" ", strip=True) for th in table.find_all("th")]
        rows = [[td.get_text(" ", strip=True) for td in tr.find_all("td")] for tr in table.find_all("tr")]
        rows = [r for r in rows if len(r) >= 2 and _pct(r[1]) is not None]
        if head[:2] == ["Type", "% Net assets"]:
            out["asset"] = {r[0]: _pct(r[1]) for r in rows}
        elif head[:1] == ["Sector"] and any(r[0] in SUPER for r in rows):
            parent = None
            for r in rows:
                if r[0] in SUPER:
                    parent = r[0]
                    out["regions"].setdefault(parent, {})
                elif parent:
                    out["regions"][parent][r[0]] = _pct(r[1])
        elif head[:1] == ["Sector"] and not out["sectors"]:
            out["sectors"] = {r[0]: _pct(r[1]) for r in rows}
    return out


def fetch(prices: Prices, holding_id: str, name: str) -> dict | None:
    ref = prices.resolve(holding_id.upper(), name)
    if not ref:
        return None
    r = prices.s.get(PAGE, params={"s": ref["symbol"]}, timeout=30)
    r.raise_for_status()
    data = parse(r.text)
    if not data["asset"] and not data["regions"]:
        return None
    return {**data, "symbol": ref["symbol"], "ft_name": ref["ft_name"], "fetched": date.today().isoformat()}


def refresh(progress=lambda fraction, message: None) -> dict:
    """Fetch every held fund whose breakdown is missing or stale. Returns counts."""
    held = {}
    for src in core.call("GET", "/v1/portfolio")["sources"]:
        for acc in src["data"].get("accounts", []):
            for h in acc.get("holdings", []):
                held.setdefault(h["id"].lower(), h["name"])
    known = {d["key"]: d for d in core.call("GET", f"/v1/state/{COLLECTION}").get("items", [])}
    due = [(i, n) for i, n in held.items()
           if i not in known or (date.today() - date.fromisoformat(known[i]["data"].get("fetched", "2000-01-01"))).days
           >= REFRESH_DAYS]
    prices, done, missing = Prices(), 0, []
    for k, (hid, name) in enumerate(due, 1):
        progress(k / max(len(due), 1), f"{k} of {len(due)} funds")
        try:
            data = fetch(prices, hid, name)
        except Exception as e:  # one fund's page failing shouldn't stop the rest
            log.warning("no breakdown for %s: %s", name, e)
            data = None
        if data:
            core.put(COLLECTION, hid, data)
            done += 1
        else:
            missing.append(name)
        time.sleep(0.5)
    if missing:
        log.info("no FT breakdown for: %s", ", ".join(missing))
    return {"funds": len(held), "fetched": done, "missing": missing}
