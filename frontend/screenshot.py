"""Screenshot the hub (desktop + phone) for visual review, in a throwaway headless Chrome profile.

  .venv/bin/python frontend/screenshot.py /tmp/hub   -> /tmp/hub-desktop.png, /tmp/hub-phone.png
  .venv/bin/python frontend/screenshot.py /tmp/hub ".ev"   (click the first match before capturing)
  HUB_REDACT=1 ...   blur calendar entries and the calendar's "Next" line (for anything shared)
  HUB_DEMO=1 ...     demo mode: made-up data, no Home Assistant connection (what the README's pictures use)
  HUB_QUERY=tv=1 ... extra query (tv=1 the TV layout, ambient=1 the screensaver); HUB_SCALE=2 sharper desktop shots
  HUB_SIZE=1440x1180 the desktop viewport
  HUB_CLIP="#invest #health" also capture just those elements, as <prefix>-<name>-<id>.png ("^#calendar": the page
                     from the top down to the end of that element, as <prefix>-<name>-top.png)

The HA token from .env is only put in the temporary profile's localStorage, which is deleted afterwards.
"""
import asyncio, base64, json, os, shutil, subprocess, sys, tempfile, time, urllib.request
import websockets
sys.path.insert(0, os.getcwd())
from music_sync.service import load_env

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
URL = "http://localhost:8123/local/hub/index.html"

async def main(prefix, click=None):
    load_env()
    profile = tempfile.mkdtemp(dir=os.path.dirname(prefix))
    proc = subprocess.Popen([CHROME, "--headless=new", f"--user-data-dir={profile}", "--remote-debugging-port=9333",
                             "--hide-scrollbars", "--force-device-scale-factor=1", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json")); break
            except OSError:
                time.sleep(0.2)
        ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
        async with websockets.connect(ws_url, max_size=None) as ws:
            n = 0
            async def cmd(method, **params):
                nonlocal n; n += 1; my = n
                await ws.send(json.dumps({"id": my, "method": method, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == my:
                        return m.get("result", m.get("error"))
            await cmd("Page.enable"); await cmd("Runtime.enable")
            await cmd("Page.navigate", url="http://localhost:8123/local/hub/vendor/haws.js")
            await asyncio.sleep(1)
            tokens = {"hassUrl": "http://localhost:8123", "clientId": "http://localhost:8123/",
                      "access_token": os.environ["TOKEN"], "refresh_token": "", "expires": int(time.time() * 1000) + 3.6e9, "expires_in": 3.6e6}
            if not os.environ.get("HUB_DEMO"):  # demo mode never connects, so it gets no token
                await cmd("Runtime.evaluate", expression=f"localStorage.hassTokens = {json.dumps(json.dumps(tokens))}")
            query = "&".join(q for q in ("demo=1" if os.environ.get("HUB_DEMO") else "", os.environ.get("HUB_QUERY", "")) if q)
            dw, dh = (int(v) for v in os.environ.get("HUB_SIZE", "1440x1180").split("x"))
            scale = float(os.environ.get("HUB_SCALE", "1"))
            logs = []
            for name, w, h, mobile in (("desktop", dw, dh, False), ("phone", 390, 2200, True)):
                await cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=2 if mobile else scale, mobile=mobile)
                await cmd("Page.navigate", url=URL + (f"?{query}" if query else ""))
                await asyncio.sleep(5)
                if os.environ.get("HUB_REDACT"):
                    css = ".ev b,.ev span,.ev small,.calendar .kicker{filter:blur(6px)}"  # every calendar text, the header's "Next ·" too
                    await cmd("Runtime.evaluate", expression=f"document.head.insertAdjacentHTML('beforeend','<style>{css}</style>')")
                r = await cmd("Runtime.evaluate", expression="[...document.querySelectorAll('section')].map(s=>s.id+':'+s.innerText.slice(0,60).replace(/\\n/g,' | ')).join('\\n')", returnByValue=True)
                logs.append(f"== {name}\n" + r["result"]["value"])
                if click:
                    await cmd("Runtime.evaluate", expression=f"document.querySelector({json.dumps(click)})?.click()")
                    await asyncio.sleep(0.8)
                shot = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True)
                open(f"{prefix}-{name}.png", "wb").write(base64.b64decode(shot["data"]))
                for sel in os.environ.get("HUB_CLIP", "").split():
                    top, q = sel.startswith("^"), sel.lstrip("^")
                    r = await cmd("Runtime.evaluate", returnByValue=True, expression=f"(() => {{ const r = document.querySelector({json.dumps(q)})?.getBoundingClientRect(); return r && [r.x + scrollX, r.y + scrollY, r.width, r.height]; }})()")
                    box = r["result"].get("value")
                    if box:
                        x, y, cw, ch = (0, 0, w, box[1] + box[3] + 24) if top else box
                        sel = "top" if top else sel
                        shot = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                                         clip={"x": x, "y": y, "width": cw, "height": ch, "scale": 1})
                        open(f"{prefix}-{name}-{sel.strip('#.')}.png", "wb").write(base64.b64decode(shot["data"]))
            print("\n".join(logs))
    finally:
        proc.terminate(); proc.wait(5)
        shutil.rmtree(profile, ignore_errors=True)

asyncio.run(main(*sys.argv[1:3]))
