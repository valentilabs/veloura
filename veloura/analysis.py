"""Reference-track analysis (runs locally; audio never leaves the Mac).

analyze(path) -> dict with tempo (+ half/double-time alternatives), key, chords per
bar, an approximate 16-step drum grid (kick / snare / hats), energy, brightness,
low-end weight, an energy curve and the length in bars. Everything here is an
ESTIMATE: tempo can be off by a factor of 2, key and chords by a related key, and
the drum grid is the most likely pattern, not a transcription. The AI is told so.

Decoding uses macOS's built-in `afconvert` (MP3, M4A/AAC, WAV, AIFF, CAF...).
Needs numpy + librosa from the project's .venv.
"""

import os
import subprocess
import tempfile

SR = 22050
MAX_SECONDS = 120
NOTE = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
# Krumhansl-Kessler key profiles
MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


class AnalysisError(RuntimeError):
    pass


def decode(path):
    """Any audio file -> mono float32 samples at SR, using afconvert. Returns (y, duration_seconds)."""
    import numpy as np
    import soundfile as sf
    if not os.path.isfile(path):
        raise AnalysisError("File not found.")
    with tempfile.TemporaryDirectory() as d:
        wav = os.path.join(d, "a.wav")
        p = subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16@%d" % SR, "-c", "1", path, wav],
                           capture_output=True, text=True, timeout=120)
        if p.returncode != 0 or not os.path.exists(wav):
            raise AnalysisError("macOS couldn't read this file (%s). Try WAV, MP3, M4A or AIFF."
                                % (p.stderr.strip()[:120] or "unknown format"))
        y, sr = sf.read(wav, dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    duration = len(y) / float(SR)
    if duration < 2:
        raise AnalysisError("The file is shorter than 2 seconds.")
    if duration > MAX_SECONDS:  # analyse a central window: intros are often sparse
        start = int((duration - MAX_SECONDS) / 2 * SR)
        y = y[start:start + MAX_SECONDS * SR]
    return np.ascontiguousarray(y), duration


def _key(chroma):
    import numpy as np
    profile = chroma.mean(axis=1)
    scores = []
    for tonic in range(12):
        for mode, tpl in (("major", MAJOR), ("minor", MINOR)):
            r = np.corrcoef(profile, np.roll(tpl, tonic))[0, 1]
            scores.append((r, tonic, mode))
    scores.sort(reverse=True)
    best, second = scores[0], scores[1]
    return {"key": "%s %s" % (NOTE[best[1]], best[2]), "confidence": round(float(best[0] - second[0]), 3),
            "alternative": "%s %s" % (NOTE[second[1]], second[2])}


def _chord_name(vec):
    import numpy as np
    best = None
    for root in range(12):
        for quality, ints in (("", (0, 4, 7)), ("m", (0, 3, 7))):
            tpl = np.zeros(12)
            for i in ints:
                tpl[(root + i) % 12] = 1
            score = float(np.dot(vec, tpl) / (np.linalg.norm(vec) * np.linalg.norm(tpl) + 1e-9))
            if best is None or score > best[0]:
                best = (score, NOTE[root] + quality)
    return best[1]


def _band_onsets(S, freqs, lo, hi):
    import librosa
    import numpy as np
    rows = (freqs >= lo) & (freqs < hi)
    env = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[rows], ref=np.max), sr=SR)
    return env / (np.percentile(env, 99) + 1e-9)


