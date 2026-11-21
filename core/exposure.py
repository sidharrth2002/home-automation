"""Portfolio exposure: each fund's breakdown (documents fund_exposure/<holding id>, fetched from the FT by the
`exposure` task) weighted by what's held, plus the cash accounts, for the Hub.

- asset: GBP in shares, bonds, cash and other. Savings, Premium Bonds, cash accounts and uninvested cash count as
  cash; a holding with no breakdown yet is "Not analysed". Negative cash in a fund (borrowing, derivatives) nets.
- regions: GBP of *shares* by region (the FT's regional weightings cover a fund's shares only), grouped by
  super-region.
Only what counts towards the total is included.
"""
from .db import DB

CASH_TYPES = {"savings", "premium_bonds", "cash", "current"}
GROUPS = {"Americas": "Americas", "Greater Europe": "Europe", "Greater Asia": "Asia-Pacific"}
ASSET_ORDER = ("Shares", "Bonds", "Cash", "Other", "Not analysed")


def asset_class(ft_type: str) -> str:
    t = ft_type.lower()
    return "Shares" if "stock" in t else "Bonds" if "bond" in t else "Cash" if t == "cash" else "Other"


def compute(sources: list[dict], breakdowns: dict[str, dict]) -> dict:
    """sources: finance.current() rows; breakdowns: holding id -> fund_exposure document data."""
    asset = dict.fromkeys(ASSET_ORDER, 0.0)
    regions: dict[tuple[str, str], float] = {}
    funds = analysed = 0
    fetched = []
    for row in sources:
        for acc in row["data"].get("accounts", []):
            if acc.get("in_total", True) is False:
                continue
            if acc.get("type") in CASH_TYPES:
                asset["Cash"] += acc.get("total") or acc.get("cash") or 0
                continue
            asset["Cash"] += acc.get("cash") or 0  # uninvested cash in an investment account
            for h in acc.get("holdings", []):
                value = h.get("value") or 0
                funds += 1
                b = breakdowns.get(str(h.get("id", "")).lower())
                if not b or not b.get("asset"):
                    asset["Not analysed"] += value
                    continue
                analysed += 1
                fetched.append(b.get("fetched") or "")
                total = sum(b["asset"].values()) or 100
                for t, pct in b["asset"].items():
                    asset[asset_class(t)] += value * pct / total
                for parent, children in (b.get("regions") or {}).items():
                    for name, pct in children.items():
                        if pct:
                            key = (GROUPS.get(parent, parent), name)
                            regions[key] = regions.get(key, 0) + value * pct / 100
    return {
        "asset": [{"name": k, "value": round(v, 2)} for k, v in asset.items() if round(v, 2)],
        "regions": sorted(({"group": g, "name": n, "value": round(v, 2)} for (g, n), v in regions.items() if v >= 0.5),
                          key=lambda r: -r["value"]),
        "funds": funds, "analysed": analysed, "as_of": min(f for f in fetched if f) if any(fetched) else None,
    }


def breakdowns(db: DB) -> dict[str, dict]:
    return {d["key"]: d["data"] for d in db.list_docs("fund_exposure")}
