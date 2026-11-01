"""Read-only Hargreaves Lansdown client: logs in like the website and parses the portfolio pages.

Ported from jonathanmadeley/hl-api-client-net (MIT). HL locks the account after a few failed logins, so this
module is deliberately paranoid:

- credentials are validated locally before anything is sent;
- stage 2 (password + secure-number digits) is only submitted if the page asks for exactly 3 known digit
  positions, otherwise nothing is sent;
- ANY failed or unexpected login writes a halt file, and `login()` refuses to run again until a human clears it
  (`python -m investments login`). There are no automatic retries anywhere;
- the session cookie is saved and reused, so a normal refresh doesn't log in at all.
"""
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.cookiejar import LWPCookieJar
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://online.hl.co.uk/"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "investments"
COOKIES = DATA / "hl_cookies.txt"
HALT = DATA / "HALTED"
# Where HL lands after a successful stage 2. Kept to an explicit list: anything else (a new verification step,
# an error page) must halt rather than be mistaken for success.
LOGGED_IN_PATHS = {"/my-accounts", "/my-accounts/portfolio_overview"}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")


class Halted(RuntimeError):
    """Logging in is paused until a person checks the credentials and clears it."""


class LoginFailed(RuntimeError):
    pass


@dataclass
class Credentials:
    username: str
    dob: str  # DDMMYY, as HL's form wants it
    password: str
    secure_number: str  # 6 digits

    @classmethod
    def checked(cls, username, dob, password, secure_number):
        """Normalise and validate locally, so a typo can never cost a login attempt."""
        username = (username or "").strip()
        password = password or ""
        secure_number = re.sub(r"\s", "", secure_number or "")
        if not username:
            raise ValueError("username is empty")
        if not password:
            raise ValueError("password is empty")
        if not re.fullmatch(r"\d{6}", secure_number):
            raise ValueError("secure number must be exactly 6 digits")
        # Strict shapes only: strptime alone would happily read "1999" as 19/09/2009.
        dob = (dob or "").strip()
        m = (re.fullmatch(r"(\d{2})[/.\- ](\d{2})[/.\- ](\d{4})", dob) or re.fullmatch(r"(\d{2})(\d{2})(\d{4})", dob))
        iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", dob)
        try:
            if m:
                born = datetime(int(m[3]), int(m[2]), int(m[1]))
            elif iso:
                born = datetime(int(iso[1]), int(iso[2]), int(iso[3]))
            else:
                raise ValueError
        except ValueError:
            raise ValueError("date of birth not understood (use DD/MM/YYYY)") from None
        if not 1900 < born.year < datetime.now().year:
            raise ValueError("date of birth looks wrong")
        return cls(username, born.strftime("%d%m%y"), password, secure_number)

    @classmethod
    def from_stored(cls, username, dob, password, secure_number):
        """Re-validate what setup saved. The date is stored as HL's DDMMYY, which `checked` rightly refuses as
        typed input; the century doesn't matter for HL, so expand it just to run the same checks."""
        if re.fullmatch(r"\d{6}", dob or ""):
            yy = int(dob[4:])
            dob = f"{dob[:2]}/{dob[2:4]}/{(1900 if yy > datetime.now().year % 100 else 2000) + yy}"
        return cls.checked(username, dob, password, secure_number)


@dataclass
class Holding:
    account: str
    id: str
    name: str
    unit_type: str
    units: float | None
    price_p: float | None  # pence, as HL shows it
    value: float | None
    cost: float | None
    gain: float | None
    gain_pct: float | None


@dataclass
class Account:
    id: int
    name: str
    stock: float | None
    cash: float | None
    total: float | None
    holdings: list = field(default_factory=list)


def halted_reason():
    return HALT.read_text().strip() if HALT.exists() else None


def _halt(reason):
    DATA.mkdir(parents=True, exist_ok=True)
    HALT.write_text(f"{datetime.now():%Y-%m-%d %H:%M} {reason}\n")
    raise Halted(reason)


def _num(text):
    text = (text or "").replace(",", "").replace("£", "").replace("%", "").replace("p", "").strip()
    m = re.search(r"-?\d+(\.\d+)?", text)
    return float(m.group()) if m else None