def _band_envelopes(y):
    """Percussive onset envelopes for kick / snare / hat frequency bands (computed once)."""
    import librosa
    import numpy as np
    _, perc = librosa.effects.hpss(y)
    S = np.abs(librosa.stft(perc, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    times = librosa.frames_to_time(np.arange(S.shape[1]), sr=SR, hop_length=512)
    return times, {"kick": _band_onsets(S, freqs, 30, 150), "snare": _band_onsets(S, freqs, 160, 700),
                   "hats": _band_onsets(S, freqs, 6000, 11000)}


def _fold(times, bands, beats_t):
    """Per band, the hit probability of each of 16 steps across all bars."""
    import numpy as np
    bars = (len(beats_t) - 1) // 4
    if bars < 2:
        return None
    grids = {k: np.zeros((bars, 16)) for k in bands}
    for b in range(bars):
        for beat in range(4):
            t0, t1 = beats_t[b * 4 + beat], beats_t[b * 4 + beat + 1]
            for sub in range(4):
                center = t0 + (t1 - t0) * sub / 4.0
                half = (t1 - t0) / 8.0
                sel = (times >= center - half) & (times < center + half)
                if sel.any():
                    for k, env in bands.items():
                        grids[k][b, beat * 4 + sub] = env[sel].max()
    hits = {k: g > 0.55 for k, g in grids.items()}
    # Kick attacks and hat noise leak into the snare band: only count a snare where it clearly dominates them.
    hits["snare"] &= (grids["snare"] > grids["hats"] * 0.8) & (grids["snare"] > grids["kick"] * 1.0)
    return {k: h.mean(axis=0) for k, h in hits.items()}


def _align_downbeat(folded):
    """Rotate the 16-step grid (by whole beats) so it reads like a bar: kick on 1, backbeat snare on 2/4 or 3."""
    import numpy as np
    best = None
    for r in (0, 4, 8, 12):
        k, sn = np.roll(folded["kick"], -r), np.roll(folded["snare"], -r)
        score = 2 * k[0] + max(sn[8], (sn[4] + sn[12]) / 2) - 0.5 * sn[0]
        if best is None or score > best[0]:
            best = (score, r)
    return {key: np.roll(v, -best[1]) for key, v in folded.items()}


def _consistency(folded):
    """How repeatable the pattern is bar to bar (1 = every step is always or never hit)."""
    import numpy as np
    return float(np.mean([np.mean(np.abs(p - 0.5) * 2) for p in folded.values()]))


def _tempo_and_grid(y, sr):
    """Pick the tempo whose beat grid makes the drums most repeatable; trap's syncopated kicks fool plain beat
    trackers (e.g. 140 read as 93). Returns (tempo, beat_times, folded_grid, candidates)."""
    import librosa
    import numpy as np
    base, _ = librosa.beat.beat_track(y=y, sr=sr)
    base = float(np.atleast_1d(base)[0])
    times, bands = _band_envelopes(y)
    cands = sorted({round(c, 1) for c in (base, base * 1.5, base / 1.5, base * 2, base / 2, base * 4 / 3, base * 3 / 4)
                    if 60 <= c <= 200})
    best = None
    scored = []
    for c in cands:
        t, frames = librosa.beat.beat_track(y=y, sr=sr, start_bpm=c, tightness=400)
        tracked = librosa.frames_to_time(frames, sr=sr)
        if len(tracked) < 9:
            continue
        # Produced music has a steady tempo: fit a line through the beats (sub-frame precision) and fold the
        # drums onto that even grid instead of the frame-quantised tracker output.
        idx = np.arange(len(tracked))
        period, offset = np.polyfit(idx, tracked, 1)
        t = 60.0 / float(period)
        beats_t = offset + period * idx
        while t > 200 and len(beats_t) >= 18:   # tracker locked onto 8ths: use every other beat
            t /= 2.0
            beats_t = beats_t[::2]
        folded = _fold(times, bands, beats_t)
        if folded is None:
            continue
        score = _consistency(folded)
        scored.append((round(t, 1), round(score, 3)))
        if best is None or score > best[0]:
            best = (score, t, beats_t, folded)
    if best is None:
        return base, None, None, [base]
    return best[1], best[2], _align_downbeat(best[3]), [t for t, _ in sorted(scored, key=lambda x: -x[1])]


def _grid_summary(folded):
    out = {}
    for k, prob in folded.items():
        out[k] = {"pattern": "".join("x" if p >= 0.5 else ("o" if p >= 0.25 else ".") for p in prob),
                  "probability": [round(float(p), 2) for p in prob]}
    out["note"] = "x = hit in most bars, o = hit in some bars; step 1 is a detected beat, which may not be the downbeat."
    return out


def analyze(path):
    try:
        import librosa
        import numpy as np
    except ImportError:
        raise AnalysisError("Audio analysis needs librosa (install it into the project's .venv).")
    y, duration = decode(path)
    tempo, beats_t, folded, ranked = _tempo_and_grid(y, SR)
    beat_frames = librosa.time_to_frames(beats_t, sr=SR) if beats_t is not None else np.array([], dtype=int)
    chroma = librosa.feature.chroma_cqt(y=librosa.effects.harmonic(y), sr=SR)
    key = _key(chroma)

    chords = []
    if len(beat_frames) >= 5:
        sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
        for bar in range(min(8, sync.shape[1] // 4)):
            chords.append(_chord_name(sync[:, bar * 4:(bar + 1) * 4].mean(axis=1)))

    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=SR, n_fft=2048)
    power = (S ** 2).sum(axis=1)
    rms = librosa.feature.rms(S=S)[0]
    rms_db = 20 * np.log10(rms + 1e-9)
    onset_env = librosa.onset.onset_strength(y=y, sr=SR)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=SR)
    sec_per_bar = 240.0 / tempo if tempo else 0
    curve = []
    if sec_per_bar:
        block = int(sec_per_bar * 4 * SR / 512)  # 4-bar blocks
        for i in range(0, len(rms), max(block, 1)):
            curve.append(round(float(rms_db[i:i + block].mean()), 1))
    centroid = float(librosa.feature.spectral_centroid(S=S, sr=SR).mean())
    alternatives = []
    for t in ranked:
        if abs(t - tempo) > 2 and 60 <= t <= 200 and all(abs(t - a) > 2 for a in alternatives):
            alternatives.append(t)
    alternatives = alternatives[:2] or sorted({round(tempo / 2, 1), round(tempo * 2, 1)})
    return {
        "duration_s": round(duration, 1),
        "tempo_bpm": round(tempo, 1),
        "tempo_alternatives": alternatives,
        "length_bars": round(duration / sec_per_bar, 1) if sec_per_bar else None,
        "key": key["key"], "key_confidence": key["confidence"], "key_alternative": key["alternative"],
        "chords_per_bar": chords,
        "drums": _grid_summary(folded) if folded else None,
        "loudness_db": round(float(rms_db.mean()), 1),
        "dynamic_range_db": round(float(np.percentile(rms_db, 95) - np.percentile(rms_db, 10)), 1),
        "brightness_hz": round(centroid),
        "low_end_share": round(float(power[freqs < 120].sum() / (power.sum() + 1e-9)), 3),
        "onsets_per_second": round(len(onsets) / min(duration, MAX_SECONDS), 2),
        "energy_curve_db_per_4_bars": curve[:16],
    }


def describe(a):
    """Short plain-English summary for the UI."""
    bright = "bright" if a["brightness_hz"] > 2600 else "dark" if a["brightness_hz"] < 1600 else "balanced"
    low = "heavy low end" if a["low_end_share"] > 0.35 else "light low end" if a["low_end_share"] < 0.12 else "moderate low end"
    busy = "busy" if a["onsets_per_second"] > 4 else "sparse" if a["onsets_per_second"] < 1.8 else "steady"
    return "%s BPM (or %s), %s, %s tone, %s, %s rhythm" % (
        a["tempo_bpm"], " / ".join(str(t) for t in a["tempo_alternatives"]), a["key"], bright, low, busy)
