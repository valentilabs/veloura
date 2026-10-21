"""Ensemble writer: how real producers write each instrument in a DAW.

Research notes this follows (producer tutorials and keyboard-voicing lessons, 2026-10):
  * The harmonic backbone of trap/plugg/pluggnb/R&B loops is a chord instrument (piano, electric piano/Rhodes,
    keys) playing BLOCK CHORDS, usually extended (7ths, 9ths) in pluggnb/R&B, minor triads/7ths in trap/drill.
  * Two-hand piano: left hand holds the root low (often root + octave), right hand plays a 3-4 note voicing
    (3rd, 7th, 9th/5th) around middle C, with the melody note on TOP of the voicing. Inversions keep voice
    leading smooth; spread notes so they ring; don't put a 5th/3rd cluster down low (mud under the 808).
  * Melodies are layered: a lead (bell, flute, synth, piano) often doubled an octave up or by a second sound with
    small variations; a string or choir pad adds depth; an arp follows the chords for movement.
  * Every instrument has its own register so layers don't blur: 808 F1-C3, chords C3-C5, lead C4-C6, sparkle C6+.

Each writer takes the harmony (bar-by-bar chords), the bar count, and the lead (for parts that follow it), and
returns notes in Veloura's plan format. Chord parts are always FULL chords (3-5 notes), never single notes.
"""

import random

from . import theory

INSTRUMENTS = ["piano", "keys", "rhodes", "pad", "strings", "choir", "guitar", "bell", "pluck", "lead_synth", "arp_synth",
               "flute", "brass", "organ", "supersaw", "music_box", "vox", "bass_808", "other"]
CHORDAL = {"piano", "keys", "rhodes", "pad", "strings", "choir", "guitar", "organ", "supersaw", "brass"}
KEYWORDS = {   # preset-name words that identify each instrument (for choosing sounds inside FLEX / ZENOLOGY)
    "piano": ["piano", "grand", "upright", "keys"], "keys": ["keys", "ep", "e.piano", "electric piano", "wurli", "rhodes"],
    "rhodes": ["rhodes", "ep", "e.piano", "electric piano", "suitcase", "wurli"], "pad": ["pad", "warm", "atmos", "dream", "soft"],
    "strings": ["string", "violin", "cello", "orchestra", "ensemble"], "choir": ["choir", "vox", "voice", "ahh", "ooh"],
    "guitar": ["guitar", "nylon", "acoustic", "gtr"], "bell": ["bell", "glock", "celesta", "chime", "music box"],
    "pluck": ["pluck", "pizz", "harp", "koto"], "lead_synth": ["lead", "square", "saw", "synth"], "arp_synth": ["arp", "seq", "pluck"],
    "flute": ["flute", "pan", "whistle", "recorder"], "brass": ["brass", "horn", "trumpet"], "organ": ["organ"],
    "supersaw": ["supersaw", "saw", "trance", "rave", "hoover"], "music_box": ["music box", "box", "celesta", "toy"],
    "vox": ["vox", "vocal", "chop"], "bass_808": ["808", "bass", "sub"],
}
WORD_TO_INSTRUMENT = [("piano", "piano"), ("grand", "piano"), ("rhodes", "rhodes"), ("e.piano", "rhodes"), ("ep ", "rhodes"),
                      ("keys", "keys"), ("organ", "organ"), ("pad", "pad"), ("string", "strings"), ("violin", "strings"),
                      ("cello", "strings"), ("choir", "choir"), ("vox", "vox"), ("guitar", "guitar"), ("bell", "bell"),
                      ("glock", "bell"), ("music box", "music_box"), ("pluck", "pluck"), ("harp", "pluck"), ("flute", "flute"),
                      ("brass", "brass"), ("horn", "brass"), ("arp", "arp_synth"), ("supersaw", "supersaw"), ("lead", "lead_synth"),
                      ("808", "bass_808"), ("bass", "bass_808"), ("sub", "bass_808")]

