import asyncio
from pywizlight import discovery

async def main():
    bulbs = await discovery.discover_lights(broadcast_space="192.168.0.255")
    for b in bulbs:
        print(b.ip, await b.getMac())

asyncio.run(main())
