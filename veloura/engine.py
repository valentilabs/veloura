"""Veloura engine: conversation, proposals and verified FL Studio operations.

Every FL change goes through the Stage 1 bridge (veloura_bridge Piano Roll
script, triggered with Cmd+Opt+Y) and is reported only after Veloura has
checked FL's readback AND a separate snapshot taken after the script finished.

Session state lives in data/session.json inside the project folder.
"""

import contextlib
import copy
import re
import json
import os
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import ai, bridge_protocol as bp, drums, edition, fl_trigger, icloud, mix as mixmod, sounds, theory
from .taste import Taste
from . import library as libmod
from .fl_controller import ControllerError, ControllerLink, ControllerUnavailable
from .help_text import RECONNECT_STEPS, RECONNECT_TEXT
from .melody_plan import PlanError, validate_plan
from .midi_file import verify_midi, write_midi

ROOT = bp.ROOT
DATA_DIR = os.path.join(bp.DATA_ROOT, "data")
SESSION_FILE = os.path.join(DATA_DIR, "session.json")
EXPORT_DIR = os.path.expanduser("~/Music/Veloura Exports")

DEFAULT_SETTINGS = {
    "tempo_bpm": 140, "key": "F minor", "bars": 4, "genre": "trap", "mood": "dark", "swing": 0,
    "provider": "offline", "model": ai.DEFAULT_MODEL, "gemini_model": ai.DEFAULT_GEMINI_MODEL, "chatgpt_model": "",
    "onboarded": False, "auto_tempo": True, "tempo_auto": False, "key_auto": True, "bars_auto": True,
    "remind_loop": True, "remind_cut": True, "careful": False,
    "feel": {}, "locked_parts": [], "quality": "fast", "use_my_style": False, "auto_mixer": True, "auto_sounds": True, "guide_arrow": True, "listen_after": True,
    "kit_auto_load": False, "theme": "champagne", "rack_open": True,
}
THEMES = ("champagne", "rose-gold", "platinum", "lilac", "amber-noir")
REF_DIR = os.path.join(DATA_DIR, "references")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aif", ".aiff", ".flac", ".caf", ".aac", ".mp4")


