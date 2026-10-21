"""Groove engine: genre-specific drum programming.

Each profile encodes how a subgenre's drums actually behave: kick placement strategies, snare/clap
conventions, hi-hat language (straight, skippy drill, plugg skips, rage stutters, swung boom bap), rolls
and where they go, open hats, percussion, swing, density, and how the pattern develops across a phrase
(fills, switches, dropouts) instead of one bar copied forever.

Output lanes are Veloura drum parts on pitch 60: Kick, Snare, Clap, Hi-hat, Open hat, Perc. Notes on the
16th grid go straight into FL's step sequencer; rolls (1/32, triplets) and swung notes need the Piano Roll.

Pattern strings: one char per 16th. 'X' accent, 'x' normal, 'o' soft, 'g' ghost, '.' rest.
"""

import random

VEL = {"X": 118, "x": 102, "o": 84, "g": 58}
LANES = ("Kick", "Snare", "Clap", "Hi-hat", "Open hat", "Perc")

PROFILES = {
    "trap": {
        "label": "Modern trap",
        "kick": ["X......x..x.....", "X......x..x...x.", "X..x......x.....", "X.....x...x..x.."],
        "snare": "........X.......", "clap": "........X.......",
        "snare_fill": "........X.....gx",
        "hats": "trap", "roll_rate": 0.55, "rolls": ["32", "trip", "32x8"],
        "open": [14], "open_every": 2, "perc": "......o.......o.", "perc_rate": 0.25,
        "swing": 0.0, "plan": "A A A F A B A D", "bass": "lock",
    },
    "dark trap": {
        "label": "Dark underground trap",
        "kick": ["X.........x.....", "X......x........", "X.........x..x..", "X..........x...."],
        "snare": "........X.......", "clap": "........x.......",
        "snare_fill": "........X......g",
        "hats": "dark", "roll_rate": 0.3, "rolls": ["trip", "trip8"],
        "open": [], "open_every": 4, "perc": "...g.......g....", "perc_rate": 0.5,
        "swing": 0.04, "plan": "A A A F A A B D", "bass": "sustain",
    },
    "plugg": {
        "label": "Plugg",
        "kick": ["X..x..x...x.....", "X..x....x.x.....", "X..x..x.....x...", "X.x...x...x....."],
        "snare": "........X.......", "clap": "........X.......",
        "snare_fill": "........X...ooxX",
        "hats": "plugg", "roll_rate": 0.25, "rolls": ["trip8"],
        "open": [6], "open_every": 2, "perc": "", "perc_rate": 0.0,
        "swing": 0.14, "plan": "A A A F A B A F", "bass": "sustain",
    },
    "melodic plugg": {
        "label": "Melodic plugg",
        "kick": ["X..x......x.....", "X..x..x.........", "X.....x...x....."],
        "snare": "........X.......", "clap": "........x.......",
        "snare_fill": "........X....oox",
        "hats": "plugg", "roll_rate": 0.15, "rolls": ["trip8"],
        "open": [14], "open_every": 4, "perc": "", "perc_rate": 0.0,
        "swing": 0.12, "plan": "A A A F A A B F", "bass": "sustain",
    },
    "rage": {
        "label": "Rage",
        "kick": ["X.....x...x.x...", "X..x..x...x.....", "X.x...x...x..x..", "X.....x.x.x....."],
        "snare": "........X.......", "clap": "........X.......",
        "snare_fill": "........X...xxXX",
        "hats": "rage", "roll_rate": 0.8, "rolls": ["32", "32x8", "trip"],
        "open": [2, 10], "open_every": 1, "perc": "", "perc_rate": 0.0,
        "swing": 0.0, "plan": "A B A F A B A D", "bass": "choppy",
    },
    "jerk": {
        "label": "Jerk",
        "kick": ["X..x...x.x..x...", "X.x..x...x..x.x.", "X..x.x....x..x..", "X...x..x.x...x.."],
        "snare": "....X.......X...", "clap": "....X..o....X...",
        "snare_fill": "....X..o....X.xx",
        "hats": "jerk", "roll_rate": 0.35, "rolls": ["32", "trip"],
        "open": [6, 14], "open_every": 1, "perc": "..o..o.g..o...o.", "perc_rate": 0.9,
        "swing": 0.06, "plan": "A B A F B A B D", "bass": "choppy",
    },
    "drill": {
        "label": "Drill",
        "kick": ["X.........x.....", "X......x........", "X.........x...x.", "X.....x........."],
        "snare": "........X....x..", "clap": "........X.......",
        "snare_fill": "...g....X....x.x",
        "hats": "drill", "roll_rate": 0.6, "rolls": ["trip", "trip8"],
        "open": [], "open_every": 4, "perc": "..g.......g.....", "perc_rate": 0.3,
        "swing": 0.0, "plan": "A A B F A A B D", "bass": "sustain",
    },
    "melodic rap": {
        "label": "Melodic rap",
        "kick": ["X.......x.x.....", "X......x..x.....", "X..x......x....."],
        "snare": "........X.......", "clap": "........X.......",
        "snare_fill": "........X......o",
        "hats": "eighths", "roll_rate": 0.3, "rolls": ["trip", "32"],
        "open": [14], "open_every": 2, "perc": ".o.o.o.o.o.o.o.o", "perc_rate": 0.3,
        "swing": 0.03, "plan": "A A A F A B A F", "bass": "sustain",
    },
    "detroit": {
        "label": "Detroit / Flint",
        "kick": ["X..x..x...x..x..", "X.x...x..x...x..", "X..x.x....x.x..."],
        "snare": "....X.......X...", "clap": "....X.......X...",
        "snare_fill": "....X.......X.ox",
        "hats": "detroit", "roll_rate": 0.1, "rolls": ["32"],
        "open": [], "open_every": 4, "perc": "", "perc_rate": 0.0,
        "swing": 0.08, "plan": "A B A F A B A F", "bass": "choppy",
    },
    "ambient": {
        "label": "Ambient / atmospheric",
        "kick": ["X.........x.....", "X...............", "X.......x......."],
        "snare": "........x.......", "clap": "........o.......",
        "snare_fill": "........x.......",
        "hats": "sparse", "roll_rate": 0.05, "rolls": ["trip8"],
        "open": [], "open_every": 8, "perc": "......o.......o.", "perc_rate": 0.4,
        "swing": 0.1, "plan": "A A A A A A B B", "bass": "sustain",
    },
    "boom bap": {
        "label": "Boom bap",
        "kick": ["X......x..x.....", "X.x....x..x.....", "X......xx.....x."],
        "snare": "....X.......X...", "clap": "",
        "snare_fill": "....X..g....X..g",
        "hats": "boom", "roll_rate": 0.0, "rolls": [],
        "open": [14], "open_every": 4, "perc": "", "perc_rate": 0.0,
        "swing": 0.55, "plan": "A A A F", "bass": "sustain",
    },
    "r&b": {
        "label": "R&B",
        "kick": ["X......x.x......", "X.....x...x....."],
        "snare": "....X.......X...", "clap": "....x.......x...",
        "snare_fill": "....X.......X..g",
        "hats": "eighths", "roll_rate": 0.1, "rolls": ["trip8"],
        "open": [], "open_every": 4, "perc": "..o...o...o...o.", "perc_rate": 0.6,
        "swing": 0.2, "plan": "A A A F A A B F", "bass": "sustain",
    },
    "pop": {
        "label": "Pop",
        "kick": ["X.......X.......", "X.....x.X......."],
        "snare": "....X.......X...", "clap": "....X.......X...",
        "snare_fill": "....X.......X.xx",
        "hats": "eighths", "roll_rate": 0.1, "rolls": ["32"],
        "open": [], "open_every": 4, "perc": "", "perc_rate": 0.0,
        "swing": 0.0, "plan": "A A A F A A A F", "bass": "sustain",
    },
}
ALIASES = {"melodic trap": "melodic rap", "cloud rap": "ambient", "pluggnb": "melodic plugg", "underground": "dark trap",
           "flint": "detroit", "rnb": "r&b", "uk drill": "drill", "ny drill": "drill", "atmospheric": "ambient"}


