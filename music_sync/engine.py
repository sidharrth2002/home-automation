"""Beat detection and colour mapping, ported from wiz_spotify's system-audio-engine."""
from dataclasses import dataclass

import numpy as np

SILENCE_THRESHOLD = 0.01
MIN_BEAT_INTERVAL_MS = 90
SMOOTHING = 0.1

# (upper bound in Hz, RGB)
PALETTE = [
    (120, (255, 0, 0)),
    (250, (255, 120, 0)),
    (400, (255, 220, 0)),
    (800, (0, 255, 60)),
    (2000, (0, 90, 255)),
    (4000, (150, 0, 255)),
    (float("inf"), (255, 0, 160)),
]


@dataclass
class Beat:
    rgb: tuple
    brightness: int  # 0-255, as pywizlight expects
    interval_ms: float


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


class BeatEngine:
    def __init__(self, sensitivity=1.35, mode="auto"):
        self.sensitivity = sensitivity
        self.mode = mode
        self.reset()

    def reset(self):
        self.running_energy = 0.0
        self.last_beat_ms = 0.0
        self.last_interval_ms = 150.0
        self._alt = True

    def process(self, pcm: bytes, sample_rate: int, now_ms: float):
        """Return a Beat for this chunk, or None. Also returns the chunk RMS."""
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        if samples.size == 0:
            return None, 0.0
        rms = float(np.sqrt(np.mean(samples**2)))
        if rms < SILENCE_THRESHOLD or not self._detect(rms, now_ms):
            return None, rms

        spectrum = np.abs(np.fft.rfft(samples))
        spectrum[0] = 0
        freq = float(np.argmax(spectrum)) * sample_rate / samples.size
        rgb = next(c for limit, c in PALETTE if freq < limit)
        return Beat(rgb, self._brightness(rms), self.last_interval_ms), rms

    def _detect(self, rms, now_ms):
        if self.running_energy == 0:
            self.running_energy = rms
            self.last_beat_ms = now_ms
            return False
        beat = (
            rms / (self.running_energy or 1e-4) > self.sensitivity
            and now_ms - self.last_beat_ms > MIN_BEAT_INTERVAL_MS
        )
        self.running_energy = (1 - SMOOTHING) * self.running_energy + SMOOTHING * rms
        if beat:
            self.last_interval_ms = now_ms - self.last_beat_ms
            self.last_beat_ms = now_ms
        return beat

    def _brightness(self, rms):
        pct = clamp(round(rms * 140), 10, 100)
        if self.mode == "calm":
            pct = clamp(round(pct * 0.6), 8, 80)
        elif self.mode == "party":
            pct = 100 if self._alt else 12
            self._alt = not self._alt
        else:
            pct = clamp(pct if self._alt else round(pct * 0.75), 10, 100)
            self._alt = not self._alt
        return round(pct * 255 / 100)