def fl_started_at():
    """When the running FL Studio process started (epoch seconds), or None."""
    import subprocess
    try:
        pid = subprocess.run(["/usr/bin/pgrep", "-x", "OsxFL"], capture_output=True, text=True, timeout=5).stdout.split()
        if not pid:
            return None
        out = subprocess.run(["/bin/ps", "-o", "lstart=", "-p", pid[0]], capture_output=True, text=True,
                             timeout=5, env={"LC_ALL": "C"}).stdout.strip()
        return time.mktime(time.strptime(out, "%a %b %d %H:%M:%S %Y"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _is_unsaved_project(name):
    """FL's name for a project that was never saved ("Untitled", sometimes numbered), or no name at all."""
    return bool(re.match(r"^(untitled( \d+)?)?$", (name or "").strip().lower()))


def _is_default_sound(name):
    n = (name or "").lower().strip()
    return not n or any(w in n for w in ("init", "default", "empty", "basic", "untitled")) or n in ("3x osc",)


def _wants_drums(text, mode):
    t = (text or "").lower()
    return mode in ("genre", "inspiration", "sample") or any(w in t for w in (
        "beat", "drum", "kick", "snare", "hat", "groove", "kit", "from scratch", "instrumental", "track"))


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _key(d):
    return (d["number"], d["time"], d["length"], d["vel127"])


def _counter(items):
    out = {}
    for k in items:
        out[k] = out.get(k, 0) + 1
    return out


class EngineError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


class _NoTarget(Exception):
    def __init__(self, message, fix=None):
        super().__init__(message)
        self.fix = fix


class Engine:
    def __init__(self, session_file=SESSION_FILE, trigger=fl_trigger, timeout=5.0, controller=None):
        self.controller = controller or ControllerLink()
        self._ctl_cache = (0, None)
        self.session_file = session_file
        self.trigger = trigger
        self.timeout = timeout
        self.fl_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.busy = None
        self.cancel_event = threading.Event()
        self.started_at = time.time()   # when Veloura started: FL started before this can't see Veloura's MIDI ports
        self.state = self._load()
        getter = getattr(trigger, "fl_project_name", None)
        self.project = self.state.get("project") or (getter() if getter else None) or "Default"
        self._project_checked = 0
        self._load_project(self.project, migrate=True)
        # last time the Piano Roll bridge answered: proves it is armed for the current FL session
        self.bridge_ok_at = self.state.get("bridge_ok_at", 0)

    # ---------- persistence ----------

    @property
    def taste(self):
        if not hasattr(self, "_taste"):
            self._taste = Taste(os.path.join(os.path.dirname(self.session_file), "taste.json"))
        return self._taste

    @property
    def library(self):
        if not hasattr(self, "_library"):
            self._library = libmod.Library(os.path.join(os.path.dirname(self.session_file), "library.json"))
        return self._library

    @property
    def style(self):
        if not hasattr(self, "_style"):
            from .style import StyleLibrary
            self._style = StyleLibrary(os.path.join(os.path.dirname(self.session_file), "style.json"))
        return self._style

    def style_import(self, path=None, genre=None):
        if not path:
            import subprocess
            p = subprocess.run(["/usr/bin/osascript", "-e", "activate", "-e",
                                'POSIX path of (choose folder with prompt "Choose a folder of MIDI files in your style")'],
                               capture_output=True, text=True, timeout=600)
            if p.returncode != 0:
                return {"ok": False, "cancelled": True}
            path = p.stdout.strip()
        if not os.path.exists(path):
            raise EngineError("That file or folder doesn't exist.")
        res = self.style.import_path(path, genre)
        self.event("ok", "Learned from %d MIDI file(s)." % res["added"])
        return dict(res, ok=True)

    def listen_to_library(self):
        """Background: analyse drum sounds that haven't been listened to yet (one-time, then only new files)."""
        try:
            n = self.library.analyze_drums()
            if n:
                self.event("info", "Listened to %d drum sounds so kits can be chosen by how they sound." % n)
        except Exception:   # noqa: BLE001 - housekeeping must never break startup
            pass

    def tidy_staged_kits(self):
        try:
            saved = self.library.dedupe_staged()
        except Exception:   # noqa: BLE001 - housekeeping must never break startup
            saved = 0
        if saved:
            self.event("info", "Freed %.1f MB of duplicate kit copies (now hard links)." % (saved / 1e6))
        return saved

    def kit_prefer(self):
        kit = self.state.get("kit") or {}
        return [f["name"] for f in ((kit.get("staged") or {}).get("files") or {}).values()]

    # ---------- drum library ----------

    def library_add_folder(self, path=None):
        if not path:
            import subprocess
            p = subprocess.run(["/usr/bin/osascript", "-e", "activate", "-e",
                                'POSIX path of (choose folder with prompt "Choose a folder with your drum kits")'],
                               capture_output=True, text=True, timeout=600)
            if p.returncode != 0:
                return {"ok": False, "cancelled": True}
            path = p.stdout.strip()
        try:
            folder = self.library.add_folder(path)
        except ValueError as e:
            raise EngineError(str(e))
        self.library_scan()
        self.event("info", "Added drum folder %s; scanning it." % folder)
        return {"ok": True, "folder": folder}

    def library_scan(self):
        if self.library.scanning:
            return {"ok": True, "already": True}
        threading.Thread(target=self.library.scan, daemon=True).start()
        return {"ok": True}

    def choose_kit(self, genre=None, seed=None, keep=None, exclude=None):
        import random
        seed = random.randrange(1 << 30) if seed is None else seed
        kit = self.library.choose_kit(genre or self.state["settings"].get("genre"), seed=seed, taste=self.taste,
                                      keep=keep, exclude=exclude)
        self.library.note_used(kit)
        return {"roles": kit, "genre": genre, "seed": seed}

    def _make_local(self, paths):
        """Make sure these sounds are really on this Mac (iCloud may have evicted them) and pin their kit folders so
        they stay. Shows the download in the request's countdown. Returns the paths that still aren't local."""
        paths = [p for p in paths if p and os.path.isfile(p)]
        for folder in {icloud.kit_folder(p, self.library.data.get("folders")) for p in paths}:
            if not icloud.is_pinned(folder):
                icloud.pin(folder)

        def progress(done, total):
            if getattr(self, "progress", None) is not None:
                self.progress["detail"] = "Downloading sounds from iCloud (%d of %d)" % (done, total)
        missing = icloud.ensure_local(paths, timeout=90.0, on_progress=progress)
        if getattr(self, "progress", None) is not None:
            self.progress["detail"] = None
        return missing

    def keep_kits_local(self):
        """At startup: re-pin the kits in Veloura's library and FL's Veloura script folders so macOS can't quietly
        move them back to iCloud, and bring back anything it already evicted (keeps 5 GB free)."""
        try:
            folders = list(self.library.data.get("folders") or []) + [bp.FL_SCRIPTS_DIR, bp.CONTROLLER_DIR]
            # data/keep_folders.json: more folders to keep downloaded (e.g. kits not in the library), {"folders": [...]}
            try:
                with open(os.path.join(os.path.dirname(self.session_file), "keep_folders.json"), encoding="utf-8") as f:
                    folders += [x for x in json.load(f).get("folders", []) if isinstance(x, str)]
            except (OSError, ValueError, AttributeError):
                pass
            res = icloud.keep(folders)
            back = sum(r["evicted"] for r in res.values() if r["requested"])
            if back:
                self.event("info", "Bringing %d sound(s) back from iCloud so your kits stay on this Mac." % back)
            return res
        except Exception:   # never let this stop Veloura from starting
            return {}

    def stage_kit(self, kit_roles, label=None):
        if not kit_roles:
            raise EngineError("No sounds to load.")
        srcs = {r: s.get("path") or (self.library.get(s.get("id")) or {}).get("path") for r, s in kit_roles.items()}
        missing = set(self._make_local(list(srcs.values())))
        if missing:
            kit_roles = {r: s for r, s in kit_roles.items() if srcs[r] not in missing}
            self.event("warn", "%d sound(s) are still in iCloud and weren't copied yet." % len(missing))
            if not kit_roles:
                raise EngineError("These sounds are still downloading from iCloud (or the disk is nearly full). "
                                  "Try again in a moment.")
        staged = self.library.stage(kit_roles, label or "Kit")
        with self.state_lock:
            self.state["kit"] = {"roles": kit_roles, "staged": staged, "at": _now()}
        self.save()
        import subprocess
        first = next(iter(staged["files"].values()), None)
        if first:
            subprocess.run(["/usr/bin/open", "-R", first["file"]], timeout=10)
        self.event("ok", "Staged %d sounds in %s." % (len(staged["files"]), staged["folder"]))
        return dict(staged, check=self.check_kit())

    # ---------- automatic sample loading through FL's Browser ----------

    def browser_path(self, file_path):
        """Captions from a top-level Browser folder down to the file, plus each folder's contents. None if Veloura can't
        tell where FL's Browser shows this file (Desktop and the user's library folders are recognised)."""
        file_path = os.path.realpath(file_path)
        roots = [(os.path.realpath(os.path.expanduser("~/Desktop")), "Desktop")]
        for f in self.library.data.get("folders") or []:
            roots.append((os.path.realpath(f), os.path.basename(f)))
        for root, caption in roots:
            if file_path.startswith(root + os.sep):
                rel = os.path.relpath(file_path, root).split(os.sep)
                comps = [caption] + rel
                children, cur = {}, root
                for i, comp in enumerate(comps[:-1]):
                    folder = cur if i == 0 else os.path.join(cur, comp)
                    cur = folder
                    try:
                        children[str(i)] = [n for n in os.listdir(folder) if not n.startswith(".")]
                    except OSError:
                        return None
                return comps, children
        return None

    def load_sample(self, channel_index, file_path, channel_name=None):
        """Load an audio file into a Channel Rack channel, the way a hardware controller does: walk FL's Browser to the
        file, select the channel, choose "send to selected channel". Verified by the channel's new name."""
        if not os.path.isfile(file_path):
            return {"ok": False, "message": "File not found."}
        if self._make_local([file_path]):
            return {"ok": False, "message": "That sound is still downloading from iCloud (or the disk is nearly full)."}
        bp_ = self.browser_path(file_path)
        if not bp_:
            return {"ok": False, "code": "not_in_browser", "message": "FL's Browser doesn't show that folder."}
        comps, children = bp_
        stem = os.path.splitext(os.path.basename(file_path))[0]
        with self.fl_lock, self._quiet():
            try:
                proj = self.controller.request("project")
                chan = next((c for c in proj["channels"] if c["index"] == int(channel_index)), None)
                if not chan or (channel_name and chan["name"] != channel_name):
                    return {"ok": False, "message": "That channel moved or was renamed; refresh and try again."}
                before = chan["name"]
                self.controller.request("browser_goto", {"path": comps, "children": children, "channel": chan["index"]}, timeout=30)
                opened = False
                for _ in range(15):
                    time.sleep(0.08)
                    st = self.controller.request("browser", {"action": "caption"})
                    if st.get("in_menu"):
                        opened = st.get("focused", "").lower() == comps[-1].lower()
                        break
                if not opened:
                    try:
                        if self.controller.request("browser", {"action": "caption"}).get("in_menu"):
                            self.controller.request("browser", {"action": "escape"})
                    except (ControllerUnavailable, ControllerError):
                        pass
                    return {"ok": False, "message": "FL's Browser wasn't on the right file, so nothing was loaded."}
                self.controller.request("browser", {"action": "menu_step", "direction": 1})
                self.controller.request("browser", {"action": "enter"})
                after = before
                for _ in range(20):
                    time.sleep(0.15)
                    after = next((c["name"] for c in self.controller.request("project")["channels"] if c["index"] == chan["index"]), before)
                    if after.lower() == stem.lower():
                        break
            except (ControllerUnavailable, ControllerError) as e:
                try:
                    if self.controller.request("browser", {"action": "caption"}).get("in_menu"):
                        self.controller.request("browser", {"action": "escape"})
                except (ControllerUnavailable, ControllerError):
                    pass
                return {"ok": False, "message": str(e)}
        self._ctl_cache = (0, None)
        ok = after.lower() == stem.lower()
        norm = lambda t: re.sub(r"[^a-z0-9]+", "", t.lower())
        names = {norm(before)}
        if " - " in before:   # staged names look like "Snare - <file>" (punctuation stripped)
            names.add(norm(before.split(" - ", 1)[1]))
        prev = next((x for x in self.library.data["samples"].values() if norm(x["name"]) in names), None)
        if not ok and after.lower() != before.lower():
            # FL's Browser landed on a neighbouring file and loaded that instead. Record it so "Undo everything"
            # can put the channel's old sound back, and say so plainly.
            self._log_change("sample", channel=chan["index"], name=after, before_name=before, file=None,
                             before_file=(prev or {}).get("path"))
            self.event("warn", "FL loaded %r instead of %s into channel %d." % (after, stem, chan["index"] + 1))
            self.save()
            return {"ok": False, "channel": after, "message": "FL loaded %r instead of %s. Press Cmd+Z in FL to put "
                    "%r back, or turn off Settings > Load kits by walking FL's Browser." % (after, stem, before)}
        if ok:
            self._log_change("sample", channel=chan["index"], name=after, before_name=before, file=file_path,
                             before_file=(prev or {}).get("path"))
            self.event("ok", "Loaded %s into channel %d." % (stem, chan["index"] + 1))
            self.save()
        return {"ok": ok, "channel": after, "message": ("Loaded %s." % stem) if ok else
                "FL didn't confirm the new sound on %s." % before}

    def _set_master_mute(self, value, wait=2.0):
        """Mute/unmute FL's Master and wait until FL confirms it (FL 2026 applies mutes a moment later)."""
        end = time.time() + wait
        while True:
            self.controller.request("set_mix", {"changes": [{"kind": "mixer_mute", "track": 0, "value": bool(value)}]})
            time.sleep(0.15)
            st = self.controller.request("mix_state", timeout=4.0)
            now = next((t["muted"] for t in st["tracks"] if t["track"] == 0), None)
            if now == bool(value) or time.time() > end:
                return now == bool(value)

    def _quiet(self):
        """Mute FL's Master while Veloura walks the Browser (FL plays every sample the cursor passes), then restore it,
        confirming both with FL so Master is never left muted."""
        eng = self

        class Quiet:
            def __enter__(self_):
                self_.was = None
                try:
                    st = eng.controller.request("mix_state", timeout=4.0)
                    self_.was = next((t["muted"] for t in st["tracks"] if t["track"] == 0), False)
                    if not self_.was:
                        eng._set_master_mute(True)
                except (ControllerUnavailable, ControllerError):
                    pass
                return self_

            def __exit__(self_, *exc):
                if self_.was is False:
                    for _ in range(3):
                        try:
                            if eng._set_master_mute(False, wait=3.0):
                                break
                        except (ControllerUnavailable, ControllerError):
                            time.sleep(0.5)
                return False
        return Quiet()

    def load_kit(self, roles, proposal_id=None):
        """Put a whole kit into FL automatically: each sound onto its drum channel. Falls back to the drag-in guide
        for anything that can't be loaded."""
        chans = self.controller_status(max_age=0).get("channels") or []
        results = {}
        label = {"kick": "Kick", "snare": "Snare", "clap": "Clap", "hat": "Hi-hat", "open hat": "Open hat", "perc": "Perc", "808": "808"}
        for role, s in (roles or {}).items():
            path = s.get("path") or (self.library.get(s.get("id")) or {}).get("path")
            pseudo = {"name": label.get(role, role), "role": "drums" if role != "808" else "bass", "plan": None}
            if role == "808":
                chan = next((c for c in chans if "808" in c["name"].lower() and not drums.lane_kind(c["name"])), None) or \
                    next((c for c in chans if c["name"].lower().startswith("808")), None)
                route = {"index": chan["index"], "name": chan["name"]} if chan else {"name": None}
            else:
                route = self._resolve_route(pseudo, chans)
            if not route.get("name"):
                results[role] = {"ok": False, "message": "No %s channel to load into." % label.get(role, role)}
                continue
            r = self.load_sample(route["index"], path, route["name"])
            results[role] = dict(r, target=route["name"])
            chans = self.controller_status(max_age=0).get("channels") or chans
            if r.get("ok"):
                self.taste.note("sample", s.get("id"), "kept", context=role)
        ok = all(r.get("ok") for r in results.values()) and bool(results)
        prop = self.state["proposals"].get(proposal_id) if proposal_id else None
        if prop is not None and ok:
            with self.state_lock:
                prop["kit_loaded"] = True
            self.save()
        return {"ok": ok, "results": results}

    def check_kit(self):
        """Which staged sounds are now in FL (a channel carries the staged file's name)?"""
        kit = self.state.get("kit") or {}
        files = (kit.get("staged") or {}).get("files") or {}
        chans = [c["name"] for c in (self.controller_status().get("channels") or [])]
        out = {}
        for role, f in files.items():
            hit = next((c for c in chans if c == f["name"] or c.startswith(f["name"][:24])), None)
            out[role] = {"loaded": bool(hit), "channel": hit, "file": f["name"]}
        return out

    def kit_feedback(self, sample_id, verdict, role=None):
        self.taste.note("sample", sample_id, verdict, context=role)
        return {"ok": True}

    # ---------- progress (for the UI's working animation) ----------

    def set_progress(self, pct, stage, detail=None, estimate=None):
        self.progress = {"pct": max(0, min(100, int(pct))), "stage": stage, "detail": detail, "at": time.time(),
                         "estimate": estimate, "started": (getattr(self, "progress", None) or {}).get("started") or time.time()}

    def clear_progress(self):
        self.progress = None

    def get_progress(self):
        p = getattr(self, "progress", None)
        if not p:
            return {"active": False}
        out = dict(p, active=True, elapsed=round(time.time() - p["started"], 1))
        est = p.get("estimate")
        if est:   # the AI doesn't report progress: estimate from how long this provider usually takes, never past 90%
            lo, hi = est["from"], est["to"]
            frac = min(1.0, (time.time() - est["since"]) / max(0.3, est["seconds"]))
            out["remaining"] = round(max(0.0, est["seconds"] - (time.time() - est["since"])), 1)
            out["estimate_seconds"] = round(est["seconds"], 1)
            eased = 1 - (1 - frac) ** 1.6
            out["pct"] = int(lo + (hi - lo) * eased)
            out["estimated"] = True
        return out

    # Typical seconds per FL action kind before Veloura has measured any (background trigger: writes are quick).
    FL_ACTION_DEFAULTS = {"write": 1.5, "remove": 1.0, "revert": 1.5, "mix": 3.0, "kit": 4.0, "tempo": 0.5, "check": 0.5}

    def fl_action_seconds(self, kind):
        hist = self.state.setdefault("fl_timing", {}).get(kind) or []
        return sum(hist) / len(hist) if hist else self.FL_ACTION_DEFAULTS.get(kind, 2.0)

    @contextlib.contextmanager
    def timed_action(self, kind):
        """Show a countdown for an FL action from its recent real timings, and record how long this one took."""
        own = not getattr(self, "progress", None)   # never overwrite an AI request's progress
        secs = self.fl_action_seconds(kind)
        if own:
            self.set_progress(0, kind, None, estimate={"from": 0, "to": 95, "seconds": secs, "since": time.time()})
            self.progress["fl_action"] = kind
        t0 = time.time()
        try:
            yield
        finally:
            took = time.time() - t0
            if took >= 0.05:   # an instant refusal (nothing sent to FL) says nothing about how long FL takes
                with self.state_lock:
                    hist = self.state.setdefault("fl_timing", {}).setdefault(kind, [])
                    hist.append(round(took, 2))
                    del hist[:-8]
            if own:
                self.clear_progress()

    AI_DEFAULT_SECONDS = {"offline": 2, "gemini": 30, "claude-code": 90, "anthropic": 45, "chatgpt": 30}

    def _ai_seconds(self, provider, model=None):
        """Countdown length for an AI request: the median of the last 10 real times for this provider and model
        (a median ignores the odd slow one), else this provider's, else a default."""
        timing = self.state.setdefault("ai_timing", {})
        hist = timing.get("%s:%s" % (provider, model)) if model else None
        hist = hist or timing.get(provider) or []
        if not hist:
            return self.AI_DEFAULT_SECONDS.get(provider, 45)
        h = sorted(hist)
        mid = len(h) // 2
        return h[mid] if len(h) % 2 else (h[mid - 1] + h[mid]) / 2

    def _record_ai_seconds(self, provider, seconds, model=None):
        with self.state_lock:
            timing = self.state.setdefault("ai_timing", {})
            for key in [provider] + (["%s:%s" % (provider, model)] if model else []):
                hist = timing.setdefault(key, [])
                hist.append(round(seconds, 1))
                del hist[:-10]

    # ---------- proposals made by Veloura itself (improve, variations, groove lab) ----------

    def _make_proposal(self, parts, kind, text, reply, extra=None):
        channels = self.controller_status().get("channels") or []
        for p in parts:
            p.setdefault("action", "revise" if p["name"] in self.state["parts"] else "new")
            p.setdefault("target_hint", "")
            p.setdefault("sound", "")
            p["destination"] = self._destination(p, channels)
            p["status"] = "proposed"
            p["result"] = None
        pid = uuid.uuid4().hex[:10]
        prop = dict({"id": pid, "parts": parts, "guidance": [], "problems": [], "mix": None, "provider": "veloura",
                     "created": _now(), "mode": kind, "kind": kind, "request": text}, **(extra or {}))
        msg = {"id": uuid.uuid4().hex[:10], "role": "assistant", "text": reply, "time": _now(), "proposal_id": pid,
               "provider": "veloura"}
        with self.state_lock:
            self.state["proposals"][pid] = prop
            self.state["messages"].append(msg)
        self.save()
        return dict(msg, proposal=prop)

    def _last_harmony(self):
        for prop in reversed(list(self.state["proposals"].values())):
            h = (prop.get("info") or {}).get("harmony")
            if h:
                return h
        return None

    def current_parts(self):
        """Parts that belong to the project open in FL (their channel exists there). All parts when FL isn't connected."""
        ctl = self.controller_status()
        names = {c["name"] for c in ctl.get("channels") or []}
        parts = {n: e for n, e in self.state["parts"].items() if e.get("plan")}
        if not ctl.get("connected") or not names:
            return parts
        return {n: e for n, e in parts.items() if (e.get("channel_name") or n) in names}

    def improve(self):
        from . import insight
        parts = self.current_parts()
        with self.state_lock:
            self.state["messages"].append({"id": uuid.uuid4().hex[:10], "role": "user", "text": "Improve this beat",
                                           "time": _now(), "attachment": None})
        findings = insight.analyze(parts, self._last_harmony(), genre=self.state["settings"].get("genre"))
        out_parts, cards = [], []
        for f in findings:
            fix = f.get("fix")
            card = {k: f[k] for k in ("id", "title", "detail", "evidence", "group", "kind") if k in f}
            card["part_indexes"] = []
            if fix:
                items = fix["parts"] if fix["type"] == "group" else [fix]
                for it in items:
                    card["part_indexes"].append(len(out_parts))
                    out_parts.append({"name": it["part"], "role": it["role"], "purpose": it.get("purpose") or
                                      (parts.get(it["part"]) or {}).get("purpose"), "plan": it["plan"], "op": fix["op"],
                                      "finding": f["id"], "before": (parts.get(it["part"]) or {}).get("plan")})
            cards.append(card)
        reply = ("Here's what would lift this beat most. Each one shows the change; add the ones you like."
                 if out_parts else (findings[0]["detail"] if findings else "This beat already holds together well."))
        return self._make_proposal(out_parts, "improve", "Improve this beat", reply, {"findings": cards})

    def variations(self, name, count=3):
        from . import variations as varmod
        entry = self.state["parts"].get(name)
        if not entry:
            raise EngineError("No Veloura part called %r." % name)
        opts = varmod.options(name, entry, self._last_harmony(), genre=self.state["settings"].get("genre"), count=count,
                              seed=int(time.time()) % 10000, siblings=self.state["parts"])
        with self.state_lock:
            self.state["messages"].append({"id": uuid.uuid4().hex[:10], "role": "user", "text": "Try variations of %s" % name,
                                           "time": _now(), "attachment": None})
        parts = [{"name": name, "role": entry["role"], "purpose": entry.get("purpose"), "plan": o["plan"],
                  "option": chr(65 + i), "option_label": o["label"], "description": o["description"],
                  "op": "Variation %s: %s" % (chr(65 + i), o["label"]), "before": entry["plan"]} for i, o in enumerate(opts)]
        return self._make_proposal(parts, "variations", "Variations of %s" % name,
                                   "%d takes on %s. Compare them with the current version and add the one you like; "
                                   "the old version stays in the history." % (len(parts), name), {"variant_of": name})

    def groove_action(self, action):
        from . import grooves
        drum = {n: e for n, e in self.current_parts().items() if e.get("role") == "drums"}
        if action == "keep":
            names = sorted(set(self.state["settings"].get("locked_parts") or []) | set(drum))
            self.update_settings({"locked_parts": names})
            return {"ok": True, "locked": names}
        if action == "unlock":
            names = [n for n in self.state["settings"].get("locked_parts") or [] if n not in drum]
            self.update_settings({"locked_parts": names})
            return {"ok": True, "locked": names}
        if action not in grooves.ACTIONS:
            raise EngineError("Unknown groove action.")
        if not drum:
            raise EngineError("Make some drums first.")
        bars = max(e["plan"]["bars"] for e in drum.values())
        lanes = {n: e["plan"]["notes"] for n, e in drum.items()}
        new = grooves.transform(lanes, action, genre=self.state["settings"].get("genre"), bars=bars, seed=int(time.time()) % 1000)
        parts = []
        for n, notes in new.items():
            if notes != lanes[n]:
                plan = copy.deepcopy(drum[n]["plan"])
                plan["notes"] = notes
                parts.append({"name": n, "role": "drums", "purpose": "drums", "plan": plan, "op": "Groove: %s" % grooves.ACTIONS[action],
                              "before": drum[n]["plan"]})
        return self._make_proposal(parts, "groove", grooves.ACTIONS[action], "%s: here's the new groove." % grooves.ACTIONS[action])

    def restore_version(self, name, vid):
        entry = self.state["parts"].get(name)
        v = next((x for x in (entry or {}).get("versions") or [] if x["id"] == vid), None)
        if not v:
            raise EngineError("That version isn't available.")
        out = self._make_proposal([{"name": name, "role": entry["role"], "purpose": entry.get("purpose"),
                                    "plan": copy.deepcopy(v["plan"]), "op": "Restored %s" % v.get("label", vid)}],
                                  "restore", "Restore %s" % name, "Bringing back that version of %s." % name)
        res = self.apply(out["proposal"]["id"], 0)
        return res

    def arrangement(self, genre=None):
        from . import arrange
        groups = set()
        loop = 4
        for e in self.current_parts().values():
            groups.add({"melody": "melody", "chords": "melody", "bass": "bass", "drums": "drums"}.get(e.get("role"), "other"))
            loop = max(loop, (e.get("plan") or {}).get("bars") or 4)
        plan = arrange.plan(genre or self.state["settings"].get("genre"), loop, groups or None)
        with self.state_lock:
            self.state["arrangement"] = plan
        self.save()
        return plan

    def project_model(self, ctl=None, mix_state=None):
        """What Veloura knows about the beat, split into verified facts and inferences."""
        ctl = ctl or self.controller_status()
        parts = self.state["parts"]
        facts = {"fl_connected": bool(ctl.get("connected"))}
        if ctl.get("connected"):
            facts.update({"tempo": ctl.get("tempo"), "pattern": (ctl.get("pattern") or {}).get("number"),
                          "channels": [{"name": c["name"], "type": c.get("type")} for c in ctl.get("channels") or []]})
        facts["parts_written_by_veloura"] = [{"name": n, "role": e.get("role"), "where": e.get("target_hint"),
                                               "versions": 1 + len(e.get("history") or []), "written_at": e.get("updated")}
                                              for n, e in parts.items()]
        inferred = {}
        pitched = [{"role": e.get("role"), "plan": e.get("plan")} for e in parts.values() if e.get("role") != "drums"]
        key = None
        for e in parts.values():
            key = theory.parse_key((e.get("plan") or {}).get("key") or "")
            if key:
                break
        if key and pitched:
            bars = max((e.get("plan") or {}).get("bars") or 4 for e in parts.values())
            inferred["key"] = theory.key_label(*key)
            inferred["chords_estimated_from_notes"] = [c["symbol"] for c in theory.infer_harmony(pitched, key, bars)]
        inferred["genre_setting"] = self.state["settings"].get("genre")
        return facts, inferred

    def _load(self):
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    st = json.load(f)
                st.setdefault("settings", {})
                for k, v in DEFAULT_SETTINGS.items():
                    st["settings"].setdefault(k, v)
                # Older versions saved the default model as if it had been chosen. Until the user picks a model in
                # Settings (model_chosen), follow the current default: Haiku normally, Opus in developer mode.
                if not st["settings"].get("model_chosen"):
                    st["settings"]["model"] = ai.DEFAULT_MODEL
                if not st.get("style_learning_off_2026_10_20"):   # the developer: Veloura doesn't learn from past projects
                    st["settings"]["use_my_style"] = False
                    st["style_learning_off_2026_10_20"] = True
                if st["settings"].get("provider") not in ai.customer_providers():
                    # e.g. the personal Claude Code login, which only the developer's developer copy offers
                    st["settings"]["provider"] = "offline"
                for k in ("messages", "events"):
                    st.setdefault(k, [])
                for k in ("proposals", "parts", "references"):
                    st.setdefault(k, {})
                return st
            except (ValueError, OSError):
                backup = self.session_file + ".corrupt-%d" % int(time.time())
                shutil.copy(self.session_file, backup)
        return {"settings": dict(DEFAULT_SETTINGS), "messages": [], "proposals": {}, "parts": {}, "events": [], "references": {}}

    # ---------- projects: each FL project has its own chat, parts and history ----------

    PROJECT_KEYS = ("messages", "proposals", "parts", "kit", "arrangement", "routing", "changes")

    def _project_file(self, name):
        slug = re.sub(r"[^A-Za-z0-9 _.-]+", "_", name).strip() or "Default"
        return os.path.join(os.path.dirname(self.session_file), "projects", slug + ".json")

    def _empty_project(self):
        return {"messages": [], "proposals": {}, "parts": {}, "kit": None, "arrangement": None, "routing": {}, "changes": []}

    def _load_project(self, name, migrate=False):
        path = self._project_file(name)
        data = None
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                shutil.copy(path, path + ".corrupt-%d" % int(time.time()))
        if data is None:
            data = self._empty_project()
            if migrate:   # first run with projects: the old single session becomes this project's history
                for k in self.PROJECT_KEYS:
                    if self.state.get(k):
                        data[k] = self.state[k]
        with self.state_lock:
            for k, v in self._empty_project().items():
                self.state[k] = data.get(k, v) if data.get(k) is not None else v
            self.state["project"] = name
            self.project = name

    def check_project(self, force=False):
        """Follow the project open in FL: switch Veloura's chat and parts when it changes."""
        if not force and time.time() - self._project_checked < 3:
            return self.project
        self._project_checked = time.time()
        getter = getattr(self.trigger, "fl_project_name", None)
        name = getter() if getter else None
        if name and _is_unsaved_project(name) and not self.busy:
            # A new, never-saved FL project gets a new, empty chat, not whatever the last Untitled project left behind.
            # "New" means Veloura just moved to it from another project, or FL was restarted since that chat began.
            started = fl_started_at()
            if name != self.project and not _is_unsaved_project(self.project) and self.project != "Default":
                # FL's title reads "Untitled" for a moment while it opens or saves a project: only treat it as a
                # new project when it is still Untitled on the next check.
                if getattr(self, "_untitled_seen", None) != name:
                    self._untitled_seen = name
                    return self.project
            self._untitled_seen = None
            if name != self.project or (started and self.state.get("untitled_fl_start") != started):
                self.save()
                self._fresh_untitled(name, started)
                self.event("info", "New project in FL: started a fresh conversation.")
                self.save()
                return self.project
        if name and not _is_unsaved_project(name):
            self._untitled_seen = None
        if name and name != self.project and not self.busy:
            self.save()
            if self.project == "Untitled" and name != "Untitled" and not os.path.exists(self._project_file(name)):
                # the user just saved the new project: its chat and parts come along under the new name
                old = self._project_file("Untitled")
                with self.state_lock:
                    self.project = name
                    self.state["project"] = name
                self.save()
                if os.path.exists(old):
                    os.remove(old)
                self.event("info", "Your new project is now called %r." % name)
                return self.project
            self._load_project(name)
            self.event("info", "Switched to project %r." % name)
            self.save()
        return self.project

    def _fresh_untitled(self, name, fl_start):
        """Empty chat and parts for an unsaved FL project. An earlier unsaved chat is archived, never deleted."""
        path = self._project_file(name)
        if os.path.exists(path):
            os.replace(path, path[:-5] + " (archived %s).json.bak" % time.strftime("%Y-%m-%d %H%M%S"))
        self._load_project(name)
        with self.state_lock:
            self.state["untitled_fl_start"] = fl_start

    def list_projects(self):
        d = os.path.join(os.path.dirname(self.session_file), "projects")
        out = []
        for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        data = json.load(f)
                    out.append({"name": fn[:-5], "messages": len(data.get("messages") or []), "parts": len(data.get("parts") or {}),
                                "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(d, fn)))),
                                **self._project_summary(data)})
                except (OSError, ValueError):
                    continue
        return {"current": self.project, "projects": out, "has_starter": os.path.isfile(self._starter_path())}

    @staticmethod
    def _project_summary(data):
        """Genre, tempo, key and a small note preview of a project's latest beat, for Studio's recent beats."""
        out = {"genre": None, "tempo": None, "key": None, "preview": [], "preview_role": None}
        props = [p for p in (data.get("proposals") or {}).values() if isinstance(p, dict) and p.get("parts")]
        if not props:
            return out
        last = props[-1]
        info = last.get("info") or {}
        out.update(genre=last.get("genre"), tempo=info.get("tempo"), key=info.get("key"))
        parts = [p for p in last["parts"] if isinstance(p, dict) and (p.get("plan") or {}).get("notes")]
        part = next((p for p in parts if p.get("role") not in ("drums", "bass")), parts[0] if parts else None)
        if part:
            out["preview_role"] = part.get("role")
            out["preview"] = [[n.get("start", 0), n.get("length", .25), n.get("pitch", 60)] for n in part["plan"]["notes"][:48]]
        return out

    @property
    def FL_TEMPLATES(self):
        import glob
        apps = sorted(glob.glob("/Applications/FL Studio*.app"))
        return os.path.join(apps[-1] if apps else "/Applications/FL Studio 2026.app", "Contents/Resources/FL/Data/Templates")
    FL_PROJECTS = os.path.expanduser("~/Documents/Image-Line/FL Studio/Projects")

    def _starter_path(self):
        return os.path.join(os.path.dirname(self.session_file), "templates", "Veloura starter.flp")

    def new_fl_project(self, name, template=None):
        """Create <name>.flp from the user's starter (or FL's Empty template) and open it in FL. Never overwrites."""
        name = re.sub(r'[\\/:*?"<>|]+', "", (name or "").strip())[:60]
        if not name:
            raise EngineError("Give the project a name.")
        folder = os.path.join(self.FL_PROJECTS, name)
        path = os.path.join(folder, name + ".flp")
        if os.path.exists(path) or os.path.exists(folder):
            raise EngineError("There's already a project called %r." % name)
        src = template if template and os.path.isfile(template) else (
            self._starter_path() if os.path.isfile(self._starter_path()) else os.path.join(self.FL_TEMPLATES, "Empty", "Empty.flp"))
        if not os.path.isfile(src):
            raise EngineError("Couldn't find a template to start from.")
        os.makedirs(folder)
        shutil.copy2(src, path)
        import subprocess
        subprocess.run(["/usr/bin/open", "-b", "com.image-line.flstudio", path], timeout=20)
        self.event("ok", "Created %s and opened it in FL." % path)
        return {"ok": True, "path": path, "from": os.path.basename(src)}

    def save_starter(self):
        """Use the current FL project (its channels, plugins, mixer) as the starting point for new projects."""
        name = getattr(self.trigger, "fl_project_name", lambda: None)()
        path = self._find_project_file(name) if name and name != "Untitled" else None
        if not path:
            raise EngineError("Save this project in FL first so Veloura can find it.")
        os.makedirs(os.path.dirname(self._starter_path()), exist_ok=True)
        shutil.copy2(path, self._starter_path())
        self.event("ok", "New projects will start from %s." % os.path.basename(path))
        return {"ok": True, "from": path}

    def delete_project(self, name):
        """Forget a project's chat and history in Veloura (moved to a trash folder; the FL file itself isn't touched)."""
        if name == self.project:
            raise EngineError("That's the project open in FL. Use Start fresh instead, or switch FL to another project first.")
        path = self._project_file(name)
        if not os.path.exists(path):
            raise EngineError("No such project.")
        trash = os.path.join(os.path.dirname(path), "trash")
        os.makedirs(trash, exist_ok=True)
        shutil.move(path, os.path.join(trash, "%s %s.json" % (os.path.basename(path)[:-5], time.strftime("%Y%m%d-%H%M%S"))))
        return {"ok": True}

    def start_fresh(self):
        """New conversation for this project. The old one is archived next to it; parts already in FL stay in FL."""
        path = self._project_file(self.project)
        if os.path.exists(path):
            shutil.copy(path, path[:-5] + " (archived %s).json.bak" % time.strftime("%Y-%m-%d %H%M"))
        with self.state_lock:
            self.state["messages"] = []
            self.state["proposals"] = {}
            self.state["arrangement"] = None
        self.save()
        self.event("info", "Started a fresh conversation for %r." % self.project)
        return {"ok": True}

    def save(self):
        with self.state_lock:
            os.makedirs(os.path.dirname(self.session_file), exist_ok=True)
            glob_state = {k: v for k, v in self.state.items() if k not in self.PROJECT_KEYS}
            proj = {k: self.state.get(k) for k in self.PROJECT_KEYS}
            for path, data in ((self.session_file, glob_state), (self._project_file(getattr(self, "project", "Default")), proj)):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=1)
                os.replace(tmp, path)

    def event(self, level, text):
        with self.state_lock:
            self.state["events"].append({"time": _now(), "level": level, "text": text})
            self.state["events"] = self.state["events"][-300:]
        bp.log_attempt({"type": "app_event", "level": level, "text": text})

    def snapshot_state(self):
        with self.state_lock:
            st = copy.deepcopy(self.state)
        st["busy"] = self.busy
        st["app"] = {"version": edition.VERSION, "channel": edition.CHANNEL, "dev_mode": ai.DEV_MODE,
                     "providers": ai.customer_providers(), "claude_models": ai.CLAUDE_MODELS}
        return st

    # ---------- cancelling ----------

    def cancel(self):
        """Stop the slow thing in progress (AI reply or song analysis). FL writes are atomic and finish on their own."""
        self.cancel_event.set()
        ai.cancel_running()
        return {"ok": True}

    def _cancellable(self, fn):
        """Run fn in a worker thread; return its result, or raise Cancelled as soon as Cancel is pressed."""
        self.cancel_event.clear()
        box = {}

        def work():
            try:
                box["value"] = fn()
            except BaseException as e:  # handed back to the caller below
                box["error"] = e
        t = threading.Thread(target=work, daemon=True)
        t.start()
        while t.is_alive():
            if self.cancel_event.wait(0.2):
                raise Cancelled()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    # ---------- status ----------

    def detect_channel_roles(self, channels):
        """What each instrument channel is right now, from its loaded sound (preset name), else its channel name."""
        from . import ensemble
        roles = {}
        for c in channels or []:
            if c.get("type") not in ("plugin", "hybrid") or drums.lane_kind(c["name"]):
                continue
            cur = None
            try:
                cur = self.controller.request("presets", {"channel": c["index"], "expect_name": c["name"], "names": False},
                                              timeout=5).get("current")
            except (ControllerUnavailable, ControllerError):
                pass
            inst = ensemble.instrument_from_name(cur) or ensemble.instrument_from_name(c["name"])
            if inst:
                roles[c["name"]] = inst
        return roles

    def auto_instrument(self, pid, index):
        """The user doesn't want to hunt for a sound: use a spare instrument channel (FLEX first), pick a preset that fits
        the part's instrument, and route the part there. Never touches channels the user assigned."""
        from . import ensemble
        prop, part = self._find_part(pid, index)
        inst = part.get("instrument") or ensemble.instrument_from_name(part["name"]) or "lead_synth"
        chans = self.controller_status(max_age=0).get("channels") or []
        used = {(p.get("destination") or {}).get("channel") for p in prop["parts"] if p is not part}
        busy = {(e.get("channel_name")) for e in self.current_parts().values()}
        spare = [c for c in chans if c.get("type") in ("plugin", "hybrid") and c["name"] not in used and c["name"] not in busy
                 and not drums.lane_kind(c["name"])]
        if not spare:
            return {"ok": False, "message": "No spare instrument channel. In FL click + in the Channel Rack and add FLEX (or any "
                                            "instrument); Veloura will pick the sound for it."}
        best, best_name, best_score = None, None, -1
        words = ensemble.KEYWORDS.get(inst, [])
        for c in spare:
            try:
                info = self.controller.request("presets", {"channel": c["index"], "expect_name": c["name"]}, timeout=60)
            except (ControllerUnavailable, ControllerError):
                continue
            names = [n for n in info.get("names") or [] if n]
            if len(names) < 2:   # e.g. 3x Osc: fine as a synth lead as it is
                score, pick = (1 if inst in ("lead_synth", "arp_synth") else 0), None
            else:
                pick = max(names, key=lambda n: sum(2 for w in words if w in n.lower()))
                score = sum(2 for w in words if w in pick.lower())
                cur = info.get("current")
                if cur in names and pick in names and abs(names.index(pick) - names.index(cur)) > 80:
                    score -= 1   # too far to step through quickly
            if score > best_score:
                best, best_name, best_score = c, pick, score
        if best is None or best_score <= 0:
            return {"ok": False, "message": "Your spare instrument channels don't have a %s sound. Load one (%s)." % (
                inst.replace("_", " "), ensemble.SOUND_TIPS.get(inst, ""))}
        note = ""
        if best_name:
            with self.fl_lock:
                ok, msg, prev = sounds.switch(self.controller, best, best_name)
            if ok and prev != best_name:
                self._log_change("sound", channel=best["index"], name=best["name"], before=prev, after=best_name)
            note = " with the %r sound" % best_name if ok else ""
        with self.state_lock:
            part.setdefault("_roles", {})[best["name"]] = inst
        self.set_route(pid, index, best["index"])
        self.event("ok", "%s will play on %s%s." % (part["name"], best["name"], note))
        return {"ok": True, "channel": best["name"], "sound": best_name, "message": "%s goes on %s%s." % (part["name"], best["name"], note)}

    def instruments_needed(self, prop, channels):
        """The melodic instruments a reply needs and where each one is (or what sound to go and find)."""
        from . import ensemble
        out = []
        for i, p in enumerate(prop.get("parts") or []):
            if p.get("role") == "drums" or (p.get("purpose") == "sample"):
                continue
            d = p.get("destination") or {}
            inst = p.get("instrument") or ensemble.instrument_from_name(p["name"]) or "lead_synth"
            out.append({"index": i, "part": p["name"], "instrument": inst, "channel": d.get("channel"), "how": d.get("how"),
                        "tip": ensemble.SOUND_TIPS.get(inst, "an instrument plugin"), "status": p.get("status")})
        return out

    def refresh_routes(self, channels):
        """The Channel Rack changed (a channel added or renamed): re-check where every waiting part goes."""
        sig = tuple((c["index"], c["name"]) for c in channels)
        if sig == getattr(self, "_route_sig", None):
            return
        self._route_sig = sig
        with self.state_lock:
            for prop in self.state.get("proposals", {}).values():
                for p in prop.get("parts") or []:
                    if p.get("status") != "applied":
                        p["destination"] = self._destination(p, channels)
                if prop.get("instruments") is not None:
                    prop["instruments"] = self.instruments_needed(prop, channels)

    def status(self):
        # The slower checks (project name via System Events, the controller round trip, AI providers) run side by
        # side, so one slow answer can't hold up the rest.
        fl = self.trigger.fl_running()
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_proj = pool.submit(self.check_project) if fl else None
            f_ctl = pool.submit(self.controller_status) if fl else None
            f_prov = pool.submit(ai.provider_status)
            acc = self.trigger.accessibility_enabled()
            ctl = f_ctl.result() if f_ctl else {"connected": False, "detail": "FL Studio is not running."}
            if f_proj:
                f_proj.result()
            providers = f_prov.result()
        if fl and ctl.get("channels"):
            self.refresh_routes(ctl["channels"])
        return {
            "fl_running": fl,
            "accessibility": acc,
            "bridge_script": bp.installed_script_state(),
            "bridge_folder": bp.bridge_ready(),
            "controller_script": bp.controller_script_state(),
            "providers": providers,
            "provider": self.state["settings"]["provider"],
            "busy": self.busy,
            "controller": ctl,
            "armed": self.bridge_armed() if fl else False,
            "ready": fl and acc and bp.bridge_ready() and bp.installed_script_state() == "installed and up to date",
            "project": self.project,
            "connection_hint": self._connection_hint(fl),
            "reconnect_steps": RECONNECT_STEPS,
            "kit_folders": len(self.library.data.get("folders") or []),
        }

    def _connection_hint(self, fl):
        """Why the FL controller isn't connected, in plain words, with the fix Veloura can do."""
        if not fl:
            return {"code": "fl_closed", "text": "FL Studio isn't open. Open it from Veloura so everything connects.", "action": "open_fl"}
        ctl = self.controller_status() or {}
        if ctl.get("connected"):
            if ctl.get("safe_to_edit") is False:
                return {"code": "fl_busy", "action": "focus_fl",
                        "text": "FL has a window open that blocks changes (after an update this is usually a What's new, "
                                "sign-in or audio-settings window). Bring FL to the front and close it."}
            return None
        started = fl_started_at()
        if started and started < self.started_at - 2:
            return {"code": "fl_first", "action": "restart_fl",
                    "text": "FL Studio was opened before Veloura, so it can't see Veloura. Always open Veloura first. "
                            "Veloura can save your project, restart FL and reopen it for you."}
        return {"code": "not_setup", "action": "setup",
                "text": "The FL controller isn't connected. Check Setup step 3 (MIDI settings: Veloura to FL, port 10)."}

    def focus_fl(self):
        import subprocess
        subprocess.run(["/usr/bin/osascript", "-e", 'tell application id "com.image-line.flstudio" to activate'], timeout=10)
        return {"ok": True}

    def open_fl(self):
        import subprocess
        subprocess.run(["/usr/bin/open", "-b", "com.image-line.flstudio"], timeout=20)
        return {"ok": True}

    def _find_project_file(self, name):
        import subprocess
        try:
            out = subprocess.run(["/usr/bin/mdfind", "kMDItemFSName == '%s.flp'" % name.replace("'", "\\'")],
                                 capture_output=True, text=True, timeout=15).stdout.split("\n")
        except (OSError, subprocess.TimeoutExpired):
            out = []
        files = [f for f in out if f.endswith(".flp") and os.path.isfile(f) and "/Backup/" not in f]
        return max(files, key=os.path.getmtime) if files else None

    def restart_fl(self):
        """Save the project (Cmd+S), quit FL, and reopen the same project, now that Veloura is running first."""
        import subprocess
        name = getattr(self.trigger, "fl_project_name", lambda: None)()
        if not name or name == "Untitled":
            raise EngineError("Save your project in FL first (Cmd+S) so Veloura knows which file to reopen.")
        path = self._find_project_file(name)
        if not path:
            raise EngineError("Veloura couldn't find %s.flp on this Mac. Restart FL yourself and open it." % name)
        osa = lambda *lines: subprocess.run(["/usr/bin/osascript"] + [a for l in lines for a in ("-e", l)],
                                            capture_output=True, text=True, timeout=20)
        osa('tell application id "com.image-line.flstudio" to activate', "delay 0.4",
            'tell application "System Events" to keystroke "s" using {command down}')
        time.sleep(2.0)
        osa('tell application id "com.image-line.flstudio" to quit')
        for _ in range(60):
            if not self.trigger.fl_running():
                break
            time.sleep(0.5)
        else:
            raise EngineError("FL didn't close (maybe a save dialog is open). Finish it in FL, then try again.")
        time.sleep(1.0)
        subprocess.run(["/usr/bin/open", "-b", "com.image-line.flstudio", path], timeout=20)
        self.event("ok", "Restarted FL Studio with %s." % os.path.basename(path))
        return {"ok": True, "project": path}

    def bridge_armed(self):
        """True if the Piano Roll bridge has answered, or was run from FL's menu, since FL Studio last started."""
        import glob
        started = fl_started_at()
        markers = glob.glob(os.path.join(bp.BRIDGE_DIR, "armed-*.marker"))
        latest_marker = max((os.path.getmtime(m) for m in markers), default=0)
        for m in sorted(markers)[:-3]:   # tidy old markers (FL scripts can't delete files)
            try:
                os.remove(m)
            except OSError:
                pass
        last = max(self.bridge_ok_at or 0, latest_marker)
        # FL's "run last script again" only works since FL started AND since the script file last changed.
        try:
            script_changed = os.path.getmtime(bp.SCRIPT_INSTALLED)
        except OSError:
            script_changed = 0
        return bool(last) and last >= max(started or 0, script_changed)

    def open_any_piano_roll(self, name=None):
        """Help the user arm the bridge: open the Piano Roll of a melodic channel (or the first channel)."""
        try:
            chans = self.controller.request("project").get("channels") or []
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError("Needs the FL controller: %s" % e)
        if not chans:
            raise EngineError("Your Channel Rack is empty.")
        pick = next((c for c in chans if c["name"] == name), None) if name else None
        pick = pick or next((c for c in chans if c.get("type") == "plugin"), chans[0])
        ok, detail = self._open_target(pick)
        return {"ok": ok, "message": "Opened the Piano Roll of %r. Now choose Tools > Scripts > veloura_bridge." % pick["name"]
                if ok else detail}

    SETUP_ORDER = ("ai", "keys", "midi", "pianoroll", "kits")

    def setup_steps(self):
        """First-run checklist for a new customer, in order, each step with a live ok flag."""
        st = self.status()
        prov = st["providers"].get(st["provider"], {})
        ok = {"ai": bool(prov.get("available")) and st["provider"] != "offline",
              "keys": st["accessibility"],
              "midi": bool(st["controller"].get("connected")),
              "pianoroll": st["armed"],
              "kits": st["kit_folders"] > 0}
        return [dict({"id": i, "ok": ok[i]}, **({"provider": st["provider"]} if i == "ai" else {}))
                for i in self.SETUP_ORDER], st

    def open_accessibility_settings(self):
        import subprocess
        subprocess.run(["/usr/bin/open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                       timeout=10)
        return {"ok": True}

    def ensure_bridge(self):
        """Install or update Veloura's own FL script and exchange folder (never touches other files)."""
        bp.setup_bridge_dir()
        if bp.installed_script_state() != "installed and up to date":
            tmp = os.path.join(bp.FL_SCRIPTS_DIR, ".veloura_bridge.tmp")
            shutil.copy(bp.SCRIPT_SOURCE, tmp)
            os.replace(tmp, bp.SCRIPT_INSTALLED)
            self.event("info", "Installed the veloura_bridge script into FL Studio's Piano roll scripts folder.")
        if bp.controller_script_state() != "installed and up to date" and os.path.isdir(os.path.dirname(bp.CONTROLLER_DIR)):
            os.makedirs(bp.CONTROLLER_DIR, exist_ok=True)
            tmp = os.path.join(bp.CONTROLLER_DIR, ".veloura_controller.tmp")
            shutil.copy(bp.CONTROLLER_SOURCE, tmp)
            os.replace(tmp, bp.CONTROLLER_INSTALLED)
            self.event("info", "Installed the Veloura Controller script (restart FL Studio or re-select it in MIDI settings to load it).")
        if bp.installed_script_state() == "installed and up to date" and bp.remove_old_cadence_files():
            self.event("info", "Removed the old Cadence scripts from FL Studio (Veloura's replace them).")
        return bp.installed_script_state()

    # ---------- settings ----------

    def update_settings(self, changes):
        allowed = {"tempo_bpm", "key", "bars", "genre", "mood", "swing", "provider", "model", "gemini_model", "chatgpt_model",
                   "onboarded", "auto_tempo", "tempo_auto", "key_auto", "bars_auto", "remind_loop", "remind_cut", "careful",
                   "feel", "locked_parts", "quality", "use_my_style", "auto_mixer", "auto_sounds", "guide_arrow", "listen_after", "kit_auto_load",
                   "theme", "rack_open"}
        with self.state_lock:
            for k, v in changes.items():
                if k not in allowed:
                    continue
                if k == "feel":
                    if not isinstance(v, dict):
                        continue
                    v = {fk: max(0, min(100, float(fv))) for fk, fv in v.items()
                         if fk in theory.DEFAULT_FEEL and isinstance(fv, (int, float))}
                elif k == "locked_parts":
                    if not isinstance(v, list):
                        continue
                    v = [str(x)[:60] for x in v][:40]
                elif k == "tempo_bpm":
                    v = max(40, min(300, int(v)))
                elif k == "bars":
                    v = max(1, min(16, int(v)))
                elif k == "swing":
                    v = max(0, min(100, int(v)))
                elif k == "provider" and v not in ai.customer_providers():
                    continue
                elif k == "quality" and v not in ("best", "fast"):
                    continue
                elif k == "theme" and v not in THEMES:
                    continue
                elif k == "model":
                    v = str(v)[:60]
                    self.state["settings"]["model_chosen"] = True   # a deliberate pick is never moved by a default change
                elif k in ("onboarded", "auto_tempo", "tempo_auto", "key_auto", "bars_auto", "remind_loop", "remind_cut", "careful",
                           "use_my_style", "auto_mixer", "auto_sounds", "guide_arrow", "listen_after", "kit_auto_load", "rack_open"):
                    v = bool(v)
                else:
                    v = str(v)[:60]
                self.state["settings"][k] = v
        self.save()
        return self.state["settings"]


    # ---------- controller (Milestone C) ----------

    def controller_status(self, max_age=4.0):
        at, cached = self._ctl_cache
        if cached is not None and time.time() - at < max_age:
            return cached
        lock = getattr(self.controller, "lock", None)
        if cached is not None and cached.get("connected") and max_age > 0 and lock is not None and lock.locked():
            # Veloura itself is busy talking to FL (loading a kit, writing steps): FL is connected, it's just
            # answering Veloura. Waiting here stalled status for seconds and could time out into a false
            # "FL isn't connected".
            return dict(cached, busy=True)
        try:
            proj = self.controller.request("project", timeout=1.2)
            st = {"connected": True, "detail": "Connected (API %s)" % proj.get("api_version"), "tempo": proj.get("tempo"),
                  "pattern": proj.get("pattern"), "channels": proj.get("channels", []), "api_version": proj.get("api_version"),
                  "safe_to_edit": proj.get("safe_to_edit", True)}
        except (ControllerUnavailable, ControllerError) as e:
            # Keep virtual ports open: closing them would make them vanish from FL's MIDI settings.
            st = {"connected": False, "detail": str(e)}
        self._ctl_cache = (time.time(), st)
        return st

    def open_controller_ports(self):
        """Create Veloura's virtual MIDI ports at startup so FL can see them."""
        try:
            self.controller._ensure()
        except ControllerUnavailable:
            pass

    # ---------- sound prep (settings FL doesn't let scripts change) ----------

    BASS_WORDS = ("808", "bass", "sub")

    def sound_prep(self):
        """Checklist of per-channel settings the user wants on every sound. FL's scripting API can't change these,
        so Veloura lists them, remembers what's done, and flags new sounds."""
        ctl = self.controller_status()
        if not ctl.get("connected"):
            return {"connected": False, "items": []}
        done = self.state.setdefault("prep_done", {})
        items = []
        for c in ctl.get("channels") or []:
            name, typ = c["name"], c.get("type", "sampler")
            n = name.lower()
            tasks = []
            settings = self.state["settings"]
            if typ == "sampler" and settings.get("remind_loop", True):
                tasks.append({"id": "loop", "label": "Turn off “Use loop points”"})
            if any(w in n for w in self.BASS_WORDS) and settings.get("remind_cut", True):
                tasks.append({"id": "cut", "label": "Turn on “Cut itself”" if typ == "sampler" else
                              "Set Polyphony to Mono (so 808 notes cut each other)"})
            if not tasks:
                continue
            for t in tasks:
                t["done"] = bool(done.get("%s|%s" % (name, t["id"])))
            items.append({"channel": name, "type": typ, "tasks": tasks})
        pending = sum(1 for i in items for t in i["tasks"] if not t["done"])
        return {"connected": True, "items": items, "pending": pending}

    def set_prep(self, channel, task, done):
        with self.state_lock:
            self.state.setdefault("prep_done", {})["%s|%s" % (channel, task)] = bool(done)
        self.save()
        return self.sound_prep()

    def listen_check(self, seconds=8.0, fix=False):
        """Veloura 'listens' to the beat: it presses play, reads FL's level meter on every mixer track while the loop
        plays, stops, then watches for anything still ringing. It can't hear tone, but levels tell it a lot:
        parts that make no sound, clipping, an 808 burying the kick, sounds ringing after stop."""
        try:
            start = self.controller.request("meters")
            if start.get("playing"):
                self.controller.request("transport", {"action": "stop"})
                time.sleep(0.4)
            mix = self.controller.request("mix_state", timeout=6.0)
            self.controller.request("transport", {"action": "play"})
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError("Veloura needs the FL controller to listen: %s" % e)
        peaks, t_end = {}, time.time() + seconds
        try:
            while time.time() < t_end:
                for t in self.controller.request("meters")["tracks"]:
                    if t["track"] >= 125 or not (0 <= t["peak"] < 8):   # FL's hidden preview/current tracks report nonsense
                        continue
                    peaks[t["track"]] = max(peaks.get(t["track"], 0), t["peak"])
                time.sleep(0.12)
        finally:
            try:
                self.controller.request("transport", {"action": "stop"})
            except (ControllerUnavailable, ControllerError):
                pass
        time.sleep(0.3)
        tails = self.sound_after_stop(seconds=2.5)
        track_of = {c["name"]: c["mixer_track"] for c in mix["channels"]}
        findings = []
        master = peaks.get(0, 0)
        if master > 1.0:
            findings.append({"level": "warn", "id": "clip", "title": "The master is clipping",
                             "detail": "Peaks hit %.0f%% (over 100%% distorts). Turning the loudest parts down a little fixes it." % (master * 100),
                             "fix": {"kind": "mixer_volume_db", "target": "Master", "value": round(-20 * __import__("math").log10(master) - 1, 1)}})
        elif master < 0.25 and master > 0:
            findings.append({"level": "info", "id": "quiet", "title": "The beat is quiet", "detail": "Master peaks at %.0f%%." % (master * 100)})
        silent = []
        for name, e in self.current_parts().items():
            ch = e.get("channel_name") or name
            tr = track_of.get(ch)
            if tr is None:
                continue
            if tr != 0 and peaks.get(tr, 0) < 0.002 and ch not in silent:
                silent.append(ch)
        if silent:
            findings.append({"level": "warn", "id": "silent", "title": "Some parts make no sound",
                             "detail": ", ".join(silent[:6]) + ": check the channel has a sound loaded, isn't muted, and is in the playing pattern."})
        kick = next((peaks.get(track_of[n], 0) for n in track_of if drums.lane_kind(n) == "kick" and track_of[n] != 0), None)
        bass = next((peaks.get(track_of[n], 0) for n in track_of if "808" in n.lower() and not drums.lane_kind(n) and track_of[n] != 0), None)
        if kick and bass and bass > kick * 1.6:
            findings.append({"level": "warn", "id": "808", "title": "The 808 is burying the kick",
                             "detail": "808 peaks %.0f%% vs kick %.0f%%." % (bass * 100, kick * 100)})
        if tails.get("tracks"):
            findings.append({"level": "warn", "id": "tail", "title": "Something keeps sounding after stop",
                             "detail": tails["message"] + " Usually a sample's loop points are on, or an 808 needs Cut itself."})
        if not findings:
            findings.append({"level": "ok", "id": "good", "title": "Everything plays and the levels look healthy",
                             "detail": "Master peaks at %.0f%%." % (master * 100)})
        result = {"ok": True, "master_peak": round(master, 3), "findings": findings,
                  "tracks": [{"track": t, "peak": round(v, 3)} for t, v in sorted(peaks.items())]}
        self.event("info", "Listen check: " + "; ".join(f["title"] for f in findings))
        return result

    def listen_fix(self, kind, target, value):
        if kind != "mixer_volume_db":
            raise EngineError("Unknown fix.")
        mix = self.controller.request("mix_state", timeout=6.0)
        changes, preview, problems = mixmod.resolve([{"kind": kind, "target": target, "value": value}], mix)
        if not changes:
            raise EngineError(" ".join(problems) or "Nothing to change.")
        send, undo = mixmod.split_undo(changes)
        res = self.controller.request("set_mix", {"changes": send})["results"]
        self._log_change("listen_fix", undo=undo)
        return {"ok": all(r.get("ok") for r in res)}

    def sound_after_stop(self, seconds=4.0):
        """Diagnostic: while FL is stopped, watch every mixer track and report any that keep making sound."""
        try:
            first = self.controller.request("meters")
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError("Needs the FL controller: %s" % e)
        if first.get("playing"):
            return {"ok": False, "message": "FL is playing. Press stop in FL, then run the check within a second or two."}
        loudest, deadline = {}, time.time() + seconds
        feeds = first.get("feeds", {})
        while time.time() < deadline:
            m = self.controller.request("meters")
            if m.get("playing"):
                break
            for t in m["tracks"]:
                key = t["track"]
                if key >= 125 or not (0 <= t["peak"] < 8):
                    continue
                if t["peak"] > loudest.get(key, {}).get("peak", 0):
                    loudest[key] = dict(t, channels=feeds.get(str(key), []))
            time.sleep(0.15)
        found = sorted((t for t in loudest.values() if t["peak"] > 0.003), key=lambda t: -t["peak"])
        if not found:
            return {"ok": True, "tracks": [], "message": "Silent: nothing is making sound in FL after stop."}
        culprits = [t for t in found if t["track"] != 0] or found
        names = ", ".join("%s (insert %d, peak %.0f%%%s)" % (t["name"], t["track"], t["peak"] * 100,
                          (", fed by " + ", ".join(t["channels"])) if t["channels"] else "") for t in culprits[:4])
        return {"ok": True, "tracks": found, "message": "Still sounding after stop: " + names}

    def _log_change(self, kind, **data):
        """Remember what Veloura changed in this project (besides parts) so it can all be undone later."""
        with self.state_lock:
            self.state.setdefault("changes", []).append(dict(data, type=kind, at=_now()))
            del self.state["changes"][:-300]

    def set_fl_tempo(self, bpm):
        bpm = float(bpm)
        before = self.controller_status().get("tempo")
        if before and not any(c["type"] == "tempo" for c in self.state.get("changes") or []):
            self._log_change("tempo", before=before)
        try:
            res = self.controller.request("set_tempo", {"bpm": bpm})
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError("Could not set FL's tempo: %s" % e)
        ok = res.get("tempo") is not None and abs(res["tempo"] - bpm) < 0.01
        self._ctl_cache = (0, None)
        self.event("ok" if ok else "error", "FL tempo set to %s BPM (FL now reports %s)." % (bpm, res.get("tempo")))
        self.save()
        return {"ok": ok, "tempo": res.get("tempo")}

    def _auto_unmute(self, chan):
        """Writing to a muted channel looks like nothing happened: unmute it (a common slip)."""
        try:
            st = self.controller.request("rack_state", timeout=3.0)
            row = next((c for c in st["channels"] if c["index"] == chan["index"]), None)
            if row and row.get("muted"):
                self.controller.request("set_mix", {"changes": [{"kind": "channel_mute", "channel": chan["index"],
                                                                  "expect_name": chan["name"], "value": False}]})
                self._log_change("unmute", channel=chan["index"], name=chan["name"])
                return True
        except (ControllerUnavailable, ControllerError, KeyError):
            pass
        return False

    def fl_features(self):
        if getattr(self, "_features_at", 0) > time.time() - 30:
            return self._features
        try:
            self._features = self.controller.request("hello", timeout=3).get("features") or {}
        except (ControllerUnavailable, ControllerError):
            self._features = {}
        self._features_at = time.time()
        return self._features

    def _steps_mutation(self, chan, pattern, steps):
        params = {"channel": chan["index"], "expect_name": chan["name"], "pattern": pattern, "steps": steps}
        if self.fl_features().get("pattern_length"):
            params["fit_length"] = len(steps)          # FL 2026: grow the pattern so the whole part plays
        written = self.controller.request("write_steps", params)
        ok = drums.steps_equal(steps, written["steps"])
        confirm = self.controller.request("read_steps", {"channel": chan["index"], "expect_name": chan["name"],
                                                         "count": len(steps)})
        confirmed = drums.steps_equal(steps, confirm["steps"])
        return ok, confirmed, written

    def _apply_steps(self, part, plan, existing, allow_existing, force=False):
        """Write a drum lane into the step sequencer of its routed channel. Returns (out, None) or (None, reason)."""
        try:
            proj = self.controller.request("project")
        except (ControllerUnavailable, ControllerError):
            return None, "the Veloura Controller is not connected"
        r = self._resolve_route(part, proj["channels"])
        chan = next((c for c in proj["channels"] if c["index"] == r["index"] and c["name"] == r["name"]), None)
        if not chan:
            return None, r["problem"] or "no channel"
        if self._auto_unmute(chan):
            self.event("info", "Unmuted %s so you can hear it." % chan["name"])
        steps, problem = drums.plan_to_steps(plan)
        swing_note = ""
        if problem and self.fl_features().get("swing"):
            straight, amount = drums.deswing(plan)      # FL 2026: swing with FL's own swing knob, keep it in the steps
            steps2, problem2 = drums.plan_to_steps(straight)
            if steps2 is not None:
                steps, problem = steps2, None
                try:
                    cur = self.controller.request("swing", {})
                    if amount > cur["now"] + 0.02:
                        res = self.controller.request("swing", {"value": round(min(1.0, amount), 3)})
                        self._log_change("swing", before=res["before"])
                        swing_note = " Swing set to %d%%." % round(res["now"] * 100)
                except (ControllerUnavailable, ControllerError):
                    pass
        if problem:
            return None, problem
        pattern = proj["pattern"]["number"]
        try:
            before = self.controller.request("read_steps", {"channel": chan["index"], "expect_name": chan["name"],
                                                            "count": len(steps)})
            base = {"status": "refused", "ok": False, "mode": "steps", "channel": chan["name"], "pattern": pattern}
            if existing and existing.get("mode") == "steps":
                if existing["channel_name"] != chan["name"] or existing["channel"] != chan["index"]:
                    # A different channel (e.g. the user swapped kits): this is a fresh write, the old part stays as it was.
                    existing = None
                elif existing["pattern"] != pattern:
                    return dict(base, code="replace_failed", message=(
                        "Veloura's %s steps are in pattern %d, but FL is showing pattern %d. Switch back to pattern %d to "
                        "revise them, or add this as a new copy." % (part["name"], existing["pattern"], pattern, existing["pattern"]))), None
            if existing and existing.get("mode") == "steps":
                if drums.steps_equal(existing["written"], before["steps"]):
                    previous = existing["previous"]
                elif drums.steps_equal(existing["previous"], before["steps"]):
                    # The channel is back exactly as it was before Veloura (e.g. Cmd+Z in FL), so nothing of
                    # the user's is at risk: write this version fresh.
                    previous = before["steps"]
                    self.event("info", "Veloura noticed its earlier %s steps were undone in FL; writing fresh." % chan["name"])
                elif force:
                    previous = before["steps"]   # Reapply: the user asked to replace whatever is on this channel now
                else:
                    return dict(base, code="replace_failed", message=(
                        "The %s steps were edited since Veloura wrote them, so Veloura won't overwrite your changes. "
                        "Undo your edits or write this as a new copy." % chan["name"])), None
            if not (existing and existing.get("mode") == "steps"):
                if any(s["on"] for s in before["steps"]) and not allow_existing and self.state["settings"].get("careful"):
                    return dict(base, code="not_empty", message=(
                        "Channel %r already has steps in pattern %d. Veloura won't overwrite them unless you allow it "
                        "(Veloura's Remove button puts back exactly what was there)." % (chan["name"], pattern))), None
                previous = before["steps"]
            t0 = time.time()
            ok, confirmed, written = self._steps_mutation(chan, pattern, steps)
        except ControllerError as e:
            return {"ok": False, "status": "failed", "mode": "steps", "message": "FL rejected the step write: %s" % e}, None
        except ControllerUnavailable as e:
            return {"ok": False, "status": "no_result", "mode": "steps", "message": str(e)}, None
        hits = sum(1 for s in steps if s["on"])
        length = (written.get("pattern") or {}).get("length_steps")
        warn = ""
        if written.get("grew"):
            length = written["grew"]["to"]
        if length and length < len(steps):
            warn = " Note: FL reports this pattern as %d steps long; set the pattern length to %d bars to hear all of it." % (
                length, plan["bars"])
        out = {"ok": ok and confirmed, "status": "applied" if ok else "applied_unverified", "mode": "steps",
               "message": "Wrote %d hits to the step sequencer on channel %r (pattern %d).%s%s" % (hits, chan["name"], pattern, warn, swing_note),
               "checks": [{"check": "Every step read back as written (on/off and velocity)", "passed": ok,
                           "detail": "%d steps" % len(steps)}],
               "confirmed": confirmed, "confirm_detail": "confirmed by a separate step read-back" if confirmed else
               "the separate read-back did not match", "seconds": round(time.time() - t0, 2),
               "registry": {"mode": "steps", "channel": chan["index"], "channel_name": chan["name"], "pattern": pattern,
                            "written": steps, "previous": previous}}
        return out, None

    # ---------- chat ----------

    def chat(self, text, mode="describe", genre=None, reference_id=None):
        text = (text or "").strip()
        if not text:
            raise EngineError("Empty message.")
        request = {"mode": mode if mode in ("describe", "genre", "sample", "inspiration") else "describe", "genre": genre}
        if reference_id:
            ref = self.state["references"].get(reference_id)
            if not ref:
                raise EngineError("That reference song is no longer available.")
            request["reference"] = ref
            request["mode"] = ref["mode"]
        settings = self.state["settings"]
        from . import ensemble as _ens
        chans_now = self.controller_status().get("channels") or []
        # what each instrument channel is: worked out from the sound loaded on it, overridden by what this message says
        roles_now = dict(self.detect_channel_roles(chans_now), **_ens.parse_channel_roles(text, chans_now))
        self._chat_roles = roles_now
        with self.state_lock:
            ref = request.get("reference")
            self.state["messages"].append({"id": uuid.uuid4().hex[:10], "role": "user", "text": text, "time": _now(),
                                           "attachment": {"name": ref["name"], "mode": ref["mode"]} if ref else None})
            history = [{"role": m["role"], "text": m["text"][:500]} for m in self.state["messages"][-10:-1]]
            parts = copy.deepcopy(self.state["parts"])
        self.save()
        self.busy = "Thinking (%s)..." % settings["provider"]
        self.progress = None
        self.set_progress(3, "Reading your project", "Looking at your Channel Rack, tempo and the parts already in FL")
        try:
            ctl = self.controller_status()
            fl_context = {k: ctl.get(k) for k in ("tempo", "pattern", "channels")} if ctl.get("connected") else None
            mix_state = None
            if fl_context and settings["provider"] != "offline":
                try:
                    mix_state = self.controller.request("mix_state", timeout=6.0)
                    fl_context["mix"] = mixmod.compact_state(mix_state)
                except (ControllerUnavailable, ControllerError):
                    mix_state = None
            if fl_context and settings["provider"] != "offline":
                self.set_progress(7, "Browsing your instruments", "Listing the sounds inside your plugins")
                fl_context["sounds"] = self._sound_menu(fl_context.get("channels") or [], text)
            facts, inferred = self.project_model(ctl)
            from . import genres as _gm
            g_now = request.get("genre") or _gm.match(text) or settings.get("genre")
            fl_context = dict(fl_context or {}, facts=facts, inferred=inferred, taste=self.taste.summary(),
                              channel_instruments=dict(getattr(self, "_chat_roles", {}) or {}),
                              prefer=self.kit_prefer(),
                              style_examples=self.style.examples_for_ai(g_now) if settings.get("use_my_style") else [],
                              style_grooves=self.style.grooves_for(g_now) if settings.get("use_my_style") else None)
            chosen_kit = None
            if self.library.data["samples"] and _wants_drums(text, request["mode"]):
                from . import genres as _g
                chosen_kit = self.choose_kit(request.get("genre") or _g.match(text) or settings.get("genre"))
                fl_context["kit"] = {r: s["name"] for r, s in chosen_kit["roles"].items()}
            if not ctl.get("connected"):
                fl_context.pop("channels", None)
            if request["mode"] == "sample" and request.get("reference"):
                request["sample_channel"] = self._sample_channel(request["reference"], (fl_context or {}).get("channels") or [])
            model = {"gemini": settings.get("gemini_model"), "chatgpt": settings.get("chatgpt_model")}.get(
                settings["provider"], settings.get("model"))
            secs = self._ai_seconds(settings["provider"], model)
            self.set_progress(12, "Composing", "Choosing the key, chords and the idea",
                              estimate={"from": 12, "to": 88, "seconds": secs, "since": time.time()})
            t_ai = time.time()
            resp, problems = self._cancellable(lambda: ai.respond(
                settings["provider"], text, settings, parts, history, model=model, fl_context=fl_context, request=request,
                progress=lambda pct, stage, detail: self.set_progress(pct, stage, detail)))
            self._record_ai_seconds(settings["provider"], time.time() - t_ai, model)
            self.set_progress(95, "Finishing up", "Matching every part to your channels")
        except Cancelled:
            msg = {"id": uuid.uuid4().hex[:10], "role": "assistant", "text": "Cancelled. Nothing was changed.",
                   "time": _now(), "cancelled": True, "provider": settings["provider"]}
            with self.state_lock:
                self.state["messages"].append(msg)
            self.event("info", "AI request cancelled.")
            self.save()
            return msg
        except Exception as e:  # never lose the turn: every failure becomes a visible chat message
            text_err = str(e) if isinstance(e, ai.ProviderError) else "Something went wrong talking to the AI: %r" % (e,)
            msg = {"id": uuid.uuid4().hex[:10], "role": "assistant", "text": text_err, "time": _now(), "error": True,
                   "provider": settings["provider"]}
            with self.state_lock:
                self.state["messages"].append(msg)
            self.event("error", "AI provider error: %s" % e)
            self.save()
            return msg
        finally:
            self.busy = None
            self.clear_progress()
        pid = uuid.uuid4().hex[:10]
        channels = self.controller_status().get("channels") or []
        if request["mode"] == "sample" and request.get("reference"):
            resp["guidance"].insert(0, self._sample_guide(request["reference"], request.get("sample_channel") or "Sample", channels))
        for p in resp["parts"]:
            p["_roles"] = dict(getattr(self, "_chat_roles", {}) or {})
            p["destination"] = self._destination(p, channels)
            p["status"] = "proposed"
            p["result"] = None
            existing = parts.get(p["name"])
            p["action"] = "revise" if existing else "new"
        mix_block = None
        if resp.get("mix"):
            preview, mproblems = [], []
            if mix_state:
                _, preview, mproblems = mixmod.resolve(resp["mix"], mix_state, self._mix_name_map(
                    {"parts": resp["parts"], "mix": {"moves": resp["mix"]}}, mix_state))
            else:
                mproblems = ["Mix moves need the FL controller connected."]
            mix_block = {"moves": resp["mix"], "preview": preview, "problems": mproblems, "status": "proposed", "result": None}
        proposal = {"id": pid, "parts": resp["parts"], "guidance": resp["guidance"], "problems": problems, "mix": mix_block,
                    "instruments": None, "channel_roles": dict(getattr(self, "_chat_roles", {}) or {}),
                    "provider": resp["provider"], "created": _now(), "mode": request["mode"],
                    "reference_id": reference_id, "info": resp.get("info"), "request": text[:300],
                    "genre": self.state["settings"].get("genre"),
                    "kit": chosen_kit if resp["parts"] and any(p["role"] == "drums" for p in resp["parts"]) else None}
        msg = {"id": uuid.uuid4().hex[:10], "role": "assistant", "text": resp["reply"], "time": _now(),
               "proposal_id": pid, "provider": resp["provider"]}
        proposal["instruments"] = self.instruments_needed(proposal, channels)
        with self.state_lock:
            self.state["proposals"][pid] = proposal
            self.state["messages"].append(msg)
        for pr in problems:
            self.event("warn", pr)
        self.save()
        return msg

    @staticmethod
    def _route_key(part):
        """What a remembered routing choice is keyed on: the drum kind for drum lanes, else the part name."""
        if part.get("role") == "drums":
            return "drum:" + (drums.lane_kind(part["name"]) or part["name"].lower())
        return "part:" + part["name"].strip().lower()

    def _resolve_route(self, part, channels):
        """Decide exactly which channel a part goes to. Returns {"index","name","how","kind","problem","fix"}.
        how: chosen (user picked) > kit (the kit Veloura staged, drums) > remembered (picked before in this project) >
        exact name > matched by name."""
        out = {"index": None, "name": None, "how": None, "problem": None, "fix": None}
        chans = channels or []
        if not chans:
            out.update(problem="Veloura can't see your Channel Rack.",
                       fix="Open Veloura before FL Studio (or restart FL with Veloura open) so the controller connects.")
            out["kind"] = "pianoroll"
            return out
        by_name = {c["name"]: c for c in chans}
        r = part.get("route") or {}
        pick = None
        if r.get("how") == "chosen" and r.get("name") in by_name:
            pick, how = by_name[r["name"]], "chosen"
        kit_names = self.kit_prefer() if part.get("role") == "drums" else []
        if not pick and kit_names:
            # The kit Veloura picked for this beat, once its sounds are in the Channel Rack, wins over FL's stock
            # channels and an older remembered choice (the parts were named after the channels that existed
            # before the kit was dragged in).
            chan, _ = drums.match_channel(part["name"], [c for c in chans if c["name"] in kit_names], kit_names)
            if chan:
                pick, how = chan, "kit"
        if not pick:
            remembered = (self.state.get("routing") or {}).get(self._route_key(part))
            if remembered in by_name:
                pick, how = by_name[remembered], "remembered"
        if not pick:
            exact = [c for c in chans if c["name"].strip().lower() == part["name"].strip().lower()]
            if len(exact) == 1:
                pick, how = exact[0], "exact"
        if not pick and part.get("role") != "drums" and part.get("instrument"):
            roles = part.get("_roles") or {}
            fits = [c for c in chans if roles.get(c["name"]) == part["instrument"]]
            if len(fits) == 1:
                pick, how = fits[0], "role"
        if not pick and part.get("role") == "drums":
            chan, why = drums.match_channel(part["name"], chans, self.kit_prefer())
            if chan:
                pick, how = chan, "matched"
            else:
                out["problem"] = why
        if pick:
            ctype = pick.get("type")
            if part.get("role") == "drums" and ctype in ("plugin",) and how in ("exact", "matched"):
                out["warning"] = "%s is an instrument plugin, not a drum sample. Check it's the right channel." % pick["name"]
            if part.get("role") != "drums" and drums.lane_kind(pick["name"]) and ctype == "sampler" and how in ("exact", "matched"):
                out["warning"] = "%s looks like a drum channel." % pick["name"]
            out.update(index=pick["index"], name=pick["name"], how=how, problem=None)
            kind = drums.lane_kind(part["name"]) if part.get("role") == "drums" else None
            if kit_names and how in ("exact", "matched") and kind and not any(drums.lane_kind(n) == kind for n in kit_names):
                out["warning"] = "Your kit has no %s, so this went to %s." % (kind, pick["name"])
        else:
            kind = drums.lane_kind(part["name"]) if part.get("role") == "drums" else None
            if part.get("role") == "drums":
                out["problem"] = out["problem"] or "No channel for %s." % part["name"]
                out["fix"] = ("Pick the right channel below (Veloura remembers it for this project), or load a %s sample: "
                              "Sounds ▸ Build a kit ▸ Load into FL." % (kind or "drum"))
            else:
                out["problem"] = "No instrument channel for %s." % part["name"]
                out["fix"] = "Pick an instrument channel below, or add one in FL (e.g. FLEX or ZENOLOGY) and Veloura will use it."
        steps, why = drums.plan_to_steps(part["plan"]) if part.get("role") == "drums" and part.get("plan") else (None, None)
        out["kind"] = "steps" if steps is not None else "pianoroll"
        if part.get("role") == "drums" and steps is None:
            out["note"] = "Has rolls or swing, so it goes into the channel's Piano Roll."
        return out

    def _destination(self, part, channels):
        """Where this part will land in FL, for the UI (and the route apply() will use)."""
        r = self._resolve_route(part, channels)
        part["route"] = dict(part.get("route") or {}, **{k: r.get(k) for k in ("index", "name", "how")}) if r.get("name") else \
            {k: v for k, v in (part.get("route") or {}).items() if k != "how"} or None
        if r["name"]:
            label = ("Channel Rack · " if r["kind"] == "steps" else "Piano Roll · ") + r["name"]
            return {"kind": r["kind"], "channel": r["name"], "label": label, "open": r["name"] if r["kind"] == "pianoroll" else None,
                    "how": r["how"], "warning": r.get("warning"), "why": r.get("note") or ""}
        return {"kind": r["kind"], "label": "Needs a channel", "problem": r["problem"], "fix": r["fix"], "missing": True}

    def set_route(self, pid, index, channel_index, remember=True):
        prop, part = self._find_part(pid, index)
        chans = self.controller_status(max_age=0).get("channels") or []
        chan = next((c for c in chans if c["index"] == int(channel_index)), None)
        if not chan:
            raise EngineError("That channel isn't in your Channel Rack any more.")
        with self.state_lock:
            part["route"] = {"index": chan["index"], "name": chan["name"], "how": "chosen"}
            if remember:
                self.state.setdefault("routing", {})[self._route_key(part)] = chan["name"]
            part["destination"] = self._destination(part, chans)
        self.save()
        return {"ok": True, "destination": part["destination"]}

    # ---------- references ----------

    def add_reference(self, filename, data_path, mode):
        """Store an uploaded song/sample and analyse it. data_path is a temp file the service wrote."""
        from . import analysis
        if mode not in ("sample", "inspiration"):
            raise EngineError("Choose Sample or Inspiration.")
        base = os.path.basename(filename or "reference")
        ext = os.path.splitext(base)[1].lower()
        if ext not in AUDIO_EXT:
            raise EngineError("Use an audio file (WAV, MP3, M4A, AIFF or FLAC).")
        rid = uuid.uuid4().hex[:10]
        folder = os.path.join(REF_DIR, rid)
        os.makedirs(folder, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in " ._-()" else "_" for c in base)[:120] or ("audio" + ext)
        path = os.path.join(folder, safe)
        shutil.move(data_path, path)
        self.busy = "Listening to %s…" % safe
        try:
            a = self._cancellable(lambda: analysis.analyze(path))
        except Cancelled:
            shutil.rmtree(folder, ignore_errors=True)
            raise EngineError("Cancelled. The song wasn't added.")
        except analysis.AnalysisError as e:
            shutil.rmtree(folder, ignore_errors=True)
            raise EngineError(str(e))
        finally:
            self.busy = None
        ref = {"id": rid, "name": safe, "mode": mode, "path": path, "analysis": a, "summary": analysis.describe(a),
               "added": _now()}
        with self.state_lock:
            self.state["references"][rid] = ref
        self.event("ok", "Analysed %s (%s): %s" % (safe, mode, ref["summary"]))
        self.save()
        return ref

    def delete_reference(self, rid):
        ref = self.state["references"].pop(rid, None)
        if ref:
            shutil.rmtree(os.path.dirname(ref["path"]), ignore_errors=True)
            self.save()
        return {"ok": True}

    def reveal_reference(self, rid):
        import subprocess
        ref = self.state["references"].get(rid)
        if ref and os.path.exists(ref["path"]):
            subprocess.run(["/usr/bin/open", "-R", ref["path"]], timeout=10)
        return {"ok": bool(ref)}

    def _sample_channel(self, ref, channels):
        stem = os.path.splitext(ref["name"])[0].lower()
        for c in channels:
            n = c["name"].strip().lower()
            if n == "sample" or (len(n) > 3 and (n in stem or stem.startswith(n))):
                return c["name"]
        return "Sample"

    def _sample_guide(self, ref, channel, channels):
        loaded = any(c["name"] == channel for c in channels)
        steps = ([] if loaded else [
            "Click 'Show sample in Finder' on the reference card (Veloura reveals the file).",
            "Drag the file from Finder onto an empty space in FL's Channel Rack. FL creates a new sampler channel.",
            "Right-click the new channel > Rename, and call it exactly: %s" % channel,
        ]) + ["Open the %s channel's Piano Roll and press Add on the '%s' part, so the sample plays from bar 1." % (channel, channel),
              "Add the drums and 808. They're written in the sample's key (%s) and at its tempo." % ref["analysis"]["key"]]
        return {"title": "Put the sample in your beat", "problem": "FL doesn't let Veloura load audio files itself.",
                "why": "Once the sample is on its own channel, Veloura can trigger it and build the beat around it.",
                "where": "Finder > FL Studio Channel Rack", "steps": steps, "settings": [],
                "listen_for": "The sample starts exactly on bar 1 and the drums lock to it. If it drifts, the sample's real "
                              "tempo is one of: %s BPM." % ", ".join(str(t) for t in [ref["analysis"]["tempo_bpm"]] + ref["analysis"]["tempo_alternatives"]),
                "undo": "Delete the channel (right-click > Delete) or use Undo on the part."}

    def test_bridge(self):
        res = self.read_piano_roll()
        return {"ok": res.get("ok"), "message": ("Connected. The open Piano Roll has %d notes." % len(res["notes"]))
                if res.get("ok") else res.get("message")}

    # ---------- FL operations ----------

    def _preflight(self):
        problems = self.trigger.preflight()
        if not bp.bridge_ready() or bp.installed_script_state() != "installed and up to date":
            problems.append("The Veloura bridge script is not installed or is out of date (use 'Repair bridge').")
        if problems:
            raise EngineError(" ".join(problems))

    @staticmethod
    def _caption_matches(caption, name):
        norm = lambda x: "".join(ch for ch in x.lower() if ch.isalnum())
        c, n = norm(caption or ""), norm(name)
        return bool(n) and (n in c or (len(n) > 10 and n[:10] in c))

    def _target_channel(self, part):
        """The exact channel this part must be written to, from its route. None when it has no safe target."""
        try:
            chans = self.controller.request("project", timeout=1.5).get("channels") or []
        except (ControllerUnavailable, ControllerError):
            return None
        r = self._resolve_route(part, chans)
        if not r["name"]:
            return None
        return next((c for c in chans if c["index"] == r["index"] and c["name"] == r["name"]), None)

    def _channel_named(self, name):
        if not name:
            return None
        try:
            chans = self.controller.request("project", timeout=1.5).get("channels") or []
        except (ControllerUnavailable, ControllerError):
            return None
        hits = [c for c in chans if c["name"] == name]
        return hits[0] if len(hits) == 1 else None

    def _open_target(self, chan):
        """Open and verify the Piano Roll of `chan`. Returns (ok, detail)."""
        try:
            res = self.controller.request("open_piano_roll", {"channel": chan["index"], "expect_name": chan["name"]}, timeout=2.0)
        except ControllerError as e:
            return False, "FL refused to open that Piano Roll: %s" % e
        except ControllerUnavailable as e:
            return False, str(e)
        time.sleep(0.25)  # let FL draw the window before the shortcut arrives
        try:
            again = self.controller.request("focus_piano_roll", timeout=1.0)
        except (ControllerUnavailable, ControllerError):
            again = {}
        caption = again.get("caption") or res.get("caption") or ""
        if self._caption_matches(caption, chan["name"]):
            return True, "opened the Piano Roll of %r" % chan["name"]
        # FL's scripting caption is only "Piano roll -" (no channel name), so confirm instead that FL's F7 command
        # ran with this channel as the ONLY selected channel and the Piano Roll is the focused window.
        try:
            selected = [c["name"] for c in self.controller.request("project", timeout=1.5).get("channels", []) if c.get("selected")]
        except (ControllerUnavailable, ControllerError):
            selected = []
        # FL only reports a focused window while it's the active app. Veloura now runs the bridge with FL in the
        # background, so there the proof is that FL's open-Piano-Roll command ran with this channel as the ONLY
        # selected channel (FL opens the selected channel's Piano Roll).
        in_background = self.trigger_background_ok()
        if selected == [chan["name"]] and (again.get("focused", res.get("focused")) or in_background):
            return True, "opened the Piano Roll of %r" % chan["name"]
        return False, "couldn't confirm FL is showing %r's Piano Roll (selected: %s)" % (chan["name"], ", ".join(selected) or "nothing")

    def trigger_background_ok(self):
        """True when FL is not the frontmost app (so its focus flags say nothing about which window is open)."""
        front = getattr(self.trigger, "frontmost_app", None)
        try:
            return bool(front) and front() != getattr(self.trigger, "FL_PROCESS", "OsxFL")
        except Exception:
            return False

    def _focus_piano_roll(self):
        """With the controller connected, ask FL to bring the Piano Roll to the front before the keystroke."""
        try:
            self.controller.request("focus_piano_roll", timeout=0.8)
        except (ControllerUnavailable, ControllerError):
            pass

    def _send(self, cmd, mutating, restore_focus=True, focus=True):
        bp.send_command(cmd)
        if focus:
            self._focus_piano_roll()
        kw = {"get_started": lambda: bp.command_started(cmd["id"])} if self.trigger is fl_trigger else {}
        result, secs, _ = self.trigger.trigger_and_wait(lambda: bp.find_result(cmd["id"]), timeout=self.timeout,
                                                        retry_trigger=not mutating, restore_focus=restore_focus, **kw)
        if result is not None:
            self.bridge_ok_at = time.time()
            with self.state_lock:
                self.state["bridge_ok_at"] = self.bridge_ok_at
            self.save()
        if result is None:
            withdrawn = bp.cancel_pending()
            bp.log_attempt({"id": cmd["id"], "type": cmd["type"], "trigger": "auto", "outcome": "no_result",
                            "withdrawn": bool(withdrawn)})
        return result, secs

    def _confirm(self, result):
        """Separate read-only snapshot after the script finished; must equal the reported 'after' state."""
        snap, _ = self._send(bp.make_snapshot_command(show_message=False), mutating=False)
        if snap is None:
            return False, "the confirmation snapshot did not come back"
        same = _counter(_key(d) for d in snap.get("notes", [])) == _counter(_key(d) for d in result.get("after", []))
        return same, ("confirmed by a separate snapshot (%d notes in the Piano Roll)" % len(snap.get("notes", []))
                      if same else "the Piano Roll changed between the edit and the confirmation snapshot")

    def _run_mutation(self, cmd, verify, target=None):
        """Send, verify, confirm. Returns a result dict for the UI and logs. With `target` (a channel), Veloura
        first opens that channel's Piano Roll and checks FL really shows it; otherwise it writes nothing."""
        with self.fl_lock:
            self._preflight()
            target_note = ""
            if target:
                ok, detail = self._open_target(target)
                if not ok:
                    return {"ok": False, "status": "blocked", "code": "target_failed",
                            "message": "Nothing was changed: %s. Open that Piano Roll yourself and press Add again." % detail}
                target_note = " (Veloura %s.)" % detail
            result, secs = self._send(cmd, mutating=True, restore_focus=False, focus=not target)
            if result is None:
                self.trigger.restore_previous()
                return {"ok": False, "status": "no_result", "code": "no_result", "message": (
                    "FL Studio did not respond, so nothing was changed. Usually this means FL was restarted: open the "
                    "target Piano Roll, run Tools > Scripts > veloura_bridge once (nothing visible happens), then press "
                    "Apply again. It can also happen if a dialog is open in FL. " + RECONNECT_TEXT)}
            checks = verify(cmd, result)
            ok = result["status"] == "applied" and all(c["passed"] for c in checks)
            if not ok:
                self.trigger.restore_previous()
            out = {"ok": ok, "status": result["status"], "message": result.get("message", "") + target_note, "checks": checks,
                   "seconds": round(secs, 2), "command_id": cmd["id"], "notes_after": len(result.get("after", []))}
            if ok:
                confirmed, detail = self._confirm(result)
                out["confirmed"] = confirmed
                out["confirm_detail"] = detail
                out["ok"] = confirmed
            bp.log_attempt({"id": cmd["id"], "type": cmd["type"], "trigger": "app", "status": result["status"],
                            "ok": out["ok"], "seconds": out["seconds"]})
            return out

    def _find_part(self, pid, index):
        prop = self.state["proposals"].get(pid)
        if not prop or not (0 <= index < len(prop["parts"])):
            raise EngineError("Unknown proposal or part.")
        return prop, prop["parts"][index]

    def apply(self, pid, index, allow_existing=False, as_new=False, manual_target=False, replace=False):
        """Write a part into FL. replace=True (Reapply, and when Veloura's earlier notes can't be told apart): clear
        the target channel's Piano Roll for this pattern first, in the same bridge run, so old and new never stack."""
        prop, part = self._find_part(pid, index)
        try:
            plan = validate_plan(part["plan"])
        except PlanError as e:
            raise EngineError("Part failed validation and was not sent: %s" % e)
        existing = self.state["parts"].get(part["name"])
        if not self.state["settings"].get("careful"):
            allow_existing = True   # make music: write alongside / over what's there (Cmd+Z or Undo reverts)
        self.busy = "Writing %s into FL Studio..." % part["name"]
        fallback_note = ""
        try:
            steps_out = None
            if part["role"] == "drums" and not (existing and existing.get("mode") != "steps" and not as_new):
                with self.fl_lock:
                    steps_out, why = self._apply_steps(part, plan, None if as_new else existing, allow_existing, force=replace)
                if steps_out is None and why and "not connected" not in why and "channel" not in why:
                    fallback_note = " (Written into the channel's Piano Roll: %s.)" % why
            target = None if steps_out is not None or manual_target else self._target_channel(part)
            if steps_out is None and target is None and not manual_target:
                chans = self.controller_status(max_age=0).get("channels") or []
                r = self._resolve_route(part, chans)
                with self.state_lock:
                    part["destination"] = self._destination(part, chans)
                raise _NoTarget(r["problem"] or "Veloura isn't sure which channel %s belongs to." % part["name"], r.get("fix"))
            sound_note = ""
            if target and not part.get("sound") and part.get("instrument") and self.state["settings"].get("auto_sounds", True):
                with self.fl_lock:
                    auto = self._auto_sound(target, part.get("instrument"), self.state["settings"].get("genre"))
                if auto:
                    part["sound"] = auto
            if target and part.get("sound") and target["name"] in (part.get("_roles") or {}):
                part["sound"] = ""   # this channel already plays that instrument: keep the user's sound
            if target and part.get("role") == "bass" and target.get("type") == "sampler":
                plan, pitch_note = self._pitch_808(plan, target)
                fallback_note += pitch_note
            if target and part.get("sound"):
                self.busy = "Loading the sound %r on %s…" % (part["sound"], target["name"])
                try:
                    with self.fl_lock:
                        ok, smsg, _prev = sounds.switch(self.controller, target, part["sound"])
                    if ok and _prev and _prev != part["sound"]:
                        self._log_change("sound", channel=target["index"], name=target["name"], before=_prev, after=part["sound"])
                    sound_note = " Sound: %s." % smsg
                except (ControllerUnavailable, ControllerError) as e:
                    sound_note = " (Couldn't change the sound: %s.)" % e
                self.busy = "Writing %s into FL Studio..." % part["name"]
            if steps_out is not None:
                out = steps_out
            elif replace:
                cmd = bp.make_clear_add_command(plan, show_message=False)
                out = self._run_mutation(cmd, bp.verify_clear_add, target=target)
            elif existing and existing.get("command_id") and not as_new:
                cmd = bp.make_replace_command(plan, existing["command_id"], show_message=False)
                out = self._run_mutation(cmd, bp.verify_replace, target=target)
            else:
                cmd = bp.make_add_command(plan, allow_existing_notes=allow_existing, show_message=False)
                out = self._run_mutation(cmd, bp.verify_add, target=target)
            if target and out.get("ok"):
                out["channel"] = target["name"]
            if sound_note:
                out["message"] = out.get("message", "") + sound_note
        except _NoTarget as e:
            out = {"ok": False, "status": "blocked", "code": "no_target", "message": str(e), "fix": e.fix}
        except EngineError as e:
            out = {"ok": False, "status": "blocked", "message": str(e)}
        finally:
            self.busy = None
        out["message"] = out.get("message", "") + fallback_note
        if out["status"] == "refused" and "already has" in out.get("message", "") and "code" not in out:
            out["code"] = "not_empty"
        msg = out.get("message", "")
        if out["status"] == "refused" and ("Veloura's earlier notes" in msg or "No applied Veloura command" in msg
                                           or "already removed or replaced" in msg or "were edited since" in msg):
            out["code"] = "replace_failed"
            if not self.state["settings"].get("careful") and not as_new and not replace:
                # Veloura's earlier notes can't be told apart any more: replace the channel's notes instead of
                # writing the new version on top of the old one.
                return self.apply(pid, index, allow_existing=True, as_new=True, manual_target=manual_target, replace=True)
        with self.state_lock:
            part["status"] = "applied" if out["ok"] else ("refused" if out["status"] == "refused" else "failed")
            part["result"] = out
            if out["ok"]:
                reg = out.get("registry") or {}
                if existing and existing.get("mode") == "steps" and reg.get("channel_name") and \
                        (existing.get("channel_name"), existing.get("channel")) != (reg["channel_name"], reg.get("channel")):
                    # Written to a different channel (kit swap): keep the old part listed under its own channel.
                    self.state["parts"]["%s · %s (ch %d)" % (part["name"], existing["channel_name"], existing["channel"] + 1)] = existing
                    existing = None
                history = (existing or {}).get("history", []) if not as_new else []
                if existing and not as_new:
                    history = history + [{"command_id": existing.get("command_id"), "plan": existing["plan"], "at": existing.get("updated")}]
                versions = list((existing or {}).get("versions") or [])
                if existing and not versions and existing.get("plan") and not as_new:   # parts from before version history
                    versions = [{"id": uuid.uuid4().hex[:8], "plan": existing["plan"], "op": "Earlier take", "at": existing.get("updated"),
                                 "parent": None, "label": "v1"}]
                head = versions[-1]["id"] if versions else None
                op = part.get("op") or ("Chat: " + (prop.get("request") or "")[:60] if prop.get("request") else "Written")
                versions.append({"id": uuid.uuid4().hex[:8], "plan": plan, "op": op, "at": _now(), "parent": head,
                                 "label": "v%d" % (len(versions) + 1)})
                entry = {"role": part["role"], "command_id": out.get("command_id"), "plan": plan, "history": history[-10:],
                         "updated": _now(), "target_hint": part.get("target_hint", ""), "mode": out.get("mode", "pianoroll"),
                         "purpose": part.get("purpose"), "versions": versions[-30:], "sound": part.get("sound") or (existing or {}).get("sound")}
                entry.update(out.pop("registry", {}))
                if out.get("channel") and entry.get("mode") != "steps":
                    entry["channel_name"] = out["channel"]
                    entry["target_hint"] = "Piano Roll · %s" % out["channel"]
                if out.get("mode") == "steps":
                    entry["target_hint"] = "Step sequencer: channel %r, pattern %d" % (entry["channel_name"], entry["pattern"])
                self.state["parts"][part["name"]] = entry
            out.pop("registry", None)
        if out["ok"] and part.get("option"):
            self.taste.note("layer", "%s:%s" % (part["role"], part.get("option_label")), "kept")
        if out["ok"] and part.get("sound"):
            self.taste.note("sound", part["sound"], "kept", context=part.get("purpose"))
        self.event("ok" if out["ok"] else "error", "%s %s: %s" % (
            "Revised" if existing and not as_new else "Wrote", part["name"], out["message"]))
        self.save()
        return out

    def undo_all_plan(self):
        """What 'Undo everything Veloura did' would reverse in this project, newest first."""
        items = []
        for name, e in self.current_parts().items():
            items.append({"kind": "part", "name": name, "label": "Take %s out of %s" % (name, e.get("channel_name") or "FL")})
        for c in reversed(self.state.get("changes") or []):
            if c.get("undone"):
                continue
            if c["type"] == "mix":
                prop = self.state["proposals"].get(c["proposal"])
                if prop and (prop.get("mix") or {}).get("status") in ("applied", "partial"):
                    items.append({"kind": "mix", "proposal": c["proposal"], "label": "Undo mix changes"})
            elif c["type"] == "sound":
                items.append({"kind": "sound", "change": c, "label": "Put %s back on the %r sound" % (c["name"], c["before"])})
            elif c["type"] == "unmute":
                items.append({"kind": "unmute", "change": c, "label": "Mute %s again" % c["name"]})
            elif c["type"] == "tempo":
                items.append({"kind": "tempo", "change": c, "label": "Set the tempo back to %g BPM" % c["before"]})
            elif c["type"] == "listen_fix":
                items.append({"kind": "listen_fix", "change": c, "label": "Undo the listen-check level fix"})
            elif c["type"] == "swing":
                items.append({"kind": "swing", "change": c, "label": "Put FL's swing back to %d%%" % round(c["before"] * 100)})
            elif c["type"] == "routing":
                items.append({"kind": "routing", "change": c, "label": "Send %d channel(s) back to Master" % len(c["routed"])})
            elif c["type"] == "sample" and c.get("before_file"):
                items.append({"kind": "sample", "change": c, "label": "Put %s back on channel %d" % (c["before_name"], c["channel"] + 1)})
        return items

    def undo_all(self):
        """Reverse everything Veloura did in this project: its notes and steps (your own stay), mix moves, sounds, tempo."""
        results = []
        for it in self.undo_all_plan():
            try:
                if it["kind"] == "part":
                    r = self.remove(it["name"])
                elif it["kind"] == "mix":
                    r = self.undo_mix(it["proposal"])
                elif it["kind"] == "sound":
                    c = it["change"]
                    ok, msg, _ = sounds.switch(self.controller, {"index": c["channel"], "name": c["name"]}, c["before"])
                    r = {"ok": ok, "message": msg}
                elif it["kind"] == "unmute":
                    c = it["change"]
                    self.controller.request("set_mix", {"changes": [{"kind": "channel_mute", "channel": c["channel"],
                                                                      "expect_name": c["name"], "value": True}]})
                    r = {"ok": True}
                elif it["kind"] == "tempo":
                    r = self.set_fl_tempo(it["change"]["before"])
                elif it["kind"] == "listen_fix":
                    self.controller.request("set_mix", {"changes": it["change"]["undo"]})
                    r = {"ok": True}
                elif it["kind"] == "swing":
                    self.controller.request("swing", {"value": it["change"]["before"]})
                    r = {"ok": True}
                elif it["kind"] == "routing":
                    r = self.controller.request("set_routing", {"routes": [{"channel": x["channel"], "track": 0, "name": x["name"],
                                                                           "reset_track": x["track"]} for x in it["change"]["routed"]]})
                    r = {"ok": all(x.get("ok") for x in r["results"])}
                elif it["kind"] == "sample":
                    c = it["change"]
                    r = self.load_sample(c["channel"], c["before_file"])
                else:
                    continue
                if r.get("ok") and it.get("change"):
                    it["change"]["undone"] = True
            except (EngineError, ControllerError, ControllerUnavailable) as e:
                r = {"ok": False, "message": str(e)}
            results.append({"label": it["label"], "ok": bool(r.get("ok")), "message": r.get("message", "")})
        if any(r["ok"] for r in results):
            with self.state_lock:
                self.state["changes"] = [c for c in self.state.get("changes") or [] if not c.get("undone")]
        self.event("info", "Undo everything: %d of %d reversed." % (sum(r["ok"] for r in results), len(results)))
        self.save()
        return {"ok": all(r["ok"] for r in results), "results": results}

    def reapply(self, pid, index, channel_index=None):
        """Write a part again: to the same channel (e.g. after a hiccup) or moved to another channel (Veloura takes its
        notes back out of the wrong one first)."""
        prop, part = self._find_part(pid, index)
        existing = self.state["parts"].get(part["name"])
        if channel_index is not None:
            chans = self.controller_status(max_age=0).get("channels") or []
            chan = next((c for c in chans if c["index"] == int(channel_index)), None)
            if not chan:
                raise EngineError("That channel isn't in your Channel Rack any more.")
            moved = existing and (existing.get("channel_name") or "") != chan["name"]
            if moved:
                rm = self.remove(part["name"])
                if not rm.get("ok"):
                    return dict(rm, message="Couldn't take %s out of %s first: %s" % (part["name"], existing.get("channel_name"), rm.get("message")))
            self.set_route(pid, index, channel_index)
            with self.state_lock:
                part["status"] = "proposed"
            return self.apply(pid, index, as_new=bool(moved), replace=True)
        with self.state_lock:
            part["status"] = "proposed"
        return self.apply(pid, index, replace=True)   # clear what's in that Piano Roll first: never stack on old notes

    def remove(self, name):
        entry = self.state["parts"].get(name)
        if not entry:
            raise EngineError("No Veloura part called %r." % name)
        self.busy = "Removing %s..." % name
        if entry.get("mode") == "steps":
            try:
                out = self._restore_steps(entry, entry["previous"], "Restored channel %r to how it was before Veloura." % entry["channel_name"])
            finally:
                self.busy = None
            if out["ok"]:
                with self.state_lock:
                    del self.state["parts"][name]
            self.event("ok" if out["ok"] else "error", "Remove %s: %s" % (name, out["message"]))
            self.save()
            return out
        try:
            cmd = bp.make_remove_command(entry["command_id"], show_message=False)
            out = self._run_mutation(cmd, target=self._channel_named(entry.get("channel_name")), verify=lambda c, r: [{"check": "FL-side check: only Veloura's notes removed",
                                                          "passed": bool((r.get("in_run_verification") or {}).get("passed")),
                                                          "detail": ""}])
        except EngineError as e:
            out = {"ok": False, "status": "blocked", "message": str(e)}
        finally:
            self.busy = None
        if out["ok"]:
            with self.state_lock:
                del self.state["parts"][name]
        self.event("ok" if out["ok"] else "error", "Remove %s: %s" % (name, out["message"]))
        self.save()
        return out

    def revert(self, name):
        entry = self.state["parts"].get(name)
        if not entry or not entry.get("history"):
            raise EngineError("No earlier version of %r to go back to." % name)
        prev = entry["history"][-1]
        self.busy = "Reverting %s..." % name
        if entry.get("mode") == "steps":
            steps, problem = drums.plan_to_steps(prev["plan"])
            try:
                out = self._restore_steps(entry, steps or [], "Reverted %s to the previous version." % name) if steps else \
                    {"ok": False, "status": "refused", "message": problem}
            finally:
                self.busy = None
            if out["ok"]:
                with self.state_lock:
                    entry["history"] = entry["history"][:-1]
                    entry["plan"] = prev["plan"]
                    entry["written"] = steps
                    entry["updated"] = _now()
                    self._add_version(entry, prev["plan"], "Undo")
            self.event("ok" if out["ok"] else "error", "Revert %s: %s" % (name, out["message"]))
            self.save()
            return out
        try:
            cmd = bp.make_replace_command(prev["plan"], entry["command_id"], show_message=False)
            out = self._run_mutation(cmd, bp.verify_replace, target=self._channel_named(entry.get("channel_name")))
        except EngineError as e:
            out = {"ok": False, "status": "blocked", "message": str(e)}
        finally:
            self.busy = None
        if out["ok"]:
            with self.state_lock:
                entry["history"] = entry["history"][:-1]
                entry["command_id"] = out["command_id"]
                entry["plan"] = prev["plan"]
                entry["updated"] = _now()
                self._add_version(entry, prev["plan"], "Undo")
        self.event("ok" if out["ok"] else "error", "Revert %s: %s" % (name, out["message"]))
        self.save()
        return out

    @staticmethod
    def _add_version(entry, plan, op):
        vs = entry.setdefault("versions", [])
        vs.append({"id": uuid.uuid4().hex[:8], "plan": plan, "op": op, "at": _now(), "parent": vs[-1]["id"] if vs else None,
                   "label": "v%d" % (len(vs) + 1)})
        del vs[:-30]

    def _restore_steps(self, entry, target_steps, message):
        chan = {"index": entry["channel"], "name": entry["channel_name"]}
        with self.fl_lock:
            try:
                cur = self.controller.request("read_steps", {"channel": chan["index"], "expect_name": chan["name"],
                                                             "count": len(entry["written"])})
                if cur["pattern"]["number"] != entry["pattern"]:
                    return {"ok": False, "status": "refused", "message": "Switch FL back to pattern %d first." % entry["pattern"]}
                if not drums.steps_equal(entry["written"], cur["steps"]):
                    return {"ok": False, "status": "refused", "message": (
                        "The %s steps were edited since Veloura wrote them; Veloura won't overwrite your edits. "
                        "Use Cmd+Z in FL or edit by hand." % chan["name"])}
                swung = {s["step"] for s in entry["written"] if s.get("shift")}
                steps = []
                for s in target_steps:
                    st = dict(s, velocity=s.get("velocity") if s.get("on") else None)
                    if st.get("on") and st["step"] in swung and "shift" not in st:
                        st["shift"] = 0   # take Veloura's swing off steps it no longer owns
                    steps.append(st)
                ok, confirmed, _ = self._steps_mutation(chan, entry["pattern"], steps)
            except (ControllerError, ControllerUnavailable) as e:
                return {"ok": False, "status": "failed", "message": str(e)}
        return {"ok": ok and confirmed, "status": "applied" if ok else "applied_unverified", "mode": "steps",
                "message": message if ok and confirmed else "Step read-back did not match; check the Channel Rack.",
                "confirmed": confirmed}

    def sound_list(self, index, name):
        """All the sounds (presets) an instrument channel exposes, for the UI's sound picker."""
        with self.fl_lock:
            return self.controller.request("presets", {"channel": int(index), "expect_name": name}, timeout=60)

    def switch_sound(self, index, name, sound):
        if not sound:
            raise EngineError("Which sound?")
        with self.fl_lock:
            ok, msg, prev = sounds.switch(self.controller, {"index": int(index), "name": name}, sound)
        if ok and prev and prev != sound:
            self._log_change("sound", channel=int(index), name=name, before=prev, after=sound)
        self.event("ok" if ok else "error", "Sound for %s: %s." % (name, msg))
        return {"ok": ok, "message": msg, "previous": prev}

    def _pitch_808(self, plan, target):
        """An 808 SAMPLE plays at its own pitch on C5 (MIDI 60) in FL's sampler. Writing it down at C2 plays it two or
        three octaves too low (slow and muddy). So move the line next to C5, tuned so every note is in key for the
        sample's own pitch (from its name or detected), keeping the melody of the 808 intact."""
        sample = self.library.find_by_channel(target["name"])
        spc = self.library.sample_pitch(sample) if sample else None
        notes = plan["notes"]
        if not notes:
            return plan, ""
        ref = sorted(notes, key=lambda n: n["start"])[0]["pitch"]
        w = ((ref % 12) - (spc if spc is not None else 0) + 6) % 12 - 6   # nearest way round: within half an octave of the root
        shift = (60 + w) - ref
        if shift == 0:
            return plan, ""
        moved = dict(plan, notes=[dict(n, pitch=max(0, min(127, n["pitch"] + shift))) for n in notes])
        tuned = " (tuned to the sample's %s)" % "C C# D D# E F F# G G# A A# B".split()[spc] if spc is not None else ""
        return moved, " 808 placed at the sample's natural pitch%s." % tuned

    def _auto_sound(self, target, instrument, genre=None):
        """A preset on this instrument plugin that fits the part's instrument (e.g. a piano patch for the piano part).
        None if the channel's current sound already fits, or nothing fits, or the plugin doesn't list presets."""
        from . import ensemble
        words = ensemble.KEYWORDS.get(instrument or "", [])
        if not words or target.get("type") not in ("plugin", "hybrid"):
            return None
        try:
            head = self.controller.request("presets", {"channel": target["index"], "expect_name": target["name"], "names": False}, timeout=10)
            key = (head.get("plugin"), head.get("count"))
            cache = getattr(self, "_preset_cache", {})
            self._preset_cache = cache
            if key not in cache:
                cache[key] = self.controller.request("presets", {"channel": target["index"], "expect_name": target["name"]}, timeout=60)
            names = [n for n in cache[key].get("names") or [] if n]
        except (ControllerUnavailable, ControllerError):
            return None
        cur = (head.get("current") or "").lower()
        if any(w in cur for w in words) or len(names) < 2:
            return None
        if not _is_default_sound(cur):
            return None   # the user already chose a sound on this channel: never replace it
        gwords = [w for w in (genre or "").split() if len(w) > 3]
        def score(n):
            t = n.lower()
            return (sum(2 for w in words if w in t) + sum(1 for w in gwords if w in t) + 3 * self.taste.score("sound", n)
                    - (0.5 if any(x in t for x in ("fx", "noise", "drum", "perc")) else 0))
        best = max(names, key=score)
        return best if score(best) >= 2 else None

    def _sound_menu(self, channels, text):
        """For instrument plugins that publish presets to FL: a shortlist of sound names the AI may choose from."""
        menu = {}
        for c in channels:
            if c.get("type") not in ("plugin", "hybrid"):
                continue
            try:
                head = self.controller.request("presets", {"channel": c["index"], "expect_name": c["name"],
                                                           "names": False}, timeout=10)
                key = (head.get("plugin"), head.get("count"))
                cache = getattr(self, "_preset_cache", {})
                self._preset_cache = cache
                if key not in cache:
                    cache[key] = self.controller.request("presets", {"channel": c["index"], "expect_name": c["name"]},
                                                         timeout=60)
                info = dict(cache[key], current=head.get("current"))
            except (ControllerUnavailable, ControllerError):
                continue
            if info.get("count", 0) > 1:
                menu[c["name"]] = {"plugin": info.get("plugin"), "current": info.get("current"), "total": info["count"],
                                   "choices": sounds.shortlist(info["names"], text)}
        return menu

    # ---------- Veloura Channel Rack (live mirror of FL's step sequencer) ----------

    def rack_state(self, all_patterns=False):
        try:
            return dict(self.controller.request("rack_state", {"all": bool(all_patterns)}, timeout=6.0), connected=True)
        except (ControllerUnavailable, ControllerError) as e:
            return {"connected": False, "detail": str(e)}

    def rack_select_pattern(self, number):
        try:
            with self.fl_lock:
                return self.controller.request("select_pattern", {"number": int(number)})
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError(str(e))

    def rack_toggle(self, index, name, step, on, velocity=100, pattern=None):
        """Click a step in Veloura's rack: set it on/off in FL's current pattern (one FL undo point)."""
        if not isinstance(step, int) or not 0 <= step < 256:
            raise EngineError("Bad step.")
        try:
            with self.fl_lock:
                params = {"channel": int(index), "expect_name": name, "steps": [
                    {"step": step, "on": bool(on), "velocity": int(velocity) if on else None}]}
                if pattern is not None:
                    params["in_pattern"] = int(pattern)
                res = self.controller.request("write_steps", params)
        except ControllerError as e:
            raise EngineError("FL refused the change: %s" % e)
        except ControllerUnavailable as e:
            raise EngineError(str(e))
        now = next((s for s in res["steps"] if s["step"] == step), {})
        return {"ok": bool(now.get("on")) == bool(on), "on": bool(now.get("on"))}

    def rack_mute(self, index, name, muted):
        try:
            with self.fl_lock:
                res = self.controller.request("set_mix", {"changes": [{"kind": "channel_mute", "channel": int(index),
                                                                       "expect_name": name, "value": bool(muted)}]})
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError(str(e))
        r = res["results"][0]
        if not r.get("ok"):
            raise EngineError(r.get("error", "FL refused the change"))
        return {"ok": True, "muted": r.get("now")}

    # ---------- mix moves ----------

    def _mix_name_map(self, prop, state):
        """Map the names the AI used in mix moves to the real channels: the part's routed channel, remembered routing,
        then the drum type (so "808 HiHat" finds this project's hat channel)."""
        chans = [{"index": c["index"], "name": c["name"]} for c in state.get("channels", [])]
        names = {c["name"] for c in chans}
        out = {}
        for p in (prop or {}).get("parts") or []:
            ch = (p.get("destination") or {}).get("channel")
            if ch in names:
                out[p["name"].strip().lower()] = ch
        for n, e in self.state["parts"].items():
            if e.get("channel_name") in names:
                out.setdefault(n.strip().lower(), e["channel_name"])
        for m in ((prop or {}).get("mix") or {}).get("moves") or []:
            t = (m.get("target") or "").strip()
            if t.lower() in out or t in names or t.lower() == "master":
                continue
            remembered = (self.state.get("routing") or {}).get("drum:" + (drums.lane_kind(t) or ""))
            if remembered in names:
                out[t.lower()] = remembered
                continue
            if drums.lane_kind(t):
                ch, _ = drums.match_channel(t, chans, self.kit_prefer())
                if ch:
                    out[t.lower()] = ch["name"]
        return out

    def mixer_setup(self):
        """Route every channel that plays straight into Master to its own named insert (one FL undo step)."""
        try:
            with self.fl_lock:
                res = self.controller.request("mixer_setup", timeout=10.0)
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError(str(e))
        if res["routed"]:
            self._log_change("routing", routed=res["routed"])
            self.event("ok", "Gave %d channel(s) their own mixer insert." % len(res["routed"]))
            self.save()
        return dict(res, ok=True)

    def apply_mix(self, pid):
        prop = self.state["proposals"].get(pid)
        block = prop and prop.get("mix")
        if not block:
            raise EngineError("No mix moves in that reply.")
        self.busy = "Mixing in FL…"
        try:
            with self.fl_lock:
                state = self.controller.request("mix_state", timeout=6.0)
            if any(c["mixer_track"] == 0 for c in state["channels"]):   # automate the routing step people forget
                self.mixer_setup()
            with self.fl_lock:
                state = self.controller.request("mix_state", timeout=6.0)
                changes, preview, problems = mixmod.resolve(block["moves"], state, self._mix_name_map(prop, state))
                if not changes:
                    raise EngineError("None of the mix moves could be applied: %s" % " ".join(problems))
                send, undo = mixmod.split_undo(changes)
                res = self.controller.request("set_mix", {"changes": send}, timeout=10.0)["results"]
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError("Couldn't reach FL's controller: %s" % e)
        finally:
            self.busy = None
        failed = [r for r in res if not r.get("ok")]
        ok = not failed
        self._log_change("mix", proposal=pid)
        with self.state_lock:
            block.update(status="applied" if ok else "partial", preview=preview, problems=problems,
                         undo=[u for u, r in zip(undo, res) if r.get("ok")],
                         result={"ok": ok, "applied": len(res) - len(failed), "failed": [r.get("error") for r in failed]})
        self.event("ok" if ok else "warn", "Mix: applied %d change(s)%s." % (len(res) - len(failed),
                   "; %d failed" % len(failed) if failed else ""))
        self.save()
        return {"ok": ok, "applied": len(res) - len(failed), "failed": [r.get("error") for r in failed], "problems": problems}

    def undo_mix(self, pid):
        prop = self.state["proposals"].get(pid)
        block = prop and prop.get("mix")
        if not block or not block.get("undo"):
            raise EngineError("Nothing to undo for that mix.")
        try:
            with self.fl_lock:
                res = self.controller.request("set_mix", {"changes": block["undo"]}, timeout=10.0)["results"]
        except (ControllerUnavailable, ControllerError) as e:
            raise EngineError("Couldn't reach FL's controller: %s" % e)
        ok = all(r.get("ok") for r in res)
        with self.state_lock:
            block["status"] = "undone" if ok else "partial"
            block["undo"] = [] if ok else block["undo"]
        self.event("ok" if ok else "warn", "Mix undone." if ok else "Mix undo was only partly applied.")
        self.save()
        return {"ok": ok}

    def read_piano_roll(self):
        with self.fl_lock:
            self._preflight()
            snap, secs = self._send(bp.make_snapshot_command(show_message=False), mutating=False)
        if snap is None:
            return {"ok": False, "message": "FL Studio did not respond. Is the Piano Roll focused? " + RECONNECT_TEXT}
        return {"ok": True, "notes": snap.get("notes", []), "ppq": snap.get("ppq"), "seconds": round(secs, 2)}

    # ---------- export (Mode C) ----------

    def export(self, pid=None, index=None, name=None, directory=None):
        if name:
            entry = self.state["parts"].get(name)
            if not entry:
                raise EngineError("No Veloura part called %r." % name)
            plan, label = entry["plan"], name
        else:
            _, part = self._find_part(pid, index)
            plan, label = validate_plan(part["plan"]), part["name"]
        directory = directory or EXPORT_DIR
        os.makedirs(directory, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in label).strip() or "part"
        path = os.path.join(directory, "%s %s.mid" % (safe, time.strftime("%Y%m%d-%H%M%S")))
        write_midi(plan, path)
        problems = verify_midi(plan, path)
        self.event("ok" if not problems else "error", "Exported %s to %s%s" % (label, path, "" if not problems else " (verify failed)"))
        self.save()
        return {"ok": not problems, "path": path, "problems": problems,
                "instructions": "Fallback (manual step): drag this file onto a channel in FL Studio's Channel Rack, or "
                                "open the channel's Piano Roll and use its menu > File > Import MIDI file."}
