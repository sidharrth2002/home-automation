"""Turns analysis frames into per-bulb colours.

Bulbs alternate roles: even ones follow the beat/kicks, odd ones also catch snares and hats. When the
tempo is locked the show fires on *predicted* beats, `latency_ms` early, so the light lands on the beat
instead of ~100 ms after it; otherwise it reacts to detected kicks/snares. Brightness is a fast-attack,
tempo-scaled decay over a loudness-following floor, hue follows the music's harmony, and drops get a
white flash, a hue jump and a temporary boost.
"""
import colorsys
import math

from .analysis import Frame, TempoTracker

PROFILES = {
    "calm": dict(floor=0.3, floor_gain=0.35, depth=0.35, decay=1.2, spread=0.04, hue_tau=5.0, sat=0.85,
                 beat_step=0.0, bar_step=0.0, accent=0.0, flash=False, chase=False, drop_jump=0.15),
    "auto": dict(floor=0.12, floor_gain=0.3, depth=0.85, decay=0.45, spread=0.1, hue_tau=2.0, sat=1.0,
                 beat_step=0.0, bar_step=0.04, accent=0.35, flash=True, chase=False, drop_jump=0.4),
    "party": dict(floor=0.02, floor_gain=0.12, depth=1.0, decay=0.3, spread=0.5, hue_tau=1.0, sat=1.0,
                  beat_step=0.03, bar_step=0.08, accent=0.5, flash=True, chase=True, drop_jump=0.5),
}
FLASH_S = 0.12


def _decay(dt, tau):
    return math.exp(-dt / max(tau, 1e-3))


class Show:
    def __init__(self, n_bulbs):
        self.n = max(1, n_bulbs)
        self.mode = "auto"
        self.latency_ms = 60.0
        self.env = [0.0] * self.n
        self.sparkle = [0.0] * self.n
        self.hue_offset = 0.0
        self.boost = 0.0
        self.flash_until = 0.0
        self.beats = 0
        self.pending = []  # (fire_time, kind, strength) for negative-latency delays
        self.last_t = None
        self.last_kick = 0.0

    @property
    def profile(self):
        return PROFILES.get(self.mode, PROFILES["auto"])

    def update(self, f: Frame, tempo: TempoTracker, now: float):
        p = self.profile
        dt = 0.0 if self.last_t is None else now - self.last_t
        self.last_t = now
        lead = self.latency_ms / 1000
        delay = max(0.0, -lead)

        kicks = [o for o in f.onsets if o.band == "bass"]
        if kicks:
            self.last_kick = max(o.strength for o in kicks)

        beat_times = tempo.due(now, max(lead, 0.0))
        if tempo.locked:
            for bt in beat_times:
                self.pending.append((bt + delay if delay else now, "beat", max(0.6, self.last_kick)))
        else:
            for o in f.onsets:
                if o.band in ("bass", "mid") and (o.band == "bass" or not kicks):
                    self.pending.append((o.t + delay, "beat", o.strength))
        for o in f.onsets:
            if o.band in ("mid", "high"):
                self.pending.append((o.t + delay, "accent", o.strength))
        if f.drop:
            self.pending.append((now + delay, "drop", 1.0))

        due = [e for e in self.pending if e[0] <= now]
        self.pending = [e for e in self.pending if e[0] > now]

        tau = p["decay"] * (tempo.period or 0.5)
        self.env = [e * _decay(dt, min(max(tau, 0.06), 1.5)) for e in self.env]
        self.sparkle = [s * _decay(dt, 0.08) for s in self.sparkle]
        self.boost *= _decay(dt, 6.0)

        for _, kind, strength in due:
            getattr(self, "_" + kind)(strength, now)

        return self._render(f, now)

    def _beat(self, strength, now):
        p = self.profile
        self.beats += 1
        self.hue_offset += p["beat_step"] + (p["bar_step"] if self.beats % 4 == 0 else 0.0)
        if p["chase"] and self.n > 1:
            self.env[self.beats % self.n] = 1.0
            return
        for i in range(self.n):
            role = 1.0 if i % 2 == 0 or self.n == 1 else 0.6
            self.env[i] = max(self.env[i], strength * role)

    def _accent(self, strength, now):
        p = self.profile
        if not p["accent"]:
            return
        for i in range(self.n):
            if i % 2 == 1 or self.n == 1:
                self.sparkle[i] = max(self.sparkle[i], p["accent"] * strength)
                self.env[i] = max(self.env[i], 0.5 * strength)

    def _drop(self, strength, now):
        p = self.profile
        self.hue_offset += p["drop_jump"]
        self.boost = 1.0
        if p["flash"]:
            self.flash_until = now + FLASH_S
        self.env = [1.0] * self.n

    def _render(self, f: Frame, now):
        p = self.profile
        if now < self.flash_until:
            return [{"state": True, "temp": 6500, "dimming": 100}] * self.n
        frames = []
        floor = min(0.6, p["floor"] + p["floor_gain"] * f.loudness)
        depth = min(1.0, p["depth"] + 0.3 * self.boost)
        for i in range(self.n):
            level = floor + (1 - floor) * depth * self.env[i]
            offset = p["spread"] * (i - (self.n - 1) / 2) if self.n > 1 else 0.0
            hue = (f.hue + self.hue_offset + offset) % 1.0
            sat = p["sat"] * (1 - 0.7 * self.sparkle[i])
            r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
            frames.append({"state": True, "r": round(r * 255), "g": round(g * 255), "b": round(b * 255),
                           "dimming": max(10, min(100, round(level * 100)))})
        return frames