class HL:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})
        self.s.cookies = LWPCookieJar(str(COOKIES))
        if COOKIES.exists():
            try:
                self.s.cookies.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                pass

    def _save(self):
        self.s.cookies.save(ignore_discard=True, ignore_expires=True)
        COOKIES.chmod(0o600)

    def _get(self, path):
        r = self.s.get(BASE + path, timeout=30)
        r.raise_for_status()
        return r

    @staticmethod
    def _path(r):
        return urlparse(r.url).path.rstrip("/")

    def logged_in(self):
        """Cheap check: does the portfolio page load without bouncing to the login form?"""
        try:
            r = self._get("my-accounts/portfolio_overview")
        except requests.RequestException:
            return False
        return "login" not in self._path(r) and 'id="portfolio"' in r.text

    def login(self, creds: Credentials, *, manual=False):
        """Two-stage login. Never retries; any failure halts until `python -m investments login` succeeds."""
        if HALT.exists() and not manual:
            raise Halted(halted_reason())

        # Stage 1: username + date of birth.
        page = self._get("my-accounts/login-step-one")
        token = self._token(page.text)
        r = self.s.post(BASE + "my-accounts/login-step-one", timeout=30, data={
            "username": creds.username, "date-of-birth": creds.dob, "hl_vt": token})
        if self._path(r) != "/my-accounts/login-step-two":
            _halt(f"stage 1 (username/date of birth) was not accepted: ended on {self._path(r)}. {self._error(r.text)}")

        # Stage 2: password + three digits of the secure number. Work out which digits are wanted first, and
        # send nothing unless that's unambiguous.
        soup = BeautifulSoup(r.text, "html.parser")
        box = soup.find("div", class_="secure-number-container")
        if box is None:
            _halt("stage 2 page has no secure-number box (HL changed the page, or added a step); nothing was sent")
        cells = [d for d in box.find_all("div")
                 if {"secure-number-grey-box", "secure-number-container__label"} & set(d.get("class", []))]
        wanted = [i for i, d in enumerate(cells) if "secure-number-container__label" in d.get("class", [])]
        if len(cells) != 6 or len(wanted) != 3:
            _halt(f"couldn't tell which secure-number digits HL wants ({len(cells)} boxes, {len(wanted)} asked); "
                  "nothing was sent")
        token = self._token(r.text)
        r = self.s.post(BASE + "my-accounts/login-step-two", timeout=30, data={
            "online-password-verification": creds.password,
            "secure-number[1]": creds.secure_number[wanted[0]],
            "secure-number[2]": creds.secure_number[wanted[1]],
            "secure-number[3]": creds.secure_number[wanted[2]],
            "submit": "Log in", "hl_vt": token})
        if self._path(r) not in LOGGED_IN_PATHS:
            _halt(f"stage 2 (password/secure number) was not accepted: ended on {self._path(r)}. {self._error(r.text)}")

        HALT.unlink(missing_ok=True)
        self._save()

    @staticmethod
    def _token(html):
        tag = BeautifulSoup(html, "html.parser").find("input", attrs={"name": "hl_vt"})
        if not tag or not tag.get("value"):
            _halt("login form has no hl_vt token (HL changed the page); nothing was sent")
        return tag["value"]

    @staticmethod
    def _error(html):
        soup = BeautifulSoup(html, "html.parser")
        for sel in (".error", ".alert", ".message--error", "[role=alert]"):
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return "HL says: " + el.get_text(" ", strip=True)[:200]
        return ""

    # ── reading ──────────────────────────────────────────────────
    def accounts(self) -> list[Account]:
        r = self._get("my-accounts/portfolio_overview")
        table = BeautifulSoup(r.text, "html.parser").find("table", id="portfolio")
        if table is None:
            raise RuntimeError("portfolio table not found (session expired or page changed)")
        out = []
        for row in table.tbody.find_all("tr"):
            td = row.find_all("td")
            link = td[0].find("a")
            if not link:
                continue
            m = re.search(r"/account/(\d+)", link["href"]) or re.search(r"/(\d+)/?$", link["href"])
            out.append(Account(id=int(m.group(1)), name=link.get_text(" ", strip=True),
                               stock=_num(td[1].get_text()), cash=_num(td[2].get_text()),
                               total=_num(td[3].get_text())))
        self._save()
        return out

    def holdings(self, account: Account) -> list[Holding]:
        r = self._get(f"my-accounts/account_summary/account/{account.id}")
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for table in soup.find_all("table", class_="holdings-table"):
            heads = [th.get_text(" ", strip=True).lower() for th in table.find("thead").find_all("th")] \
                if table.find("thead") else []

            def col(td, *names, fallback):
                for i, h in enumerate(heads):
                    if any(n in h for n in names) and i < len(td):
                        return td[i]
                return td[fallback] if fallback < len(td) else None

            for row in (table.tbody.find_all("tr") if table.tbody else []):
                td = row.find_all("td")
                if len(td) < 6 or not td[0].find("a"):
                    continue
                lines = [l.strip() for l in td[1].get_text("\n").split("\n") if l.strip()]
                href = td[0].find("a")["href"]
                gain = col(td, "gain/loss (£)", "gain/loss £", fallback=16)
                gain_pct = col(td, "gain/loss (%)", "gain/loss %", fallback=17)
                out.append(Holding(
                    account=account.name, id=href.rstrip("/").split("/")[-1],
                    name=lines[0] if lines else "?", unit_type=lines[-1] if len(lines) > 1 else "",
                    units=_num(col(td, "units held", fallback=2).get_text()),
                    price_p=_num(col(td, "price", fallback=3).get_text()),
                    value=_num(col(td, "value", fallback=4).get_text()),
                    cost=_num(col(td, "cost", fallback=5).get_text()),
                    gain=_num(gain.get_text()) if gain else None,
                    gain_pct=_num(gain_pct.get_text()) if gain_pct else None))
        return out

    def snapshot(self):
        accounts = self.accounts()
        for a in accounts:
            a.holdings = self.holdings(a)
            time.sleep(1.5)  # be polite
        return [asdict(a) for a in accounts]


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=1))
    path.chmod(0o600)