def profile_name(genre):
    g = (genre or "trap").lower()
    g = ALIASES.get(g, g)
    return g if g in PROFILES else "trap"


def _hits(pattern):
    return [(i, VEL[c]) for i, c in enumerate(pattern[:16]) if c in VEL]


def _note(t, vel, ln=0.25):
    return {"pitch": 60, "start": round(t, 6), "length": round(ln, 6), "velocity": max(1, min(127, int(vel)))}


def _roll(kind, t0, length=1.0, base=70, top=110):
    sub = {"32": 0.125, "32x8": 0.125, "trip": 1 / 6.0, "trip8": 1 / 3.0}[kind]
    span = 0.5 if kind == "32" else length
    count = int(round(span / sub))
    start = t0 + (length - span)
    return [_note(start + i * sub, base + (top - base) * i / max(1, count - 1), sub) for i in range(count)]


def _hat_bar(mode, bar_t, rnd, fullness, roll):
    """One bar of closed hats in the profile's language. Returns notes; `roll` = roll kind for beat 4 or None."""
    out = []
    if mode == "trap":
        rate = 1 if fullness > 60 else 2
        for s in range(0, 16, rate):
            out.append(_note(bar_t + s / 4, 100 if s % 4 == 0 else (78 if s % 2 == 0 else 64)))
    elif mode == "dark":
        for s in (0, 2, 4, 6, 8, 10, 12, 14):
            if rnd.random() < 0.85:
                out.append(_note(bar_t + s / 4, 92 if s % 4 == 0 else 66))
    elif mode == "plugg":
        for s in (0, 2, 4, 6, 8, 12, 14) if rnd.random() < 0.6 else (0, 2, 4, 8, 10, 12, 14):
            out.append(_note(bar_t + s / 4, 96 if s % 4 == 0 else 70))
    elif mode == "rage":
        for s in range(16):
            out.append(_note(bar_t + s / 4, 104 if s % 4 == 0 else (82 if s % 2 == 0 else 68)))
        if rnd.random() < 0.5:   # a mid-bar stutter
            s = rnd.choice([5, 7, 9])
            out = [n for n in out if abs(n["start"] - (bar_t + s / 4)) > 1e-6]
            out += _roll("32", bar_t + s / 4 - 0.25, 0.5, 66, 96)[2:]
    elif mode == "jerk":
        for s in range(16):
            if s in (3, 11) and rnd.random() < 0.6:
                continue   # gaps that make it choppy
            out.append(_note(bar_t + s / 4, 108 if s in (0, 6, 8, 14) else 74))
    elif mode == "drill":
        base = rnd.choice(["x..x..x.x..x..x.", "x..x..x...x.x...", "x.x..x..x..x.x.."])
        for s, v in _hits(base):
            out.append(_note(bar_t + s / 4, 96 if s % 4 == 0 else 78))
        if rnd.random() < 0.55:   # a triplet burst somewhere in the bar
            b = rnd.choice([1, 2])
            out = [n for n in out if not (bar_t + b <= n["start"] < bar_t + b + 1)]
            out += _roll("trip", bar_t + b, 1.0, 70, 95)[:3 + rnd.randint(0, 3)]
    elif mode == "detroit":
        for s, v in _hits("x.oox.oox.oox.oo"):
            out.append(_note(bar_t + s / 4, v))
    elif mode == "boom":
        for s in range(0, 16, 2):
            out.append(_note(bar_t + s / 4, 92 if s % 4 == 0 else 72))
        for s in (3, 11):
            if rnd.random() < 0.5:
                out.append(_note(bar_t + s / 4, 50))
    elif mode == "sparse":
        for s in (0, 4, 8, 12) if fullness < 50 else range(0, 16, 2):
            out.append(_note(bar_t + s / 4, 70 if s % 8 == 0 else 56))
    else:   # eighths
        for s in range(0, 16, 2):
            out.append(_note(bar_t + s / 4, 94 if s % 4 == 0 else 70))
    if roll:
        out = [n for n in out if n["start"] < bar_t + 3 - 1e-6]
        out += _roll(roll, bar_t + 3, 1.0)
    return out