# What a producer stacks for each style: (instrument, job). Jobs: chords, lead, double, counter, pad, arp, sparkle, bass.
RECIPES = {
    "trap": [("keys", "chords"), ("pad", "pad"), ("bell", "lead"), ("pluck", "counter"), ("bass_808", "bass")],   # the Yo stack
    "dark trap": [("pad", "pad"), ("piano", "chords"), ("bell", "lead"), ("choir", "counter"), ("bass_808", "bass")],
    "plugg": [("keys", "chords"), ("lead_synth", "lead"), ("pad", "pad"), ("bell", "double"), ("bass_808", "bass")],
    "melodic plugg": [("rhodes", "chords"), ("bell", "lead"), ("pad", "pad"), ("arp_synth", "arp"), ("music_box", "sparkle"), ("bass_808", "bass")],
    "rage": [("supersaw", "chords"), ("arp_synth", "arp"), ("lead_synth", "lead"), ("bass_808", "bass")],
    "jerk": [("pluck", "chords"), ("bell", "lead"), ("lead_synth", "double"), ("bass_808", "bass")],
    "drill": [("piano", "chords"), ("strings", "pad"), ("choir", "counter"), ("bell", "lead"), ("bass_808", "bass")],
    "melodic rap": [("piano", "chords"), ("guitar", "arp"), ("strings", "pad"), ("bell", "lead"), ("bass_808", "bass")],
    "melodic trap": [("keys", "chords"), ("pad", "pad"), ("bell", "lead"), ("pluck", "counter"), ("bass_808", "bass")],
    "detroit": [("piano", "chords"), ("piano", "lead"), ("bass_808", "bass")],
    "ambient": [("pad", "pad"), ("rhodes", "chords"), ("bell", "lead"), ("strings", "counter"), ("bass_808", "bass")],
    "cloud rap": [("pad", "pad"), ("rhodes", "chords"), ("bell", "lead"), ("choir", "counter"), ("bass_808", "bass")],
    "boom bap": [("rhodes", "chords"), ("brass", "lead"), ("bass_808", "bass")],
    "r&b": [("rhodes", "chords"), ("strings", "pad"), ("guitar", "arp"), ("bell", "lead"), ("bass_808", "bass")],
    "pop": [("piano", "chords"), ("pad", "pad"), ("lead_synth", "lead"), ("pluck", "arp"), ("bass_808", "bass")],
}
EXTENDED = {"plugg", "melodic plugg", "r&b", "cloud rap", "ambient", "boom bap", "melodic rap", "melodic trap"}
COMP = {   # chord rhythm per style: onsets in 16ths and lengths (in 16ths) within one bar
    "sustain": [(0, 16)],
    "half": [(0, 8), (8, 8)],
    "plugg": [(0, 6), (6, 4), (10, 6)],
    "rnb": [(0, 7), (7, 3), (10, 6)],
    "stab": [(0, 3), (6, 2), (10, 3), (14, 2)],
    "drill": [(0, 6), (6, 2), (8, 8)],
    "pulse": [(0, 4), (4, 4), (8, 4), (12, 4)],
}
STYLE_COMP = {"trap": "half", "dark trap": "sustain", "plugg": "plugg", "melodic plugg": "plugg", "rage": "pulse",
              "jerk": "stab", "drill": "drill", "melodic rap": "half", "melodic trap": "half", "detroit": "stab",
              "ambient": "sustain", "cloud rap": "sustain", "boom bap": "rnb", "r&b": "rnb", "pop": "half"}


def instrument_from_name(text):
    t = (text or "").lower() + " "
    for word, inst in WORD_TO_INSTRUMENT:
        if word in t:
            return inst
    return None


def _note(p, start, length, vel):
    return {"pitch": int(p), "start": round(start, 6), "length": round(max(0.0625, length), 6), "velocity": int(vel)}


KEY = {"key": None}   # set by write_for: extensions are chosen from the key's scale


def chord_pcs(seg, extended=False):
    """Chord tones for voicing; with extended, add the 7th and 9th the way pluggnb/R&B keys players do, taken from
    the key (so a V chord in minor gets its b7 and b9, never notes outside the key)."""
    pcs = list(seg["pcs"])
    root = seg["root"]
    if extended:
        scale = set(theory.scale_pcs(KEY["key"])) if KEY["key"] else None
        for options in (((root + 10) % 12, (root + 11) % 12), ((root + 2) % 12, (root + 1) % 12)):
            pick = next((pc for pc in options if scale is None or pc in scale), None)
            if pick is not None and pick not in pcs:
                pcs.append(pick)
    return pcs, root


