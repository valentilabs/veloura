"""Variations: alternative versions of a part that keep its identity, for A/B comparison.

Melodies: new phrase endings, rhythmic displacement, inverted contour, register/density changes, or a
fresh motif in the same harmony. Basslines: sustained / locked to the kick / choppy. Drums: the Groove
Lab actions. Every option stays in key and is validated like any other part.
"""

import copy
import random

from . import grooves, theory


def _with(plan, notes):
    p = copy.deepcopy(plan)
    p["notes"] = theory.dedupe([dict(n) for n in notes])
    return p


def _context(plan, harmony_symbols=None):
    key = theory.parse_key(plan.get("key") or "") or (5, "minor")
    bars = plan.get("bars") or 4
    harmony = theory.harmony_from_symbols(harmony_symbols, bars) if harmony_symbols else None
    if not harmony:
        harmony = theory.infer_harmony([{"role": "melody", "plan": plan}], key, bars)
    return key, bars, harmony


def develop_endings(plan, key, harmony, seed=0):
    """Keep bars 1-3 of each 4-bar phrase, rewrite the last bar's second half as an answer resolving to a chord tone."""
    rnd = random.Random(seed + 11)
    bars = plan["bars"]
    out = []
    for n in plan["notes"]:
        bar = int(n["start"] // 4)
        in_tail = bar % 4 == 3 and n["start"] - bar * 4 >= 2
        if not in_tail:
            out.append(dict(n))
            continue
        step = rnd.choice([-2, -1, 1, 2])
        p = theory.scale_step(n["pitch"], step, key)
        out.append(dict(n, pitch=p))
    for bar in range(3, bars, 4):   # land the phrase on a stable tone
        tail = [n for n in out if bar * 4 + 2 <= n["start"] < bar * 4 + 4]
        if tail:
            last = max(tail, key=lambda n: n["start"])
            ch = theory.chord_at(harmony, last["start"])
            last["pitch"] = theory.nearest_pitch(last["pitch"], set(ch["pcs"]) if ch else {key[0]})
    return _with(plan, out)


def motif_repeat(plan, key, harmony):
    """Rebuild a wandering line around its first bar: A A' A B per 4 bars."""
    bars = plan["bars"]
    first = [n for n in plan["notes"] if n["start"] < 4]
    if not first:
        return copy.deepcopy(plan)
    out = []
    for bar in range(bars):
        src = first if bar % 4 != 3 else [n for n in plan["notes"] if bar * 4 <= n["start"] < bar * 4 + 4] or first
        for n in src:
            off = n["start"] % 4 if src is first else n["start"] - bar * 4
            p = n["pitch"]
            if bar % 4 == 1 and off >= 2:
                p = theory.scale_step(p, 1, key)
            ch = theory.chord_at(harmony, bar * 4 + off)
            if ch and abs(off - round(off)) < 1e-6 and off % 2 == 0:
                p = theory.nearest_pitch(p, set(ch["pcs"]))
            out.append(dict(n, start=bar * 4 + off, pitch=p))
    return _with(plan, out)


def displace(plan, amount=0.5):
    """Shift the rhythm by an 8th (wrapping inside each bar)."""
    out = []
    for n in plan["notes"]:
        bar = int(n["start"] // 4)
        off = (n["start"] - bar * 4 + amount) % 4
        ln = min(n["length"], 4 - off)
        out.append(dict(n, start=round(bar * 4 + off, 6), length=round(max(0.125, ln), 6)))
    return _with(plan, out)


def invert(plan, key):
    """Mirror the contour around the line's centre, staying in key."""
    c = theory.median_pitch(plan["notes"]) or 69
    sc = set(theory.scale_pcs(key))
    return _with(plan, [dict(n, pitch=theory.nearest_pitch(2 * c - n["pitch"], sc)) for n in plan["notes"]])


def drum_fills(lanes, bars, genre=None, seed=0):
    """Fill at the end of every 4th bar (snare pickup / hat roll) and a kick dropout on the last beat of the loop."""
    out = {k: [dict(n) for n in v] for k, v in lanes.items()}
    for name, notes in out.items():
        kind = grooves.lane_of(name)
        for bar in range(3, bars, 4):
            t3 = bar * 4 + 3
            if kind == "snare":
                for off, vel in ((3.5, 70), (3.75, 96)):
                    if not any(abs(n["start"] - (bar * 4 + off)) < 1e-6 for n in notes):
                        notes.append({"pitch": 60, "start": bar * 4 + off, "length": 0.25, "velocity": vel})
            elif kind == "hat":
                notes[:] = [n for n in notes if not (t3 <= n["start"] < t3 + 1)]
                notes += grooves._roll("trip" if seed % 2 else "32", t3, 1.0)
        if kind == "kick" and bars >= 4:
            notes[:] = [n for n in notes if not (bars * 4 - 1 <= n["start"] < bars * 4)]
        notes.sort(key=lambda n: n["start"])
    return out


def options(name, entry, harmony_symbols=None, genre=None, count=3, seed=0, siblings=None):
    """Up to `count` distinct alternatives for one part: [{"label", "description", "plan"}]."""
    plan = entry["plan"]
    role = entry.get("role")
    key, bars, harmony = _context(plan, harmony_symbols)
    out = []
    if role == "drums":
        lanes = {name: plan["notes"]}
        for action in ("bounce", "space", "new"):
            t = grooves.transform(lanes, action, genre=genre, bars=bars, seed=seed + len(out))
            out.append({"label": grooves.ACTIONS[action], "description": {
                "bounce": "Extra syncopated hits and accents for more swing in the step.",
                "space": "Fewer hits so the other parts breathe.",
                "new": "A different %s pattern in the same style." % name}[action], "plan": _with(plan, t[name])})
    elif role == "bass":
        kick = None
        for sname, s in (siblings or {}).items():
            if s.get("role") == "drums" and grooves.lane_of(sname) == "kick":
                kick = sorted({round(n["start"] * 4) for n in s["plan"]["notes"]})
        for style, label, desc in (("sustain", "Long and smooth", "Sustained roots that change with the chords."),
                                   ("locked", "Locked to the kick", "Hits with every kick for punch."),
                                   ("choppy", "Short and bouncy", "Short notes with octave jumps, more rhythm than sustain.")):
            notes = theory.gen_bass(harmony, bars, kick_steps=kick if style != "sustain" else None, style=style, seed=seed)
            out.append({"label": label, "description": desc, "plan": _with(plan, notes)})
    else:
        cands = [
            ("New phrase endings", "Same hook, a different answer at the end of each phrase.", develop_endings(plan, key, harmony, seed)),
            ("Off the beat", "The same notes pushed an 8th later: more bounce and tension.", displace(plan)),
            ("Mirrored", "The contour flipped (rises where it fell) but still in key.", invert(plan, key)),
            ("Fresh idea", "A new motif over the same chords.", _with(plan, theory.compose_lead(key, harmony, bars, seed=seed + 99,
                                                                                                genre=genre))),
        ]
        base = plan["notes"]
        scored = []
        for label, desc, p in cands:
            diff = _difference(base, p["notes"])
            scored.append((diff, label, desc, p))
        scored = [s for s in scored if s[0] > 0.05]
        for _, label, desc, p in scored[:count]:
            out.append({"label": label, "description": desc, "plan": p})
    for o in out:
        theory.refine([{"name": name, "role": role, "purpose": entry.get("purpose"), "plan": o["plan"]}], key, harmony, bars)
    return out[:count]


def _difference(a, b):
    sa = {(round(n["start"] * 4), n["pitch"]) for n in a}
    sb = {(round(n["start"] * 4), n["pitch"]) for n in b}
    return 1 - len(sa & sb) / max(1, len(sa | sb))
