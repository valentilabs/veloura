"""Offline composer: rule-based (NOT AI) generation of melodies, 808/bass and drum lanes.

Used when no AI provider is configured, and as a deterministic generator for
tests. Output uses the same response shape as the AI providers:

    {"reply": str, "parts": [part, ...], "guidance": [guide, ...], "provider": "offline"}

where each part is {"name", "role", "action", "target_hint", "plan"} and plan
is a cadence.melody/1 plan (see melody_plan.py). Drum lanes are separate parts
whose notes sit on pitch 60 (C5 in FL Studio), which plays a sampler channel's
sample at its original pitch.
"""

import random
import re

from . import guidance as guides

NOTE_INDEX = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6,
              "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
SCALES = {
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "harmonic minor": [0, 2, 3, 5, 7, 8, 11],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "major": [0, 2, 4, 5, 7, 9, 11],
}
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

DRUM_LANES = ("Kick", "Snare", "Hi-hat", "Open hat", "808")


# ---------- request parsing ----------

def parse_key(text):
    """Find a key like 'F minor', 'C# min', 'Bbm', 'E phrygian'. Returns (tonic_pc, scale_name) or None."""
    m = re.search(r"\b([A-Ga-g])\s?([#b♯♭]?)\s?(harmonic minor|minor|min|major|maj|phrygian|dorian|m)\b", text)
    if not m:
        return None
    name = (m.group(1).upper() + m.group(2).replace("♯", "#").replace("♭", "b").upper())
    pc = NOTE_INDEX.get(name)
    if pc is None:
        return None
    mode = m.group(3).lower()
    scale = {"min": "minor", "m": "minor", "maj": "major"}.get(mode, mode)
    return pc, scale


def key_label(pc, scale):
    return "%s %s" % (FLAT_NAMES[pc], scale)


def parse_request(text, settings):
    t = text.lower()
    req = {
        "tempo": settings.get("tempo_bpm", 140),
        "key": parse_key(text) or parse_key(settings.get("key", "F minor")) or (5, "minor"),
        "bars": settings.get("bars", 4),
        "mood": settings.get("mood", ""),
    }
    m = re.search(r"(\d{2,3})\s?bpm", t)
    if m and 40 <= int(m.group(1)) <= 300:
        req["tempo"] = int(m.group(1))
    m = re.search(r"\b(\d{1,2})[- ]?bars?\b", t)
    if m and 1 <= int(m.group(1)) <= 16:
        req["bars"] = int(m.group(1))
    if "dark" in t and req["key"][1] == "minor" and not parse_key(text):
        req["key"] = (req["key"][0], "harmonic minor")
    req["dark"] = any(w in t for w in ("dark", "evil", "sinister", "eerie", "creepy", "underground"))
    req["bouncy"] = any(w in t for w in ("bounce", "bouncy", "groovy", "swing", "jerk", "plugg"))
    req["spacious"] = any(w in t for w in ("spacious", "ambient", "slow", "airy", "space", "sparse", "simple", "simpler", "less busy"))
    req["busy"] = any(w in t for w in ("busy", "busier", "fast", "rage", "energetic", "more notes", "hype"))
    req["vary"] = any(w in t for w in ("less repetitive", "vary", "variation", "different", "change it up", "another", "new one"))
    req["higher"] = any(w in t for w in ("higher", "octave up", "brighter"))
    req["lower"] = any(w in t for w in ("lower", "octave down", "deeper"))
    req["wants"] = set()
    if any(w in t for w in ("melody", "lead", "bell", "pluck", "piano", "keys", "flute", "synth line")):
        req["wants"].add("melody")
    if any(w in t for w in ("808", "bass")):
        req["wants"].add("bass")
    if any(w in t for w in ("drum", "kick", "snare", "hat", "hi-hat", "hihat", "clap", "percussion", "groove")):
        req["wants"].add("drums")
    if any(w in t for w in ("beat", "track", "instrumental", "from scratch")) and not req["wants"]:
        req["wants"] = {"melody", "bass", "drums"}
    return req


# ---------- generators ----------

def _plan(title, req, notes, target):
    pc, scale = req["key"]
    return {"schema": "cadence.melody/1", "title": title, "tempo_bpm": req["tempo"], "time_signature": [4, 4],
            "key": key_label(pc, scale), "bars": req["bars"], "target": target,
            "notes": sorted(notes, key=lambda n: (n["start"], n["pitch"]))}


def _scale_pitch(pc, scale, degree, octave_base):
    steps = SCALES[scale]
    octave, idx = divmod(degree, len(steps))
    return octave_base + pc + 12 * octave + steps[idx]


