"""Regenerate the README's pictures from the Hub's demo mode: made-up data, so nothing personal is ever in them.

  .venv/bin/python frontend/readme_images.py      (the Hub is served by Home Assistant, so ./home up first)

Writes docs/hero.jpg (the screensaver on a TV and the Hub on a phone), docs/hub.jpg (the top of the Hub),
docs/hub-money.jpg, docs/hub-health.jpg and docs/tv.jpg (the TV layout on a TV). The photos in them are the guest
set: Wikimedia Commons landscapes, each credited on screen.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SHOT = [sys.executable, str(ROOT / "frontend" / "screenshot.py")]

FRAME = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; width: {w}px; height: {h}px; overflow: hidden; background: #07070b; }
.bg { position: absolute; inset: 0; background:
  radial-gradient(60% 70% at 8% 0%, rgba(255,79,139,.42), transparent 60%),
  radial-gradient(55% 70% at 100% 100%, rgba(91,75,255,.45), transparent 60%),
  radial-gradient(40% 50% at 60% 0%, rgba(255,154,61,.18), transparent 70%); }
.tv { position: absolute; left: {tvx}px; top: {tvy}px; width: {tvw}px; }
.tv .screen { width: 100%; aspect-ratio: 16 / 9; border-radius: 10px; overflow: hidden; background: #000;
  box-shadow: 0 0 0 12px #0c0c10, 0 0 0 13px #2a2a33, 0 60px 120px -30px rgba(0,0,0,.9), 0 0 140px -20px rgba(255,120,150,.35); }
.tv .screen img { width: 100%; height: 100%; object-fit: cover; display: block; }
.tv .stand { width: 18%; height: 54px; margin: 13px auto 0; background: linear-gradient(#17171d, #0c0c10); }
.tv .base { width: 34%; height: 10px; margin: 0 auto; border-radius: 6px; background: #1a1a21; }
.phone { position: absolute; left: {px}px; top: {py}px; width: {pw}px; aspect-ratio: 9 / 19.5; border-radius: 58px;
  background: #0b0b0f; padding: 13px; box-sizing: border-box;
  box-shadow: 0 0 0 2px #34343e, 0 50px 110px -20px rgba(0,0,0,.95), 0 0 90px -20px rgba(123,108,255,.45); }
.phone .screen { width: 100%; height: 100%; border-radius: 46px; overflow: hidden; position: relative; background: #07070b; }
.phone .screen img { width: 100%; display: block; }
.phone .island { position: absolute; top: 12px; left: 50%; width: 31%; height: 30px; transform: translateX(-50%);
  border-radius: 20px; background: #000; z-index: 2; }
</style></head><body><div class="bg"></div>{body}</body></html>"""


def shoot(out: Path, **env):
    subprocess.run(SHOT + [str(out)], check=True, capture_output=True, env={**os.environ, "HUB_DEMO": "1", **env})


def compose(html: str, w: int, h: int, out: Path, scale: int = 2):
    page = out.with_suffix(".html")
    page.write_text(html)
    png = out.with_suffix(".frame.png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--allow-file-access-from-files", "--hide-scrollbars",
                    f"--force-device-scale-factor={scale}", f"--window-size={w},{h}", f"--screenshot={png}",
                    f"file://{page}"], check=True, capture_output=True)
    return Image.open(png)


def save(im: Image.Image, name: str, width: int):
    im = im.convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    im.save(DOCS / name, quality=86, optimize=True, progressive=True)
    print(f"docs/{name}: {im.width}x{im.height}, {(DOCS / name).stat().st_size // 1024} KB")


def frame(**kw) -> str:
    html = FRAME
    for k, v in kw.items():
        html = html.replace("{" + k + "}", str(v))
    return html


def main():
    with tempfile.TemporaryDirectory() as d:
        t = Path(d)
        shoot(t / "hub", HUB_SCALE="2", HUB_CLIP="^#calendar #invest #health")
        shoot(t / "ambient", HUB_QUERY="ambient=1", HUB_SIZE="1920x1080")
        shoot(t / "tv", HUB_QUERY="tv=1", HUB_SIZE="1920x1080")
        Image.open(t / "tv-desktop.png").crop((0, 0, 1920, 1080)).save(t / "tv-screen.png")
        Image.open(t / "hub-phone.png").crop((0, 0, 780, 1690)).save(t / "phone-screen.png")

        save(Image.open(t / "hub-desktop-top.png"), "hub.jpg", 2400)
        save(Image.open(t / "hub-desktop-invest.png"), "hub-money.jpg", 2400)
        save(Image.open(t / "hub-desktop-health.png"), "hub-health.jpg", 1400)

        hero = frame(w=1800, h=1040, tvx=110, tvy=96, tvw=1270, px=1330, py=230, pw=380, body=f"""
          <div class="tv"><div class="screen"><img src="file://{t}/ambient-desktop.png"></div><div class="stand"></div><div class="base"></div></div>
          <div class="phone"><div class="screen"><div class="island"></div><img src="file://{t}/phone-screen.png"></div></div>""")
        save(compose(hero, 1800, 1040, t / "hero"), "hero.jpg", 2400)
        tv = frame(w=1600, h=1000, tvx=110, tvy=70, tvw=1380, px=-999, py=0, pw=0, body=f"""
          <div class="tv"><div class="screen"><img src="file://{t}/tv-screen.png"></div><div class="stand"></div><div class="base"></div></div>""")
        save(compose(tv, 1600, 1000, t / "tvframe"), "tv.jpg", 2000)


if __name__ == "__main__":
    main()
