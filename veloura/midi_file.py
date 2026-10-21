"""Standard MIDI File export (Mode C fallback) and a reader to verify exports.

Writes a format-0 file at 96 ticks per quarter note: one track holding tempo,
time signature, key signature (when the key is recognised) and the notes on
MIDI channel 1. FL Studio can import it (File > Import > MIDI file) or you can
drag it onto a channel.
"""

import os
import struct

from .melody_plan import beats_to_ticks

FILE_PPQ = 96

_MAJOR = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "C#": 7,
          "F": -1, "Bb": -2, "Eb": -3, "Ab": -4, "Db": -5, "Gb": -6, "Cb": -7}
_MINOR = {"A": 0, "E": 1, "B": 2, "F#": 3, "C#": 4, "G#": 5, "D#": 6, "A#": 7,
          "D": -1, "G": -2, "C": -3, "F": -4, "Bb": -5, "Eb": -6, "Ab": -7}


def parse_key(text):
    """'F minor' -> (sharps_or_flats, is_minor), or None if not recognised."""
    if not text:
        return None
    parts = text.replace("♭", "b").replace("♯", "#").split()
    if len(parts) != 2:
        return None
    tonic = parts[0][:1].upper() + parts[0][1:]
    mode = parts[1].lower()
    if mode in ("minor", "min", "m"):
        return (_MINOR[tonic], 1) if tonic in _MINOR else None
    if mode in ("major", "maj"):
        return (_MAJOR[tonic], 0) if tonic in _MAJOR else None
    return None


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def build_midi_bytes(plan):
    events = []  # (tick, order, data); note-offs sort before note-ons at the same tick
    title = (plan.get("title") or "Veloura melody").encode("utf-8")[:120]
    events.append((0, 0, b"\xff\x03" + _vlq(len(title)) + title))
    us_per_quarter = int(round(60_000_000 / plan["tempo_bpm"]))
    events.append((0, 0, b"\xff\x51\x03" + us_per_quarter.to_bytes(3, "big")))
    num, den = plan["time_signature"]
    events.append((0, 0, bytes([0xFF, 0x58, 0x04, num, den.bit_length() - 1, 24, 8])))
    key = parse_key(plan.get("key"))
    if key:
        events.append((0, 0, bytes([0xFF, 0x59, 0x02, key[0] & 0xFF, key[1]])))
    for n in plan["notes"]:
        start, _ = beats_to_ticks(n["start"], FILE_PPQ)
        length, _ = beats_to_ticks(n["length"], FILE_PPQ)
        events.append((start, 2, bytes([0x90, n["pitch"], n["velocity"]])))
        events.append((start + length, 1, bytes([0x80, n["pitch"], 0])))
    events.sort(key=lambda e: (e[0], e[1]))

    track = bytearray()
    last = 0
    for tick, _, data in events:
        track += _vlq(tick - last) + data
        last = tick
    track += b"\x00\xff\x2f\x00"
    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, FILE_PPQ)
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def write_midi(plan, path):
    """Write the plan to a new .mid file. Refuses to overwrite an existing file."""
    if os.path.exists(path):
        raise FileExistsError("%s already exists; choose a new file name." % path)
    data = build_midi_bytes(plan)
    with open(path, "xb") as f:
        f.write(data)
    return path


def read_midi(path):
    """Parse a MIDI file into {ppq, tempo_bpm, time_signature, key, notes}."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"MThd":
        raise ValueError("Not a MIDI file")
    _, fmt, ntracks, ppq = struct.unpack(">IHHH", data[4:14])
    pos = 14
    info = {"ppq": ppq, "format": fmt, "tempo_bpm": None, "time_signature": None, "key": None, "notes": []}
    for _ in range(ntracks):
        assert data[pos:pos + 4] == b"MTrk", "bad track header"
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        pos += 8
        end = pos + length
        tick = 0
        status = None
        open_notes = {}
        while pos < end:
            delta = 0
            while True:
                b = data[pos]
                pos += 1
                delta = (delta << 7) | (b & 0x7F)
                if not b & 0x80:
                    break
            tick += delta
            b = data[pos]
            if b == 0xFF:
                mtype, mlen = data[pos + 1], data[pos + 2]
                body = data[pos + 3:pos + 3 + mlen]
                pos += 3 + mlen
                if mtype == 0x51:
                    info["tempo_bpm"] = round(60_000_000 / int.from_bytes(body, "big"), 3)
                elif mtype == 0x58:
                    info["time_signature"] = [body[0], 2 ** body[1]]
                elif mtype == 0x59:
                    sf = body[0] - 256 if body[0] > 127 else body[0]
                    info["key"] = (sf, body[1])
                continue
            if b & 0x80:
                status = b
                pos += 1
            kind = status & 0xF0
            if kind in (0x80, 0x90):
                pitch, vel = data[pos], data[pos + 1]
                pos += 2
                if kind == 0x90 and vel > 0:
                    open_notes.setdefault(pitch, []).append((tick, vel))
                elif open_notes.get(pitch):
                    start, v = open_notes[pitch].pop(0)
                    info["notes"].append({"pitch": pitch, "start_tick": start, "length_ticks": tick - start, "velocity": v})
            elif kind in (0xC0, 0xD0):
                pos += 1
            else:
                pos += 2
        pos = end
    info["notes"].sort(key=lambda n: (n["start_tick"], n["pitch"]))
    return info


def verify_midi(plan, path):
    """Compare an exported file with the plan. Returns a list of problems (empty = match)."""
    info = read_midi(path)
    problems = []
    expected = sorted(
        (n["pitch"], beats_to_ticks(n["start"], info["ppq"])[0], beats_to_ticks(n["length"], info["ppq"])[0], n["velocity"])
        for n in plan["notes"]
    )
    actual = sorted((n["pitch"], n["start_tick"], n["length_ticks"], n["velocity"]) for n in info["notes"])
    if expected != actual:
        problems.append("Notes differ: expected %d, found %d (or values differ)" % (len(expected), len(actual)))
    if info["tempo_bpm"] is None or abs(info["tempo_bpm"] - plan["tempo_bpm"]) > 0.01:
        problems.append("Tempo differs: %s" % info["tempo_bpm"])
    if info["time_signature"] != list(plan["time_signature"]):
        problems.append("Time signature differs: %s" % info["time_signature"])
    return problems
