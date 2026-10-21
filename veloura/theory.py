"""Music theory engine: keys, chords, progressions, voicing, layering, melody writing and validation.

Everything here is deterministic and pure (no FL access). Veloura uses it to:
  * understand the harmony of a beat (chords per bar, from the AI or from a genre progression),
  * generate supporting layers that fit the lead and the chords (pads, stabs, counter-melodies, doubles,
    harmonies, arps, 808 lines locked to the kick),
  * write memorable motif-based leads offline,
  * check and repair what the AI writes: wrong notes vs deliberate tension, bass against the chords,
    clashes between layers, layers fighting for the same register, too many notes, awkward leaps,
  * apply the "feel" controls (simple-complex, repetitive-varied, sparse-full, smooth-angular,
    melodic-atmospheric, familiar-experimental) to the actual notes.

Notes use the melody_plan convention: {"pitch", "start" (beats), "length" (beats), "velocity"}.
"""

import random
import re

PC = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8,
      "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11, "CB": 11, "E#": 5, "FB": 4, "B#": 0}
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

SCALES = {
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic minor": [0, 2, 3, 5, 7, 8, 11],
    "melodic minor": [0, 2, 3, 5, 7, 9, 11],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
    "minor pentatonic": [0, 3, 5, 7, 10],
    "major pentatonic": [0, 2, 4, 7, 9],
}
MODE_ALIASES = {"min": "minor", "m": "minor", "maj": "major", "aeolian": "minor", "ionian": "major",
                "harm minor": "harmonic minor", "": "minor"}

QUALITIES = {  # intervals above the root
    "maj": [0, 4, 7], "min": [0, 3, 7], "dim": [0, 3, 6], "aug": [0, 4, 8], "sus2": [0, 2, 7], "sus4": [0, 5, 7],
    "5": [0, 7], "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10], "7": [0, 4, 7, 10], "dim7": [0, 3, 6, 9],
    "m7b5": [0, 3, 6, 10], "minmaj7": [0, 3, 7, 11], "add9": [0, 4, 7, 14], "madd9": [0, 3, 7, 14],
    "maj9": [0, 4, 7, 11, 14], "min9": [0, 3, 7, 10, 14], "9": [0, 4, 7, 10, 14], "6": [0, 4, 7, 9], "min6": [0, 3, 7, 9],
    "min11": [0, 3, 7, 10, 14, 17], "7b9": [0, 4, 7, 10, 13],
}
QUALITY_ALIASES = [  # longest first
    ("7b9", "7b9"),
    ("minmaj7", "minmaj7"), ("mmaj7", "minmaj7"), ("maj9", "maj9"), ("maj7", "maj7"), ("M7", "maj7"), ("min11", "min11"),
    ("m11", "min11"), ("min9", "min9"), ("m9", "min9"), ("min7", "min7"), ("m7b5", "m7b5"), ("ø", "m7b5"),
    ("m7", "min7"), ("min6", "min6"), ("m6", "min6"), ("madd9", "madd9"), ("add9", "add9"), ("dim7", "dim7"),
    ("dim", "dim"), ("°", "dim"), ("aug", "aug"), ("+", "aug"), ("sus2", "sus2"), ("sus4", "sus4"), ("sus", "sus4"),
    ("min", "min"), ("m", "min"), ("maj", "maj"), ("9", "9"), ("7", "7"), ("6", "6"), ("5", "5"), ("", "maj"),
]

# Idiomatic progressions (scale degrees 0-6; "q" overrides the diatonic quality where the style needs it).
GENRE_PROGRESSIONS = {
    "trap": [[0, 5, 2, 6], [0, 3, 5, 4], [0, 5, 0, 4], [0, 6, 5, 6]],
    "dark trap": [[0, 1, 0, 4], [0, 5, 4, 0], [0, 0, 5, 4]],
    "plugg": [[3, 2, 5, 4], [1, 4, 0, 0], [3, 4, 2, 5], [0, 5, 3, 4]],
    "rage": [[0, 5, 0, 5], [0, 3, 0, 3], [0, 5, 3, 4]],
    "jerk": [[0, 4, 0, 4], [0, 3, 0, 3], [0, 5, 3, 4]],
    "drill": [[0, 0, 5, 4], [0, 5, 3, 4], [0, 1, 0, 4]],
    "melodic trap": [[0, 5, 2, 6], [0, 3, 6, 2], [5, 3, 0, 4]],
    "melodic rap": [[0, 5, 2, 6], [0, 3, 6, 2], [5, 3, 0, 4]],
    "cloud rap": [[0, 3, 0, 3], [3, 2, 1, 4], [0, 5, 3, 3]],
    "ambient": [[0, 3, 0, 3], [0, 5, 3, 3], [3, 0, 5, 0]],
    "boom bap": [[1, 4, 0, 0], [0, 3, 1, 4], [0, 5, 1, 4]],
    "r&b": [[3, 2, 5, 1], [1, 4, 0, 5], [3, 4, 2, 5]],
    "detroit": [[0, 0, 5, 4], [0, 1, 0, 1], [0, 5, 0, 4]],
    "pop": [[0, 4, 5, 3], [5, 3, 0, 4], [0, 5, 3, 4]],
}
GENRE_SEVENTHS = {"plugg", "r&b", "cloud rap", "boom bap", "melodic trap", "melodic rap", "ambient"}

DEFAULT_FEEL = {"complexity": 50, "variation": 50, "fullness": 50, "angular": 35, "atmosphere": 40, "experimental": 20}
FEEL_LABELS = [("complexity", "Simple", "Complex"), ("variation", "Repetitive", "Varied"), ("fullness", "Sparse", "Full"),
               ("angular", "Smooth", "Angular"), ("atmosphere", "Melodic", "Atmospheric"),
               ("experimental", "Familiar", "Experimental")]

ROLE_PRIORITY = {"lead": 0, "melody": 0, "bass": 1, "chords": 2, "pad": 2, "counter": 3, "harmony": 3, "double": 4,
                 "arp": 3, "bell": 3, "other": 5}
EPS = 1e-6


def feel_of(feel):
    out = dict(DEFAULT_FEEL)
    for k, v in (feel or {}).items():
        if k in out and isinstance(v, (int, float)):
            out[k] = max(0, min(100, float(v)))
    return out


# ---------------------------------------------------------------- keys and chords

def _pc(letter, accidental):
    acc = {"#": "#", "♯": "#", "b": "B", "♭": "B"}.get(accidental or "", "")
    return PC.get(letter.upper() + acc)


def parse_key(label):
    """'F minor', 'C# min', 'Bbm', 'E phrygian', 'A' -> (tonic_pc, mode). None if unreadable."""
    if not isinstance(label, str):
        return None
    m = re.match(r"\s*([A-Ga-g])\s*([#b♯♭]?)\s*(.*)$", label)
    if not m:
        return None
    pc = _pc(m.group(1), m.group(2))
    mode = m.group(3).strip().lower()
    mode = MODE_ALIASES.get(mode, mode)
    if mode not in SCALES:
        mode = "minor" if mode.startswith("min") else "major" if mode.startswith("maj") else None
    if pc is None or mode is None:
        return None
    return pc, mode


