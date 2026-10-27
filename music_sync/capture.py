import asyncio
from pathlib import Path

AUDIOTEE = Path(__file__).resolve().parent.parent / "bin" / "audiotee"
SAMPLE_RATE = 44100
CHUNK_MS = 150


async def chunks():
    """Yield raw 16-bit mono PCM chunks of whatever macOS is playing."""
    proc = await asyncio.create_subprocess_exec(
        str(AUDIOTEE), "--sample-rate", str(SAMPLE_RATE), "--chunk-duration", str(CHUNK_MS / 1000),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    size = SAMPLE_RATE * CHUNK_MS // 1000 * 2
    try:
        while True:
            yield await proc.stdout.readexactly(size)
    except asyncio.IncompleteReadError:
        return
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()
