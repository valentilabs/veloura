"""Blueprints: complete beats modelled on reference projects the user loves.

"Yo" (veloura/references/yo.json, read from the user's FL project on 2026-10-15) is the house standard for trap:
  * 8 bars, 4 chords x 2 bars, extended harmony: i9 - bVImaj9 - bVImaj7/bIII - V7b9 (Fm9 Dbmaj9 Dbmaj7/Ab C7b9)
  * keys: rootless 4-note close voicings, struck on beats 1 and 3, held ~2 beats, one velocity
  * pad: one wide voicing per chord (root low, the rest spread up two octaves), held the whole chord
  * arp lead: per chord a rising 16th-note arpeggio whose notes all ring to the same end, then a 3-note falling
    answer in the chord's second bar; the last chord ends on a rising tag
  * stabs: mid-register triads on the off-beats (1.5, 2.5, 3, 3.5) to keep the loop moving
  * bass (acoustic/synth bass): root on 1 (held), octave pop on the "and" of 2, root again on 3
  * 808: the 3-3-2 rhythm (steps 0, 6, 10) on the chord root, octave-up accents about once a bar in each
    chord's second bar
  * drums: kick 0/7/10 (+ an extra kick in bar 6), snare on 3 with a ghost+hit fill closing bars 4 and 8, even 8th
    hats with 1/32 rolls ramping into bars 5 and the loop restart (skipping the snare-fill spot)
  * every part at one even velocity; only rolls and ghost notes vary
Each writer takes any key/harmony, so Veloura can make endless new beats in exactly this style.
"""

import json
import os
import random

from . import theory

# Yo is one good example, not a template (2026-10-20): with VARIETY on, each request picks a family per part
# (chord rhythm, 808 rhythm, drum groove), seeded per request, so consecutive beats don't sound alike. Yo stays one of
# the families. False = always the original Yo.
VARIETY = True
KEYS_FAMILIES = ("yo", "lift", "half", "plugg", "rnb", "drill", "sustain")


def pick(families, seed, salt):
    """The family for this request (always the first, Yo, when VARIETY is off)."""
    return random.Random(seed * 7919 + salt).choice(families) if VARIETY else families[0]

REF_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "references")