def key_label(pc, mode):
    names = SHARP if mode in ("major", "lydian", "mixolydian", "major pentatonic") and pc in (7, 2, 9, 4, 11, 6) else FLAT
    return "%s %s" % (names[pc % 12], mode)


def scale_pcs(key):
    pc, mode = key
    return [(pc + i) % 12 for i in SCALES[mode]]


def parse_chord(symbol):
    """'Cm7', 'Ab', 'F#dim', 'Bbsus4', 'Ebmaj7/G' -> {"symbol", "root", "quality", "pcs", "bass"} or None."""
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    s = symbol.strip()
    bass = None
    if "/" in s:
        s, b = s.split("/", 1)
        bm = re.match(r"([A-Ga-g])([#b]?)$", b.strip())
        if bm:
            bass = _pc(bm.group(1), bm.group(2))
    m = re.match(r"([A-Ga-g])([#b]?)(.*)$", s)
    if not m:
        return None
    root = _pc(m.group(1), m.group(2))
    if root is None:
        return None
    rest = m.group(3).strip()
    quality = None
    for alias, q in QUALITY_ALIASES:
        if rest == alias or (alias and rest.lower() == alias.lower() and alias not in ("M7",)):
            quality = q
            break
    if quality is None:
        for alias, q in QUALITY_ALIASES:
            if alias and rest.startswith(alias):
                quality = q
                break
    quality = quality or "maj"
    pcs = sorted({(root + i) % 12 for i in QUALITIES[quality]})
    if bass is not None and bass not in pcs:
        pcs = sorted(set(pcs) | {bass})
    return {"symbol": symbol.strip(), "root": root, "quality": quality, "pcs": pcs,
            "bass": bass if bass is not None else root}


