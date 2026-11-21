"""Premium Bonds checker, on made-up holder numbers and replies (no network, no core).

Run: .venv/bin/python -m tests.test_premium_bonds
"""
import io
import logging
import os
from datetime import date

from core.client import CoreError
from investments import premium_bonds as pb

HOLDER = "99999999990"  # made up


class FakeCore:
    CoreError = CoreError

    def __init__(self, nsandi=None):
        self.docs, self.live, self.nsandi = {}, {}, nsandi

    def get(self, collection, key):
        if (collection, key) not in self.docs:
            raise CoreError(404, "not found")
        return {"data": self.docs[(collection, key)]}

    def put(self, collection, key, data):
        self.docs[(collection, key)] = data

    def call(self, method, path, body=None):
        assert method == "GET" and path == "/v1/portfolio/nsandi"
        if self.nsandi is None:
            raise CoreError(404, "not found")
        return {"data": self.nsandi}

    def report(self, entity, state, attrs):
        self.live[entity] = (state, attrs)


def reply(status="no", header="Sorry, no prize in the November 2026 draw", history=(), holder="ok"):
    return {"holder_number": holder, "status": status, "header": header, "tagline": "", "history": list(history)}


def run():
    # draw dates: the first working day, skipping weekends and the bank holidays that can land on the 1st
    assert pb.draw_date(2026, 11) == date(2026, 11, 2)   # 1 Nov 2026 is a Sunday
    assert pb.draw_date(2027, 1) == date(2027, 1, 4)     # New Year's Day (Fri), then the weekend
    assert pb.draw_date(2024, 4) == date(2024, 4, 2)   # Easter Monday, 1 April 2024
    assert pb._easter(2025) == date(2025, 4, 20)
    assert pb.next_check(date(2026, 11, 3)) == date(2026, 11, 5) and pb.next_check(date(2026, 11, 5)) == date(2026, 12, 4)

    # parsing replies: win, no win, invalid number, junk
    won = pb.ask(HOLDER, "this_month", post=lambda f: reply("win", "Congratulations! November 2026", [
        {"prize": "25", "bond_number": "123ABC456", "date": "2026-11-02"}, {"prize": "0", "bond_number": "0"}]))
    assert won["won"] and won["prizes"] == [{"prize": 25, "date": "2026-11-02"}], won  # no bond numbers kept
    assert not pb.ask(HOLDER, "this_month", post=lambda f: reply())["won"]
    assert not pb.ask(HOLDER, "this_month", post=lambda f: reply("failure"))["won"], "only 'win' is a win"
    nov = pb.draw_date(2026, 11)
    assert pb._for_month({"header": "You may have won in the November 2026 draw"}, nov), "'may' is not a month"
    assert not pb._for_month({"header": "Results for the October 2026 draw"}, nov)
    assert pb._for_month({"header": "Sorry, you didn't win"}, nov)
    for bad, exc in ((reply(holder="is invalid"), pb.InvalidHolder), ({"oops": 1}, ValueError)):
        try:
            pb.ask(HOLDER, "this_month", post=lambda f, bad=bad: bad)
            raise AssertionError("should have raised")
        except exc:
            pass
    sent = []
    pb.ask(HOLDER, "unclaimed_prize", post=lambda f: sent.append(f) or reply())
    assert sent == [{"field_premium_bond_period": "unclaimed_prize", "field_premium_bond_number": HOLDER}]

    # the task
    logs = io.StringIO()
    handler = logging.StreamHandler(logs)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    fake, asked, notes = FakeCore({"accounts": [{"name": "Premium Bonds", "total": 1000.0},
                                                {"name": "Income Bonds", "total": 50.0}]}), [], []
    pb.core = fake
    answers = {"this_month": reply("win", "Congratulations, you won in the November 2026 draw",
                                   [{"prize": "50", "bond_number": "111", "date": "2026-11-02"}]),
               "unclaimed_prize": reply()}

    def ask(holder, period):
        asked.append(period)
        return pb.ask(holder, period, post=lambda f: answers[period])
    try:
        pb.check(date(2026, 11, 6), ask=ask)
        raise AssertionError("needs the holder number")
    except pb.NotConfigured:
        pass
    state, attrs = fake.live[pb.SENSOR]
    assert state == "not set up" and attrs["holding"] == 1000.0, "the Hub still shows the card and the holding"
    fake.docs[pb.HOLDER_DOC] = {"holder": HOLDER}  # set by the finance session through the core
    assert pb.holder_number() == HOLDER
    try:
        out = pb.check(date(2026, 11, 3), ask=ask, notify=lambda t, m: notes.append(m))  # before results are due
        assert asked == ["unclaimed_prize"] and "won" not in out, (asked, out)        # only the monthly unclaimed check
        asked.clear()
        out = pb.check(date(2026, 11, 5), ask=ask, notify=lambda t, m: notes.append(m))
        assert asked == ["this_month"] and out["won"] and out["draw"] == "2026-11", (asked, out)
        assert notes == ["You won £50 in the November 2026 draw."]
        state, attrs = fake.live[pb.SENSOR]
        assert state == "won" and attrs["holding"] == 1000.0 and attrs["won_this_year_total"] == 50
        assert attrs["next_check"] == "2026-12-04" and attrs["last_error"] is None
        asked.clear()
        assert pb.check(date(2026, 11, 6), ask=ask)["checked"] is False and asked == []  # month done: no request

        # not published yet: the reply names last month, so nothing is recorded and tomorrow asks again
        answers["this_month"] = reply("no", "Sorry, no prize in the November 2026 draw")
        out = pb.check(date(2026, 12, 7), ask=ask)
        assert out.get("published") is False and "2026-12" not in fake.docs[pb.DOC]["draws"]

        # NS&I down: recorded, the sensor says error, nothing raised (so the queue doesn't retry against NS&I)
        def down(holder, period):
            raise OSError("connection refused")
        out = pb.check(date(2026, 12, 8), ask=down)
        assert out["error"] and fake.live[pb.SENSOR][0] == "error"
        answers["this_month"] = reply("no", "Sorry, no prize in the December 2026 draw")
        pb.check(date(2026, 12, 9), ask=ask)
        assert fake.live[pb.SENSOR][0] == "no win" and fake.docs[pb.DOC]["last_error"] is None
    finally:
        logging.getLogger().removeHandler(handler)

    # nothing sensitive leaves: the holder number stays in its own document only, no amounts in the logs
    kept = repr({k: v for k, v in fake.docs.items() if k != pb.HOLDER_DOC}) + repr(fake.live)
    assert HOLDER not in kept and HOLDER not in logs.getvalue()
    assert "50" not in logs.getvalue() and "£" not in logs.getvalue(), logs.getvalue()
    print("premium bonds OK")


if __name__ == "__main__":
    run()
