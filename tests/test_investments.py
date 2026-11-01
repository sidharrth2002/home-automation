"""Login safety for the HL client, against a fake HL (no network)."""
import tempfile
from pathlib import Path
from unittest import mock

from investments import hl

STAGE1 = '<form><input name="hl_vt" value="t1"></form>'
def stage2(asked=(1, 3, 5), boxes=6):
    cells = "".join(f'<div class="{"secure-number-container__label" if i in asked else "secure-number-grey-box"}"></div>'
                    for i in range(boxes))
    return f'<input name="hl_vt" value="t2"><div class="secure-number-container">{cells}</div>'


class Resp:
    def __init__(self, url, text=""):
        self.url, self.text = "https://online.hl.co.uk/" + url, text
    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, stage1_to="my-accounts/login-step-two", stage2_page=None, stage2_to="my-accounts"):
        self.posts = []
        self.stage1_to, self.stage2_page, self.stage2_to = stage1_to, stage2_page or stage2(), stage2_to
        self.cookies = mock.MagicMock()
        self.headers = {}
    def get(self, url, **kw):
        return Resp("my-accounts/login-step-one", STAGE1)
    def post(self, url, data, **kw):
        self.posts.append(data)
        if url.endswith("login-step-one"):
            return Resp(self.stage1_to, self.stage2_page)
        return Resp(self.stage2_to, "")


def client(session, tmp):
    hl.DATA, hl.HALT, hl.COOKIES = tmp, tmp / "HALTED", tmp / "cookies.txt"
    c = hl.HL.__new__(hl.HL)
    c.s = session
    c._save = lambda: None
    return c


CREDS = hl.Credentials.checked("sid", "01/02/1999", "pw", "123456")


def expect(exc, fn):
    try:
        fn()
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def run():
    # malformed credentials never reach the network
    for bad in (("", "01/02/1999", "pw", "123456"), ("sid", "01/02/1999", "pw", "12345"),
                ("sid", "1999", "pw", "123456"), ("sid", "01/02/1999", "", "123456")):
        expect(ValueError, lambda: hl.Credentials.checked(*bad))
    assert CREDS.dob == "010299"

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        # happy path: digits 2, 4, 6 of the secure number are sent
        s = FakeSession(); client(s, tmp).login(CREDS)
        assert s.posts[1]["secure-number[1]"] == "2" and s.posts[1]["secure-number[3]"] == "6", s.posts[1]
        assert not hl.HALT.exists()

        # stage 1 rejected -> halt, and the next automatic login sends nothing at all
        s = FakeSession(stage1_to="my-accounts/login-step-one")
        expect(hl.Halted, lambda: client(s, tmp).login(CREDS))
        assert len(s.posts) == 1 and hl.HALT.exists()
        s2 = FakeSession()
        expect(hl.Halted, lambda: client(s2, tmp).login(CREDS))
        assert s2.posts == [], "must not touch HL while halted"
        hl.HALT.unlink()

        # ambiguous secure-number page -> the password is never submitted
        for page in (stage2(asked=(1, 3)), stage2(boxes=8), "<input name='hl_vt' value='x'><p>new 2FA step</p>"):
            s = FakeSession(stage2_page=page)
            expect(hl.Halted, lambda: client(s, tmp).login(CREDS))
            assert len(s.posts) == 1, "stage 2 must not be posted"
            hl.HALT.unlink()

        # wrong password -> halt after exactly one stage-2 attempt
        s = FakeSession(stage2_to="my-accounts/login-step-two")
        expect(hl.Halted, lambda: client(s, tmp).login(CREDS))
        assert len(s.posts) == 2 and hl.HALT.exists()

        # a manual login is allowed to clear the halt
        s = FakeSession(); client(s, tmp).login(CREDS, manual=True)
        assert not hl.HALT.exists()
    print("investments login safety OK")


if __name__ == "__main__":
    run()