def load_reference(name="yo"):
    try:
        with open(os.path.join(REF_DIR, name + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def yo_harmony(key, bars=8, seed=0):
    """Four chords, two bars each: i9 - bVImaj9 - bVImaj7/bIII - V7b9 (minor keys); I - vi9 - IVmaj7 - V9 (major)."""
    t, mode = key
    names = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    rnd = random.Random(seed)
    if "minor" in mode or mode in ("phrygian", "dorian"):
        options = [
            ["%sm9" % names[t], "%smaj9" % names[(t + 8) % 12], "%smaj7/%s" % (names[(t + 8) % 12], names[(t + 3) % 12]), "%s7b9" % names[(t + 7) % 12]],
            ["%sm9" % names[t], "%smaj7" % names[(t + 3) % 12], "%smaj9" % names[(t + 8) % 12], "%s7b9" % names[(t + 7) % 12]],
            ["%sm9" % names[t], "%sm7" % names[(t + 5) % 12], "%smaj9" % names[(t + 8) % 12], "%s7" % names[(t + 7) % 12]],
        ]
    else:
        options = [["%smaj9" % names[t], "%sm9" % names[(t + 9) % 12], "%smaj7" % names[(t + 5) % 12], "%s9" % names[(t + 7) % 12]]]
    prog = options[0] if seed % 3 == 0 else rnd.choice(options)
    per = 2 if bars >= 8 else 1
    segs = []
    for i in range(max(1, bars // per)):
        ch = theory.parse_chord(prog[i % 4])
        segs.append(dict(ch, start=float(i * per * 4), length=float(per * 4)))
    return segs


def _n(p, s, l, v):
    return {"pitch": int(p), "start": round(s, 6), "length": round(l, 6), "velocity": int(v)}


def _voicing_rootless(seg, prev=None):
    """4 notes without the root, sitting between C4 and A4 like the reference (C4 Eb4 G4 Ab4 over Fm9)."""
    pcs = [pc for pc in seg["pcs"] if pc != seg["root"]] or seg["pcs"]
    cands = []
    for low in range(58, 63):
        if low % 12 not in pcs:
            continue
        v, p = [low], low
        while len(v) < 4 and p < 72:
            p += 1
            if p % 12 in pcs and p % 12 not in [x % 12 for x in v]:
                v.append(p)
        if len(v) == 4:
            cands.append(v)
    if not cands:
        return theory.voice_chord(pcs, 64, prev, size=4)
    if prev:
        return min(cands, key=lambda v: sum(min(abs(a - b) for b in prev) for a in v))
    return min(cands, key=lambda v: abs(v[0] - 60))


def keys(harmony, bars, velocity=80, family="yo"):
    if family not in ("yo", "lift"):   # a genre comping rhythm (onsets/lengths in 16ths per bar), rootless voicings
        from .ensemble import COMP
        out, prev = [], None
        for seg in harmony:
            v = _voicing_rootless(seg, prev=prev)
            prev = v
            b = seg["start"]
            while b < seg["start"] + seg["length"] - 1e-6:
                for st, ln in COMP[family]:
                    s0 = b + st / 4.0
                    if s0 < seg["start"] + seg["length"] - 1e-6:
                        out += [_n(p, s0, min(ln / 4.0, seg["start"] + seg["length"] - s0) * 0.95, velocity) for p in v]
                b += 4.0
        return theory.dedupe(out)
    out, prev = [], None
    half = 4.0 * bars / 2
    for seg in harmony:
        v = _voicing_rootless(seg, prev=prev)
        prev = v
        lift = family == "lift" and bars >= 8 and seg["start"] >= half - 1e-6
        if lift and v[0] + 12 <= 76:
            v = sorted(v[1:] + [v[0] + 12])   # next inversion up: same chord, brighter top
        t = seg["start"]
        while t < seg["start"] + seg["length"] - 1e-6:
            if lift:   # 1 ... push on the "and" of 2 ... 3
                out += [_n(p, t, 1.4, velocity) for p in v] + [_n(p, t + 1.5, 0.4, velocity) for p in v] \
                    + [_n(p, t + 2.0, 1.9, velocity) for p in v]
                t += 4.0
                continue
            out += [_n(p, t, 1.9, velocity) for p in v]
            t += 2.0
    return theory.dedupe(out)


def pad(harmony, bars, velocity=80):
    """Spaced like the reference: a low note (the tonic held under the second chord), a colour tone in the middle
    octave, then the 7th and 3rd/9th on top (F2 G3 Ab4 C5 | F2 Ab3 C5 Eb5 | Db3 Ab3 C5 F5 | C3 G3 Bb4 E5)."""
    out = []
    tonic = harmony[0]["root"] if harmony else 0
    for i, seg in enumerate(harmony):
        r = seg["root"]
        iv = lambda *xs: next((pc for pc in seg["pcs"] if (pc - r) % 12 in xs), None)
        third, fifth, seventh, ninth = iv(3, 4), iv(6, 7, 8), iv(10, 11), iv(1, 2)
        pedal = i == 1 and len(harmony) >= 4
        low = theory.nearest_pitch(41, {tonic if pedal else seg["bass"]}, 38, 50)
        if i == 0:   # the home chord: 9th in the middle, 3rd and 5th on top
            mid = theory.nearest_pitch(55, {ninth if ninth is not None else fifth}, 52, 59)
            tops = [theory.nearest_pitch(68, {third}, 65, 71), None]
            tops[1] = theory.nearest_pitch(tops[0] + 4, {fifth}, tops[0] + 2, tops[0] + 6)
        else:
            mid = theory.nearest_pitch(56, {fifth if fifth is not None else third}, 52, 59)
            t1 = theory.nearest_pitch(71, {seventh if seventh is not None else third}, 68, 73)
            up = third if third is not None and 2 <= (third - t1) % 12 <= 7 else (ninth if ninth is not None else third)
            tops = [t1, theory.nearest_pitch(t1 + 4, {up}, t1 + 2, t1 + 7)]
        out += [_n(p, seg["start"], seg["length"] - 0.08, velocity) for p in sorted({low, mid, *tops})]
    return theory.dedupe(out)


def arp_lead(harmony, bars, key, velocity=100, seed=0):
    """Rising 16th arpeggio per chord, all notes ringing to the same end, then a falling 3-note answer."""
    out = []
    last = len(harmony) - 1
    for i, seg in enumerate(harmony):
        pcs = list(seg["pcs"])
        start = theory.nearest_pitch(65, {seg["root"]}, 58, 68)
        tones, p = [start], start
        while len(tones) < 5:          # climb in thirds: root, 3rd, 5th, 7th, 9th (never by step)
            p += 3
            while p % 12 not in pcs:
                p += 1
            tones.append(p)
        third = next((pc for pc in pcs if (pc - seg["root"]) % 12 in (3, 4)), None)
        tones.append(theory.nearest_pitch(tones[-1] + 1, {third}, tones[-1] + 1, tones[-1] + 5) if third is not None else tones[-1] + 3)
        t0 = seg["start"]
        end = t0 + 3.75
        for k, p in enumerate(tones):
            s = t0 + k * 0.25 if k < 5 else t0 + 1.5
            out.append(_n(p, s, end - s, velocity))
        if seg["length"] >= 8:
            if i == last:   # rising tag into the loop restart
                tag = [theory.nearest_pitch(70, set(pcs), 66, 74)]
                while len(tag) < 4:
                    q = tag[-1] + 1
                    while q % 12 not in pcs:
                        q += 1
                    tag.append(q)
                out += [_n(q, t0 + 6.0 + k * 0.5, 0.5, velocity) for k, q in enumerate(tag)]
            else:           # falling answer in the chord's second bar
                top = sorted(tones)[-1]
                ans, q = [top], top
                while len(ans) < 3:
                    q -= 1
                    while q % 12 not in pcs:
                        q -= 1
                    ans.append(q)
                out += [_n(ans[0], t0 + 6.0, 0.5, velocity), _n(ans[1], t0 + 6.5, 0.5, velocity), _n(ans[2], t0 + 7.0, 1.0, velocity)]
    return theory.dedupe(out)


def stabs(harmony, bars, velocity=80):
    """Off-beat triad stabs in the middle register (1.5, 2.5, 3, 3.5 in each bar)."""
    out, prev = [], None
    rhythm = [(1.5, 1.0), (2.5, 0.5), (3.0, 0.5), (3.5, 0.5)]
    for seg in harmony:
        v = theory.voice_chord(seg["pcs"], 61, prev, size=3)
        prev = v
        b = seg["start"]
        while b < seg["start"] + seg["length"] - 1e-6:
            out += [_n(p, b + s, l, velocity) for s, l in rhythm for p in v]
            b += 4
    return theory.dedupe(out)


def bass_line(harmony, bars, velocity=110):
    """Acoustic/synth bass: root on 1 (held), octave pop on the 'and' of 2, root on 3."""
    out = []
    for seg in harmony:
        r = theory.nearest_pitch(29, {seg["bass"]}, 24, 35)
        b = seg["start"]
        while b < seg["start"] + seg["length"] - 1e-6:
            out += [_n(r, b, 1.25, velocity), _n(r + 12, b + 1.5, 0.5, velocity), _n(r, b + 2.0, 1.25, velocity)]
            b += 4
    return theory.dedupe(out)


def eight_o_eight(harmony, bars, velocity=110, lift=False):
    """3-3-2 on the root, octave-up accents in the chord's second bar. Like the reference, the 808 holds the tonic
    under the second chord (a pedal), then follows the roots."""
    out = []
    tonic = harmony[0]["root"] if harmony else 0
    for i, seg in enumerate(harmony):
        root = tonic if i == 1 and len(harmony) >= 4 else seg["root"]   # the chord's root, not a slash bass
        r = theory.nearest_pitch(41, {root}, 36, 47)
        b, k = seg["start"], 0
        while b < seg["start"] + seg["length"] - 1e-6:
            second = k % 2 == 1
            hits = [(0.0, 1.5, 0), (1.5, 1.0, 0), (2.5, 1.5, 12 if second else 0)]
            if lift and int(round(b / 4)) % 4 == 1:   # bars 2 and 6: bounce up to the 5th
                hits[1] = (1.5, 1.0, 7)
            if second and k % 4 == 3:
                hits[0] = (0.0, 1.5, 12)
            out += [_n(r + up, b + s, l, velocity) for s, l, up in hits]
            b += 4
            k += 1
    return theory.dedupe(out)


def drums(bars, seed=0, lift=False):
    """The Yo groove for any length: kick 0/7/10 (+ bar 6 extra), snare on 3 with fills, even 8ths + rolls."""
    lanes = {"Kick": [], "Snare": [], "Hi-hat": []}
    for bar in range(bars):
        t = bar * 4.0
        for s in (0, 7, 10):
            lanes["Kick"].append(_n(60, t + s / 4, 0.25, 110))
        if bar % 8 == 5:
            lanes["Kick"].append(_n(60, t + 3.5, 0.25, 110))
        lanes["Snare"].append(_n(60, t + 2.0, 0.25, 112))
        fill = bar % 4 == 3
        if fill:
            lanes["Snare"] += [_n(60, t + 3.5, 0.25, 60), _n(60, t + 3.75, 0.25, 112)]
        roll_into_6 = bar % 8 == 4
        for s in range(0, 16, 2):
            st = t + s / 4
            if (fill and st >= t + 3) or (roll_into_6 and st >= t + 3.5):
                continue
            lanes["Hi-hat"].append(_n(60, st, 0.25, 97))
        if fill:
            vel = 71
            for k in range(8):
                st = t + 3 + k * 0.125
                if abs(st - (t + 3.5)) < 1e-6:
                    continue        # leave room for the ghost snare
                lanes["Hi-hat"].append(_n(60, st, 0.125, vel))
                vel = min(97, vel + 4)
        if roll_into_6:
            lanes["Hi-hat"] += [_n(60, t + 3.5 + k * 0.125, 0.125, 71 + 7 * k) for k in range(4)]
        if lift and bar % 8 == 1:   # a short 1/32 roll closing bar 2
            lanes["Hi-hat"] = [h for h in lanes["Hi-hat"] if not (t + 3.5 - 1e-6 <= h["start"] < t + 4 - 1e-6)]
            lanes["Hi-hat"] += [_n(60, t + 3.5 + k * 0.125, 0.125, 75 + 7 * k) for k in range(4)]
    return lanes


LAYERS = [   # (part name, instrument, purpose, writer)
    ("Keys", "keys", "chords"), ("Pad", "pad", "pad"), ("Arp Lead", "bell", "lead"), ("Stabs", "pluck", "counter"),
    ("Bass", "bass_808", "bass"), ("808", "bass_808", "bass"),
]


def yo_beat(key, bars=8, seed=0, with_acoustic_bass=True):
    """All the parts of a Yo-style beat for a key: {name: (role, instrument, purpose, notes)} plus the harmony."""
    h = yo_harmony(key, bars, seed)
    parts = {
        "Keys": ("chords", "keys", "chords", keys(h, bars)),
        "Pad": ("chords", "pad", "pad", pad(h, bars)),
        "Arp Lead": ("melody", "bell", "lead", arp_lead(h, bars, key, seed=seed)),
        "Stabs": ("chords", "pluck", "counter", stabs(h, bars)),
        "808": ("bass", "bass_808", "bass", eight_o_eight(h, bars)),
    }
    if with_acoustic_bass:
        parts["Bass"] = ("bass", "bass_808", "bass", bass_line(h, bars))
    for lane, notes in drums(bars, seed).items():
        parts[lane] = ("drums", None, "drums", notes)
    return parts, h


def ai_example():
    """Compact description of the Yo reference for the AI prompt (bars 1-2 of each layer + the drum grid)."""
    ref = load_reference()
    if not ref:
        return None
    N = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    nn = lambda p: "%s%d" % (N[p % 12], p // 12 - 1)
    ex = {"name": "Yo", "tempo": ref["tempo"], "key": ref["key"], "chords (2 bars each)": ref["chords"], "layers_first_2_bars": {}}
    for name, notes in ref["layers"].items():
        if "stabs" in name:
            notes = [n for n in notes if n["length"] >= 0.25]   # the user doesn't want the strum slivers copied
        ex["layers_first_2_bars"][name] = [[nn(n["pitch"]), n["start"], n["length"]] for n in notes if n["start"] < 8][:24]
    ex["drums_16th_steps_bars_1_4"] = ref.get("drums_steps_bar1to4")
    return ex
