"""Revaluing hand-written holdings from FT prices, and publishing their price history for the Hub (all faked)."""
from datetime import date
from unittest import mock

from investments import __main__ as inv


class FakePrices:
    def __init__(self, series):
        self.series = series

    def history(self, key, name):
        return self.series[key]


def run():
    d1, d2 = date(2026, 11, 20), date(2026, 11, 21)
    priceable = {"items": [
        {"key": "gb00b0000001", "name": "Pounds Fund", "implied_gbp": 2.0},     # FT quotes it in pounds
        {"key": "gb00b0000002", "name": "Pence Fund", "implied_gbp": 1.5},      # FT quotes it in pence
        {"key": "made-up-slug", "name": "No ISIN", "implied_gbp": 1.0}]}         # skipped: can't be looked up
    prices = FakePrices({"GB00B0000001": [(d1, 1.98), (d2, 2.02)], "GB00B0000002": [(d1, 149.0), (d2, 151.0)]})
    calls, posts = [], []

    def call(method, path, body=None, **kw):
        calls.append((method, path, body))
        return priceable if path == "/v1/portfolio/priceable" else {}
    inv._published_series.clear()
    with mock.patch.object(inv.core, "call", call), \
         mock.patch.object(inv, "post", lambda state, attrs, entity: posts.append((entity, state, attrs["series"]))):
        assert inv.revalue(prices) == 2
        assert inv.revalue(prices) == 2  # an hour later: prices again, but the history only once a day
    recorded = {p.split("/")[-1]: b["price_gbp"] for m, p, b in calls if m == "PUT"}
    assert recorded == {"gb00b0000001": 2.02, "gb00b0000002": 1.51}, recorded
    assert [e for e, _, _ in posts] == ["sensor.investment_gb00b0000001", "sensor.investment_gb00b0000002"], posts
    by = {e: (s, series) for e, s, series in posts}
    assert by["sensor.investment_gb00b0000001"][0] == 202.0, "pounds become pence, like HL's"
    assert by["sensor.investment_gb00b0000002"][0] == 151.0, "pence stay pence"
    print("revalue OK")


if __name__ == "__main__":
    run()
