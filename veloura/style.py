"""Style library: learn from the user's own MIDI (their beats, or MIDI packs they like).

This is Veloura's practical form of "training": instead of retraining a model, it extracts what makes those
files sound the way they do (drum grooves with their velocities, chord progressions, motif rhythms) and
  * lets the groove engine reuse the user's grooves for that genre (with Veloura's fills and dropouts on top),
  * shows the AI a few compact examples of the user's style with every request.
Everything stays local in data/style.json.
"""

import json
import os
import re
import struct
import time

from . import theory

GM = {35: "kick", 36: "kick", 37: "snare", 38: "snare", 40: "snare", 39: "clap", 42: "hat", 44: "hat", 46: "open",
      41: "perc", 43: "perc", 45: "perc", 47: "perc", 48: "perc", 50: "perc", 49: "open", 51: "open", 54: "perc", 56: "perc",
      60: "perc", 61: "perc", 62: "perc", 63: "perc", 64: "perc", 69: "perc", 70: "perc", 75: "perc", 76: "perc"}
LANE_NAMES = {"kick": "Kick", "snare": "Snare", "clap": "Clap", "hat": "Hi-hat", "open": "Open hat", "perc": "Perc"}


def _vlq(data, pos):
    n = 0
    while True:
        b = data[pos]
        pos += 1
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            return n, pos


