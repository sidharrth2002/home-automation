"""Daily price history for each holding, from the Financial Times' public fund pages.

HL only shows today's price, so history comes from FT, keyed by ISIN. UK funds' ISINs follow from the SEDOL
(GB00 + SEDOL + check digit); anything else is looked up by name. Only public fund identifiers are sent to FT,
never holdings or amounts. Each fund is fetched at most once a day and cached under data/investments/prices/.
"""
import json
import logging
import time
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

from .hl import DATA, UA

log = logging.getLogger("investments.prices")
CACHE = DATA / "prices"
IDS = DATA / "ft_ids.json"
SEARCH = "https://markets.ft.com/data/searchapi/searchsecurities"
HISTORY = "https://markets.ft.com/data/equities/ajax/get-historical-prices"
YEARS = 5
EPOCH = date(1970, 1, 1)


def gb_isin(sedol: str) -> str:
    """GB00 + SEDOL + the ISIN check digit (Luhn over the letters-as-numbers expansion)."""
    base = "GB00" + sedol.upper()
    digits = "".join(str(int(c, 36)) for c in base)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return base + str((10 - total % 10) % 10)


class Prices:
    def __init__(self):
        CACHE.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self.ids = json.loads(IDS.read_text()) if IDS.exists() else {}

    def _search(self, query):
        r = self.s.get(SEARCH, params={"query": query}, timeout=20)
        r.raise_for_status()
        found = (r.json().get("data") or {}).get("security") or []
        found = [f for f in found if f.get("assetClass") in ("Funds", "ETFs", "Equities")] or found
        return found[0] if found else None

    def resolve(self, sedol, name):
        """FT's internal id for a holding, cached. Tries the GB ISIN first, then the fund's name."""
        if sedol in self.ids:
            return self.ids[sedol]
        hit = self._search(gb_isin(sedol)) or self._search(name)
        entry = {"xid": hit["xid"], "symbol": hit["symbol"], "ft_name": hit["name"]} if hit else None
        self.ids[sedol] = entry
        IDS.write_text(json.dumps(self.ids, indent=1))
        return entry

    def history(self, sedol, name):
        """[(date, close)] for the last YEARS years, oldest first; refreshed at most once a day."""
        path = CACHE / f"{sedol}.json"
        if path.exists():
            cached = json.loads(path.read_text())
            if cached.get("fetched") == date.today().isoformat():
                return [(date.fromisoformat(d), p) for d, p in cached["series"]]
        ref = self.resolve(sedol, name)
        if not ref:
            log.warning("no FT match for %s (%s)", name, sedol)
            return []
        end = date.today()
        r = self.s.get(HISTORY, timeout=30, params={
            "startDate": (end - timedelta(days=365 * YEARS)).strftime("%Y/%m/%d"),
            "endDate": end.strftime("%Y/%m/%d"), "symbol": ref["xid"]})
        r.raise_for_status()
        series = []
        for tr in BeautifulSoup("<table>" + r.json().get("html", "") + "</table>", "html.parser").find_all("tr"):
            td = tr.find_all("td")
            if len(td) < 5:
                continue
            day = td[0].get_text("|", strip=True).split("|")[0]
            try:
                series.append((datetime.strptime(day, "%A, %B %d, %Y").date(), float(td[4].get_text(strip=True).replace(",", ""))))
            except ValueError:
                continue
        series.sort()
        path.write_text(json.dumps({"fetched": date.today().isoformat(), "symbol": ref["symbol"],
                                    "series": [[d.isoformat(), p] for d, p in series]}))
        time.sleep(0.5)
        return series


def compact(series, daily_days=400):
    """Daily points for the last `daily_days`, weekly before that, as [days since epoch, close].

    Keeps a 5-year series around 6 KB, well inside what an HA state attribute should carry.
    """
    if not series:
        return []
    cutoff = series[-1][0] - timedelta(days=daily_days)
    out, last_week = [], None
    for d, p in series:
        if d < cutoff:
            week = d.isocalendar()[:2]
            if week == last_week:
                continue
            last_week = week
        out.append([(d - EPOCH).days, round(p, 2)])
    return out
