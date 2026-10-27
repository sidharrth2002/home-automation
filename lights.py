import asyncio
import sys
from pywizlight import wizlight, PilotBuilder

BULBS = {"a": "192.168.0.240", "b": "192.168.0.120"}


async def main(cmd, *args):
    for ip in BULBS.values():
        bulb = wizlight(ip)
        if cmd == "on":
            await bulb.turn_on(PilotBuilder(brightness=int(args[0]) if args else 255))
        elif cmd == "off":
            await bulb.turn_off()
        elif cmd == "toggle":
            await bulb.lightSwitch()
        elif cmd == "color":
            r, g, b = map(int, args)
            await bulb.turn_on(PilotBuilder(rgb=(r, g, b)))
        elif cmd == "status":
            state = (await bulb.updateState())[0]
            print(ip, "on" if state.get_state() else "off", state.get_brightness())


asyncio.run(main(*sys.argv[1:]))
