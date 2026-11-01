"""Run: .venv/bin/python -m tests.test_netflix"""
import tempfile
from datetime import datetime
from pathlib import Path

from netflix.history import continue_watching, parse, split_title

TODAY = datetime(2026, 11, 1, 18, 0)


def write(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return Path(f.name)


def test_titles():
    assert split_title("Stranger Things: Stranger Things 4: Chapter One: The Hellfire Club") == \
        ("Stranger Things", "Stranger Things 4", "Chapter One: The Hellfire Club")
    assert split_title("Glass Onion: A Knives Out Mystery") == ("Glass Onion: A Knives Out Mystery", None, None)
    assert split_title("Roma") == ("Roma", None, None)


def test_uk_viewing_activity():
    # UK accounts export d/m/yy; 13/10 only parses as day-first, but 05/10 vs 10/05 is ambiguous on its own.
    p = write('Title,Date\n"Slow Horses: Season 4: Identity Theft",31/10/26\n"Roma",30/10/26\n'
              '"Slow Horses: Season 4: Hello Goodbye",13/10/26\n"Dark: Season 1: Secrets",05/10/26\n')
    h = parse(p, today=TODAY)
    assert [v.when.day for v in h.views] == [31, 30, 13, 5] and h.views[3].when.month == 10
    cont = continue_watching(h)
    assert [(v.show, v.episode, n) for v, n in cont] == [("Slow Horses", "Identity Theft", 2), ("Dark", "Secrets", 1)]
    assert h.stats["episodes_7d"] == 1 and h.stats["movies_30d"] == 1


def test_us_viewing_activity():
    p = write('Title,Date\n"Wednesday: Season 2: Woe Is Me",10/28/26\n"Wednesday: Season 2: Episode 1",10/3/26\n')
    h = parse(p, today=TODAY)
    assert h.views[0].when == datetime(2026, 10, 28) and h.views[1].when == datetime(2026, 10, 3)


def test_full_export():
    p = write("Profile Name,Start Time,Duration,Attributes,Title,Supplemental Video Type,Device Type,Bookmark,"
              "Latest Bookmark,Country\n"
              "Sid,2026-10-31 21:10:00,00:41:20,,Severance: Season 2: Cold Harbor,,TV,00:41:20,00:41:20,GB\n"
              "Sid,2026-10-31 21:05:00,00:00:30,,Severance: Season 2 (Trailer),TRAILER,TV,00:00:30,00:00:30,GB\n"
              "Guest,2026-10-31 20:00:00,01:00:00,,Some Film,,TV,01:00:00,01:00:00,GB\n"
              "Sid,2026-10-30 20:00:00,00:20:00,,Severance: Season 2: Chikhai Bardo,,TV,00:20:00,00:20:00,GB\n")
    h = parse(p, today=TODAY)
    assert h.profile == "Sid" and len(h.views) == 2  # trailer and the other profile dropped
    assert h.views[0].position_s == 41 * 60 + 20 and h.stats["hours_7d"] == 1.0


if __name__ == "__main__":
    for t in (test_titles, test_uk_viewing_activity, test_us_viewing_activity, test_full_export):
        t()
        print(f"{t.__name__} OK")