def degree_chord(key, degree, seventh=False):
    """Diatonic chord on a scale degree (0-based) of a 7-note key."""
    pc, mode = key
    sc = SCALES[mode] if len(SCALES[mode]) == 7 else SCALES["minor" if "minor" in mode else "major"]
    d = degree % 7
    tones = [sc[(d + k) % 7] + 12 * ((d + k) // 7) for k in (0, 2, 4, 6)]
    root = (pc + tones[0]) % 12
    ints = [t - tones[0] for t in tones]
    third, fifth, sev = ints[1], ints[2], ints[3]
    q = {(4, 7): "maj", (3, 7): "min", (3, 6): "dim", (4, 8): "aug"}.get((third, fifth), "maj")
    if seventh:
        q = {("maj", 11): "maj7", ("maj", 10): "7", ("min", 10): "min7", ("min", 11): "minmaj7", ("dim", 10): "m7b5",
             ("dim", 9): "dim7"}.get((q, sev), q)
    name = (FLAT[root]) + {"maj": "", "min": "m", "dim": "dim", "aug": "aug", "maj7": "maj7", "7": "7", "min7": "m7",
                           "minmaj7": "mMaj7", "m7b5": "m7b5", "dim7": "dim7"}[q]
    return parse_chord(name) or {"symbol": name, "root": root, "quality": q,
                                 "pcs": sorted({(root + i) % 12 for i in QUALITIES[q]}), "bass": root}


def genre_harmony(key, bars, genre=None, seed=0, sevenths=None):
    """A bar-by-bar progression that suits the genre: [{"start", "length", "symbol", "root", "pcs", ...}]."""
    rnd = random.Random(seed * 31 + 7)
    choices = GENRE_PROGRESSIONS.get(genre or "", GENRE_PROGRESSIONS["trap"])
    prog = rnd.choice(choices)
    if key[1] in ("major", "lydian", "mixolydian", "major pentatonic") and genre in (None, "trap", "drill", "rage", "detroit", "dark trap"):
        prog = rnd.choice(GENRE_PROGRESSIONS["pop"])
    use7 = (genre in GENRE_SEVENTHS) if sevenths is None else sevenths
    seg = 1 if bars >= 4 else 0.5
    out = []
    t, i = 0.0, 0
    while t < bars * 4 - EPS:
        deg = prog[i % len(prog)]
        ch = degree_chord(key, deg, seventh=use7)
        if key[1] == "harmonic minor" or (genre in ("trap", "drill", "dark trap") and deg == 4 and "minor" in key[1]):
            if deg == 4:  # harmonic-minor V for tension
                root = (key[0] + 7) % 12
                ch = parse_chord(FLAT[root] + ("7" if use7 else ""))
        length = 4.0 * seg if bars >= 4 else 2.0
        out.append(dict(ch, start=t, length=length))
        t += length
        i += 1
    return out


def harmony_from_symbols(chords, bars):
    """AI chords [{"bar": 1-based, "beat": 1-based, "symbol"}] -> harmony segments covering the loop."""
    pts = []
    for c in chords or []:
        try:
            bar = int(c.get("bar", 1))
            beat = float(c.get("beat", 1) or 1)
        except (TypeError, ValueError):
            continue
        ch = parse_chord(c.get("symbol"))
        if ch and 1 <= bar <= bars and 1 <= beat < 5:
            pts.append(((bar - 1) * 4 + beat - 1, ch))
    pts.sort(key=lambda p: p[0])
    out = []
    for i, (t, ch) in enumerate(pts):
        end = pts[i + 1][0] if i + 1 < len(pts) else bars * 4
        if end - t > EPS:
            out.append(dict(ch, start=t, length=end - t))
    if out and out[0]["start"] > EPS:  # nothing at the top: extend the first chord back
        out[0]["length"] += out[0]["start"]
        out[0]["start"] = 0.0
    return out


def chord_at(harmony, t):
    for seg in harmony or []:
        if seg["start"] - EPS <= t < seg["start"] + seg["length"] - EPS:
            return seg
    return harmony[-1] if harmony else None


def harmony_symbols(harmony):
    return [{"bar": int(s["start"] // 4) + 1, "beat": round(s["start"] % 4 + 1, 3), "symbol": s["symbol"]} for s in harmony or []]


# ---------------------------------------------------------------- pitch helpers

def nearest_pitch(target, pcs, lo=0, hi=127, prefer_down=False):
    """The pitch with one of these pitch classes closest to target, inside lo..hi when possible (never a note outside
    the pitch classes: if the range is too narrow it widens instead of returning a wrong note)."""
    pcs = set(pcs)
    for a, b in ((lo, hi), (lo - 12, hi + 12), (0, 127)):
        best = None
        for p in range(max(0, a), min(127, b) + 1):
            if p % 12 in pcs:
                d = abs(p - target) + (0.1 if (p > target) == prefer_down else 0)
                if best is None or d < best[0]:
                    best = (d, p)
        if best:
            return best[1]
    return max(0, min(127, target))


def scale_step(pitch, steps, key):
    """Move a pitch by `steps` scale degrees (pitch snapped to the scale first)."""
    pcs = scale_pcs(key)
    p = nearest_pitch(pitch, pcs)
    direction = 1 if steps > 0 else -1
    for _ in range(abs(steps)):
        p += direction
        while p % 12 not in pcs:
            p += direction
    return p


def _overlap(a, b):
    return min(a["start"] + a["length"], b["start"] + b["length"]) - max(a["start"], b["start"])


def _strong(t):
    return abs((t * 2) - round(t * 2)) < EPS  # on an 8th-note position or stronger


def _beat(t):
    return abs(t - round(t)) < EPS


def median_pitch(notes):
    ps = sorted(n["pitch"] for n in notes)
    return ps[len(ps) // 2] if ps else None


# ---------------------------------------------------------------- analysis metrics

def in_key_ratio(notes, key, harmony=None):
    if not notes:
        return 1.0
    sc = set(scale_pcs(key))
    good = 0
    for n in notes:
        ch = chord_at(harmony, n["start"]) if harmony else None
        if n["pitch"] % 12 in sc or (ch and n["pitch"] % 12 in ch["pcs"]):
            good += 1
    return good / len(notes)


def clashes(parts_notes, harmony=None, min_overlap=0.5):
    """Sustained minor-2nd / minor-9th rubs between DIFFERENT parts (excluding tones both in the current chord).
    parts_notes: {name: notes}. Returns [(name_a, note_a, name_b, note_b)]."""
    out = []
    names = list(parts_notes)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for na in parts_notes[a]:
                for nb in parts_notes[b]:
                    if _overlap(na, nb) < min_overlap - EPS:
                        continue
                    iv = abs(na["pitch"] - nb["pitch"]) % 12
                    if iv not in (1, 11):
                        continue
                    ch = chord_at(harmony, max(na["start"], nb["start"])) if harmony else None
                    if ch and na["pitch"] % 12 in ch["pcs"] and nb["pitch"] % 12 in ch["pcs"]:
                        continue  # written into the chord (e.g. maj7): deliberate colour
                    out.append((a, na, b, nb))
    return out


def bar_similarity(notes, bar_a, bar_b):
    """0..1 how alike two bars are (onset + pitch-class match)."""
    def sig(bar):
        return {(round((n["start"] - bar * 4) * 4), n["pitch"] % 12) for n in notes if bar * 4 - EPS <= n["start"] < bar * 4 + 4 - EPS}
    a, b = sig(bar_a), sig(bar_b)
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def repetition_score(notes, bars):
    """Average similarity of each bar to the bar 2 or 4 before it (motif reuse), 0..1."""
    if bars < 2:
        return 1.0
    sims = []
    for b in range(1, bars):
        ref = b - 2 if b >= 2 else b - 1
        sims.append(bar_similarity(notes, b, ref))
    return sum(sims) / len(sims)


def density(notes, bars):
    return len(notes) / max(1, bars)


def register_overlap(a, b):
    """Fraction of the narrower part's range shared with the other part."""
    if not a or not b:
        return 0.0
    a_lo, a_hi = min(n["pitch"] for n in a), max(n["pitch"] for n in a)
    b_lo, b_hi = min(n["pitch"] for n in b), max(n["pitch"] for n in b)
    shared = min(a_hi, b_hi) - max(a_lo, b_lo)
    width = max(1, min(a_hi - a_lo, b_hi - b_lo))
    return max(0.0, shared / width) if shared > 0 else 0.0


def onset_overlap(a, b):
    sa = {round(n["start"] * 4) for n in a}
    sb = {round(n["start"] * 4) for n in b}
    return len(sa & sb) / max(1, min(len(sa), len(sb)))


def max_leap(notes):
    ns = sorted(notes, key=lambda n: (n["start"], -n["pitch"]))
    leaps = [abs(ns[i + 1]["pitch"] - ns[i]["pitch"]) for i in range(len(ns) - 1)]
    return max(leaps) if leaps else 0


def topline(notes):
    """The highest note at each onset (the melody a listener hears)."""
    by = {}
    for n in notes:
        k = round(n["start"], 6)
        if k not in by or n["pitch"] > by[k]["pitch"]:
            by[k] = n
    return [by[k] for k in sorted(by)]


# ---------------------------------------------------------------- refining (validation + repair)

def _is_passing(prev, n, nxt, key):
    """A short off-beat note moving by step between scale notes: a deliberate passing/neighbour tone."""
    if n["length"] > 0.5 + EPS or _beat(n["start"]):
        return False
    sc = set(scale_pcs(key))
    ok_prev = prev is not None and prev["pitch"] % 12 in sc and abs(prev["pitch"] - n["pitch"]) <= 2
    ok_next = nxt is not None and nxt["pitch"] % 12 in sc and abs(nxt["pitch"] - n["pitch"]) <= 2
    return ok_prev and ok_next


def fix_out_of_key(notes, key, harmony, feel, repairs, label):
    """Snap accidental wrong notes to the chord or scale; keep deliberate passing tones and chord tones."""
    f = feel_of(feel)
    sc = set(scale_pcs(key))
    ns = sorted(notes, key=lambda n: (n["start"], n["pitch"]))
    fixed = kept = 0
    for i, n in enumerate(ns):
        ch = chord_at(harmony, n["start"]) if harmony else None
        pcs_ok = sc | set(ch["pcs"] if ch else [])
        if n["pitch"] % 12 in pcs_ok:
            continue
        prev = ns[i - 1] if i else None
        nxt = ns[i + 1] if i + 1 < len(ns) else None
        if _is_passing(prev, n, nxt, key) or (f["experimental"] >= 75 and n["length"] <= 0.5 + EPS):
            kept += 1
            continue
        target = set(ch["pcs"]) if ch and n["length"] >= 1 - EPS else (set(ch["pcs"]) | sc if ch else sc)
        n["pitch"] = nearest_pitch(n["pitch"], target)
        fixed += 1
    if fixed:
        repairs.append("%s: %d wrong note%s moved into the key/chord" % (label, fixed, "" if fixed == 1 else "s"))
    if kept:
        repairs.append("%s: kept %d deliberate passing tone%s" % (label, kept, "" if kept == 1 else "s"))
    return ns


def fix_bass(notes, key, harmony, repairs, label, lo=31, hi=55):
    """The bass must support the chords: the first note under each chord is its root (or chord bass), others chord/scale tones."""
    if not harmony:
        return notes
    sc = set(scale_pcs(key))
    ns = sorted(notes, key=lambda n: (n["start"], n["pitch"]))
    fixed = moved = 0
    seen = set()
    for n in ns:
        if n["pitch"] < lo or n["pitch"] > hi:
            while n["pitch"] < lo:
                n["pitch"] += 12
            while n["pitch"] > hi:
                n["pitch"] -= 12
            moved += 1
        ch = chord_at(harmony, n["start"])
        if not ch:
            continue
        first = id(ch) not in seen
        seen.add(id(ch))
        if first or n["length"] >= 2 - EPS:
            want = {ch["bass"], ch["root"]} if first else set(ch["pcs"])
            if n["pitch"] % 12 not in want and not (not first and n["pitch"] % 12 in ch["pcs"]):
                n["pitch"] = nearest_pitch(n["pitch"], {ch["bass"]}, lo, hi)
                fixed += 1
        elif n["pitch"] % 12 not in sc and n["pitch"] % 12 not in ch["pcs"]:
            n["pitch"] = nearest_pitch(n["pitch"], set(ch["pcs"]), lo, hi)
            fixed += 1
    if fixed:
        repairs.append("%s: %d note%s set to the chord root so the low end supports the harmony" % (label, fixed, "" if fixed == 1 else "s"))
    if moved:
        repairs.append("%s: %d note%s moved into the 808 range" % (label, moved, "" if moved == 1 else "s"))
    return ns


def fix_clashes(layers, harmony, repairs):
    """layers: list of {"name", "role", "notes"}; lower-priority layers give way when two parts rub (m2/m9)."""
    by_name = {l["name"]: l for l in layers}
    fixed = {}
    for _ in range(3):
        found = clashes({l["name"]: l["notes"] for l in layers}, harmony)
        if not found:
            break
        for a, na, b, nb in found:
            pa, pb = ROLE_PRIORITY.get(by_name[a]["role"], 5), ROLE_PRIORITY.get(by_name[b]["role"], 5)
            loser_name, n, other = (b, nb, na) if pb >= pa else (a, na, nb)
            ch = chord_at(harmony, max(na["start"], nb["start"])) if harmony else None
            if ch:   # the note that isn't in the chord is the mistake, whoever plays it
                in_a, in_b = na["pitch"] % 12 in ch["pcs"], nb["pitch"] % 12 in ch["pcs"]
                if in_a and not in_b:
                    loser_name, n, other = b, nb, na
                elif in_b and not in_a:
                    loser_name, n, other = a, na, nb
            ch = chord_at(harmony, n["start"]) if harmony else None
            pcs = set(ch["pcs"]) if ch else {other["pitch"] % 12, (other["pitch"] + 7) % 12}
            cand = [p for p in range(n["pitch"] - 4, n["pitch"] + 5) if p % 12 in pcs and abs(p - other["pitch"]) % 12 not in (1, 11)]
            if cand:
                n["pitch"] = min(cand, key=lambda p: abs(p - n["pitch"]))
                fixed[loser_name] = fixed.get(loser_name, 0) + 1
    for name, k in fixed.items():
        repairs.append("%s: %d note%s nudged to stop rubbing against another layer" % (name, k, "" if k == 1 else "s"))


def separate_registers(layers, repairs):
    """Two non-doubling melodic layers in the same register with the same rhythm fight: move the lesser one an octave."""
    mel = [l for l in layers if l["role"] in ("lead", "melody", "counter", "chords", "pad", "arp", "bell", "other") and l["notes"]
           and l.get("purpose") not in ("double", "harmony")]
    mel.sort(key=lambda l: ROLE_PRIORITY.get(l["role"], 5))
    for i, a in enumerate(mel):
        for b in mel[i + 1:]:
            if register_overlap(a["notes"], b["notes"]) > 0.6 and onset_overlap(a["notes"], b["notes"]) > 0.55:
                ma, mb = median_pitch(a["notes"]), median_pitch(b["notes"])
                shift = -12 if mb <= ma else 12
                floor = 48 if b["role"] != "bass" else 24   # melodic layers never sink into the 808's range
                if all(floor <= n["pitch"] + shift <= 108 for n in b["notes"]):
                    for n in b["notes"]:
                        n["pitch"] += shift
                    repairs.append("%s: moved an octave %s so it doesn't fight %s" % (b["name"], "down" if shift < 0 else "up", a["name"]))


def thin(notes, max_per_bar, bars, repairs, label):
    """Too many notes: drop the weakest (off-beat, quiet, short) ones, keeping each bar's first note."""
    out = []
    removed = 0
    for bar in range(bars):
        bn = [n for n in notes if bar * 4 - EPS <= n["start"] < bar * 4 + 4 - EPS]
        if len(bn) <= max_per_bar:
            out += bn
            continue
        first = min(bn, key=lambda n: n["start"])
        rest = [n for n in bn if n is not first]
        rest.sort(key=lambda n: (_beat(n["start"]), _strong(n["start"]), n["velocity"], n["length"]), reverse=True)
        keep = [first] + rest[:max_per_bar - 1]
        removed += len(bn) - len(keep)
        out += keep
    if removed:
        repairs.append("%s: thinned %d notes to leave space" % (label, removed))
    return sorted(out, key=lambda n: (n["start"], n["pitch"]))


def smooth_leaps(notes, max_jump, repairs, label, lo=36, hi=96):
    ns = sorted(notes, key=lambda n: (n["start"], -n["pitch"]))
    folded = 0
    line = topline(ns)
    for i in range(1, len(line)):
        d = line[i]["pitch"] - line[i - 1]["pitch"]
        if abs(d) > max_jump:
            alt = line[i]["pitch"] - 12 if d > 0 else line[i]["pitch"] + 12
            if lo <= alt <= hi and abs(alt - line[i - 1]["pitch"]) < abs(d):
                line[i]["pitch"] = alt
                folded += 1
    if folded:
        repairs.append("%s: smoothed %d big leap%s" % (label, folded, "" if folded == 1 else "s"))
    return ns


def dedupe(notes):
    seen = {}
    for n in sorted(notes, key=lambda n: (n["start"], n["pitch"], -n["length"])):
        k = (round(n["start"], 6), n["pitch"])
        if k not in seen:
            seen[k] = n
    out = sorted(seen.values(), key=lambda n: (n["pitch"], n["start"]))
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        if a["pitch"] == b["pitch"] and a["start"] + a["length"] > b["start"] + EPS:
            a["length"] = round(max(1 / 96, b["start"] - a["start"]), 6)
    return sorted(out, key=lambda n: (n["start"], n["pitch"]))


def layer_role(part):
    """Map a Veloura part to a theory layer role."""
    purpose = (part.get("purpose") or "").lower()
    if part.get("role") == "bass":
        return "bass"
    if part.get("role") == "chords" or (part.get("instrument") in ("piano", "keys", "rhodes", "pad", "strings", "choir", "guitar",
                                                                  "organ", "supersaw", "brass") and purpose not in ("lead", "counter", "double")):
        return "pad" if part.get("instrument") in ("pad", "strings", "choir") else "chords"
    if purpose in ("counter", "harmony", "double", "arp", "pad", "bell", "chords", "lead"):
        return {"pad": "pad", "chords": "chords"}.get(purpose, purpose)
    if part.get("role") == "melody":
        return "lead"
    return "other"


def refine(parts, key, harmony, bars, feel=None, genre=None):
    """Validate and repair the pitched parts of a beat together. Mutates notes in place.
    parts: list of Veloura parts (dicts with "name", "role", "plan", optional "purpose"). Drums and samples are skipped.
    Returns {"repairs": [...], "report": {...}} (report = measurable facts for tests and the UI)."""
    f = feel_of(feel)
    repairs = []
    layers = []
    for p in parts:
        plan = p.get("plan") or {}
        if p.get("role") == "drums" or not plan.get("notes"):
            continue
        if p.get("role") == "other" and all(n["pitch"] == 60 for n in plan["notes"]) and len(plan["notes"]) <= bars:
            continue  # a sample trigger, not a melody
        role = layer_role(p)
        notes = plan["notes"]
        onsets = {}
        for n in notes:
            onsets[round(n["start"], 4)] = onsets.get(round(n["start"], 4), 0) + 1
        if role in ("counter", "other", "lead") and p.get("purpose") != "lead" and onsets and len(notes) / len(onsets) >= 2.5:
            role = "chords"   # it plays chords (e.g. stabs): never thin it into single notes
        if role == "bass":
            notes = fix_bass(notes, key, harmony, repairs, p["name"])
        else:
            notes = fix_out_of_key(notes, key, harmony, f, repairs, p["name"])
            if role in ("lead", "counter", "bell", "other", "arp"):
                cap = int(round(4 + f["fullness"] * 0.06 + f["complexity"] * 0.06))   # ~4..16 notes a bar
                if role == "counter":
                    cap = max(3, cap // 2)
                notes = thin(notes, cap, bars, repairs, p["name"])
                if f["angular"] < 50:
                    notes = smooth_leaps(notes, 7 if f["angular"] < 25 else 9, repairs, p["name"])
        plan["notes"] = dedupe(notes)
        layers.append({"name": p["name"], "role": role, "purpose": p.get("purpose") if role not in ("chords", "pad") else "harmony",
                       "notes": plan["notes"]})
    separate_registers(layers, repairs)
    fix_clashes(layers, harmony, repairs)
    for l in layers:
        l["notes"][:] = dedupe(l["notes"])
    report = {
        "in_key": {l["name"]: round(in_key_ratio(l["notes"], key, harmony), 3) for l in layers},
        "clashes": len(clashes({l["name"]: l["notes"] for l in layers}, harmony)),
        "repetition": {l["name"]: round(repetition_score(l["notes"], bars), 2) for l in layers if l["role"] in ("lead", "counter")},
    }
    return {"repairs": repairs, "report": report}


# ---------------------------------------------------------------- generating layers

def voice_chord(pcs, center=62, prev=None, size=None):
    """Voice a chord near `center`; with `prev`, pick the voicing that moves the least (voice leading)."""
    pcs = list(pcs)
    size = size or min(4, max(3, len(pcs)))
    cands = []
    for lowest in range(center - 9, center + 4):
        if lowest % 12 not in pcs:
            continue
        v = [lowest]
        need = [pc for pc in pcs if pc != lowest % 12]
        p = lowest
        while need and len(v) < size:
            p += 1
            if p % 12 in need:
                v.append(p)
                need.remove(p % 12)
        while len(v) < size:
            v.append(v[len(v) - 3] + 12 if len(v) >= 3 else v[-1] + 12)
        cands.append(v)
    if not cands:
        return [center]
    if prev:
        return min(cands, key=lambda v: sum(min(abs(a - b) for b in prev) for a in v) + 0.1 * abs(sum(v) / len(v) - center))
    return min(cands, key=lambda v: abs(sum(v) / len(v) - center))


def gen_chords(harmony, bars, style="sustain", center=62, velocity=78, seed=0):
    """Pad / keys / stabs from the harmony, with voice leading."""
    rnd = random.Random(seed + 101)
    notes, prev = [], None
    for seg in harmony:
        v = voice_chord(seg["pcs"], center, prev)
        prev = v
        if style == "sustain":
            hits = [(seg["start"], seg["length"])]
        elif style == "stabs":
            pattern = rnd.choice([[0, 1.5, 3], [0, 0.75, 2.5], [0, 2, 3.5], [0.5, 2.5]])
            hits = [(seg["start"] + o, 0.5) for o in pattern if o < seg["length"] - EPS]
        else:  # "pulse": quarter notes
            hits = [(seg["start"] + o, 0.9) for o in range(int(seg["length"]))]
        for st, ln in hits:
            for p in v:
                notes.append({"pitch": p, "start": round(st, 6), "length": round(min(ln, seg["start"] + seg["length"] - st), 6),
                              "velocity": velocity})
    return notes


def gen_bass(harmony, bars, kick_steps=None, style="sustain", lo=34, seed=0, fullness=50):
    """808 / bass that supports the chords. With kick_steps (16th indices across the loop) the 808 locks to the kick."""
    rnd = random.Random(seed + 202)
    notes = []
    hi = lo + 18
    kicks = sorted(kick_steps or [])
    for seg in harmony:
        root = nearest_pitch(lo + 5, {seg["bass"]}, lo, hi)
        s0, s1 = int(round(seg["start"] * 4)), int(round((seg["start"] + seg["length"]) * 4))
        hits = [k for k in kicks if s0 <= k < s1]
        if not hits:
            hits = [s0] if style == "sustain" else [s0, s0 + 6, s0 + 10][:2 + (fullness > 60)]
        if hits[0] != s0 and (s0 not in kicks):
            hits = [s0] + hits if style != "choppy" else hits
        for i, h in enumerate(hits):
            end = hits[i + 1] if i + 1 < len(hits) else s1
            ln = (end - h) / 4.0
            if style == "choppy":
                ln = min(ln, 0.5)
            pitch = root
            if i and rnd.random() < (0.15 + fullness / 600.0):
                pitch = root + rnd.choice([7, 5, 7]) if root + 7 <= hi + 2 else root - 5   # move by a 5th/4th, not octaves
            notes.append({"pitch": pitch, "start": h / 4.0, "length": round(max(0.25, ln - 0.0), 6), "velocity": 110 if i == 0 else 100})
    return dedupe(notes)


def gen_double(lead, interval=12):
    return [dict(n, pitch=n["pitch"] + interval, velocity=max(1, n["velocity"] - 18)) for n in lead
            if 0 <= n["pitch"] + interval <= 127]


def gen_harmony_line(lead, key, harmony, below=True):
    """A third (diatonic) under the lead on its longer notes, adjusted to the chord."""
    out = []
    for n in lead:
        if n["length"] < 0.5 - EPS:
            continue
        p = scale_step(n["pitch"], -2 if below else 2, key)
        ch = chord_at(harmony, n["start"])
        if ch and p % 12 not in ch["pcs"]:
            alt = scale_step(n["pitch"], -3 if below else 3, key)
            p = alt if alt % 12 in ch["pcs"] else p
        out.append(dict(n, pitch=p, velocity=max(1, n["velocity"] - 14)))
    return out


def gen_counter(lead, key, harmony, bars, center=55, seed=0, density=50):
    """A counter-melody that answers in the gaps the lead leaves (call and response), in its own register."""
    rnd = random.Random(seed + 303)
    occupied = set()
    for n in lead:
        for s in range(int(round(n["start"] * 4)), int(round((n["start"] + n["length"]) * 4))):
            occupied.add(s)
    total = bars * 16
    out = []
    s = 0
    while s < total:
        if s in occupied:
            s += 1
            continue
        gap = 0
        while s + gap < total and (s + gap) not in occupied:
            gap += 1
        if gap >= 4:   # a beat or more of space: answer
            ch = chord_at(harmony, s / 4.0)
            pcs = ch["pcs"] if ch else scale_pcs(key)
            count = 2 if gap < 8 else (3 if density < 60 else 4)
            p = nearest_pitch(center + rnd.choice([-2, 0, 3]), set(pcs))
            pos = s + (1 if rnd.random() < 0.5 else 0)
            for k in range(count):
                if pos >= s + gap:
                    break
                ln = 2 if k < count - 1 else min(4, s + gap - pos)
                out.append({"pitch": p, "start": pos / 4.0, "length": max(1, ln) / 4.0, "velocity": 82 - 4 * k})
                p = scale_step(p, rnd.choice([-1, 1, 2, -2]), key)
                pos += ln
        s += max(gap, 1)
    if len(out) < bars:   # the lead leaves no gaps: sustain guide tones underneath instead of competing
        out, prev = [], None
        for seg in harmony or []:
            third = [pc for pc in seg["pcs"] if pc != seg["root"] and pc != (seg["root"] + 7) % 12] or seg["pcs"]
            p = nearest_pitch(prev if prev else center, set(third))
            prev = p
            out.append({"pitch": p, "start": seg["start"], "length": seg["length"], "velocity": 70})
    return dedupe(out)


def gen_arp(harmony, bars, rate=0.25, center=67, pattern="up", velocity=88):
    notes, prev = [], None
    for seg in harmony:
        v = voice_chord(seg["pcs"], center, prev, size=3)
        prev = v
        seq = v + [v[0] + 12] if pattern == "up" else v + v[-2:0:-1]
        t, i = seg["start"], 0
        while t < seg["start"] + seg["length"] - EPS:
            notes.append({"pitch": seq[i % len(seq)], "start": round(t, 6), "length": rate * 0.9, "velocity": velocity - (8 if i % 2 else 0)})
            t += rate
            i += 1
    return dedupe(notes)


def gen_bell(harmony, bars, center=79, seed=0):
    rnd = random.Random(seed + 404)
    notes = []
    for seg in harmony:
        for o in rnd.choice([[0, 1.5], [0.5, 2.5], [0, 2, 3.5], [1, 3]]):
            if o < seg["length"]:
                notes.append({"pitch": nearest_pitch(center + rnd.choice([-3, 0, 4]), set(seg["pcs"])), "start": seg["start"] + o,
                              "length": 0.5, "velocity": 76})
    return dedupe(notes)


# ---------------------------------------------------------------- writing a lead (motif development)

RHYTHM_VOCAB = {  # one-bar rhythms in 16ths: (start, length)
    "sparse": [[(0, 6), (8, 4), (12, 4)], [(0, 4), (6, 2), (10, 6)], [(2, 4), (8, 8)]],
    "medium": [[(0, 3), (3, 3), (6, 2), (8, 4), (12, 2), (14, 2)], [(0, 4), (4, 2), (6, 2), (8, 4), (12, 4)],
               [(0, 2), (3, 3), (6, 4), (10, 2), (12, 4)], [(0, 3), (3, 3), (8, 3), (11, 3), (14, 2)]],
    "busy": [[(0, 2), (2, 2), (4, 1), (5, 1), (6, 2), (8, 2), (10, 2), (12, 2), (14, 2)],
             [(0, 1), (1, 1), (2, 2), (4, 2), (6, 1), (7, 1), (8, 2), (10, 2), (12, 1), (13, 1), (14, 2)],
             [(0, 2), (2, 1), (3, 1), (4, 2), (6, 2), (8, 1), (9, 1), (10, 2), (12, 2), (14, 2)]],
}
GENRE_LEAD_REGISTER = {"plugg": 74, "rage": 67, "jerk": 72, "drill": 62, "trap": 69, "dark trap": 64, "melodic trap": 69,
                       "melodic rap": 69, "cloud rap": 74, "ambient": 72, "boom bap": 67, "r&b": 69, "detroit": 60, "pop": 69}


def compose_lead(key, harmony, bars, feel=None, genre=None, seed=0):
    """A motif-based lead: a 1-bar idea, repeated and developed (A A' A B / A A' A C), resolving at phrase ends."""
    f = feel_of(feel)
    rnd = random.Random(seed + 505)
    level = f["fullness"] * 0.5 + f["complexity"] * 0.5
    vocab = RHYTHM_VOCAB["sparse" if level < 35 else "busy" if level > 70 else "medium"]
    if f["atmosphere"] > 70:
        vocab = RHYTHM_VOCAB["sparse"]
    rhythm = list(rnd.choice(vocab))
    center = GENRE_LEAD_REGISTER.get(genre or "", 69)
    max_step = 2 if f["angular"] < 30 else 3 if f["angular"] < 65 else 5

    def contour(start_pitch, bar_t, length):
        ch = chord_at(harmony, bar_t)
        pcs = set(ch["pcs"]) if ch else set(scale_pcs(key))
        p = nearest_pitch(start_pitch, pcs)
        out = [p]
        for k in range(1, length):
            st = rhythm[k][0]
            strong = st % 4 == 0
            step = rnd.choice([-max_step, -1, -1, 1, 1, 2, max_step, 0] if f["angular"] >= 30 else [-1, -1, 1, 1, 2, -2, 0])
            q = scale_step(out[-1], step, key) if step else out[-1]
            if strong:
                chk = chord_at(harmony, bar_t + st / 4.0)
                q = nearest_pitch(q, set(chk["pcs"]) if chk else pcs)
            if q > center + 12 or q < center - 9:   # keep the range without leaving the key
                q = nearest_pitch(q, set(scale_pcs(key)), center - 9, center + 12)
            out.append(q)
        return out

    motif = contour(center + rnd.choice([-3, 0, 2, 4]), 0.0, len(rhythm))
    answer = contour(center + rnd.choice([2, 4, 5]), 8.0 if bars > 2 else 4.0, len(rhythm))
    var = f["variation"] / 100.0
    notes = []
    for bar in range(bars):
        pos = bar % 4
        t0 = bar * 4.0
        ch = chord_at(harmony, t0)
        if pos == 0 or (pos == 2 and var < 0.75):
            pitches = list(motif)
        elif pos == 1:
            pitches = list(motif)
            k = 1 + int(var * 3)              # vary the tail
            for i in range(len(pitches) - k, len(pitches)):
                pitches[i] = scale_step(pitches[i], rnd.choice([-2, -1, 1, 2]), key)
        elif pos == 2:
            pitches = [scale_step(p, 2, key) for p in motif]     # sequence the motif up a third
        else:
            pitches = list(answer) if var >= 0.25 else list(motif)
        if harmony:   # make the motif fit this bar's chord on strong beats
            for i, (st, _) in enumerate(rhythm):
                chk = chord_at(harmony, t0 + st / 4.0)
                if st % 8 == 0 and chk:
                    pitches[i] = nearest_pitch(pitches[i], set(chk["pcs"]))
        steps = list(rhythm)
        last_phrase_bar = pos == 3 or bar == bars - 1
        if last_phrase_bar:   # resolve: land on a stable tone and let it ring
            steps[-1] = (steps[-1][0], 16 - steps[-1][0])
            stable = {key[0], (key[0] + SCALES[key[1]][2 if len(SCALES[key[1]]) > 4 else 1]) % 12}
            if ch:
                stable = (stable & set(ch["pcs"])) or set(ch["pcs"])
            pitches[-1] = nearest_pitch(pitches[-1], stable)
        if bars >= 8 and bar >= bars // 2 and var > 0.6 and pos == 0:
            pitches = [p + (12 if p + 12 <= center + 15 else 0) if i == 0 else p for i, p in enumerate(pitches)]
        for (st, ln), p in zip(steps, pitches):
            vel = 104 if st in (0, 8) else 96 if st % 4 == 0 else rnd.choice([82, 86, 90])
            notes.append({"pitch": p, "start": t0 + st / 4.0, "length": ln / 4.0, "velocity": vel})
    if f["atmosphere"] > 60:   # legato: let notes sustain into the next
        notes.sort(key=lambda n: n["start"])
        for i in range(len(notes) - 1):
            notes[i]["length"] = max(notes[i]["length"], round(notes[i + 1]["start"] - notes[i]["start"], 6))
    if f["angular"] < 50:   # smooth: no big jumps between phrases either
        notes = smooth_leaps(notes, 7 if f["angular"] < 25 else 9, [], "lead")
    if f["experimental"] > 70:   # a chromatic neighbour or two
        for n in notes:
            if not _beat(n["start"]) and n["length"] <= 0.5 and rnd.random() < 0.12:
                n["pitch"] += rnd.choice([-1, 1])
    return dedupe(notes)


def generate_layer(kind, key, harmony, bars, lead=None, kick_steps=None, feel=None, genre=None, seed=0, register=None):
    """One supporting layer by its musical purpose."""
    f = feel_of(feel)
    center = {"low": 50, "mid": 62, "high": 74}.get(register or "", None)
    if kind in ("pad", "chords", "keys"):
        style = "sustain" if (kind == "pad" or f["atmosphere"] > 55) else ("stabs" if f["fullness"] > 45 else "sustain")
        return gen_chords(harmony, bars, style=style, center=center or (60 if kind == "pad" else 62), seed=seed,
                          velocity=70 if kind == "pad" else 82)
    if kind in ("bass", "808"):
        style = {"jerk": "choppy", "rage": "choppy", "detroit": "choppy"}.get(genre, "sustain" if f["fullness"] < 70 else "locked")
        return gen_bass(harmony, bars, kick_steps=kick_steps, style=style, seed=seed, fullness=f["fullness"])
    if kind == "double" and lead:
        return gen_double(lead, 12 if (register or "high") != "low" else -12)
    if kind == "harmony" and lead:
        return gen_harmony_line(lead, key, harmony)
    if kind == "counter":
        lead_c = median_pitch(lead) if lead else 69
        return gen_counter(lead or [], key, harmony, bars, center=center or (lead_c - 12 if lead_c else 57), seed=seed,
                           density=f["fullness"])
    if kind == "arp":
        return gen_arp(harmony, bars, rate=0.25 if f["fullness"] > 55 else 0.5, center=center or 67)
    if kind == "bell":
        return gen_bell(harmony, bars, center=center or 79, seed=seed)
    if kind == "lead":
        return compose_lead(key, harmony, bars, feel=f, genre=genre, seed=seed)
    return []


def infer_harmony(parts, key, bars):
    """Guess a bar-by-bar chord from the bass (roots) and other pitched parts when no harmony was given."""
    sc = scale_pcs(key)
    out = []
    for bar in range(bars):
        t0, t1 = bar * 4, bar * 4 + 4
        weights = {}
        for p in parts:
            if p.get("role") == "drums":
                continue
            for n in (p.get("plan") or {}).get("notes", []):
                ov = min(n["start"] + n["length"], t1) - max(n["start"], t0)
                if ov > 0:
                    w = ov * (2.5 if p.get("role") == "bass" else 1)
                    weights[n["pitch"] % 12] = weights.get(n["pitch"] % 12, 0) + w
        best, best_score = None, -1
        for d in range(7 if len(SCALES[key[1]]) == 7 else 0):
            ch = degree_chord(key, d)
            score = sum(weights.get(pc, 0) for pc in ch["pcs"]) + 0.5 * weights.get(ch["root"], 0)
            if score > best_score:
                best, best_score = ch, score
        best = best or degree_chord((key[0], "minor" if "minor" in key[1] else "major"), 0)
        out.append(dict(best, start=float(t0), length=4.0))
    # merge equal neighbours
    merged = []
    for seg in out:
        if merged and merged[-1]["symbol"] == seg["symbol"]:
            merged[-1]["length"] += seg["length"]
        else:
            merged.append(seg)
    del sc
    return merged


# ---------------------------------------------------------------- velocity: consistent, producer-like dynamics

GENRE_LOUDNESS = {"ambient": -10, "cloud rap": -8, "r&b": -5, "melodic plugg": -4, "rage": 4, "jerk": 2, "drill": 0}


# Human variation (velocity accents, looseness) only belongs to music made with real players. Trap, plugg, rage,
# drill, jerk and other digitally produced rap stay perfectly even and quantized; only rolls and deliberate ghost
# notes change level. Live-feel styles (sample-based boom bap, live-band R&B) may breathe.
HUMANIZED = {"boom bap", "r&b"}


def shape_velocity(notes, role, lane=None, genre=None):
    """Producer dynamics: EVEN velocity unless there's a musical reason. Rolls ramp up, ghost snares are soft, and
    only humanized styles (boom bap, drill, R&B, jerk) accent hats on the beat. Everything else stays level."""
    if not notes:
        return notes, 0
    g = GENRE_LOUDNESS.get(genre or "", 0)
    human = (genre or "") in HUMANIZED
    before = [n["velocity"] for n in notes]
    ordered = sorted(notes, key=lambda n: n["start"])

    def clamp(v, lo=1, hi=127):
        return int(max(lo, min(hi, round(v))))

    pos16 = lambda n: n["start"] * 4
    on_grid = lambda n: abs(pos16(n) - round(pos16(n))) < 1e-6
    if role == "drums":
        if lane == "kick":
            for n in ordered:
                n["velocity"] = clamp(110 + g, 90, 122)
        elif lane in ("snare", "clap"):
            for n in ordered:
                st = int(round(pos16(n))) % 16 if on_grid(n) else -1
                ghost = st not in (4, 8, 12) and n["velocity"] < 90       # deliberate ghost notes only
                n["velocity"] = clamp((60 if ghost else 112) + g, 45, 122)
        elif lane == "hat":
            run = []
            for i, n in enumerate(ordered):
                close = (i and n["start"] - ordered[i - 1]["start"] < 0.25 - 1e-6) or \
                        (i + 1 < len(ordered) and ordered[i + 1]["start"] - n["start"] < 0.25 - 1e-6)
                if close:
                    run.append(n)
                    continue
                if run:
                    _ramp(run, 70 + g, 100 + g)
                    run = []
                if human:
                    st = pos16(n)
                    v = 100 if on_grid(n) and int(round(st)) % 4 == 0 else 84
                else:
                    v = 96                                               # trap hats: tight and even
                n["velocity"] = clamp(v + g, 50, 112)
            if run:
                _ramp(run, 70 + g, 100 + g)
        elif lane == "open":
            for n in ordered:
                n["velocity"] = clamp(92 + g, 60, 110)
        else:
            for n in ordered:
                n["velocity"] = clamp(90 + g, 50, 110)
    elif role == "bass":
        for n in ordered:
            n["velocity"] = clamp(110, 90, 118)
    else:
        level = 80 if role == "chords" else 100
        for n in ordered:
            v = level
            if role != "chords" and n["velocity"] < 70:
                v = level - 18          # an intended soft note (e.g. a harmony voice) stays softer
            n["velocity"] = clamp(v + g, 50, 115)
    changed = sum(1 for a, n in zip(before, notes) if abs(a - n["velocity"]) > 8)
    return notes, changed


def _ramp(run, lo, hi):
    k = len(run)
    for i, n in enumerate(run):
        n["velocity"] = int(max(40, min(115, round(lo + (hi - lo) * (i / max(1, k - 1))))))


def velocity_spread(notes):
    """Largest jump between consecutive (non-roll) notes: a measure of 'wild' dynamics."""
    ordered = sorted(notes, key=lambda n: n["start"])
    jumps = [abs(ordered[i + 1]["velocity"] - ordered[i]["velocity"]) for i in range(len(ordered) - 1)
             if ordered[i + 1]["start"] - ordered[i]["start"] >= 0.25 - 1e-6]
    return max(jumps) if jumps else 0



# ---------------------------------------------------------------- tidy: notes on real grid lines, no jammed notes

def snap(t, grid):
    return round(round(t / grid) * grid, 6)


def tidy_808(notes, bars, repairs=None, label="808"):
    """Trap 808 lines move by small steps: anything wider than a 5th is pulled back to the nearest octave of that note.
    One short octave accent per 8 bars is allowed (that's an accent, not a pattern)."""
    ns = sorted(notes, key=lambda n: n["start"])
    allowed = max(1, bars)   # the house reference (Yo) accents an octave up about once a bar
    folded = 0
    for i in range(1, len(ns)):
        d = ns[i]["pitch"] - ns[i - 1]["pitch"]
        if abs(d) > 7:
            if abs(d) == 12 and ns[i]["length"] <= 0.5 and allowed > 0:
                allowed -= 1
                continue
            while ns[i]["pitch"] - ns[i - 1]["pitch"] > 7:
                ns[i]["pitch"] -= 12
            while ns[i]["pitch"] - ns[i - 1]["pitch"] < -7:
                ns[i]["pitch"] += 12
            folded += 1
    if folded and repairs is not None:
        repairs.append("%s: kept %d big jump%s close (trap 808s move by small steps)" % (label, folded, "" if folded == 1 else "s"))
    return ns


def tidy_notes(notes, kind, repairs=None, label="part"):
    """Every note on a musical grid line and no tiny jammed notes.
    kind: 'roll' (hi-hats: 1/32 and 1/16-triplet rolls allowed), 'drum', 'chord', 'melody', 'bass'."""
    if not notes:
        return notes
    sixteenth, trip8 = 0.25, 1 / 3.0
    out, moved, dropped = [], 0, 0
    triplet_feel = kind in ("melody", "chord") and sum(1 for n in notes if abs(n["start"] * 3 - round(n["start"] * 3)) < 0.02
                                                        and abs(n["start"] * 4 - round(n["start"] * 4)) > 0.02) > len(notes) * 0.4
    for n in notes:
        st = n["start"]
        if kind == "roll":
            cands = [snap(st, 0.25), snap(st, 0.125), snap(st, 1 / 6.0)]
        elif triplet_feel:
            cands = [snap(st, sixteenth), snap(st, trip8)]
        else:
            cands = [snap(st, sixteenth)]
        new = min(cands, key=lambda c: abs(c - st))
        moved += abs(new - st) > 1e-4
        unit = 0.125 if kind == "roll" else sixteenth
        ln = max(unit, round(round(n["length"] / unit) * unit, 6)) if n["length"] >= unit * 0.75 else n["length"]
        if ln < unit * 0.75 and kind != "roll":
            dropped += 1                                   # a sliver of a note: not part of the pattern
            continue
        out.append(dict(n, start=new, length=ln))
    if kind == "chord":   # grace notes squeezed just before a chord hit
        onsets = {}
        for n in out:
            onsets.setdefault(n["start"], []).append(n)
        hits = {t for t, g in onsets.items() if len(g) >= 2}
        keep = []
        for n in out:
            nxt = min((h for h in hits if h > n["start"]), default=None)
            if n["start"] not in hits and nxt is not None and nxt - n["start"] <= 0.25 + 1e-6 and n["length"] <= 0.25 + 1e-6:
                dropped += 1
                continue
            keep.append(n)
        out = keep
    out = dedupe(out)
    if repairs is not None and (moved or dropped):
        bits = []
        if moved:
            bits.append("put %d note%s on the grid" % (moved, "" if moved == 1 else "s"))
        if dropped:
            bits.append("removed %d tiny/jammed note%s" % (dropped, "" if dropped == 1 else "s"))
        repairs.append("%s: %s" % (label, ", ".join(bits)))
    return out


def calm_pushes(notes, repairs=None, label="part", per_bar=1):
    """Short-note melodies (plucks, bells, arps): the AI likes starting notes on the in-between 16th of a beat (beat + 1/4
    or + 3/4) to feel human, and overdoes it. Keep `per_bar` of those pushes in each bar (the first), move the rest to
    the nearest 8th (the later one on a tie) keeping where each note ends, and stretch lone 1/16 notes to an 1/8 when
    the next note leaves room. Pitches never change."""
    if not notes:
        return notes
    out = sorted((dict(n) for n in notes), key=lambda n: (n["start"], n["pitch"]))
    onsets = {round(n["start"], 4) for n in out}
    in_run = lambda t: round(t - 0.25, 4) in onsets or round(t + 0.25, 4) in onsets   # part of a deliberate 16th run
    kept, moved, stretched = {}, 0, 0
    for n in out:
        frac = round((n["start"] * 4) % 2, 4)   # 1 = an in-between 16th
        if abs(frac - 1) > 1e-3 or in_run(n["start"]):
            continue
        bar = int(n["start"] // 4)
        if kept.get(bar, 0) < per_bar:
            kept[bar] = kept.get(bar, 0) + 1
            continue
        end = n["start"] + n["length"]
        for target in (n["start"] + 0.25, n["start"] - 0.25):
            if round(target, 4) not in onsets and target >= 0 and end - target >= 0.25 - 1e-6:
                onsets.discard(round(n["start"], 4))
                onsets.add(round(target, 4))
                n["start"], n["length"] = round(target, 6), round(end - target, 6)
                moved += 1
                break
    out.sort(key=lambda n: (n["start"], n["pitch"]))
    for i, n in enumerate(out):
        if n["length"] <= 0.25 + 1e-6 and not in_run(n["start"]):
            nxt = next((m["start"] for m in out[i + 1:] if m["start"] > n["start"] + 1e-6), None)
            if nxt is None or nxt - n["start"] >= 0.5 - 1e-6:
                n["length"] = 0.5
                stretched += 1
    if repairs is not None and (moved or stretched):
        repairs.append("%s: steadier rhythm (%d push%s moved onto the 8th, %d short note%s lengthened)" % (
            label, moved, "" if moved == 1 else "es", stretched, "" if stretched == 1 else "s"))
    return out


def is_short_note_line(notes, instrument=None):
    """Plucked or short-note melodies: where too many pushes sound clumsy."""
    if instrument in ("pluck", "bell", "music_box", "arp_synth", "guitar", "lead_synth", "keys", "piano", "rhodes"):
        return True
    lengths = sorted(n["length"] for n in notes)
    return bool(lengths) and lengths[len(lengths) // 2] <= 0.5 + 1e-6
