"""Real-time music analysis, run once per STFT hop (~23 ms of mono audio).

- Onsets: spectral flux in three bands (bass = kicks, mid = snares/vocals, high = hats), each with an
  adaptive median threshold and peak picking, so beats are found by *change*, not raw loudness.
- Tempo: autocorrelation of the onset envelope with a log-normal tempo prior and metrical support,
  then a comb filter for beat phase and a light PLL on kicks. Lets the show fire on predicted beats
  (with latency compensation) instead of always reacting late.
- Harmony: a chroma vector mapped onto the circle of fifths gives a hue that follows key/chords, and a
  clarity score (how tonal the music is).
- AGC: per-band peak followers so quiet and loud tracks drive the lights the same way.
- Drops: a sustained breakdown followed by energy returning with a kick.
"""
import math
from collections import deque
from dataclasses import dataclass

import numpy as np

SR = 44100
N_FFT = 2048
HOP = 1024
FPS = SR / HOP

BANDS = {"bass": (40, 160), "mid": (160, 2500), "high": (2500, 11000)}
FLUX_WEIGHTS = {"bass": 1.0, "mid": 0.6, "high": 0.4}
MIN_GAP_S = {"bass": 0.1, "mid": 0.09, "high": 0.06}
AGC_DECAY = 0.5 ** (1 / (10 * FPS))  # peak followers halve over ~10s


def _ema_alpha(tau_s):
    return 1 - math.exp(-1 / (FPS * tau_s))


@dataclass
class Onset:
    t: float
    band: str
    strength: float  # 0..1


@dataclass
class Frame:
    t: float
    rms: float
    loudness: float  # 0..1 after AGC
    bands: dict  # band -> 0..1 after AGC
    onsets: list
    hue: float  # 0..1
    clarity: float  # 0..1
    drop: bool


class OnsetDetector:
    """Adaptive-threshold peak picker with one hop of lookahead."""

    def __init__(self, band):
        self.min_gap = MIN_GAP_S[band]
        self.band = band
        self.hist = deque(maxlen=int(0.5 * FPS))
        self.recent = deque([0.0, 0.0, 0.0], maxlen=3)
        self.peak = 1e-4
        self.last_t = -1.0

    def push(self, t, flux, sensitivity):
        self.peak = max(flux, self.peak * AGC_DECAY)
        self.recent.append(flux)
        before, cand, after = self.recent
        thresh = (np.median(self.hist) if self.hist else 0.0) * sensitivity + 0.1 * self.peak
        self.hist.append(cand)
        t_cand = t - 1 / FPS
        if cand > thresh and cand >= before and cand > after and t_cand - self.last_t >= self.min_gap:
            self.last_t = t_cand
            strength = min(1.0, 0.25 + (cand - thresh) / (0.6 * self.peak + 1e-9))
            return Onset(t_cand, self.band, strength)
        return None