def generate(genre=None, bars=4, seed=0, fullness=50, variation=50, swing=None, energy=50):
    """A full drum pattern for the genre. Returns {"profile", "lanes": {lane: notes}, "kick_steps", "swing", "signature"}."""
    name = profile_name(genre)
    pr = PROFILES[name]
    rnd = random.Random(seed * 7919 + bars)
    plan = pr["plan"].split()
    kicks = pr["kick"]
    a = kicks[seed % len(kicks)] if variation < 80 else rnd.choice(kicks)
    b = kicks[(seed + 1) % len(kicks)] if len(kicks) > 1 else a
    lanes = {k: [] for k in LANES}
    kick_steps = []
    for bar in range(bars):
        t0 = bar * 4.0
        sec = plan[bar % len(plan)] if bars > 1 else "A"
        if bars <= 4 and sec == "B" and variation < 40:
            sec = "A"
        kick = b if sec == "B" else a
        if sec in ("A", "B") and variation > 65 and rnd.random() < 0.3:   # small kick variation
            k = list(kick)
            spot = rnd.choice([3, 6, 11, 13, 14])
            k[spot] = "o" if k[spot] == "." else "."
            kick = "".join(k)
        drop = sec == "D"
        for s, v in _hits(kick):
            if drop and s >= 12:
                continue   # drop the last beat of the phrase before the loop comes back
            if fullness < 30 and v < 100 and s % 4 != 0 and rnd.random() < 0.5:
                continue
            lanes["Kick"].append(_note(t0 + s / 4, v))
            kick_steps.append(bar * 16 + s)
        fill = sec in ("F", "D")
        snare = pr["snare_fill"] if fill else pr["snare"]
        for s, v in _hits(snare):
            lanes["Snare"].append(_note(t0 + s / 4, v))
        for s, v in _hits(pr["clap"]):
            lanes["Clap"].append(_note(t0 + s / 4, v))
        roll = None
        if pr["rolls"] and (fill or rnd.random() < pr["roll_rate"] * (0.5 if bar % 2 == 0 else 1)) and energy > 25:
            roll = rnd.choice(pr["rolls"])
        lanes["Hi-hat"] += _hat_bar(pr["hats"], t0, rnd, fullness, roll)
        every = pr["open_every"]
        if pr["open"] and bar % every == every - 1:
            for s in pr["open"]:
                lanes["Open hat"].append(_note(t0 + s / 4, 84, 0.5))
                lanes["Hi-hat"] = [n for n in lanes["Hi-hat"] if abs(n["start"] - (t0 + s / 4)) > 1e-6]
        if pr["perc"] and rnd.random() < pr["perc_rate"] * (0.6 + fullness / 125.0):
            for s, v in _hits(pr["perc"]):
                lanes["Perc"].append(_note(t0 + s / 4, v))
    sw = pr["swing"] if swing is None else swing
    lanes = {k: apply_swing(v, sw) if k in ("Hi-hat", "Perc", "Open hat") else v for k, v in lanes.items()}
    return {"profile": name, "label": pr["label"], "lanes": {k: v for k, v in lanes.items() if v},
            "kick_steps": kick_steps, "swing": sw, "signature": signature(lanes, bars)}


