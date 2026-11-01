"""Parse Netflix viewing-history exports into "recently watched" and "continue watching".

Supports both official exports:
- NetflixViewingHistory.csv (Account > Profile > Viewing activity > Download all): Title, Date.
  The date format follows the account's locale, so it's inferred from the file.
- ViewingActivity.csv (Account > Download your personal information): adds start times, session duration
  and the playback position you stopped at, which gives real "stopped at 41:20" progress.
"""
import csv
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

DATE_FORMATS = ["%m/%d/%y", "%d/%m/%y", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y", "%d.%m.%Y", "%y-%m-%d"]


@dataclass
class View:
    when: datetime
    show: str
    season: str | None = None
    episode: str | None = None
    watched_s: int | None = None  # this session's length (full export only)
    position_s: int | None = None  # where playback stopped (full export only)

    @property
    def is_movie(self):
        return self.episode is None

    @property
    def label(self):
        return self.show if self.is_movie else f"{self.show} · {self.season}: {self.episode}"


@dataclass
class History:
    views: list[View]  # newest first
    source: str
    profile: str | None = None
    stats: dict = field(default_factory=dict)


def split_title(title: str):
    """'Show: Season 2: Episode name' -> (show, season, episode). Two-part titles are movies with colons."""
    parts = [p.strip() for p in title.split(": ")]
    if len(parts) >= 3:
        return parts[0], parts[1], ": ".join(parts[2:])
    return title.strip(), None, None


def _hms(value: str):
    try:
        h, m, s = (int(x) for x in value.strip().split(":"))
        return h * 3600 + m * 60 + s
    except (ValueError, AttributeError):
        return None


def _infer_date_format(dates: list[str], today: datetime):
    """Pick the format that parses every row, never lands in the future and best keeps the file's
    newest-first order (US m/d vs UK d/m is otherwise ambiguous)."""
    best, best_score = None, -1
    for fmt in DATE_FORMATS:
        try:
            parsed = [datetime.strptime(d, fmt) for d in dates]
        except ValueError:
            continue
        if any(p > today + timedelta(days=1) for p in parsed):
            continue
        ordered = sum(a >= b for a, b in zip(parsed, parsed[1:]))
        if ordered > best_score:
            best, best_score = fmt, ordered
    if best is None:
        raise ValueError("unrecognised date format in Netflix export")
    return best


def parse(path, profile: str | None = None, today: datetime | None = None) -> History:
    today = today or datetime.now()
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return History([], "empty")

    if "Start Time" in rows[0]:  # full personal-data export
        rows = [r for r in rows if not (r.get("Supplemental Video Type") or "").strip()]  # skip trailers/previews
        profiles = [r["Profile Name"] for r in rows]
        profile = profile or max(set(profiles), key=profiles.count)
        views = []
        for r in rows:
            if r["Profile Name"] != profile:
                continue
            show, season, episode = split_title(r["Title"])
            views.append(View(datetime.strptime(r["Start Time"], "%Y-%m-%d %H:%M:%S"), show, season, episode,
                              _hms(r.get("Duration")), _hms(r.get("Bookmark"))))
        views.sort(key=lambda v: v.when, reverse=True)
        source = "full export"
    else:
        fmt = _infer_date_format([r["Date"] for r in rows], today)
        views = [View(datetime.strptime(r["Date"], fmt), *split_title(r["Title"])) for r in rows]
        source = "viewing activity"

    week, month = today - timedelta(days=7), today - timedelta(days=30)
    stats = {
        "episodes_7d": sum(1 for v in views if v.when >= week and not v.is_movie),
        "movies_30d": sum(1 for v in views if v.when >= month and v.is_movie),
        "titles_total": len(views),
    }
    if any(v.watched_s for v in views):
        stats["hours_7d"] = round(sum(v.watched_s or 0 for v in views if v.when >= week) / 3600, 1)
    return History(views, source, profile, stats)


def continue_watching(history: History, limit=6):
    """Latest episode per show, most recent show first."""
    shows: OrderedDict[str, tuple[View, int]] = OrderedDict()
    for v in history.views:
        if v.is_movie:
            continue
        if v.show not in shows:
            shows[v.show] = (v, 1)
        else:
            latest, n = shows[v.show]
            shows[v.show] = (latest, n + 1)
    return list(shows.values())[:limit]


def relative(when: datetime, today: datetime):
    days = (today.date() - when.date()).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago" if days < 14 \
        else when.strftime("%-d %b")
