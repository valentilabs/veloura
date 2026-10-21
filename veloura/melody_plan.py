"""Melody plan: the structured, validated musical data Veloura works with.

Timing convention (used everywhere in Veloura):
  * Positions and lengths are in BEATS, where 1 beat = 1 quarter note.
  * Every value must sit on a grid of 1/96 beat (GRID_PER_BEAT).
  * FL Studio stores note times in ticks. The FL bridge script converts with
    ticks = round(beats * PPQ), reading PPQ from FL Studio at run time.
  * Velocity is MIDI-style, 1-127. FL stores velocity as 0.0-1.0, so the
    bridge writes velocity / 127.

Nothing in a plan is ever executed as code. A plan that fails validation is
rejected before anything is sent to FL Studio.
"""

import json
import math

SCHEMA = "cadence.melody/1"
GRID_PER_BEAT = 96
MAX_NOTES = 256
MAX_BARS = 16

ALLOWED_KEYS = {"schema", "title", "tempo_bpm", "time_signature", "key", "bars", "target", "notes"}
REQUIRED_KEYS = {"schema", "tempo_bpm", "time_signature", "bars", "notes"}
NOTE_KEYS = {"pitch", "start", "length", "velocity"}


class PlanError(ValueError):
    """Raised when a plan is invalid. `problems` lists every issue found."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _on_grid(beats):
    # Tolerates rounding such as 0.166667 for 1/6 beat (within 1/100 of a grid step).
    scaled = beats * GRID_PER_BEAT
    return abs(scaled - round(scaled)) < 0.01


def _snap(beats):
    return round(beats * GRID_PER_BEAT) / GRID_PER_BEAT


def beats_to_ticks(beats, ppq):
    """Convert beats to integer ticks. Returns (ticks, exact)."""
    raw = beats * ppq
    ticks = int(round(raw))
    return ticks, abs(raw - ticks) < 1e-6


def validate_plan(data, repairs=None):
    """Check a melody plan and return a normalized copy. Raises PlanError for real errors.

    Harmless imprecision is repaired instead of rejected (and described in `repairs` if a list is given):
    starts and lengths are snapped to the 1/96-beat grid (at most 1/192 beat, about 2 ms, of change), and
    overlapping notes of the same pitch are trimmed so the earlier one ends where the next begins.
    """
    if repairs is None:
        repairs = []
    problems = []
    if not isinstance(data, dict):
        raise PlanError(["Plan must be a JSON object."])

    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        problems.append("Unknown field(s): %s" % ", ".join(sorted(unknown)))
    missing = REQUIRED_KEYS - set(data)
    if missing:
        problems.append("Missing field(s): %s" % ", ".join(sorted(missing)))
    if problems:
        raise PlanError(problems)

    if data["schema"] != SCHEMA:
        problems.append("schema must be %r" % SCHEMA)

    tempo = data["tempo_bpm"]
    if not _is_number(tempo) or not (20 <= tempo <= 999):
        problems.append("tempo_bpm must be a number from 20 to 999")

    ts = data["time_signature"]
    if not (isinstance(ts, list) and len(ts) == 2 and all(_is_int(v) for v in ts)):
        problems.append("time_signature must be [numerator, denominator], e.g. [4, 4]")
    elif ts != [4, 4]:
        problems.append("Only 4/4 is supported in Stage 1")

    bars = data["bars"]
    if not _is_int(bars) or not (1 <= bars <= MAX_BARS):
        problems.append("bars must be a whole number from 1 to %d" % MAX_BARS)
        bars = None

    for field in ("title", "key", "target"):
        if field in data and not isinstance(data[field], str):
            problems.append("%s must be text" % field)

    notes = data["notes"]
    if not isinstance(notes, list) or not notes:
        problems.append("notes must be a non-empty list")
        raise PlanError(problems)
    if len(notes) > MAX_NOTES:
        problems.append("Too many notes (%d); the limit is %d" % (len(notes), MAX_NOTES))

    pattern_beats = bars * 4 if bars else None
    clean = []
    snapped = trimmed = 0
    for i, n in enumerate(notes, start=1):
        where = "note %d" % i
        if not isinstance(n, dict):
            problems.append("%s must be an object" % where)
            continue
        if set(n) != NOTE_KEYS:
            problems.append("%s must have exactly: pitch, start, length, velocity" % where)
            continue
        pitch, start, length, vel = n["pitch"], n["start"], n["length"], n["velocity"]
        ok = True
        if not _is_int(pitch) or not (0 <= pitch <= 127):
            problems.append("%s: pitch must be a whole number 0-127 (got %r)" % (where, pitch))
            ok = False
        if not _is_int(vel) or not (1 <= vel <= 127):
            problems.append("%s: velocity must be a whole number 1-127 (got %r)" % (where, vel))
            ok = False
        if not _is_number(start) or start < 0:
            problems.append("%s: start must be a number of beats >= 0 (got %r)" % (where, start))
            ok = False
        if not _is_number(length) or length <= 0:
            problems.append("%s: length must be a number of beats > 0 (got %r)" % (where, length))
            ok = False
        if not ok:
            continue
        if not (_on_grid(start) and _on_grid(length)):
            snapped += 1
        start, length = _snap(start), max(_snap(length), 1.0 / GRID_PER_BEAT)
        if pattern_beats is not None and start >= pattern_beats - 1e-9:
            problems.append("%s: starts at beat %g, after the end of the %d-bar pattern" % (where, start, bars))
            continue
        if pattern_beats is not None and start + length > pattern_beats + 1e-9:
            if start + length - pattern_beats <= 0.25 + 1e-9:   # a hair over the loop end: trim it
                length = pattern_beats - start
                trimmed += 1
            else:
                problems.append("%s: ends at beat %g, past the end of the %d-bar pattern" % (where, start + length, bars))
                continue
        clean.append({"pitch": pitch, "start": start, "length": length, "velocity": vel})

    if problems:
        raise PlanError(problems)

    # Same-pitch notes may not overlap in FL: drop exact duplicates, trim an earlier note to end where the next begins.
    by_pitch = {}
    for n in clean:
        by_pitch.setdefault(n["pitch"], []).append(n)
    kept, dupes, overlaps = [], 0, 0
    for pitch, group in by_pitch.items():
        group.sort(key=lambda n: (n["start"], -n["length"]))
        prev = None
        for n in group:
            if prev is not None and abs(n["start"] - prev["start"]) < 1e-9:
                dupes += 1
                continue
            if prev is not None and n["start"] < prev["start"] + prev["length"] - 1e-9:
                prev["length"] = round(n["start"] - prev["start"], 6)
                overlaps += 1
            kept.append(n)
            prev = n
    clean = kept
    if snapped:
        repairs.append("%d note time(s) snapped to the 1/%d-beat grid" % (snapped, GRID_PER_BEAT))
    if trimmed:
        repairs.append("%d note(s) trimmed to end at the loop end" % trimmed)
    if overlaps:
        repairs.append("%d overlapping same-pitch note(s) shortened" % overlaps)
    if dupes:
        repairs.append("%d duplicate note(s) removed" % dupes)

    clean.sort(key=lambda n: (n["start"], n["pitch"]))
    out = {k: data[k] for k in data if k != "notes"}
    out["notes"] = clean
    return out


def load_plan(path):
    """Read and validate a plan file. Raises PlanError."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise PlanError(["File not found: %s" % path])
    except json.JSONDecodeError as e:
        raise PlanError(["Not valid JSON: %s" % e])
    return validate_plan(data)