def apply_swing(notes, amount):
    """Delay off-beat 16ths. amount 0..1 (1 = full triplet feel). Rolls (off-grid notes) are left alone."""
    if amount <= 0:
        return notes
    off = amount / 12.0
    out = []
    for n in notes:
        pos = n["start"] * 4
        if abs(pos - round(pos)) < 1e-6 and int(round(pos)) % 2 == 1:
            n = dict(n, start=round(n["start"] + off, 6), length=round(max(0.02, n["length"] - off), 6))
        out.append(n)
    return out


def signature(lanes, bars):
    """Compact fingerprint used to compare grooves: set of (lane, step) in the first 2 bars."""
    sig = set()
    for lane, notes in lanes.items():
        for n in notes:
            if n["start"] < 8:
                sig.add((lane, round(n["start"] * 4)))
    return sig


def distance(a, b):
    sa, sb = a if isinstance(a, set) else set(a), b if isinstance(b, set) else set(b)
    return 1 - len(sa & sb) / max(1, len(sa | sb))


# ---------------------------------------------------------------- Groove Lab actions

ACTIONS = {
    "bounce": "More bounce",
    "space": "More space",
    "swing": "Add swing",
    "new": "Different groove",
    "authentic": "More authentic",
}


def transform(lanes, action, genre=None, bars=4, seed=0):
    """Apply a Groove Lab action to existing drum lanes {lane: notes}. Returns new lanes (copies)."""
    rnd = random.Random(seed * 31 + sorted(ACTIONS).index(action) if action in ACTIONS else seed)
    lanes = {k: [dict(n) for n in v] for k, v in lanes.items()}
    kick = next((k for k in lanes if "kick" in k.lower()), None)
    hat = next((k for k in lanes if "hat" in k.lower() and "open" not in k.lower()), None)
    if action == "bounce":
        if kick:
            have = {round(n["start"] * 4) for n in lanes[kick]}
            for bar in range(bars):
                for s in rnd.sample([3, 6, 11, 14], 2 if bar % 2 else 1):
                    st = bar * 16 + s
                    if st not in have and (st - 1) not in have:
                        lanes[kick].append(_note(st / 4, 88))
        if hat:
            for n in lanes[hat]:
                pos = n["start"] * 4
                if abs(pos - round(pos)) < 1e-6:
                    n["velocity"] = 108 if round(pos) % 4 == 0 else max(50, n["velocity"] - 14)
            lanes[hat] = apply_swing(lanes[hat], 0.12)
    elif action == "space":
        if kick:
            lanes[kick] = [n for n in lanes[kick] if round(n["start"] * 4) % 16 == 0 or n["velocity"] >= 100 and rnd.random() < 0.7]
        if hat:
            lanes[hat] = [n for n in lanes[hat] if abs(n["start"] * 2 - round(n["start"] * 2)) < 1e-6 and
                          (round(n["start"] * 2) % 2 == 0 or rnd.random() < 0.5)]
        for k in list(lanes):
            if "perc" in k.lower():
                lanes[k] = lanes[k][::2]
    elif action == "swing":
        for k in lanes:
            if "kick" not in k.lower() and "snare" not in k.lower() and "clap" not in k.lower():
                lanes[k] = apply_swing(lanes[k], 0.2)
    elif action in ("new", "authentic"):
        g = generate(genre, bars, seed=seed + (17 if action == "new" else 0), variation=30 if action == "authentic" else 70)
        out = {}
        for k in lanes:
            kind = lane_of(k)
            src = next((v for gk, v in g["lanes"].items() if lane_of(gk) == kind), None)
            out[k] = src if src is not None else lanes[k]
        return out
    for k in lanes:
        lanes[k].sort(key=lambda n: n["start"])
    return lanes


