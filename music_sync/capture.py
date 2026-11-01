import asyncio
from pathlib import Path

import numpy as np

AUDIOTEE = Path(__file__).resolve().parent.parent / "bin" / "audiotee"
SAMPLE_RATE = 44100
CHUNK_S = 0.02
MIC_TARGET_RMS = 0.05
MIC_MAX_GAIN = 40.0
MIC_AGC_TAU_S = 6.0
MIC_NOISE_RMS = 0.0004


async def hops(hop):
    """Yield float32 mono arrays of exactly `hop` samples of whatever macOS is playing."""
    proc = await asyncio.create_subprocess_exec(
        str(AUDIOTEE), "--sample-rate", str(SAMPLE_RATE), "--chunk-duration", str(CHUNK_S),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    buf = np.zeros(0, np.float32)
    leftover = b""
    try:
        while data := await proc.stdout.read(16384):
            data = leftover + data
            cut = len(data) - len(data) % 2
            leftover = data[cut:]
            buf = np.concatenate([buf, np.frombuffer(data[:cut], "<i2").astype(np.float32) / 32768])
            while len(buf) >= hop:
                yield buf[:hop]
                buf = buf[hop:]
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


async def mic_hops(hop):
    """Yield float32 mono arrays of `hop` samples from the default microphone (e.g. to hear the TV).

    Audio only ever lives in this process's memory; nothing is recorded or sent anywhere.
    """
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)

    def put(block):
        if queue.full():  # never let a stall build latency; drop the oldest block
            queue.get_nowait()
        queue.put_nowait(block)

    def callback(indata, frames, time_info, status):
        loop.call_soon_threadsafe(put, indata[:, 0].copy())

    # A laptop mic across the room hears the TV at ~-55 dBFS, below the analyser's floor; ride a slow gain so the
    # room's loudness sits near MIC_TARGET_RMS whatever the input volume or TV volume is.
    alpha = 1 - np.exp(-hop / SAMPLE_RATE / MIC_AGC_TAU_S)
    level = None
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=hop, callback=callback):
        while True:
            block = await queue.get()
            rms = float(np.sqrt(np.mean(block ** 2)))
            if rms > MIC_NOISE_RMS:  # don't let true silence pump the gain up
                level = rms if level is None else level + alpha * (rms - level)
            gain = 1.0 if level is None else min(MIC_MAX_GAIN, max(1.0, MIC_TARGET_RMS / level))
            yield np.clip(block * gain, -1, 1)
