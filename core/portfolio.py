"""The `portfolio` collection: one document per source (portfolio/hl, portfolio/hsbc, ...), merged into
sensor.investments for the Hub, the TV and the widget.

A source document:

    {"name": "HSBC", "kind": "manual",            # "auto" (a service fetches it) or "manual" (written over the API)
     "as_of": "2026-11-21",                        # when the figures were true, optional
     "status": "ok",                               # or "paused", with "paused_reason"
     "accounts": [
       {"name": "GIA", "type": "gia", "cash": 120.0,
        "holdings": [{"name": "Some Index Fund C Inc", "id": "gb00b00000000", "value": 1000.0, "units": 950.5,
                      "status": "pending", "settles": "2026-11-23"}]},
       {"name": "Regular Saver", "type": "savings", "cash": 500.0, "interest_pct": 5.0, "matures": "2027-05-01"}]}

Money is GBP. An account's total is its cash plus its holdings' values unless it gives `total`; `"in_total": false`
keeps an account on record but out of the headline figure. Unknown fields are kept as they are, for later use.
"""
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccountType = Literal["isa", "gia", "sipp", "pension", "lisa", "savings", "premium_bonds", "current", "cash", "other"]


class Holding(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1)
    id: str | None = Field(None, description="ISIN, SEDOL or any stable id; made from the name if left out")
    value: float = Field(description="GBP, what it's worth now (for a pending buy: the amount being invested)")
    units: float | None = Field(None, description="with an ISIN id, lets core revalue it from fund prices")
    price_p: float | None = None
    cost: float | None = None
    gain: float | None = None
    gain_pct: float | None = None
    day_change: float | None = None
    day_change_pct: float | None = None
    yield_pct: float | None = None
    status: Literal["held", "pending"] = "held"
    settles: date | None = None


class Account(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1)
    key: str | None = Field(None, description="stable id within the source; made from the name if left out")
    type: AccountType = "other"
    cash: float | None = None
    total: float | None = Field(None, description="cash + holdings if left out")
    stock: float | None = None
    interest_pct: float | None = None
    matures: date | None = None
    in_total: bool = Field(True, description="false keeps it on record but out of the headline figure")
    holdings: list[Holding] = []


class Source(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1)
    kind: Literal["auto", "manual"] = "manual"
    as_of: date | None = None
    status: Literal["ok", "paused"] = "ok"
    paused_reason: str | None = None
    accounts: list[Account] = []


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def validate(data) -> dict:
    """Check a source document and fill in what can be worked out (ids, account totals). Raises ValueError
    (pydantic's ValidationError is one)."""
    doc = (data if isinstance(data, Source) else Source.model_validate(data)).model_dump(mode="json", exclude_none=True)
    for acc in doc["accounts"]:
        for h in acc["holdings"]:
            h["id"] = str(h.get("id") or _slug(h["name"])).lower()
        if acc.get("total") is None:
            acc["total"] = round((acc.get("cash") or 0) + sum(h["value"] for h in acc["holdings"]), 2)
    return doc


def merge(sources: list[dict], history: dict[str, float], today: str) -> tuple[float, dict]:
    """sensor.investments (state, attributes) from the source documents (store rows) and the daily-total history.

    Keeps the attribute names the Hub, TV and widget already read; adds `sources` and each holding's `source`.
    """
    accounts, holdings, cash = [], [], 0.0
    status, reasons, updated = "ok", [], []
    for row in sources:
        doc, src = row["data"], row["id"]
        updated.append(row["updated"])
        if doc.get("status") == "paused":
            status = "paused"
            reasons.append(f"{doc['name']}: {doc.get('paused_reason') or 'paused'}")
        for acc in doc.get("accounts", []):
            counted = acc.get("in_total", True) is not False
            accounts.append({"name": acc["name"] if len(sources) == 1 else f"{doc['name']} {acc['name']}",
                             "total": acc.get("total"), "stock": acc.get("stock"), "cash": acc.get("cash"),
                             "type": acc.get("type"), "source": src, "in_total": counted})
            if counted:
                cash += acc.get("cash") or 0
            for h in acc.get("holdings", []):
                holdings.append({**{k: h.get(k) for k in ("name", "value", "cost", "gain", "gain_pct", "units",
                                                          "price_p", "unit_type", "day_change", "day_change_pct",
                                                          "yield_pct", "stock_type", "status", "settles")},
                                 "account": h.get("account") or acc["name"], "sedol": h["id"], "source": src,
                                 "in_total": counted})
    counted_accounts = [a for a in accounts if a["in_total"]]
    total = round(sum(a["total"] or 0 for a in counted_accounts), 2)
    held = [h for h in holdings if h["in_total"]]
    holdings.sort(key=lambda h: -(h["value"] or 0))
    with_cost = [h for h in held if h.get("cost") is not None]
    cost = sum(h["cost"] for h in with_cost)
    gain = sum(h["gain"] if h.get("gain") is not None else h["value"] - h["cost"] for h in with_cost)
    history = {**history, today: total}
    day = [h for h in held if h.get("day_change") is not None]
    if day:
        day_change = round(sum(h["day_change"] for h in day), 2)
        base = sum(h["value"] or 0 for h in day) - day_change
    else:  # no per-holding change from any source: fall back to yesterday's total
        previous = [v for d, v in sorted(history.items()) if d < today]
        day_change = round(total - previous[-1], 2) if previous else None
        base = previous[-1] if previous else 0
    attrs = {"friendly_name": "Investments", "icon": "mdi:chart-line", "unit_of_measurement": "GBP",
             "status": status, "updated": max(updated) if updated else None,
             "cash": round(cash, 2), "invested_cost": round(cost, 2), "gain": round(gain, 2),
             "gain_pct": round(gain / cost * 100, 2) if cost else None, "day_change": day_change,
             "day_change_pct": round(day_change / base * 100, 2) if day_change is not None and base else None,
             "accounts": accounts, "holdings": holdings,
             "history": [[d, v] for d, v in sorted(history.items())[-180:]],
             "sources": [{"id": r["id"], "name": r["data"]["name"], "kind": r["data"].get("kind"),
                          "as_of": r["data"].get("as_of"), "updated": r["updated"], "status": r["data"].get("status")}
                         for r in sources]}
    if reasons:
        attrs["paused_reason"] = "; ".join(reasons)
    return total, attrs