def lane_of(name):
    n = name.lower()
    if "open" in n:
        return "open"
    if "kick" in n or n.startswith("bd"):
        return "kick"
    if "clap" in n:
        return "clap"
    if "snare" in n or "rim" in n:
        return "snare"
    if "hat" in n or "hh" in n:
        return "hat"
    if "perc" in n or "shaker" in n or "tamb" in n:
        return "perc"
    return None


def fit_to_channels(lanes, channels, match_channel):
    """Name lanes after the user's Channel Rack channels. A lane with no channel is merged where it makes sense
    (Clap -> Snare and back) or kept under its standard name. Returns {part_name: notes}."""
    out = {}
    names = [c["name"] for c in channels or []]
    for lane, notes in lanes.items():
        chan, _ = match_channel(lane, channels or [])
        if not chan and lane == "Clap":
            chan, _ = match_channel("Snare", channels or [])
        if not chan and lane == "Snare":
            chan, _ = match_channel("Clap", channels or [])
        if not chan and lane == "Open hat" and not any("open" in n.lower() for n in names):
            continue   # no open hat loaded: skip it rather than stacking it on the closed hat
        if not chan and lane == "Perc" and names:
            continue
        key = chan["name"] if chan else lane
        out.setdefault(key, [])
        have = {round(n["start"], 6) for n in out[key]}
        out[key] += [n for n in notes if round(n["start"], 6) not in have]
    for k in out:
        out[k].sort(key=lambda n: n["start"])
    return out


