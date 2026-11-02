"""Photo picking, on made-up records (no photos, no network): people first, never a solo selfie, variety."""
import random
from datetime import date

from photos import __main__ as ph


def rec(name, faces=0, me=False, largest=0.02, focal=6.8, day="2024-11-03", sharp=500, bright=120, landscape=True,
        make="Apple", w=4032, h=3024):
    return {"name": name, "folder": "/drive/root:/Pictures/Camera Roll/2024/11", "taken": f"{day}T12:00:00Z", "make": make,
            "focal": focal, "w": w, "h": h, "size": 1,
            "look": {"ok": True, "faces": faces, "me": me, "largest_face": largest, "sharpness": sharp,
                     "brightness": bright, "landscape": landscape}}


def run():
    today = date(2026, 11, 2)
    # metadata filter: screenshots, saved images (no camera) and small images are never looked at
    assert ph.worth_a_look(rec("IMG_1.HEIC"))
    assert not ph.worth_a_look(rec("Screenshot 2024.png"))
    assert not ph.worth_a_look(rec("IMG-2024-WA0001.jpg", make=None))
    assert not ph.worth_a_look(rec("small.jpg", w=800, h=600))
    assert ph.worth_a_look(rec("selfie.HEIC", focal=2.2)), "selfies are looked at; whether they're kept depends on who's in them"

    # scoring: you with people > people > a plain good photo; solo selfies and close-ups never
    with_me = ph.score(rec("a", faces=3, me=True))
    people = ph.score(rec("b", faces=3))
    plain = ph.score(rec("c", faces=0))
    assert with_me > people > plain > 0
    assert ph.score(rec("solo selfie", faces=1, focal=2.2, largest=0.2)) == 0
    assert ph.score(rec("group selfie", faces=4, focal=2.2, largest=0.08, me=True)) >= with_me - 0.01
    assert ph.score(rec("close-up", faces=1, largest=0.15)) == 0
    assert ph.score(rec("blurry", faces=3, sharp=20)) == 0
    assert ph.score(rec("dark", faces=3, bright=10)) == 0
    assert ph.score(rec("portrait", faces=4, me=True, landscape=False)) == 0, "landscape only"
    assert ph.score({"name": "unlooked", "look": None}) == 0

    # picking: at most two from one day, a share from this month in past years, nothing that scored zero
    index = {"items": {}}
    for i in range(30):
        index["items"][f"party{i}"] = rec(f"p{i}", faces=4, me=True, day="2024-11-03")  # one big night out
    for i in range(30):
        index["items"][f"trip{i}"] = rec(f"t{i}", faces=3, day=f"2023-0{1 + i % 9}-{10 + i % 18}")
    for i in range(10):
        index["items"][f"selfie{i}"] = rec(f"s{i}", faces=1, focal=2.2, largest=0.2, day=f"2025-11-{10 + i}")
    chosen = ph.pick(index, today, n=12, rng=random.Random(1))
    assert len(chosen) == 12
    assert sum(1 for c in chosen if c.startswith("party")) <= ph.MAX_PER_DAY, "one event mustn't take over the frame"
    assert not any(c.startswith("selfie") for c in chosen), "solo selfies are never picked"

    assert ph.label(date(2024, 11, 3), today) == "November 2024 · 2 years ago"
    assert ph.label(date(2023, 5, 1), today) == "May 2023"
    print("photo picking OK")


if __name__ == "__main__":
    run()
