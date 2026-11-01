"""Trading 212 client against a fake API (no network): read-only, polite, and it stops when the key is refused."""
import base64
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from investments import t212


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Only `get` exists: any attempt to POST/PUT/DELETE (i.e. to change something) fails the test."""

    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.routes(url, params, len(self.calls))


def tx(day, amount, type_="INTEREST_ON_FREE_CASH", ref=None):
    return {"dateTime": f"{day}T05:00:00Z", "amount": amount, "type": type_, "reference": ref or f"{type_}-{day}",
            "currency": "GBP"}


def history(url, params, n):
    if "summary" in url:
        return Resp(body={"currency": "GBP", "cash": {"availableToTrade": 1000.0, "inPies": 50.0, "reservedForOrders": 0},
                          "investments": {"currentValue": 0, "totalCost": 0, "unrealizedProfitLoss": 0}, "totalValue": 1050.0})
    if params is not None:  # first page, newest first
        return Resp(body={"items": [tx("2026-10-31", 0.11), tx("2026-10-30", 5000, "DEPOSIT"), tx("2026-10-29", 0.11)],
                          "nextPagePath": "/api/v0/equity/history/transactions?cursor=2&limit=50"})
    return Resp(body={"items": [tx("2026-10-28", 0.10), tx("2026-10-27", 0.10), tx("2026-10-26", 0.07, "LENDING_INTEREST")]})


def client(routes, tmp):
    t212.DATA, t212.HALT = tmp, tmp / "T212_HALTED"
    t212.INTEREST_FILE, t212.LAST_FILE = tmp / "t212_interest.json", tmp / "t212_last.json"
    c = t212.T212("key-12345678", "secret-12345678")
    c.s = FakeSession(routes)
    return c


def run():
    # a malformed key never reaches the network
    for bad in (("", "secret-12345678"), ("key-12345678", "short"), ("key 12345678", "secret-12345678")):
        try:
            t212.T212(*bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")
    assert "Basic " + base64.b64encode(b"key-12345678:secret-12345678").decode() == \
        t212.T212("key-12345678", "secret-12345678").s.headers["Authorization"]

    with tempfile.TemporaryDirectory() as d, mock.patch("investments.t212.time.sleep"):
        tmp = Path(d)

        # summary: cash is everything uninvested (free + in pies + reserved)
        c = client(history, tmp)
        assert c.summary()["cash"] == 1050.0

        # interest: only the two interest types; deposits are ignored; pages are followed
        c.s.calls.clear()
        pay = c.interest()
        assert [(p["date"], p["amount"]) for p in pay] == [("2026-10-31", 0.11), ("2026-10-29", 0.11), ("2026-10-28", 0.1),
                                                           ("2026-10-27", 0.1), ("2026-10-26", 0.07)], pay
        assert len(c.s.calls) == 2

        # a later refresh stops as soon as a page lies entirely before what it already has
        c2 = client(history, tmp)
        c2.interest()
        assert len(c2.s.calls) == 2, "first page contains today's payment, so the second is still checked"
        newest = [tx("2026-10-31", 0.11), tx("2026-10-30", 5000, "DEPOSIT")]
        old_page = lambda url, params, n: Resp(body={"items": [tx("2026-10-01", 1, "DEPOSIT")] * 3,
                                                       "nextPagePath": "/api/v0/x?cursor=9"}) if n > 1 else \
            Resp(body={"items": newest, "nextPagePath": "/api/v0/x?cursor=2"})
        c3 = client(old_page, tmp)
        c3.interest()
        assert len(c3.s.calls) == 2, f"should stop after the page of old items, made {len(c3.s.calls)} calls"

        # figures for the dashboard
        info = t212.summarise(pay, 1050.0, today=date(2026, 11, 1))
        assert info["last_date"] == "2026-10-31" and info["last_amount"] == 0.11
        assert info["month"] == 0 and info["all_time"] == 0.49 and info["ytd"] == 0.49
        assert info["est_rate_pct"] == round(0.11 * 365 / 1050 * 100, 2)
        assert t212.summarise([], 0)["last_date"] is None  # nothing paid yet must not crash

        # a refused key halts at once and is never retried; the halt file blocks the service
        denied = client(lambda *a: Resp(401), tmp)
        try:
            denied.summary()
        except t212.Rejected:
            pass
        else:
            raise AssertionError("401 must halt")
        assert len(denied.s.calls) == 1 and t212.HALT.exists() and "refused" in t212.halted_reason()
        t212.HALT.unlink()
        no_scope = client(lambda *a: Resp(403), tmp)
        try:
            no_scope.interest()
        except t212.Rejected:
            assert "lacks a permission" in t212.halted_reason()
        else:
            raise AssertionError("403 must halt")
        t212.HALT.unlink()

        # rate limited once: waits, then succeeds; twice: gives up rather than hammering
        seq = iter([Resp(429, headers={"x-ratelimit-reset": "0"}), history("summary", None, 1)])
        c4 = client(lambda *a: next(seq), tmp)
        assert c4.summary()["cash"] == 1050.0 and len(c4.s.calls) == 2
        c5 = client(lambda *a: Resp(429), tmp)
        try:
            c5.summary()
        except RuntimeError:
            assert len(c5.s.calls) == 2
        else:
            raise AssertionError("repeated 429 must stop")
    print("trading212 client OK")


if __name__ == "__main__":
    run()