MELODY_RHYTHMS = {
    "bouncy": [(0, 3), (3, 3), (6, 2), (8, 3), (11, 3), (14, 2)],
    "spacious": [(0, 6), (8, 4), (12, 4)],
    "busy": [(0, 2), (2, 2), (4, 1), (5, 1), (6, 2), (8, 2), (10, 2), (12, 2), (14, 2)],
    "default": [(0, 4), (4, 2), (6, 2), (8, 4), (12, 2), (14, 2)],
}


def _rhythm_kind(req):
    if req.get("busy"):
        return "busy"
    if req.get("spacious"):
        return "spacious"
    if req.get("bouncy"):
        return "bouncy"
    return "default"


def compose_melody(req, seed):
    rnd = random.Random(seed)
    pc, scale = req["key"]
    base = 60 if not req.get("lower") else 48
    if req.get("higher"):
        base += 12
    rhythm = MELODY_RHYTHMS[_rhythm_kind(req)]

    def motif(start_degree):
        degs, d = [], start_degree
        for _ in rhythm:
            degs.append(d)
            d += rnd.choice([-2, -1, -1, 0, 1, 1, 2, 3, -3])
            d = max(-2, min(9, d))
        return degs

    a = motif(rnd.choice([0, 2, 4, 7]))
    b = motif(rnd.choice([2, 4, 5]))
    vary = req.get("vary")
    notes = []
    for bar in range(req["bars"]):
        pos = bar % 4
        if pos == 0:
            degs = a
        elif pos == 1:
            degs = a[:-2] + [d + rnd.choice([-1, 1, 2]) for d in a[-2:]] if not vary else b
        elif pos == 2:
            degs = a if not vary else [d + 2 for d in a]
        else:
            degs = (b[:-1] if not vary else motif(rnd.choice([4, 5]))[:-1]) + [0]  # resolve to the tonic
        steps = rhythm
        if pos == 3:  # let the last note of the phrase ring
            steps = rhythm[:-1] + [(rhythm[-1][0], 16 - rhythm[-1][0])]
        for (s, l), deg in zip(steps, degs):
            vel = 104 if s in (0, 8) else rnd.choice([84, 88, 92, 96])
            notes.append({"pitch": _scale_pitch(pc, scale, deg, base), "start": bar * 4 + s / 4.0,
                          "length": l / 4.0, "velocity": vel})
    return notes


PROGRESSIONS = {"minor": [0, 5, 2, 6], "harmonic minor": [0, 5, 3, 4], "phrygian": [0, 1, 5, 0],
                "dorian": [0, 3, 6, 4], "major": [0, 4, 5, 3]}
BASS_RHYTHMS = {
    "bouncy": [(0, 3), (3, 3), (7, 1), (8, 6), (14, 2)],
    "spacious": [(0, 12), (12, 4)],
    "busy": [(0, 2), (3, 2), (6, 2), (8, 2), (10, 3), (14, 2)],
    "default": [(0, 6), (6, 2), (8, 8)],
}


def compose_bass(req, seed):
    rnd = random.Random(seed + 7)
    pc, scale = req["key"]
    prog = PROGRESSIONS.get(scale, [0, 5, 2, 6])
    rhythm = BASS_RHYTHMS[_rhythm_kind(req)]
    base = 36 if not req.get("higher") else 48  # 808s around C2-C3
    if req.get("lower"):
        base = 24
    notes = []
    for bar in range(req["bars"]):
        root = prog[bar % len(prog)]
        for i, (s, l) in enumerate(rhythm):
            deg = root
            if i == len(rhythm) - 1 and rnd.random() < 0.4:
                deg = root + 7  # octave pop on the last hit
            notes.append({"pitch": _scale_pitch(pc, scale, deg, base), "start": bar * 4 + s / 4.0,
                          "length": l / 4.0, "velocity": 110 if s == 0 else 100})
    return notes