def read_midi(path):
    """Notes with channel and track: {ppq, tempo, tracks: [{name, notes: [{pitch, start, length, velocity, channel}]}]}
    (start/length in beats)."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MThd":
        raise ValueError("Not a MIDI file")
    _, fmt, ntracks, ppq = struct.unpack(">IHHH", data[4:14])
    if ppq & 0x8000:
        raise ValueError("SMPTE-timed MIDI isn't supported")
    pos, tempo, tracks = 8 + struct.unpack(">I", data[4:8])[0], None, []
    for _ in range(ntracks):
        if data[pos:pos + 4] != b"MTrk":
            break
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        pos += 8
        end = pos + length
        tick, status, opened, notes, name = 0, None, {}, [], ""
        while pos < end:
            delta, pos = _vlq(data, pos)
            tick += delta
            b = data[pos]
            if b == 0xFF:
                mtype = data[pos + 1]
                mlen, p2 = _vlq(data, pos + 2)
                body = data[p2:p2 + mlen]
                pos = p2 + mlen
                if mtype == 0x51 and tempo is None:
                    tempo = round(60_000_000 / int.from_bytes(body, "big"), 2)
                elif mtype == 0x03:
                    name = body.decode("latin-1", "ignore")
                continue
            if b in (0xF0, 0xF7):
                slen, p2 = _vlq(data, pos + 1)
                pos = p2 + slen
                continue
            if b & 0x80:
                status = b
                pos += 1
            kind, ch = status & 0xF0, status & 0x0F
            if kind in (0x80, 0x90):
                pitch, vel = data[pos], data[pos + 1]
                pos += 2
                if kind == 0x90 and vel > 0:
                    opened.setdefault((ch, pitch), []).append((tick, vel))
                elif opened.get((ch, pitch)):
                    st, v = opened[(ch, pitch)].pop(0)
                    notes.append({"pitch": pitch, "start": st / ppq, "length": max(1, tick - st) / ppq, "velocity": v, "channel": ch})
            elif kind in (0xC0, 0xD0):
                pos += 1
            else:
                pos += 2
        pos = end
        if notes:
            tracks.append({"name": name, "notes": sorted(notes, key=lambda n: (n["start"], n["pitch"]))})
    return {"ppq": ppq, "tempo": tempo, "tracks": tracks}


def _is_drums(track, filename):
    notes = track["notes"]
    if not notes:
        return False
    if all(n["channel"] == 9 for n in notes):
        return True
    txt = (track.get("name", "") + " " + filename).lower()
    if any(w in txt for w in ("drum", "kick", "hat", "snare", "perc", "808 kick")):
        return True
    return False


def _lane_for(filename_or_track, pitch):
    t = filename_or_track.lower()
    for w, lane in (("open", "open"), ("kick", "kick"), ("clap", "clap"), ("snare", "snare"), ("hat", "hat"), ("hh", "hat"), ("perc", "perc")):
        if w in t:
            return lane
    return GM.get(pitch)


def analyze(path, genre=None):
    """What Veloura learns from one MIDI file."""
    mid = read_midi(path)
    fname = os.path.splitext(os.path.basename(path))[0]
    lanes, melodic = {}, []
    for tr in mid["tracks"]:
        if _is_drums(tr, fname):
            hint = tr.get("name") or fname
            for n in tr["notes"]:
                lane = _lane_for(hint, n["pitch"])
                if lane:
                    lanes.setdefault(lane, []).append(n)
        else:
            melodic += tr["notes"]
    out = {"file": os.path.basename(path), "genre": genre, "tempo": mid["tempo"], "added": time.strftime("%Y-%m-%d %H:%M")}
    if lanes:
        bars = max(1, min(8, int(max(n["start"] for v in lanes.values() for n in v) // 4) + 1))
        out["groove"] = {"bars": bars, "lanes": {LANE_NAMES[l]: [{"pitch": 60, "start": round(round(n["start"] * 4) / 4, 6), "length": 0.25,
                                                                  "velocity": int(n["velocity"])} for n in v if n["start"] < bars * 4]
                                                 for l, v in lanes.items()}}
    if melodic:
        hist = [0] * 12
        for n in melodic:
            hist[n["pitch"] % 12] += n["length"]
        key = _best_key(hist)
        bars = max(1, min(16, int(max(n["start"] for n in melodic) // 4) + 1))
        plan_notes = [{"pitch": n["pitch"], "start": n["start"], "length": n["length"], "velocity": n["velocity"]} for n in melodic if n["start"] < bars * 4]
        harmony = theory.infer_harmony([{"role": "melody", "plan": {"notes": plan_notes}}], key, bars)
        top = theory.topline(plan_notes)
        out["melody"] = {"key": theory.key_label(*key), "bars": bars, "chords": [h["symbol"] for h in harmony],
                         "rhythm_16ths": sorted({int(round((n["start"] % 4) * 4)) for n in top})[:16],
                         "notes_per_bar": round(len(top) / bars, 1), "range": [min(n["pitch"] for n in top), max(n["pitch"] for n in top)]}
    if "groove" not in out and "melody" not in out:
        raise ValueError("No notes in that file")
    return out


def _best_key(hist):
    best, score = (0, "minor"), -1
    for pc in range(12):
        for mode in ("minor", "major"):
            sc = set((pc + i) % 12 for i in theory.SCALES[mode])
            s = sum(h for i, h in enumerate(hist) if i in sc) + 0.5 * hist[pc]
            if s > score:
                best, score = (pc, mode), s
    return best


def _pattern_string(notes, bar=0):
    hits = {int(round((n["start"] - bar * 4) * 4)): n["velocity"] for n in notes if bar * 4 <= n["start"] < bar * 4 + 4}
    return "".join(("X" if hits[i] >= 100 else "x" if hits[i] >= 75 else "o") if i in hits else "." for i in range(16))


class StyleLibrary:
    def __init__(self, path):
        self.path = path
        self.data = {"items": []}
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)

    def import_path(self, path, genre=None):
        """A .mid file or a folder of them. Returns {"added": n, "skipped": [...]}."""
        files = []
        if os.path.isdir(path):
            for dp, dn, fn in os.walk(path):
                files += [os.path.join(dp, f) for f in fn if f.lower().endswith((".mid", ".midi"))]
        else:
            files = [path]
        added, skipped = 0, []
        for f in files[:500]:
            g = genre or _genre_from_path(f)
            try:
                item = analyze(f, g)
            except (ValueError, IndexError, struct.error) as e:
                skipped.append("%s: %s" % (os.path.basename(f), e))
                continue
            item["id"] = "%x" % (abs(hash((f, os.path.getmtime(f)))) % (1 << 40))
            self.data["items"] = [i for i in self.data["items"] if i.get("file") != item["file"] or i.get("genre") != g] + [item]
            added += 1
        self.save()
        return {"added": added, "skipped": skipped[:20], "total": len(self.data["items"])}

    def remove(self, item_id):
        self.data["items"] = [i for i in self.data["items"] if i.get("id") != item_id]
        self.save()

    def summary(self):
        items = self.data["items"]
        return {"total": len(items), "grooves": sum(1 for i in items if i.get("groove")), "melodies": sum(1 for i in items if i.get("melody")),
                "items": [{"id": i.get("id"), "file": i["file"], "genre": i.get("genre"), "groove": bool(i.get("groove")),
                           "melody": (i.get("melody") or {}).get("chords", [])[:4], "key": (i.get("melody") or {}).get("key")} for i in items[-200:]]}

    def grooves_for(self, genre):
        g = (genre or "").lower()
        return [i["groove"] for i in self.data["items"] if i.get("groove") and (not g or (i.get("genre") or "").lower() in (g, ""))]

    def examples_for_ai(self, genre, limit=3):
        """Compact examples of the user's style for the prompt."""
        out = []
        g = (genre or "").lower()
        items = [i for i in self.data["items"] if (i.get("genre") or "").lower() == g] or self.data["items"]
        for i in items[-limit:]:
            ex = {"from": i["file"]}
            if i.get("groove"):
                ex["drums_bar1"] = {lane: _pattern_string(notes) for lane, notes in i["groove"]["lanes"].items()}
            if i.get("melody"):
                ex["melody"] = {k: i["melody"][k] for k in ("key", "chords", "rhythm_16ths", "notes_per_bar")}
            out.append(ex)
        return out


def _genre_from_path(path):
    t = path.lower()
    for g in ("melodic plugg", "pluggnb", "plugg", "rage", "jerk", "drill", "detroit", "dark trap", "trap", "boom bap", "r&b", "rnb", "ambient", "cloud"):
        if re.search(r"\b%s\b" % re.escape(g), t):
            return {"pluggnb": "melodic plugg", "rnb": "r&b", "cloud": "cloud rap"}.get(g, g)
    return None