# ---------------------------------------------------------------- which drums may hit together

KICK_ON_BACKBEAT_OK = {"jerk", "detroit", "boom bap", "pop"}


def deconflict(lanes, genre=None, bars=4):
    """Drums that shouldn't hit at the same moment, resolved the way producers program them:
      * snare + clap may stack on the backbeat (a layer), but a clap never doubles a ghost snare;
      * an open hat replaces the closed hat on its step; no open hat inside a hat roll;
      * percussion stays off kick and snare/clap hits (it fills the gaps);
      * the kick stays off the snare's backbeat unless the style does that on purpose (jerk, Detroit, boom bap);
      * the 808 may (should) hit with the kick: it isn't a drum lane here.
    lanes: {part name: notes}. Returns (lanes, [repairs])."""
    kinds = {name: lane_of(name) for name in lanes}
    at = lambda notes: {round(n["start"], 4) for n in notes}
    by = {}
    for name, k in kinds.items():
        by.setdefault(k, set()).update(at(lanes[name]))
    repairs = []

    def drop(name, positions, why):
        before = len(lanes[name])
        lanes[name] = [n for n in lanes[name] if round(n["start"], 4) not in positions]
        if len(lanes[name]) < before:
            repairs.append("%s: removed %d hit%s %s" % (name, before - len(lanes[name]), "" if before - len(lanes[name]) == 1 else "s", why))

    backbeat = {round(b * 4 + o, 4) for b in range(bars) for o in ((2.0,) if genre not in ("boom bap", "r&b", "pop", "jerk", "detroit") else (1.0, 3.0))}
    snare_hits = by.get("snare", set()) | by.get("clap", set())
    for name, k in kinds.items():
        if k == "clap" and "snare" in by:
            drop(name, by["snare"] - backbeat, "that doubled ghost snares")
        if k == "hat" and "open" in by:
            drop(name, by["open"], "under the open hat")
        if k == "open":
            hats = sorted(by.get("hat", set()))
            rolls = {hats[i] for i in range(len(hats) - 1) if hats[i + 1] - hats[i] < 0.25 - 1e-6} | \
                    {hats[i + 1] for i in range(len(hats) - 1) if hats[i + 1] - hats[i] < 0.25 - 1e-6}
            drop(name, {p for p in at(lanes[name]) if any(abs(p - r) < 0.26 for r in rolls)}, "inside a hat roll")
        if k == "perc":
            drop(name, by.get("kick", set()) | snare_hits, "on top of the kick/snare")
        if k == "kick" and (genre or "") not in KICK_ON_BACKBEAT_OK:
            drop(name, snare_hits & backbeat, "on the snare's backbeat")
    return lanes, repairs