def compose_drums(req, seed):
    """Returns {lane_name: notes}. One-shot hits on pitch 60, 1/16 long unless rolls."""
    rnd = random.Random(seed + 13)
    lanes = {"Kick": [], "Snare": [], "Hi-hat": [], "Open hat": []}
    kick_patterns = [[0, 7, 10], [0, 3, 10], [0, 6, 11], [0, 10, 13]]
    if req.get("bouncy"):
        kick_patterns = [[0, 3, 7, 10], [0, 6, 9, 14], [0, 3, 10, 13]]
    if req.get("spacious"):
        kick_patterns = [[0, 10], [0, 11]]
    hat_step = 1 if req.get("busy") else 2
    for bar in range(req["bars"]):
        off = bar * 4
        for s in rnd.choice(kick_patterns):
            lanes["Kick"].append({"pitch": 60, "start": off + s / 4.0, "length": 0.25, "velocity": 112 if s == 0 else 100})
        lanes["Snare"].append({"pitch": 60, "start": off + 2.0, "length": 0.25, "velocity": 112})
        if req.get("bouncy") and bar % 2 == 1:
            lanes["Snare"].append({"pitch": 60, "start": off + 3.75, "length": 0.25, "velocity": 70})
        roll_bar = (bar % 2 == 1) and not req.get("spacious")
        for s in range(0, 16, hat_step):
            if roll_bar and s >= 12:
                break
            lanes["Hi-hat"].append({"pitch": 60, "start": off + s / 4.0, "length": 0.25,
                                    "velocity": 96 if s % 4 == 0 else 74})
        if roll_bar:
            # last beat: a triplet or 1/32 roll, velocity ramping up
            sub = rnd.choice([1 / 6.0, 1 / 8.0])
            count = int(round(1 / sub))
            for i in range(count):
                lanes["Hi-hat"].append({"pitch": 60, "start": round(off + 3 + i * sub, 6), "length": round(sub, 6),
                                        "velocity": 60 + i * (40 // count)})
        if bar % 2 == 0 and not req.get("spacious"):
            lanes["Open hat"].append({"pitch": 60, "start": off + 3.5, "length": 0.5, "velocity": 80})
    return lanes


# ---------- responder ----------

ROLE_TARGETS = {
    "melody": "Open the Piano Roll of your melody instrument (e.g. a bell, pluck or keys channel).",
    "bass": "Open the Piano Roll of your 808 / bass channel.",
}


def _part(name, role, plan, action):
    target = ROLE_TARGETS.get(role) or ("Open the Piano Roll of your %s channel (a sampler channel with your %s sample)." % (name, name.lower()))
    return {"name": name, "role": role, "action": action, "target_hint": target, "plan": plan}


def _ensemble_channels(layers, channels):
    """Give each layer the user's channel whose name fits the instrument (piano -> 'Piano', 'FLEX Keys'...). Bass-type
    channels only take the 808; one channel per layer."""
    from . import drums as drummod, ensemble
    melodic = [c for c in channels if not drummod.lane_kind(c["name"])]
    taken, out = set(), {}
    for inst, job in sorted(layers, key=lambda l: 0 if l[1] == "bass" else 1):
        words = ensemble.KEYWORDS.get(inst, [])
        bassy = lambda c: any(w in c["name"].lower() for w in ("808", "bass", "sub"))
        pool = [c for c in melodic if c["name"] not in taken and bassy(c) == (job == "bass")]
        pick = next((c for c in pool if any(w in c["name"].lower() for w in words)), None)
        if pick is None and job != "bass":
            pick = next((c for c in pool if ensemble.instrument_from_name(c["name"]) in (None, "lead_synth", inst)), None)
        if pick:
            taken.add(pick["name"])
            out[(inst, job)] = pick["name"]
    return out


def respond(text, settings, existing_parts, seed=None):
    """Build a response for a chat message without an AI model, using the theory and groove engines."""
    from . import genres, producer, theory
    seed = random.randrange(1 << 30) if seed is None else seed
    req = parse_request(text, settings)
    guide_list = guides.match(text)
    wants = set(req["wants"])
    genre = genres.match(text) or settings.get("genre") or "trap"
    if req["dark"] and genre == "trap":
        genre = "dark trap"
    feel = dict(settings.get("feel") or {})
    if req["busy"]:
        feel["fullness"] = max(feel.get("fullness", 50), 75)
    if req["spacious"]:
        feel["fullness"] = min(feel.get("fullness", 50), 25)
    if req["vary"]:
        feel["variation"] = max(feel.get("variation", 50), 80)
    channels = settings.get("_channels") or []
    revising = not wants and existing_parts and (req["vary"] or req["busy"] or req["spacious"] or req["higher"] or req["lower"])
    pc, scale = req["key"]
    klabel = key_label(pc, scale)
    parts = []

    def blank(name, role, purpose, generate=True, register=None):
        return {"name": name, "role": role, "purpose": purpose, "generate": generate, "register": register,
                "action": "revise" if name in existing_parts else "new", "sound": "",
                "target_hint": ROLE_TARGETS.get(role) or "Your %s channel" % name,
                "plan": {"schema": "cadence.melody/1", "title": name, "tempo_bpm": req["tempo"], "time_signature": [4, 4],
                         "key": klabel, "bars": req["bars"], "target": name, "notes": []}}

    groove = None
    if revising:
        for name, e in existing_parts.items():
            role = e.get("role") or "melody"
            if role == "drums":
                groove = {"profile": genre}
            purpose = e.get("purpose") or {"bass": "bass", "chords": "chords", "drums": "drums"}.get(role, "lead")
            parts.append(blank(name, role, purpose))
            parts[-1]["action"] = "revise"
            parts[-1]["keep_name"] = True
    else:
        sample_part = None
        if settings.get("_mode") == "sample":
            wants = {"bass", "drums"}
            loop = settings.get("_sample_bars") or req["bars"]
            loop = max(1, min(req["bars"], int(round(loop)) if loop <= req["bars"] else req["bars"]))
            name = settings.get("_sample_channel") or "Sample"
            sample_part = blank(name, "other", "sample", generate=False)
            sample_part["plan"]["notes"] = [{"pitch": 60, "start": float(b * 4), "length": float(loop * 4), "velocity": 100}
                                            for b in range(0, req["bars"], loop)]
            parts.append(sample_part)
        elif settings.get("_mode") in ("genre", "inspiration") and not wants:
            wants = {"melody", "bass", "drums"}
        from . import ensemble
        recipe = ensemble.RECIPES.get(genre, ensemble.RECIPES["trap"])
        if genre in ("trap", "melodic trap", "melodic rap", "dark trap") and {"melody", "bass"} <= wants:
            recipe = [("keys", "chords"), ("pad", "pad"), ("bell", "lead"), ("pluck", "counter"), ("bass_808", "bass")]
        full_beat = {"melody", "bass", "drums"} <= wants or ({"melody", "bass"} <= wants)
        layers = [(inst, job) for inst, job in recipe if (job == "bass" and "bass" in wants) or
                  (job != "bass" and "melody" in wants and (full_beat or job in ("lead", "chords")))]
        if "melody" in wants and not any(j == "lead" for _, j in layers):
            layers.insert(0, ("bell", "lead"))
        names = _ensemble_channels(layers, channels)
        used = set()
        for inst, job in layers:
            default = {"lead": "Melody", "bass": "808"}.get(job) or inst.replace("_", " ").title().replace("Bass 808", "808")
            name = names.get((inst, job)) or default
            while name in used:
                name += " 2"
            used.add(name)
            role = "bass" if job == "bass" else "chords" if job in ("chords", "pad") else "melody"
            part = blank(name, role, {"sparkle": "bell"}.get(job, job))
            part["instrument"] = inst
            parts.append(part)
        if "drums" in wants:
            groove = {"profile": genre, "energy": 75 if req["busy"] else 35 if req["spacious"] else 60}
    finished, info, problems = producer.finish(parts, {"key": klabel}, groove, settings=dict(settings, bars=req["bars"], tempo_bpm=req["tempo"]),
                                               channels=channels, genre=genre, feel=feel, seed=seed)
    for p in finished:
        p["generate"] = False   # already written by the engines
    if req["higher"] or req["lower"]:
        for p in finished:
            if p["role"] in ("melody", "chords"):
                shift = 12 if req["higher"] else -12
                if all(0 <= n["pitch"] + shift <= 127 for n in p["plan"]["notes"]):
                    for n in p["plan"]["notes"]:
                        n["pitch"] += shift
    if "drums" in wants and not revising:   # "add hats" / "kick and snare": only the lanes asked for
        t = text.lower().replace("-", "").replace("hihat", "hat").replace("hats", "hat")
        only = [k for k in ("kick", "snare", "clap", "hat", "open", "perc") if k in t]
        if only:
            from .grooves import lane_of
            finished = [p for p in finished if p["role"] != "drums" or lane_of(p["name"]) in only or
                        (lane_of(p["name"]) == "open" and "open" in only)]
    tempo_note = "%d BPM, %s, %d bars" % (req["tempo"], key_label(*req["key"]), req["bars"])
    if finished:
        groove_note = (" Drums: %s groove." % info["groove"]["label"]) if info.get("groove") else ""
        chords = " ".join(c["symbol"] for c in info["harmony"][:4])
        reply = ("Offline draft (%s, chords %s): %s.%s Built by Veloura's theory and groove engines, not an AI model; connect "
                 "ChatGPT (recommended) in Settings for full production judgment." % (tempo_note, chords, ", ".join(p["name"] for p in finished), groove_note))
    elif guide_list:
        reply = "This one needs a manual step in FL Studio. Guided steps below."
    else:
        reply = ("The offline composer understands melody, 808/bass, drums, hats, a genre, a key, a BPM, 'less repetitive', "
                 "'simpler', 'busier' and 'octave up/down'. Connect an AI provider in Settings for full conversation.")
    return {"reply": reply, "parts": finished, "guidance": guide_list, "provider": "offline", "info": info,
            "problems": problems}