def voicing(pcs, root, lo, hi, prev=None, size=4, top=None, drop_root=True):
    """A close voicing of `size` notes between lo..hi. With prev: least movement (voice leading). With top: that pitch is
    the top voice (melody on top). drop_root: the bass/left hand has the root, so the right hand can leave it out."""
    tones = [pc for pc in pcs if not (drop_root and pc == root and len(pcs) > 3)]
    cands = []
    for start in range(lo, hi - 6):
        if start % 12 not in tones:
            continue
        v, need, p = [start], [pc for pc in tones if pc != start % 12], start
        while len(v) < size and p < hi:
            p += 1
            if p % 12 in need:
                v.append(p)
                need.remove(p % 12)
            elif not need and p % 12 in tones and p - v[-1] >= 3:
                v.append(p)
        if len(v) >= min(size, 3) and v[-1] <= hi:
            cands.append(v)
    if top is not None:
        cands = [c for c in cands if abs(c[-1] - top) <= 2] or cands
    if not cands:
        return theory.voice_chord(pcs, (lo + hi) // 2, prev)
    if prev:
        return min(cands, key=lambda v: sum(min(abs(a - b) for b in prev) for a in v) + 0.2 * abs(v[-1] - prev[-1]))
    return min(cands, key=lambda v: abs(sum(v) / len(v) - (lo + hi) / 2))


def _bars_of(harmony, bars):
    for seg in harmony:
        yield seg


def write_piano(harmony, bars, genre=None, seed=0, lead=None, comp=None):
    """Two hands: left hand root (+ octave) low, right hand a 3-4 note voicing, in the style's comping rhythm.
    If a lead is given, its strong-beat notes sit on top of the right-hand voicing (melody on top)."""
    rnd = random.Random(seed + 11)
    pattern = COMP[comp or STYLE_COMP.get(genre or "", "half")]
    ext = (genre or "") in EXTENDED
    notes, prev = [], None
    for seg in harmony:
        pcs, root = chord_pcs(seg, ext)
        lh = theory.nearest_pitch(43, {seg["bass"]}, 36, 50)
        t0, end = seg["start"], seg["start"] + seg["length"]
        bar_t = t0
        while bar_t < end - 1e-6:
            for st, ln in pattern:
                s = bar_t + st / 4.0
                if s >= end - 1e-6:
                    continue
                L = min(ln / 4.0, end - s)
                top = None
                if lead:
                    on = [n for n in lead if abs(n["start"] - s) < 0.13]
                    top = max(on, key=lambda n: n["pitch"])["pitch"] if on else None
                rh = voicing(pcs, root, 55, 79, prev, size=4 if ext else 3, top=top)
                prev = rh
                vel = 92 if st == 0 else 80
                if st == 0 or len(pattern) <= 2:
                    notes.append(_note(lh, s, L * 0.98, vel + 4))
                    if rnd.random() < 0.6:
                        notes.append(_note(lh + 12, s, L * 0.98, vel - 8))   # octave in the left hand
                for p in rh:
                    notes.append(_note(p, s, L * 0.96, vel))
            bar_t += 4
    return theory.dedupe(notes)


def write_keys(harmony, bars, genre=None, seed=0, comp=None, rootless=True):
    """Electric piano / keys: extended 4-5 note block chords (often rootless, the 808 has the root), syncopated."""
    pattern = COMP[comp or STYLE_COMP.get(genre or "", "plugg")]
    notes, prev = [], None
    for seg in harmony:
        pcs, root = chord_pcs(seg, True)
        t0, end = seg["start"], seg["start"] + seg["length"]
        bar_t = t0
        while bar_t < end - 1e-6:
            for k, (st, ln) in enumerate(pattern):
                s = bar_t + st / 4.0
                if s >= end - 1e-6:
                    continue
                v = voicing(pcs, root, 53, 77, prev, size=4, drop_root=rootless)
                prev = v
                for p in v:
                    notes.append(_note(p, s, min(ln / 4.0, end - s) * 0.95, 84 if k == 0 else 74))
            bar_t += 4
    return theory.dedupe(notes)


def write_pad(harmony, bars, genre=None, seed=0, wide=True):
    """Pad: whole-chord sustains, 4-5 notes, wide (root low, the rest spread above), smooth voice leading."""
    notes, prev = [], None
    for seg in harmony:
        pcs, root = chord_pcs(seg, (genre or "") in EXTENDED)
        low = theory.nearest_pitch(50, {root}, 45, 56)
        upper = voicing(pcs, root, 58, 82, prev, size=4)
        prev = upper
        for p in ([low] if wide else []) + upper:
            notes.append(_note(p, seg["start"], seg["length"] * 0.99, 70))
    return theory.dedupe(notes)


def write_strings(harmony, bars, genre=None, seed=0):
    """String section: cellos on the root (low), violas/violins on 3rd/5th/7th in open voicing, long legato notes."""
    notes, prev = [], None
    for seg in harmony:
        pcs, root = chord_pcs(seg, False)
        cello = theory.nearest_pitch(43, {root}, 36, 50)
        upper = voicing(pcs, root, 57, 81, prev, size=3)
        prev = upper
        spread = [upper[0] - 12 if upper[0] - 12 > cello + 4 else upper[0]] + upper[1:]
        for p in [cello] + spread:
            notes.append(_note(p, seg["start"], seg["length"] * 0.99, 72))
    return theory.dedupe(notes)


def write_choir(harmony, bars, genre=None, seed=0):
    """Choir: root, fifth, octave and third in the vocal range, sustained ('ahh')."""
    notes, prev = [], None
    for seg in harmony:
        pcs, root = chord_pcs(seg, False)
        v = voicing(pcs, root, 55, 76, prev, size=4, drop_root=False)
        prev = v
        for p in v:
            notes.append(_note(p, seg["start"], seg["length"] * 0.99, 68))
    return theory.dedupe(notes)


GUITAR_PICKS = [[0, 2, 1, 3, 2, 3, 1, 2], [0, 1, 2, 3, 2, 1, 2, 3], [0, 2, 3, 2, 1, 2, 3, 2]]


def write_guitar(harmony, bars, genre=None, seed=0):
    """Fingerpicked guitar: bass note on the beat, then the upper chord tones picked in 8ths (p-i-m-a patterns)."""
    rnd = random.Random(seed + 21)
    pick = rnd.choice(GUITAR_PICKS)
    notes, prev = [], None
    for seg in harmony:
        pcs, root = chord_pcs(seg, (genre or "") in EXTENDED)
        bass = theory.nearest_pitch(45, {seg["bass"]}, 40, 52)
        shape = voicing(pcs, root, 55, 74, prev, size=3)
        prev = shape
        strings = [bass] + shape
        t, end, i = seg["start"], seg["start"] + seg["length"], 0
        while t < end - 1e-6:
            p = strings[pick[i % len(pick)] % len(strings)]
            notes.append(_note(p, t, 0.75, 86 if i % 4 == 0 else 72))   # let notes ring over each other
            t += 0.5
            i += 1
    return theory.dedupe(notes)


def write_arp(harmony, bars, genre=None, seed=0, rate=None, center=67):
    """Arp synth: chord tones up/down in 16ths (rage, plugg) or 8ths."""
    rate = rate or (0.25 if genre in ("rage", "melodic plugg", "pop") else 0.5)
    notes, prev = [], None
    for seg in harmony:
        pcs, root = chord_pcs(seg, (genre or "") in EXTENDED)
        v = voicing(pcs, root, center - 7, center + 12, prev, size=4, drop_root=False)
        prev = v
        seq = v + [v[0] + 12] + v[-2:0:-1]
        t, i = seg["start"], 0
        while t < seg["start"] + seg["length"] - 1e-6:
            notes.append(_note(seq[i % len(seq)], t, rate * 0.85, 86 - (6 if i % 2 else 0)))
            t += rate
            i += 1
    return theory.dedupe(notes)


def write_supersaw(harmony, bars, genre=None, seed=0):
    """Rage supersaw: big sustained chords (root, fifth, octave, third on top) re-struck each beat."""
    notes = []
    for seg in harmony:
        pcs, root = chord_pcs(seg, False)
        r = theory.nearest_pitch(57, {root}, 52, 63)
        fifth = r + 7
        third = theory.nearest_pitch(r + 15, set(pcs) - {root, (root + 7) % 12} or set(pcs), r + 12, r + 17)
        t = seg["start"]
        while t < seg["start"] + seg["length"] - 1e-6:
            for p in (r, fifth, r + 12, third):
                notes.append(_note(p, t, 0.9, 96))
            t += 1.0
    return theory.dedupe(notes)


def harmonize_lead(lead, key, harmony, mode="thirds"):
    """Add a harmony voice under a lead (bells/keys players double hooks in 3rds or 6ths below), chord-aware."""
    out = []
    for n in lead:
        if n["length"] < 0.25 - 1e-6:
            continue
        step = -2 if mode == "thirds" else -5
        p = theory.scale_step(n["pitch"], step, key)
        ch = theory.chord_at(harmony, n["start"])
        if ch and p % 12 not in ch["pcs"]:
            p = theory.nearest_pitch(p, set(ch["pcs"]), n["pitch"] - 9, n["pitch"] - 2)
        out.append(dict(n, pitch=p, velocity=max(1, n["velocity"] - 12)))
    return out


REGISTER = {"bell": 79, "music_box": 84, "pluck": 64, "flute": 74, "lead_synth": 72, "piano": 72, "keys": 72, "rhodes": 72,
            "brass": 67, "vox": 72, "strings": 67, "choir": 64, "guitar": 64, "arp_synth": 64, "supersaw": 67, "organ": 67}


def to_register(notes, instrument):
    """Shift a line by octaves so its middle sits where the instrument sounds best (keeps the key and the shape)."""
    if not notes or instrument not in REGISTER:
        return notes
    mid = theory.median_pitch(notes)
    shift = 12 * round((REGISTER[instrument] - mid) / 12.0)
    if shift and all(36 <= n["pitch"] + shift <= 108 for n in notes):
        return [dict(n, pitch=n["pitch"] + shift) for n in notes]
    return notes


def write_for(instrument, job, key, harmony, bars, genre=None, lead=None, kick_steps=None, feel=None, seed=0):
    """Notes for one layer: an instrument doing a job."""
    f = theory.feel_of(feel)
    KEY["key"] = key
    if job == "bass" or instrument == "bass_808":
        return theory.generate_layer("bass", key, harmony, bars, kick_steps=kick_steps, feel=f, genre=genre, seed=seed)
    if job == "chords":
        if instrument == "piano":
            return write_piano(harmony, bars, genre, seed, lead=lead)
        if instrument in ("keys", "rhodes", "organ", "pluck"):
            return write_keys(harmony, bars, genre, seed, comp="stab" if instrument == "pluck" else None)
        if instrument == "guitar":
            return write_guitar(harmony, bars, genre, seed)
        if instrument == "supersaw":
            return write_supersaw(harmony, bars, genre, seed)
        if instrument == "strings":
            return write_strings(harmony, bars, genre, seed)
        if instrument == "choir":
            return write_choir(harmony, bars, genre, seed)
        return write_pad(harmony, bars, genre, seed)
    if job == "pad":
        if instrument == "strings":
            return write_strings(harmony, bars, genre, seed)
        if instrument == "choir":
            return write_choir(harmony, bars, genre, seed)
        return write_pad(harmony, bars, genre, seed)
    if job == "arp":
        if instrument == "guitar":
            return write_guitar(harmony, bars, genre, seed)
        return write_arp(harmony, bars, genre, seed, center=REGISTER.get(instrument, 64))
    if job == "lead":
        notes = to_register(theory.compose_lead(key, harmony, bars, feel=f, genre=genre, seed=seed), instrument)
        if instrument in ("piano", "bell", "keys", "rhodes", "music_box"):   # polyphonic leads: hook doubled in 3rds
            notes = theory.dedupe(notes + harmonize_lead(notes, key, harmony))
        return notes
    if job == "double" and lead:
        return theory.gen_double(lead, 12)
    if job == "sparkle" and lead:
        return [dict(n, pitch=n["pitch"] + 12, velocity=max(1, n["velocity"] - 22)) for n in lead
                if int(n["start"] // 4) % 2 == 1 and n["pitch"] + 12 <= 108]
    if job == "counter":
        if instrument in ("choir", "strings"):
            return write_choir(harmony, bars, genre, seed) if instrument == "choir" else write_strings(harmony, bars, genre, seed)
        return to_register(theory.gen_counter(lead or [], key, harmony, bars, center=REGISTER.get(instrument, 64), seed=seed,
                                              density=f["fullness"]), instrument)
    return theory.generate_layer("lead", key, harmony, bars, feel=f, genre=genre, seed=seed)


def polyphony(notes):
    """Average number of notes sounding together at each onset (1.0 = single notes only)."""
    if not notes:
        return 0
    by = {}
    for n in notes:
        by.setdefault(round(n["start"], 3), 0)
        by[round(n["start"], 3)] += 1
    return sum(by.values()) / len(by)


def thicken(notes, key, harmony, instrument, genre=None):
    """The AI wrote a chord instrument as single notes: keep its rhythm, play the full chord at every onset
    (its note becomes the top voice)."""
    KEY["key"] = key
    ext = (genre or "") in EXTENDED or instrument in ("keys", "rhodes")
    out, prev = [], None
    onsets = {}
    for n in notes:
        onsets.setdefault(round(n["start"], 4), []).append(n)
    for st in sorted(onsets):
        group = onsets[st]
        top = max(group, key=lambda n: n["pitch"])
        seg = theory.chord_at(harmony, st)
        if not seg:
            out += group
            continue
        pcs, root = chord_pcs(seg, ext)
        lo, hi = (53, 79) if instrument not in ("pad", "strings", "choir") else (50, 82)
        top_p = top["pitch"] if lo + 6 <= top["pitch"] <= hi else None
        v = voicing(pcs, root, lo, hi, prev, size=4 if ext else 3, top=top_p)
        prev = v
        out += [dict(top, pitch=p) for p in v]
        if instrument == "piano":
            out.append(dict(top, pitch=theory.nearest_pitch(43, {seg["bass"]}, 36, 50)))
    return theory.dedupe(out)


def _norm_channel(t):
    import re
    t = (t or "").lower().replace("#", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def parse_channel_roles(text, channels):
    """Read 'Zenology is a piano sound, Zenology 2 is a string, ...' -> {"ZENOLOGY": "piano", "ZENOLOGY #2": "strings"}.
    Matches the user's words to Channel Rack names (case, '#' and spacing don't matter; 'Zenology' alone means the
    channel without a number)."""
    import re
    names = {_norm_channel(c["name"]): c["name"] for c in channels or []}
    out = {}
    for m in re.finditer(r"([A-Za-z0-9 #._'-]{2,40}?)\s+(?:is|=|as|will be|plays|for)\s+(?:a|an|the|my)?\s*([a-z0-9 ._-]{2,30})", text or "", re.I):
        who, what = _norm_channel(m.group(1)), m.group(2).lower()
        inst = instrument_from_name(what) or {"string": "strings", "synth lead": "lead_synth", "lead": "lead_synth"}.get(what.split()[0])
        if not inst:
            continue
        cand = [full for n, full in names.items() if n == who or n.endswith(" " + who) or who.endswith(" " + n) or who == n.replace(" ", "")]
        if not cand:   # "zenology 2" vs "ZENOLOGY #2": compare words and number
            wn = who.split()
            cand = [full for n, full in names.items() if n.split() == wn or (len(wn) >= 1 and n.split()[:len(wn)] == wn and len(n.split()) == len(wn))]
        if len(cand) == 1:
            out[cand[0]] = inst
    return out


SOUND_TIPS = {
    "piano": "ZENOLOGY: search “Piano”, or FL Keys (stock)", "keys": "ZENOLOGY: “E.Piano”, or FL Keys", "rhodes": "ZENOLOGY: “E.Piano”/“Rhodes”, or FL Keys",
    "pad": "ZENOLOGY or FLEX: search “Pad”", "strings": "ZENOLOGY: “Strings”, or FLEX: “Strings”", "choir": "ZENOLOGY: “Choir”/“Vox”",
    "guitar": "ZENOLOGY: “Guitar”/“Nylon”", "bell": "ZENOLOGY: “Bell”, FLEX: “Bell”, or Fruity DX10", "pluck": "FLEX or ZENOLOGY: “Pluck”",
    "lead_synth": "FLEX: “Lead”, ZENOLOGY: “Lead”, or 3x Osc", "arp_synth": "FLEX: “Arp”/“Pluck”", "flute": "ZENOLOGY: “Flute”",
    "brass": "ZENOLOGY: “Brass”", "organ": "ZENOLOGY: “Organ”", "supersaw": "FLEX or ZENOLOGY: “Saw”/“Supersaw”",
    "music_box": "ZENOLOGY: “Music Box”/“Celesta”", "vox": "ZENOLOGY: “Vox”", "bass_808": "an 808 sample from your kit",
}