class TempoTracker:
    HISTORY_S = 8.0
    MIN_BPM, MAX_BPM = 60, 200
    LOCK_CONFIDENCE = 0.25

    def __init__(self):
        n = int(self.HISTORY_S * FPS)
        self.env = deque(maxlen=n)
        self.times = deque(maxlen=n)
        self.period = None
        self.confidence = 0.0
        self.next_beat = None
        self._candidate = None
        self._since = 0

    @property
    def bpm(self):
        return 60 / self.period if self.period else None

    @property
    def locked(self):
        return self.period is not None and self.next_beat is not None and self.confidence >= self.LOCK_CONFIDENCE

    def push(self, t, value):
        self.env.append(value)
        self.times.append(t)
        self._since += 1
        if self._since >= FPS / 2 and len(self.env) >= 4 * FPS:
            self._since = 0
            self._estimate()

    def _estimate(self):
        env = np.asarray(self.env)
        x = env - env.mean()
        n = len(x)
        spec = np.fft.rfft(x, 2 * n)
        ac = np.fft.irfft(spec * np.conj(spec))[:n]
        if ac[0] <= 1e-12:
            self.confidence *= 0.5
            return
        ac /= ac[0]
        lo = int(FPS * 60 / self.MAX_BPM)
        hi = min(int(FPS * 60 / self.MIN_BPM) + 1, n // 2 - 1)
        lags = np.arange(lo, hi)
        prior = np.exp(-0.5 * (np.log2(60 * FPS / lags / 120) / 0.9) ** 2)
        # Metrical support: a true beat period also correlates at twice its lag.
        score = (np.clip(ac[lags], 0, None) + 0.5 * np.clip(ac[2 * lags], 0, None)) * prior
        i = int(np.argmax(score))
        lag = float(lags[i])
        a, b, c = ac[lags[i] - 1], ac[lags[i]], ac[lags[i] + 1]
        denom = a - 2 * b + c
        if denom < 0:
            lag += 0.5 * (a - c) / denom
        period = lag / FPS
        self.confidence = 0.6 * self.confidence + 0.4 * float(max(0.0, b))

        if self.period is None or abs(period / self.period - 1) < 0.04:
            self.period = period if self.period is None else 0.8 * self.period + 0.2 * period
            self._candidate = None
        elif self._candidate and abs(period / self._candidate - 1) < 0.04:
            self.period, self._candidate, self.next_beat = period, None, None  # tempo change confirmed
        else:
            self._candidate = period
        self._update_phase(env)

    def _update_phase(self, env):
        """Comb filter: the phase whose beat grid lands on the most onset energy wins."""
        lag = self.period * FPS
        n = len(env)
        best, best_off = -1.0, 0
        for off in range(int(lag)):
            idx = np.round(n - 1 - off - np.arange(0, n // lag) * lag).astype(int)
            idx = idx[idx >= 0]
            score = env[idx].sum()
            if score > best:
                best, best_off = score, off
        last_beat = self.times[n - 1 - best_off]
        now = self.times[-1]
        candidate = last_beat + math.ceil((now - last_beat) / self.period + 1e-9) * self.period
        if self.next_beat is None:
            self.next_beat = candidate
        else:
            d = (candidate - self.next_beat + self.period / 2) % self.period - self.period / 2
            self.next_beat += 0.5 * d

    def observe_kick(self, t):
        """Nudge the beat grid towards kicks that land near it."""
        if not self.locked:
            return
        prev = self.next_beat - self.period
        nearest = prev if abs(t - prev) < abs(t - self.next_beat) else self.next_beat
        err = t - nearest
        if abs(err) < 0.15 * self.period:
            self.next_beat += 0.25 * err

    def due(self, now, lead):
        """Beat times that should fire by `now`, `lead` seconds early."""
        out = []
        if self.next_beat is None or self.period is None:
            return out
        if now - self.next_beat > self.period:  # we fell behind (e.g. a stall); resync forward
            self.next_beat += math.ceil((now - self.next_beat) / self.period) * self.period
        while self.next_beat - lead <= now:
            out.append(self.next_beat)
            self.next_beat += self.period
        return out


class Analyzer:
    def __init__(self):
        self.window = np.hanning(N_FFT).astype(np.float32)
        freqs = np.fft.rfftfreq(N_FFT, 1 / SR)
        self.band_bins = {b: (freqs >= lo) & (freqs < hi) for b, (lo, hi) in BANDS.items()}
        sel = (freqs >= 100) & (freqs <= 4000)
        self.chroma_sel = sel
        self.chroma_pc = ((np.round(12 * np.log2(freqs[sel] / 440)) + 69) % 12).astype(int)
        # Circle of fifths: neighbouring keys get neighbouring hues.
        self.pc_vec = np.exp(1j * 2 * np.pi * ((np.arange(12) * 7) % 12) / 12)

        self.buf = np.zeros(N_FFT, np.float32)
        self.prev_logmag = None
        self.detectors = {b: OnsetDetector(b) for b in BANDS}
        self.tempo = TempoTracker()
        self.band_peak = {b: 1e-6 for b in BANDS}
        self.loud_peak = 1e-6
        self.flux_peak = 1e-6
        self.chroma = np.full(12, 1 / 12)
        self.hue_vec = 1 + 0j
        self.hue_tau = 2.0
        self.sensitivity = 1.35

        self.e_short = self.e_long = 0.0
        self.breakdown_since = None
        self.breakdown_ref = 0.0
        self.last_drop = -1e9

    def process(self, samples, t):
        self.buf[:-HOP] = self.buf[HOP:]
        self.buf[-HOP:] = samples
        rms = float(np.sqrt(np.mean(samples * samples)))

        mag = np.abs(np.fft.rfft(self.buf * self.window))
        logmag = np.log1p(mag)
        pos = np.zeros_like(logmag) if self.prev_logmag is None else np.maximum(logmag - self.prev_logmag, 0)
        self.prev_logmag = logmag

        bands, onsets, env = {}, [], 0.0
        for b, bins in self.band_bins.items():
            energy = float(np.sqrt(np.mean(mag[bins] ** 2)))
            self.band_peak[b] = max(energy, self.band_peak[b] * AGC_DECAY)
            bands[b] = energy / self.band_peak[b]
            flux = float(pos[bins].mean())
            env += FLUX_WEIGHTS[b] * flux
            if rms > 1e-3:
                o = self.detectors[b].push(t, flux, self.sensitivity)
                if o:
                    onsets.append(o)
                    if b == "bass":
                        self.tempo.observe_kick(o.t)

        self.flux_peak = max(env, self.flux_peak * AGC_DECAY)
        self.tempo.push(t, env / self.flux_peak)

        self.loud_peak = max(rms, self.loud_peak * AGC_DECAY)
        loudness = rms / self.loud_peak

        c = np.bincount(self.chroma_pc, weights=mag[self.chroma_sel], minlength=12)
        if c.sum() > 1e-9:
            self.chroma += _ema_alpha(1.0) * (c / c.sum() - self.chroma)
        r = complex(np.dot(self.chroma, self.pc_vec))
        clarity = min(1.0, abs(r) * 4)
        if abs(r) > 1e-9:
            self.hue_vec += _ema_alpha(self.hue_tau) * clarity * (r / abs(r) - self.hue_vec)
        hue = (math.atan2(self.hue_vec.imag, self.hue_vec.real) / (2 * math.pi)) % 1.0

        return Frame(t, rms, loudness, bands, onsets, hue, clarity, self._detect_drop(t, rms, onsets))

    def _detect_drop(self, t, rms, onsets):
        self.e_short += _ema_alpha(0.3) * (rms - self.e_short)
        self.e_long += _ema_alpha(6.0) * (rms - self.e_long)
        if self.e_long < 1e-4:
            return False
        if self.e_short < 0.45 * self.e_long:
            if self.breakdown_since is None:
                self.breakdown_since, self.breakdown_ref = t, self.e_long
            return False
        if self.breakdown_since is None:
            return False
        long_enough = t - self.breakdown_since > 1.5
        expired = t - self.breakdown_since > 20
        kick = any(o.band == "bass" for o in onsets)
        if expired:
            self.breakdown_since = None
        elif long_enough and kick and max(rms, self.e_short) > 0.8 * self.breakdown_ref and t - self.last_drop > 8:
            self.breakdown_since, self.last_drop = None, t
            return True
        return False
