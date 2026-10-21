"""Drum Library: index the user's drum-kit folders, classify every sound, and pick kits for a beat.

Everything stays on this Mac (data/library.json). Original files are never moved, renamed or changed:
Veloura reads them, and when a kit is staged for FL it COPIES the chosen files into
~/Music/Veloura Kit/<kit name>/ with clear names.

Classification uses, in order of trust: words in the file name, words in the folder names, and (for files
still uncertain) a short audio analysis (length, brightness, low-end weight, pitchedness). A category that
can't be decided is stored as "uncertain" instead of a guess, and the user can correct any sound.

Why staging instead of loading: FL Studio's scripting API cannot load samples into channels, and FL ignores
"open this file" requests for audio (checked 2026-10-14: `open -a "FL Studio 2024" file.wav` added nothing).
So Veloura prepares the kit and the user drags each sound onto its channel; Veloura then checks the
channel names to confirm what landed.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time

AUDIO_EXT = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a")
CATEGORIES = ["kick", "snare", "clap", "hat", "open hat", "perc", "808", "fx", "loop", "uncertain"]
CATEGORY_LABELS = {"kick": "Kicks", "snare": "Snares", "clap": "Claps", "hat": "Closed hats", "open hat": "Open hats",
                   "perc": "Percussion", "808": "808s & bass", "fx": "FX & textures", "loop": "Loops", "uncertain": "Unsorted"}
WORDS = {
    "open hat": ["openhat", "open hat", "open hh", "ohh", "oh", "openhh", "open_hat", "ophat", "crash", "ride", "cymbal"],
    "hat": ["hihat", "hi hat", "hat", "hh", "chh", "closedhat", "closed", "hats"],
    "kick": ["kick", "kik", "kck", "bd", "bassdrum", "kicks"],
    "snare": ["snare", "snr", "sd", "rim", "rimshot", "snares"],
    "clap": ["clap", "clp", "claps", "snap", "snaps"],
    "perc": ["perc", "percs", "percussion", "shaker", "tamb", "tambourine", "conga", "bongo", "cowbell", "tom", "toms",
             "block", "clave", "triangle", "agogo", "guiro", "woodblock", "bell"],
    "808": ["808", "808s", "bass", "sub", "subbass", "reese", "slide"],
    "fx": ["fx", "sfx", "riser", "impact", "sweep", "noise", "texture", "vox", "vocal", "chant", "tag", "ambience",
           "transition", "reverse", "rev", "downlifter", "uplifter", "whoosh", "foley", "atmos"],
    "loop": ["loop", "loops", "bpm", "melody", "melodies", "midi"],
}
CHARACTER_WORDS = ["punchy", "hard", "heavy", "dirty", "dist", "distorted", "soft", "dry", "wet", "crisp", "tight", "short",
                   "long", "dark", "bright", "lofi", "lo-fi", "analog", "vinyl", "clean", "fat", "deep", "thin", "warm",
                   "trap", "drill", "plugg", "rage", "jerk", "detroit", "boom", "bap", "rnb", "pluggnb", "ambient",
                   "glitch", "gritty", "huge", "big", "small", "airy", "metallic", "wood", "acoustic", "live"]
GENRE_TASTE = {   # character words a genre likes and dislikes
    "trap": (["punchy", "hard", "crisp", "trap", "tight", "big"], ["lofi", "vinyl", "acoustic", "live"]),
    "dark trap": (["dark", "dirty", "gritty", "heavy", "hard"], ["bright", "clean", "airy"]),
    "plugg": (["soft", "bright", "clean", "plugg", "airy", "pluggnb"], ["dist", "distorted", "dirty", "heavy"]),
    "melodic plugg": (["soft", "bright", "airy", "plugg", "pluggnb", "clean"], ["dist", "dirty", "heavy"]),
    "rage": (["hard", "dist", "distorted", "dirty", "huge", "big", "rage"], ["soft", "lofi", "acoustic"]),
    "jerk": (["punchy", "tight", "jerk", "crisp", "short", "dry"], ["long", "wet", "ambient"]),
    "drill": (["drill", "dark", "tight", "crisp", "hard"], ["soft", "bright", "lofi"]),
    "melodic rap": (["clean", "punchy", "warm", "crisp"], ["dist", "dirty"]),
    "detroit": (["punchy", "short", "dry", "detroit", "tight"], ["long", "ambient", "wet"]),
    "ambient": (["soft", "airy", "wet", "warm", "ambient", "lofi"], ["hard", "dist", "distorted"]),
    "boom bap": (["vinyl", "lofi", "acoustic", "boom", "bap", "warm", "dry", "live"], ["trap", "dist", "808"]),
    "r&b": (["soft", "warm", "clean", "rnb", "crisp"], ["dist", "dirty", "hard"]),
    "pop": (["clean", "punchy", "bright", "crisp"], ["dirty", "lofi"]),
}
KIT_ROLES = ["kick", "snare", "clap", "hat", "open hat", "perc", "808"]
STAGE_ROOT = os.path.expanduser("~/Music/Veloura Kit")
ANALYZE_LIMIT = 400


def _tokens(text):
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = text.lower().replace("hi-hat", "hihat").replace("hi hat", "hihat").replace("open hat", "openhat")
    return [t for t in re.split(r"[^a-z0-9]+", text) if t]


def _match(tokens, words):
    joined = " ".join(tokens)
    hits = 0
    for w in words:
        if " " in w:
            hits += w in joined
        elif w in tokens:
            hits += 1
        elif len(w) >= 4 and any(t.startswith(w) or (len(t) > 4 and w in t) for t in tokens):
            hits += 1
    return hits


def classify_name(path, root=None):
    """(category, confidence 0..1, source) from the file and folder names."""
    rel = os.path.relpath(path, root) if root else os.path.basename(path)
    parts = rel.split(os.sep)
    fname = os.path.splitext(parts[-1])[0]
    ft = _tokens(fname)
    folder_t = [t for p in parts[:-1] for t in _tokens(p)]

    def score(tokens):
        sc = {c: _match(tokens, WORDS[c]) for c in WORDS}
        if sc["open hat"]:
            sc["hat"] = 0
        if sc["808"] and (sc["kick"] or sc["snare"] or sc["clap"] or sc["hat"] or sc["open hat"] or sc["perc"]):
            sc["808"] = 0   # "808 Kick": 808 names the kit, not the sound
        if sc["loop"] and any(sc[c] for c in ("kick", "snare", "hat", "clap")) and "loop" not in tokens and "loops" not in tokens:
            sc["loop"] = 0
        return {c: v for c, v in sc.items() if v}

    fs = score(ft)
    if len(fs) == 1:
        return next(iter(fs)), 0.95, "file name"
    if len(fs) > 1:
        best = sorted(fs.items(), key=lambda kv: -kv[1])
        if best[0][1] > best[1][1]:
            return best[0][0], 0.75, "file name"
    ds = score(folder_t[-2:]) or score(folder_t)
    if fs and ds:
        both = [c for c in fs if c in ds]
        if len(both) == 1:
            return both[0], 0.8, "file + folder name"
    if len(ds) == 1 and not fs:
        return next(iter(ds)), 0.7, "folder name"
    return "uncertain", 0.0, "names didn't say"


def character(path):
    t = _tokens(os.path.relpath(path, os.path.dirname(os.path.dirname(path))))
    return sorted({w for w in CHARACTER_WORDS if w in t or (len(w) > 4 and any(w in x for x in t))})


def _meta(path):
    info = {"size": os.path.getsize(path)}
    try:
        import soundfile
        si = soundfile.info(path)
        info.update({"duration": round(si.frames / float(si.samplerate), 3), "sample_rate": si.samplerate,
                     "channels": si.channels, "format": si.format})
    except Exception:
        if path.lower().endswith(".wav"):
            try:
                import wave
                with wave.open(path) as w:
                    info.update({"duration": round(w.getnframes() / float(w.getframerate()), 3),
                                 "sample_rate": w.getframerate(), "channels": w.getnchannels(), "format": "WAV"})
            except Exception:
                pass
    return info


def _fingerprint(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(65536))
    return "%d-%s" % (os.path.getsize(path), h.hexdigest()[:16])


def analyze_audio(path):
    """Cheap audio features for unsure files: brightness, low-end share, pitchedness."""
    import numpy as np
    import soundfile
    data, sr = soundfile.read(path, frames=int(2.5 * 48000), always_2d=True)
    y = data.mean(axis=1)
    if not len(y) or np.max(np.abs(y)) < 1e-4:
        return None
    y = y / (np.max(np.abs(y)) + 1e-9)
    n = 1 << int(np.ceil(np.log2(min(len(y), sr))))
    spec = np.abs(np.fft.rfft(y[:n] * np.hanning(min(n, len(y[:n]))), n=n))
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    power = spec ** 2   # power, so a strong tone outweighs a little broadband noise
    total = power.sum() + 1e-9
    centroid = float((power * freqs).sum() / total)
    low = float(power[freqs < 150].sum() / total)
    peak = spec.max()
    flatness = float(np.exp(np.mean(np.log(spec + 1e-9))) / (np.mean(spec) + 1e-9))
    win = max(1, sr // 100)   # 10 ms envelope
    env = np.array([np.abs(y[i:i + win]).max() for i in range(0, len(y), win)])
    top = int(np.argmax(env))
    below = np.nonzero(env[top:] < 0.1 * env[top])[0]
    decay = float((below[0] if len(below) else len(env) - top) * win / sr)
    return {"centroid": round(centroid), "low_share": round(low, 3), "flatness": round(flatness, 3), "decay": round(decay, 3),
            "peak_hz": round(float(freqs[int(np.argmax(spec))])) if peak > 0 else 0}


def classify_audio(feat, duration):
    """A best guess from audio features; returns (category, confidence)."""
    if not feat:
        return "uncertain", 0.0
    d = duration or feat["decay"]
    if feat["low_share"] > 0.45 and d > 0.6 and feat["flatness"] < 0.2:
        return "808", 0.55
    if feat["low_share"] > 0.35 and d <= 0.7:
        return "kick", 0.55
    noisy = feat["flatness"] > 0.5
    if noisy and feat["centroid"] > 6000 and feat["decay"] < 0.12:
        return "hat", 0.5
    if noisy and feat["centroid"] > 6000 and feat["decay"] >= 0.25:
        return "open hat", 0.45
    return "uncertain", 0.0


class Library:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.scanning = None
        self.data = {"folders": [], "samples": {}, "overrides": {}, "scanned_at": None}
        try:
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)

    # ----- folders and scanning

    def add_folder(self, folder):
        folder = os.path.realpath(os.path.expanduser(folder))
        if not os.path.isdir(folder):
            raise ValueError("That folder doesn't exist.")
        if folder in ("/", os.path.expanduser("~")):
            raise ValueError("Pick a drum-kit folder, not your whole disk or home folder.")
        if folder not in self.data["folders"]:
            self.data["folders"].append(folder)
            self.save()
        return folder

    def remove_folder(self, folder):
        self.data["folders"] = [f for f in self.data["folders"] if f != folder]
        self.data["samples"] = {k: v for k, v in self.data["samples"].items() if v["root"] != folder}
        self.save()

    def scan(self, progress=None, analyze=True):
        """Walk every folder (recursively), keep what's still there, add new files, classify."""
        self.scanning = {"done": 0, "found": 0, "phase": "Finding sounds"}
        seen = {}
        try:
            for root in list(self.data["folders"]):
                for dirpath, dirnames, files in os.walk(root):
                    dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.endswith((".app", ".logicx"))]
                    for fn in files:
                        if fn.startswith(".") or fn.startswith("._") or not fn.lower().endswith(AUDIO_EXT):
                            continue
                        full = os.path.join(dirpath, fn)
                        sid = hashlib.sha1(full.encode("utf-8")).hexdigest()[:12]
                        seen[sid] = (full, root)
                        self.scanning["found"] = len(seen)
            old = self.data["samples"]
            samples = {}
            fps = {}
            ordered = sorted(seen.items(), key=lambda kv: ("copy" in os.path.basename(kv[1][0]).lower(), len(kv[1][0])))
            for i, (sid, (full, root)) in enumerate(ordered):
                self.scanning.update(done=i, phase="Sorting sounds")
                prev = old.get(sid)
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                if prev and prev.get("mtime") == mtime:
                    samples[sid] = prev
                else:
                    cat, conf, src = classify_name(full, root)
                    rel = os.path.relpath(full, root)
                    samples[sid] = dict(_meta(full), id=sid, path=full, root=root, name=os.path.splitext(os.path.basename(full))[0],
                                        kit=rel.split(os.sep)[0] if os.sep in rel else os.path.basename(root),
                                        folder=os.path.basename(os.path.dirname(full)), category=cat, confidence=conf,
                                        source=src, character=character(full), mtime=mtime)
                try:
                    fp = samples[sid].get("fp") or _fingerprint(full)
                except OSError:
                    continue
                samples[sid]["fp"] = fp
                if fp in fps:
                    samples[sid]["duplicate_of"] = fps[fp]
                else:
                    samples[sid].pop("duplicate_of", None)
                    fps[fp] = sid
            if analyze:
                unsure = [s for s in samples.values() if s["category"] == "uncertain" and "audio" not in s][:ANALYZE_LIMIT]
                for i, s in enumerate(unsure):
                    self.scanning.update(done=i, phase="Listening to unlabelled sounds", found=len(unsure))
                    try:
                        s["audio"] = analyze_audio(s["path"])
                    except Exception:
                        s["audio"] = None
                    cat, conf = classify_audio(s["audio"], s.get("duration"))
                    if cat != "uncertain":
                        s.update(category=cat, confidence=conf, source="audio analysis")
            self.data["samples"] = samples
            self.data["scanned_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if analyze:
                self.scanning.update(phase="Listening to your drum sounds", done=0)
                self.analyze_drums()
            self.save()
        finally:
            self.scanning = None
        return self.summary()

    # ----- reading

    def category_of(self, s):
        return self.data["overrides"].get(s["id"], s["category"])

    def set_category(self, sid, category):
        if category not in CATEGORIES or sid not in self.data["samples"]:
            raise ValueError("Unknown sound or category.")
        self.data["overrides"][sid] = category
        self.save()

    def summary(self):
        counts = {c: 0 for c in CATEGORIES}
        kits = set()
        dups = 0
        for s in self.data["samples"].values():
            counts[self.category_of(s)] += 1
            kits.add((s["root"], s["kit"]))
            dups += 1 if s.get("duplicate_of") else 0
        return {"favorites": len(self.data.get("favorites", [])), "hidden": len(self.data.get("hidden", [])),
                "folders": [{"path": f, "name": os.path.basename(f), "exists": os.path.isdir(f),
                             "count": sum(1 for s in self.data["samples"].values() if s["root"] == f)} for f in self.data["folders"]],
                "total": len(self.data["samples"]), "counts": counts, "kits": len(kits), "duplicates": dups,
                "scanned_at": self.data["scanned_at"], "scanning": self.scanning,
                "labels": CATEGORY_LABELS}

    def list(self, category=None, query=None, limit=200, hidden=False):
        q = (query or "").lower()
        out = []
        favs, hid = self._set("favorites"), self._set("hidden")
        for s in self.data["samples"].values():
            if s.get("duplicate_of") or ((s["id"] in hid) != bool(hidden)):
                continue
            cat = self.category_of(s)
            if category and cat != category:
                continue
            if q and q not in s["name"].lower() and q not in s["kit"].lower():
                continue
            out.append(dict({k: s.get(k) for k in ("id", "name", "kit", "folder", "duration", "confidence", "source", "character")},
                            category=cat, corrected=s["id"] in self.data["overrides"], favorite=s["id"] in favs,
                            hidden=s["id"] in hid))
        out.sort(key=lambda s: (not s["favorite"], s["kit"].lower(), s["name"].lower()))
        return out[:limit]

    def get(self, sid):
        return self.data["samples"].get(sid)

    # ----- choosing a kit

    # ----- favourites, hidden sounds, variety

    def _set(self, key):
        return set(self.data.setdefault(key, []))

    def favorite(self, sid, on=True):
        favs = self._set("favorites")
        (favs.add if on else favs.discard)(sid)
        self.data["favorites"] = sorted(favs)
        self.save()

    def hide(self, sid, on=True):
        """Remove a sound from Veloura's choices (the file itself is never touched); on=False brings it back."""
        hid = self._set("hidden")
        (hid.add if on else hid.discard)(sid)
        self.data["hidden"] = sorted(hid)
        self.save()

    def note_used(self, kit):
        """Remember what Veloura just picked so the next beats don't reuse the same sounds every time."""
        recent = self.data.setdefault("recent", {})
        for role, s in (kit or {}).items():
            lst = [x for x in recent.get(role, []) if x != s.get("id")]
            recent[role] = ([s.get("id")] + lst)[:12]
        self.save()

    def sample_pitch(self, s):
        """Pitch class (0-11) an 808/bass sample is tuned to: from its name ("808 (F#)", "Dark 808 F") or detected from
        the audio. None if unknown."""
        m = re.search(r"(?:^|[\s_\-(\[])([A-G])(#|b|sharp|flat)?(?:m|min|maj)?(?=$|[\s_\-)\].])", s.get("name") or "")
        if m:
            pc = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[m.group(1)]
            acc = m.group(2) or ""
            return (pc + (1 if acc in ("#", "sharp") else -1 if acc in ("b", "flat") else 0)) % 12
        a = s.get("audio") or {}
        if "pc" not in a and os.path.isfile(s.get("path") or ""):
            try:
                import numpy as np
                import soundfile
                import librosa
                y, sr = soundfile.read(s["path"], frames=48000, always_2d=True)
                f0 = librosa.yin(y.mean(axis=1).astype("float32"), fmin=25, fmax=300, sr=sr)
                f0 = float(np.median(f0[np.isfinite(f0)])) if len(f0) else 0
                a["pc"] = int(round(12 * np.log2(f0 / 440.0) + 69)) % 12 if f0 > 0 else None
                s["audio"] = a
            except Exception:
                a["pc"] = None
        return a.get("pc")

    def find_by_channel(self, channel_name):
        """The library sample a channel is playing, recognised from the channel's name (FL names sampler channels
        after their file; Veloura's staged files are '<Role> - <name>')."""
        norm = lambda t: re.sub(r"[^a-z0-9]+", "", (t or "").lower())
        names = {norm(channel_name)}
        if " - " in (channel_name or ""):
            names.add(norm(channel_name.split(" - ", 1)[1]))
        return next((x for x in self.data["samples"].values() if norm(x["name"]) in names), None)

    def analyze_drums(self, limit=3000):
        """Listen to drum one-shots that haven't been analysed (brightness, low end, decay) so kits can be chosen by
        how they sound, not only by their names."""
        todo = [s for s in self.data["samples"].values() if "audio" not in s and self.category_of(s) in
                ("kick", "snare", "clap", "hat", "open hat", "perc", "808") and not s.get("duplicate_of")][:limit]
        for s in todo:
            try:
                s["audio"] = analyze_audio(s["path"])
            except Exception:
                s["audio"] = None
        if todo:
            self.save()
        return len(todo)

    def tone_score(self, s, role, genre=None):
        """How well a sound's tone suits its role in modern rap: crisp bright hats, snappy (not boomy) snares/claps,
        kicks with real low end. Dark styles tolerate darker snares."""
        f = s.get("audio") or {}
        c, low, dec = f.get("centroid"), f.get("low_share"), f.get("decay")
        if c is None:
            return 0.0
        dark = (genre or "") in ("dark trap", "drill", "detroit")
        sc = 0.0
        if role in ("hat", "open hat"):
            if c < 4500:
                sc -= 3.0                       # dull, low-pitched hat
            elif c < 6500:
                sc -= 1.0
            else:
                sc += min(2.0, (c - 6500) / 2500.0)
            if role == "hat" and dec and dec > 0.35:
                sc -= 1.0                       # closed hats should be short
        elif role in ("snare", "clap"):
            lo = 900 if dark else 1300
            if c < lo or (low or 0) > 0.35:
                sc -= 2.5                       # deep, boomy, harsh
            elif c > 7500:
                sc -= 0.5                       # thin
            else:
                sc += 1.5
        elif role == "kick":
            sc += 1.5 if (low or 0) > 0.35 else -1.0
        return sc

    def choose_kit(self, genre=None, seed=0, taste=None, roles=None, keep=None, exclude=None):
        """Pick one sound per drum role. Order of importance: fits this project (style words, kit genre, tone),
        then the user's favourites and keep/swap history, then variety (recently used sounds are less likely), with a
        weighted random pick among the best few so kits differ from beat to beat. Hidden sounds are never picked."""
        import math
        import random
        rnd = random.Random(seed)
        likes, dislikes = GENRE_TASTE.get(genre or "", GENRE_TASTE["trap"])
        roles = roles or KIT_ROLES
        keep = dict(keep or {})
        exclude = set(exclude or []) | self._set("hidden")
        favs = self._set("favorites")
        recent = self.data.get("recent", {})
        pool = {r: [] for r in roles}
        for s in self.data["samples"].values():
            cat = self.category_of(s)
            if cat in pool and not s.get("duplicate_of") and s["id"] not in exclude and os.path.exists(s["path"]):
                pool[cat].append(s)
        kit, anchor = {}, None
        for role in roles:
            if role in keep and self.get(keep[role]):
                kit[role] = self.get(keep[role])
                anchor = anchor or kit[role]["kit"]
                continue
            cands = pool.get(role) or []
            if not cands:
                continue
            rec = recent.get(role, [])

            def score(s):
                words = set(s.get("character") or [])
                fit = 2 * len(words & set(likes)) - 2 * len(words & set(dislikes))
                gword = (genre or "").split()[0] if genre else ""
                fit += 1.5 if gword and gword in _tokens(s["kit"] + " " + s["folder"]) else 0
                fit += self.tone_score(s, role, genre)
                fit += s.get("confidence", 0.5)
                if role in ("kick", "snare", "clap", "hat") and (s.get("duration") or 0) > 2.5:
                    fit -= 2
                pref = (2.5 if s["id"] in favs else 0) + 4 * (taste.score("sample", s["id"]) if taste else 0)
                variety = -2.0 * (1 - rec.index(s["id"]) / 12.0) if s["id"] in rec else 0
                cohesion = 0.6 if anchor and s["kit"] == anchor else 0
                return 1.6 * fit + pref + variety + cohesion

            ranked = sorted(cands, key=score, reverse=True)[:6]
            top = score(ranked[0])
            weights = [math.exp((score(c) - top) / 1.2) for c in ranked]   # the best fit is most likely, not certain
            pick = rnd.choices(ranked, weights=weights, k=1)[0]
            kit[role] = pick
            anchor = anchor or pick["kit"]
        return {r: {k: s.get(k) for k in ("id", "name", "kit", "folder", "duration", "character", "path")} | {"favorite": s["id"] in favs}
                for r, s in kit.items()}

    # ----- staging for FL

    def stage(self, kit, label="Kit"):
        """Put the kit in ~/Music/Veloura Kit/<label time>/ as '<Role> - <name>.<ext>'. Files are HARD LINKS to the
        originals (no extra disk space, and they never break a project that uses them); the same kit staged again reuses
        its folder. Originals are untouched."""
        ids = sorted("%s:%s" % (r, s.get("id")) for r, s in kit.items())
        for old in sorted(os.listdir(STAGE_ROOT)) if os.path.isdir(STAGE_ROOT) else []:
            man = os.path.join(STAGE_ROOT, old, ".veloura-kit.json")
            try:
                with open(man, encoding="utf-8") as f:
                    m = json.load(f)
                if m.get("ids") == ids and all(os.path.isfile(x["file"]) for x in m["files"].values()):
                    return {"folder": os.path.join(STAGE_ROOT, old), "files": m["files"], "reused": True}
            except (OSError, ValueError, KeyError):
                continue
        stamp = time.strftime("%Y-%m-%d %H%M")
        safe = re.sub(r"[^A-Za-z0-9 &+-]+", "", label).strip() or "Kit"
        folder = os.path.join(STAGE_ROOT, "%s %s" % (stamp, safe))
        os.makedirs(folder, exist_ok=True)
        files = {}
        for role, s in kit.items():
            src = s.get("path") or (self.get(s["id"]) or {}).get("path")
            if not src or not os.path.isfile(src):
                continue
            ext = os.path.splitext(src)[1].lower()
            clean = re.sub(r"[^A-Za-z0-9 ._-]+", "", s["name"]).strip()[:40] or "sound"
            dest = os.path.join(folder, "%s - %s%s" % (ROLE_FILE[role], clean, ext))
            _link_or_copy(src, dest)
            files[role] = {"file": dest, "name": os.path.splitext(os.path.basename(dest))[0], "sample": s["id"]}
        with open(os.path.join(folder, ".veloura-kit.json"), "w", encoding="utf-8") as f:
            json.dump({"ids": ids, "files": files}, f)
        return {"folder": folder, "files": files}

    def dedupe_staged(self):
        """Turn staged copies back into hard links to their originals (same paths, no duplicate disk space).
        Returns bytes saved."""
        if not os.path.isdir(STAGE_ROOT):
            return 0
        by_fp = {}
        for s in self.data["samples"].values():
            if s.get("fp") and os.path.isfile(s["path"]):
                by_fp.setdefault(s["fp"], s["path"])
        saved = 0
        for dp, dn, fn in os.walk(STAGE_ROOT):
            for f in fn:
                p = os.path.join(dp, f)
                if f.startswith(".") or os.path.islink(p):
                    continue
                try:
                    st = os.stat(p)
                    if st.st_nlink > 1:
                        continue          # already a link
                    orig = by_fp.get(_fingerprint(p))
                    if not orig or os.path.samefile(orig, p):
                        continue
                    with open(orig, "rb") as a, open(p, "rb") as b:
                        if a.read() != b.read():
                            continue      # only exact copies are replaced
                    tmp = p + ".linktmp"
                    os.link(orig, tmp)
                    os.replace(tmp, p)
                    saved += st.st_size
                except OSError:
                    continue
        return saved


def _link_or_copy(src, dest):
    if os.path.exists(dest):
        os.remove(dest)
    try:
        os.link(src, dest)            # same disk: no extra space
    except OSError:
        shutil.copy2(src, dest)       # different disk: a real copy


ROLE_FILE = {"kick": "Kick", "snare": "Snare", "clap": "Clap", "hat": "Hat", "open hat": "Open Hat", "perc": "Perc", "808": "808"}
