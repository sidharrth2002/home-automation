"""Offline checks of the analysis + show pipeline on a synthetic track with known answers.

Run: .venv/bin/python -m tests.test_analysis
"""
import numpy as np

from music_sync.analysis import HOP, SR, Analyzer
from music_sync.show import Show

BPM = 128
BEAT = 60 / BPM
DURATION = 30.0
BREAK = (12.0, 18.0)  # breakdown: kicks/hats stop, chord gets quiet; drop lands at 18s


def synth(seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(DURATION * SR)) / SR
    out = np.zeros_like(t)
    kicks = []
    for k in np.arange(0.5, DURATION, BEAT):
        if BREAK[0] <= k < BREAK[1]:
            continue
        kicks.append(k)
        i = int(k * SR)
        n = min(int(0.8 * SR), len(out) - i)  # long enough that the decay never truncates into a click
        tt = np.arange(n) / SR
        f = 50 + 70 * np.exp(-tt / 0.03)  # pitch-dropping kick
        out[i:i + n] += 0.8 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.12)
        j = int((k + BEAT / 2) * SR)  # off-beat hat
        m = int(0.04 * SR)
        hat = np.diff(rng.standard_normal(m + 1)) * np.exp(-np.arange(m) / SR / 0.01)
        out[j:j + m] += 0.15 * hat[: len(out[j:j + m])]
    chord = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 261.63, 329.63, 440.0, 523.25))
    level = np.where((t >= BREAK[0]) & (t < BREAK[1]), 0.02, 0.06)
    out += level * chord
    return (out / np.max(np.abs(out)) * 0.7).astype(np.float32), np.array(kicks)


def run():
    audio, kicks = synth()
    a, show = Analyzer(), Show(2)
    show.latency_ms = 0  # compare predicted beats against the true kick times
    beats, onsets, drops, frames, bpms = [], {"bass": [], "mid": [], "high": []}, [], [], []
    for i in range(len(audio) // HOP):
        now = (i + 1) * HOP / SR
        f = a.process(audio[i * HOP:(i + 1) * HOP], now)
        for o in f.onsets:
            onsets[o.band].append(o.t)
        if f.drop:
            drops.append(now)
        if a.tempo.locked:
            beats.extend(a.tempo.due(now, 0.0))
            bpms.append((now, a.tempo.bpm))
        frames.append((f, show.update(f, a.tempo, now)))
    return a, kicks, beats, onsets, drops, frames, bpms


def main():
    a, kicks, beats, onsets, drops, frames, bpms = run()
    late = [b for t, b in bpms if t > 8 and not (BREAK[0] < t < BREAK[1] + 4)]
    bpm = float(np.median(late))
    print(f"tempo: {bpm:.1f} BPM (true {BPM}), confidence {a.tempo.confidence:.2f}")
    assert abs(bpm - BPM) < 2, bpm

    hop_s = HOP / SR
    def matched(times, refs, tol):
        return np.mean([np.min(np.abs(refs - x)) < tol for x in times]) if len(times) else 0.0

    bass_hit = matched(kicks, np.array(onsets["bass"]), 2 * hop_s)
    print(f"kick recall: {bass_hit:.0%} of {len(kicks)} kicks, {len(onsets['bass'])} bass onsets")
    assert bass_hit > 0.9

    steady = np.array([b for b in beats if 8 < b < BREAK[0] or b > BREAK[1] + 4])
    err = np.array([np.min(np.abs(kicks - b)) for b in steady])
    print(f"predicted-beat error: median {np.median(err) * 1000:.0f} ms, p90 {np.percentile(err, 90) * 1000:.0f} ms "
          f"over {len(steady)} beats")
    assert np.median(err) < 0.03

    print(f"drops at: {[round(d, 2) for d in drops]} (true {BREAK[1]})")
    first_kick = kicks[kicks >= BREAK[1]][0]
    assert len(drops) == 1 and abs(drops[0] - first_kick) < 0.1, (drops, first_kick)

    hues = [f.hue for f, _ in frames if f.t > 6]
    print(f"hue (A minor): {np.mean(hues):.3f} ± {np.std(hues):.3f}, clarity {frames[-1][0].clarity:.2f}")
    assert np.std(hues) < 0.05

    dims = np.array([[p["dimming"] for p in out if "dimming" in p] for _, out in frames if len(out) == 2 and "r" in out[0]])
    print(f"dimming range: {dims.min()}..{dims.max()}, both bulbs differ in hue: "
          f"{frames[-1][1][0]['r'], frames[-1][1][0]['g'], frames[-1][1][0]['b']} vs "
          f"{frames[-1][1][1]['r'], frames[-1][1][1]['g'], frames[-1][1][1]['b']}")
    assert dims.min() >= 10 and dims.max() >= 85
    print("OK")


def test_tv():
    """TV mode must stay dim, warm white and slow: no RGB colour, no flashes, no visible steps."""
    audio, _ = synth()
    a, show = Analyzer(), Show(2)
    show.mode = "tv"
    dims, temps, prev, max_step = [], [], None, 0
    for i in range(len(audio) // HOP):
        now = (i + 1) * HOP / SR
        out = show.update(a.process(audio[i * HOP:(i + 1) * HOP], now), a.tempo, now)
        assert all("r" not in p for p in out), "TV mode must never send RGB colour"
        if now > 5:  # after the fade-in
            d = out[0]["dimming"]
            dims.append(d)
            temps.append(out[0]["temp"])
            max_step = max(max_step, abs(d - prev)) if prev is not None else 0
            prev = d
    print(f"TV: dimming {min(dims)}..{max(dims)}%, {min(temps)}..{max(temps)}K, max step {max_step}% per hop")
    assert min(dims) >= 10 and max(dims) <= 23 and max_step <= 1
    print("TV OK")


if __name__ == "__main__":
    main()
    test_tv()
