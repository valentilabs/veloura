"""Drum lanes -> FL step sequencer (via the Veloura Controller).

Pure helpers, no FL access: match a lane to a loaded Channel Rack channel by
name, and turn a lane's plan into 16th-note steps. A lane that is not on the
16th grid (e.g. 1/32 hi-hat rolls) cannot be written as steps; Veloura then
uses the Piano Roll bridge for it.
"""

import re

LANE_ALIASES = {
    "kick": ("kick", "kck", "bd", "bass drum"),
    "snare": ("snare", "snr", "sd", "rim"),
    "clap": ("clap", "clp"),
    "hi-hat": ("hat", "hh", "hihat", "hi hat", "closed"),
    "open hat": ("open", "oh", "ohh"),
    "perc": ("perc", "shaker", "tamb", "conga", "bongo"),
}


def _norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def lane_kind(part_name):
    n = _norm(part_name)
    if "open" in n:
        return "open hat"
    for kind in ("kick", "snare", "clap", "hi-hat", "perc"):
        if any(a in n for a in LANE_ALIASES[kind]) or kind.replace("-", " ") in n:
            return kind
    return None


def _matches(kind, name):
    n = _norm(name)
    tokens = set(n.split())
    if kind == "hi-hat" and ("open" in n or "oh" in tokens):
        return False  # an open hat is not the closed hi-hat lane
    if kind == "kick" and "808" in n and "kick" not in n:
        return False  # an 808 bass channel is not the kick
    for alias in LANE_ALIASES[kind]:
        if (len(alias) <= 3 and alias in tokens) or (len(alias) > 3 and alias in n):
            return True
    return False


def match_channel(part_name, channels, prefer=None):
    """Pick the Channel Rack channel for a drum lane. Returns (channel dict, reason) or (None, reason).
    prefer: channel names to choose when several look right (e.g. the kit Veloura just staged)."""
    kind = lane_kind(part_name)
    if kind is None:
        return None, "Veloura doesn't know which kind of drum %r is." % part_name
    if prefer:   # the kit Veloura picked for this beat beats FL's stock channels, even one with the exact same name
        kit = [c for c in channels if _matches(kind, c["name"])
               and (c["name"] in prefer or any(c["name"].startswith(p) for p in prefer))]
        if len(kit) == 1:
            return kit[0], "the kit Veloura staged"
    exact = [c for c in channels if _norm(c["name"]) == _norm(part_name)]
    if len(exact) == 1:
        return exact[0], "exact name match"
    hits = [c for c in channels if _matches(kind, c["name"])]
    if len(hits) == 1:
        return hits[0], "name looks like a %s" % kind
    if len(hits) > 1 and prefer:
        pref = [c for c in hits if c["name"] in prefer or any(c["name"].startswith(p) for p in prefer)]
        if len(pref) == 1:
            return pref[0], "the kit Veloura staged"
    if len(hits) > 1:
        return None, "Several channels look like a %s (%s); rename one so Veloura can tell them apart." % (
            kind, ", ".join(repr(c["name"]) for c in hits))
    return None, "No channel named like a %s in your Channel Rack. Load one (or rename it), or use its Piano Roll." % kind


# FL's per-step shift parameter didn't behave as documented in FL 2024 (read back as -1, 2026-10-14), so swung
# notes are NOT turned into shifted steps; they go to the Piano Roll, which keeps exact timing.
MAX_SWING_SHIFT = 0.0


def plan_to_steps(plan):
    """Returns (steps, problem). steps covers every 16th in the plan: [{step, on, velocity[, shift]}].
    Swung notes (slightly after their 16th) become steps with a shift; rolls between 16ths can't be steps."""
    count = plan["bars"] * 16
    on, shift = {}, {}
    for n in plan["notes"]:
        pos = n["start"] * 4
        base = int(pos + 1e-6)
        frac = pos - base
        if frac > 1e-6 and frac > MAX_SWING_SHIFT:
            return None, "this lane has notes between 16ths (e.g. rolls), which the step sequencer can't hold"
        if base in on:
            return None, "this lane has notes between 16ths (e.g. rolls), which the step sequencer can't hold"
        on[base] = n["velocity"]
        if frac > 1e-6:
            shift[base] = round(frac, 4)
    steps = []
    for s in range(count):
        st = {"step": s, "on": s in on, "velocity": on.get(s)}
        if s in shift:
            st["shift"] = shift[s]
        steps.append(st)
    return steps, None


def steps_equal(a, b, check_velocity=True):
    """Compare two step lists on the steps they share (on/off, and velocity of 'on' steps)."""
    bm = {s["step"]: s for s in b}
    for s in a:
        t = bm.get(s["step"])
        if t is None or bool(s["on"]) != bool(t["on"]):
            return False
        if check_velocity and s["on"] and s.get("velocity") is not None and t.get("velocity") is not None \
                and abs(s["velocity"] - t["velocity"]) > 1:
            return False
    return True


def deswing(plan):
    """Swung notes back onto the 16th grid, plus the swing amount (0..1) to set on FL's own swing knob (FL 2026+).
    Rolls (notes closer than a 16th) are left alone, so a lane with rolls still needs the Piano Roll."""
    offsets, notes = [], []
    for n in plan["notes"]:
        pos = n["start"] * 4
        base = int(pos + 1e-6)
        frac = pos - base
        if 1e-6 < frac <= 0.45 and base % 2 == 1:
            offsets.append(frac)
            n = dict(n, start=round(base / 4.0, 6), length=round(n["length"] + frac / 4.0, 6))
        notes.append(n)
    amount = (sum(offsets) / len(offsets)) * 3 if offsets else 0.0     # swing a/12 beats = a/3 of a 16th
    return dict(plan, notes=notes), round(amount, 3)
