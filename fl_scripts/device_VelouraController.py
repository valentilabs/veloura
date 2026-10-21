# name=Veloura Controller
# supportedDevices=
"""Veloura Controller: FL Studio MIDI controller script (Milestone C).

Gives Veloura documented, allowlisted access to FL Studio's MIDI Controller
Scripting API: read channel names, the current pattern and tempo; set the
tempo; write and read step-sequencer steps on channels you have already
loaded; focus the Piano Roll.

Transport: FL blocks file access from controller scripts, so requests and
responses travel as SysEx over two virtual MIDI ports that the Veloura app creates
("Veloura to FL" into FL, "FL to Veloura" back out). Frames:
    F0 7D 43 KIND ID_HI ID_LO SEQ TOTAL <7-bit packed JSON> F7
(0x7D = non-commercial ID, 0x43 = 'C' for Veloura, KIND 0 = request, 1 = response)

Nothing from Veloura is executed as code; only the operations in OPS exist.
Every change is preceded by a named FL undo point ("Veloura: ...").
To remove: delete this folder from FL Studio's Settings/Hardware folder.
"""

import json
import time

import channels
import device
import general
import midi
import mixer
import patterns
import plugins
import transport
import ui

SCRIPT_BUILD = "veloura-c32"
PROTOCOL = 1
MANUFACTURER = 0x7D
TAG = 0x43
CHUNK = 200
MAX_STEPS = 256
_inbox = {}


# ---------- helpers ----------

def _api_version():
    try:
        return general.getVersion()
    except Exception:
        return None


def _tempo():
    try:
        return mixer.getCurrentTempo() / 1000.0
    except Exception:
        return None


def _channel_index(params):
    idx = params.get("channel")
    if not isinstance(idx, int) or not (0 <= idx < channels.channelCount()):
        raise ValueError("channel %r is not a valid Channel Rack index (0..%d)" % (idx, channels.channelCount() - 1))
    name = params.get("expect_name")
    if name is not None and channels.getChannelName(idx) != name:
        raise ValueError("channel %d is now named %r, not %r; the Channel Rack changed. Refresh and try again."
                         % (idx, channels.getChannelName(idx), name))
    return idx


def _pattern_info(num=None):
    num = patterns.patternNumber() if num is None else num
    info = {"number": num, "name": patterns.getPatternName(num)}
    try:
        info["length_steps"] = patterns.getPatternLength(num)
    except Exception:
        info["length_steps"] = None
    return info


STEP_SHIFT = 7   # FL step parameter: start-time shift in ticks within the step (used for swing)


def _read_steps(idx, count, with_shift=False):
    out = []
    for s in range(count):
        on = bool(channels.getGridBit(idx, s))
        vel = None
        entry = {"step": s, "on": on}
        if on:
            try:
                vel = channels.getCurrentStepParam(idx, s, 1)
            except Exception:
                vel = None
            if with_shift:
                try:
                    entry["shift"] = channels.getCurrentStepParam(idx, s, STEP_SHIFT)
                except Exception:
                    entry["shift"] = None
        entry["velocity"] = vel
        out.append(entry)
    return out


# ---------- operations ----------

def op_hello(p):
    return {"build": SCRIPT_BUILD, "api_version": _api_version(), "ppq": general.getRecPPQ(), "tempo": _tempo(),
            "idle_ticks": _idle["ticks"], "queued": len(_queue), "last_queue_error": _idle.get("err"),
            "safe_to_edit": (general.safeToEdit() if hasattr(general, "safeToEdit") else None),
            "features": {"swing": hasattr(channels, "setSwing"), "pattern_length": hasattr(patterns, "setPatternLength"),
                         "duplicate_pattern": hasattr(patterns, "duplicatePatternData")}}


def op_project(p):
    chans = []
    for i in range(channels.channelCount()):
        entry = {"index": i, "name": channels.getChannelName(i)}
        try:
            entry["type"] = {0: "sampler", 1: "hybrid", 2: "plugin", 3: "layer", 4: "audioclip", 5: "autoclip"}.get(
                channels.getChannelType(i), "other")
        except Exception:
            pass
        try:
            entry["mixer_track"] = channels.getTargetFxTrack(i)
        except Exception:
            pass
        try:
            entry["selected"] = bool(channels.isChannelSelected(i))
        except Exception:
            pass
        chans.append(entry)
    try:
        safe = bool(general.safeToEdit()) if hasattr(general, "safeToEdit") else True
    except Exception:
        safe = True
    return {"channels": chans, "pattern": _pattern_info(), "pattern_count": patterns.patternCount(),
            "tempo": _tempo(), "api_version": _api_version(), "safe_to_edit": safe}


def op_set_tempo(p):
    bpm = p.get("bpm")
    if not isinstance(bpm, (int, float)) or not (20 <= bpm <= 522):
        raise ValueError("bpm must be 20-522")
    general.saveUndo("Veloura: tempo %g" % bpm, midi.UF_None)
    general.processRECEvent(midi.REC_Tempo, int(round(bpm * 1000)), midi.REC_Control | midi.REC_UpdateControl)
    return {"tempo": _tempo()}


def op_read_steps(p):
    idx = _channel_index(p)
    count = p.get("count", 16)
    if not isinstance(count, int) or not (1 <= count <= MAX_STEPS):
        raise ValueError("count must be 1-%d" % MAX_STEPS)
    return {"channel": idx, "name": channels.getChannelName(idx), "pattern": _pattern_info(), "steps": _read_steps(idx, count)}


def op_write_steps(p):
    """Set steps on/off (and velocity) on one channel in the CURRENT pattern, then read them back."""
    idx = _channel_index(p)
    steps = p.get("steps")
    if not isinstance(steps, list) or not (1 <= len(steps) <= MAX_STEPS):
        raise ValueError("steps must be a list of 1-%d entries" % MAX_STEPS)
    expect_pattern = p.get("pattern")
    if expect_pattern is not None and expect_pattern != patterns.patternNumber():
        raise ValueError("the current pattern is %d, not %d; nothing was changed" % (patterns.patternNumber(), expect_pattern))
    clean = []
    shifts = {}
    for s in steps:
        st, on, vel = s.get("step"), s.get("on"), s.get("velocity")
        sh = s.get("shift")
        if sh is not None:
            if not isinstance(sh, (int, float)) or not (0 <= sh < 1):
                raise ValueError("shift must be a fraction of a step (0 to <1)")
            shifts[st] = sh
        if not isinstance(st, int) or not (0 <= st < MAX_STEPS) or not isinstance(on, bool):
            raise ValueError("bad step entry %r" % (s,))
        if vel is not None and (not isinstance(vel, int) or not (0 <= vel <= 127)):
            raise ValueError("bad velocity in %r" % (s,))
        clean.append((st, on, vel))
    # UF_PR covers pattern changes (the step sequencer is UF_SS = UF_PR). With UF_None, FL 2024's Cmd+Z skipped
    # Veloura's step writes (observed 2026-10-14).
    home = patterns.patternNumber()
    target = p.get("in_pattern")
    if target is not None and (not isinstance(target, int) or not (1 <= target <= max(patterns.patternCount(), home))):
        raise ValueError("pattern %r does not exist" % (target,))
    general.saveUndo("Veloura: %s steps" % channels.getChannelName(idx), getattr(midi, "UF_SS", midi.UF_PR))
    if target is not None and target != home:
        patterns.jumpToPattern(target)   # the grid API only works on the current pattern; we jump back below
    try:
        pat = patterns.patternNumber()
        ticks_per_step = general.getRecPPQ() // 4
        for st, on, vel in clean:
            channels.setGridBit(idx, st, on)
            if on and vel is not None:
                channels.setStepParameterByIndex(idx, pat, st, 1, vel)
            if on and st in shifts:
                channels.setStepParameterByIndex(idx, pat, st, STEP_SHIFT, int(round(shifts[st] * ticks_per_step)))
        count = max(st for st, _, _ in clean) + 1
        grew = None
        if p.get("fit_length") and hasattr(patterns, "setPatternLength"):
            want = p["fit_length"]
            have = patterns.getPatternLength(pat)
            if isinstance(want, int) and 16 <= want <= MAX_STEPS and (have or 0) < want:
                patterns.setPatternLength(pat, want)      # only ever grows the pattern
                grew = {"from": have, "to": patterns.getPatternLength(pat)}
        out = {"channel": idx, "name": channels.getChannelName(idx), "pattern": _pattern_info(), "grew": grew,
               "steps": _read_steps(idx, count, with_shift=bool(shifts))}
    finally:
        if patterns.patternNumber() != home:
            patterns.jumpToPattern(home)
    return out


def op_focus_piano_roll(p):
    ui.showWindow(midi.widPianoRoll)
    try:
        ui.setFocused(midi.widPianoRoll)
    except Exception:
        pass
    try:
        caption = ui.getFocusedFormCaption()
    except Exception:
        caption = ""
    return {"focused": bool(ui.getFocused(midi.widPianoRoll)), "caption": caption}


# ---------- mix ----------

MAX_PARAMS = 40


def _db(track):
    try:
        return round(mixer.getTrackVolume(track, 1), 2)
    except Exception:
        return None


def _plugin_info(index, slot):
    """Name and the first MAX_PARAMS named parameters of a loaded plugin (slot -1 = channel generator)."""
    if not plugins.isValid(index, slot):
        return None
    info = {"slot": slot, "name": plugins.getPluginName(index, slot), "params": []}
    try:
        count = plugins.getParamCount(index, slot)
    except Exception:
        count = 0
    for pi in range(min(count, 400)):
        name = plugins.getParamName(pi, index, slot)
        if not name or name.strip() == "" or name.lower().startswith("param ") and name[6:].isdigit():
            continue
        entry = {"i": pi, "name": name, "value": plugins.getParamValue(pi, index, slot)}
        try:
            entry["text"] = plugins.getParamValueString(pi, index, slot)
        except Exception:
            pass
        info["params"].append(entry)
        if len(info["params"]) >= MAX_PARAMS:
            break
    return info


def op_mix_state(p):
    chans, used = [], {0}
    for i in range(channels.channelCount()):
        t = channels.getTargetFxTrack(i)
        used.add(t)
        entry = {"index": i, "name": channels.getChannelName(i), "volume": channels.getChannelVolume(i),
                 "pan": channels.getChannelPan(i), "muted": bool(channels.isChannelMuted(i)), "mixer_track": t}
        if p.get("generators"):
            gen = _plugin_info(i, -1)
            if gen:
                entry["generator"] = gen
        chans.append(entry)
    tracks = []
    for t in sorted(used):
        fx = []
        for slot in range(10):
            try:
                info = _plugin_info(t, slot)
            except Exception:
                info = None
            if info:
                fx.append(info)
        entry = {"track": t, "name": mixer.getTrackName(t), "volume": mixer.getTrackVolume(t),
                 "volume_db": _db(t), "pan": mixer.getTrackPan(t), "muted": bool(mixer.isTrackMuted(t)), "effects": fx}
        try:
            entry["eq"] = _eq(t)
        except Exception:
            pass
        tracks.append(entry)
    return {"channels": chans, "tracks": tracks}


def _bisect(setter, reader, target, steps=18):
    """Find the 0..1 control value whose read-back (in display units) is `target` (monotonic controls)."""
    lo, hi = 0.0, 1.0
    for _ in range(steps):
        mid = (lo + hi) / 2
        setter(mid)
        if reader() < target:
            lo = mid
        else:
            hi = mid
    setter((lo + hi) / 2)
    return (lo + hi) / 2


def _eq(track):
    return [{"band": b, "gain_db": round(mixer.getEqGain(track, b, 1), 2), "freq_hz": round(mixer.getEqFrequency(track, b, 1)),
             "gain": mixer.getEqGain(track, b, 0), "freq": mixer.getEqFrequency(track, b, 0)} for b in range(mixer.getEqBandCount())]


def op_mixer_setup(p):
    """Give every channel that plays straight into Master its own free mixer insert, named after the channel, so the
    mix can be shaped per sound. One undo step. Returns what was routed."""
    general.saveUndo("Veloura: mixer routing", midi.UF_None)
    used = set(channels.getTargetFxTrack(i) for i in range(channels.channelCount()))
    free = [t for t in range(1, mixer.trackCount() - 1) if t not in used and mixer.getTrackName(t).startswith("Insert")]
    done = []
    for i in range(channels.channelCount()):
        if channels.getTargetFxTrack(i) != 0 or not free:
            continue
        t = free.pop(0)
        channels.setTargetFxTrack(i, t)
        name = channels.getChannelName(i)[:24]
        mixer.setTrackName(t, name)
        try:
            mixer.setTrackColor(t, channels.getChannelColor(i))
        except Exception:
            pass
        done.append({"channel": i, "name": channels.getChannelName(i), "track": t, "now": channels.getTargetFxTrack(i)})
    return {"routed": done, "left_on_master": [i for i in range(channels.channelCount()) if channels.getTargetFxTrack(i) == 0]}


def op_set_routing(p):
    """Point channels at mixer tracks (used to undo Veloura's routing)."""
    general.saveUndo("Veloura: mixer routing", midi.UF_None)
    out = []
    for r in p.get("routes") or []:
        i, t = r.get("channel"), r.get("track")
        ok = isinstance(i, int) and isinstance(t, int) and 0 <= i < channels.channelCount() and 0 <= t < mixer.trackCount() \
            and (not r.get("name") or channels.getChannelName(i) == r["name"])
        if ok:
            channels.setTargetFxTrack(i, t)
            rt = r.get("reset_track")
            if isinstance(rt, int) and 0 < rt < mixer.trackCount():
                mixer.setTrackName(rt, "")          # back to FL's default "Insert N"
        out.append({"channel": i, "ok": ok})
    return {"results": out}


def _volume_for_db(track, target_db):
    """FL's mixer fader is a curve; find the 0..1 value that reads back as target_db (bisection, read-back based)."""
    lo, hi = 0.0, 1.0
    for _ in range(18):
        mid = (lo + hi) / 2
        mixer.setTrackVolume(track, mid)
        if _db(track) < target_db:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def op_set_mix(p):
    """Apply a list of mix changes in one undo step, then read each one back."""
    changes = p.get("changes")
    if not isinstance(changes, list) or not (1 <= len(changes) <= 60):
        raise ValueError("changes must be a list of 1-60 items")
    general.saveUndo("Veloura: mix changes", midi.UF_None)
    out = []
    for c in changes:
        kind, res = c.get("kind"), {"kind": c.get("kind")}
        try:
            if kind in ("channel_volume", "channel_pan", "channel_mute"):
                idx = _channel_index(c)
                if kind == "channel_volume":
                    channels.setChannelVolume(idx, max(0.0, min(1.0, float(c["value"]))))
                    res["now"] = round(channels.getChannelVolume(idx), 4)
                elif kind == "channel_pan":
                    channels.setChannelPan(idx, max(-1.0, min(1.0, float(c["value"]))))
                    res["now"] = round(channels.getChannelPan(idx), 4)
                else:
                    channels.muteChannel(idx, 1 if c["value"] else 0)
                    res["now"] = bool(channels.isChannelMuted(idx))
            elif kind in ("mixer_volume_db", "mixer_volume", "mixer_pan", "mixer_mute"):
                t = c.get("track")
                if not isinstance(t, int) or not (0 <= t < mixer.trackCount()):
                    raise ValueError("bad mixer track %r" % (t,))
                if kind == "mixer_volume_db":
                    _volume_for_db(t, max(-60.0, min(5.6, float(c["value"]))))
                    res["now"] = _db(t)
                elif kind == "mixer_volume":
                    mixer.setTrackVolume(t, max(0.0, min(1.0, float(c["value"]))))
                    res["now"] = round(mixer.getTrackVolume(t), 4)
                elif kind == "mixer_pan":
                    mixer.setTrackPan(t, max(-1.0, min(1.0, float(c["value"]))))
                    res["now"] = round(mixer.getTrackPan(t), 4)
                else:
                    mixer.muteTrack(t, 1 if c["value"] else 0)
                    res["now"] = bool(mixer.isTrackMuted(t))
            elif kind in ("eq_gain_db", "eq_freq_hz", "eq_gain", "eq_freq"):
                t, band = c.get("track"), c.get("band")
                if not isinstance(t, int) or not (0 <= t < mixer.trackCount()) or band not in (0, 1, 2):
                    raise ValueError("bad EQ target")
                if kind == "eq_gain_db":
                    _bisect(lambda v: mixer.setEqGain(t, band, v), lambda: mixer.getEqGain(t, band, 1), max(-18.0, min(18.0, float(c["value"]))))
                elif kind == "eq_freq_hz":
                    _bisect(lambda v: mixer.setEqFrequency(t, band, v), lambda: mixer.getEqFrequency(t, band, 1), max(20.0, min(20000.0, float(c["value"]))))
                elif kind == "eq_gain":
                    mixer.setEqGain(t, band, max(0.0, min(1.0, float(c["value"]))))
                else:
                    mixer.setEqFrequency(t, band, max(0.0, min(1.0, float(c["value"]))))
                res["now"] = _eq(t)[band]
            elif kind == "plugin_param":
                index, slot, pi = c.get("index"), c.get("slot", -1), c.get("param")
                if not plugins.isValid(index, slot):
                    raise ValueError("no plugin at %r slot %r" % (index, slot))
                expect = c.get("expect_plugin")
                if expect and plugins.getPluginName(index, slot) != expect:
                    raise ValueError("the plugin there is now %r, not %r" % (plugins.getPluginName(index, slot), expect))
                plugins.setParamValue(max(0.0, min(1.0, float(c["value"]))), pi, index, slot)
                res["now"] = round(plugins.getParamValue(pi, index, slot), 4)
                try:
                    res["text"] = plugins.getParamValueString(pi, index, slot)
                except Exception:
                    pass
            else:
                raise ValueError("unknown change kind %r" % (kind,))
            res["ok"] = True
        except Exception as e:
            res["ok"] = False
            res["error"] = "%s: %s" % (type(e).__name__, e)
        out.append(res)
    return {"results": out}


MAX_RACK_PATTERNS = 32


def _pattern_steps(num):
    try:
        length = patterns.getPatternLength(num)
    except Exception:
        length = 16
    length = max(16, min(int(length or 16), 64))
    return length, [[s for s in range(length) if channels.getGridBit(i, s)] for i in range(channels.channelCount())]


def op_rack_state(p):
    """Read-only: the whole Channel Rack (names, colours, mute, steps) for the current pattern, and with
    {"all": true} the steps of every pattern too. The grid API only reads the current pattern, so Veloura jumps
    through them and back inside this one call (FL doesn't redraw in between). Skipped while FL is playing."""
    num = patterns.patternNumber()
    length, grid = _pattern_steps(num)
    pats = None
    if p.get("all") and not transport.isPlaying():
        pats = []
        try:
            for n in range(1, min(max(patterns.patternCount(), num), MAX_RACK_PATTERNS) + 1):   # count can read 0
                if n == num:
                    ln, g = length, grid
                else:
                    patterns.jumpToPattern(n)
                    ln, g = _pattern_steps(n)
                pats.append(dict(_pattern_info(n), length=ln, steps=g))
        finally:
            if patterns.patternNumber() != num:
                patterns.jumpToPattern(num)
    rows = []
    for i in range(channels.channelCount()):
        on = grid[i]
        row = {"index": i, "name": channels.getChannelName(i), "muted": bool(channels.isChannelMuted(i)), "steps": on}
        try:
            row["color"] = channels.getChannelColor(i) & 0xFFFFFF
        except Exception:
            pass
        try:
            row["type"] = {0: "sampler", 2: "plugin", 3: "layer", 4: "audioclip", 5: "autoclip"}.get(channels.getChannelType(i), "other")
        except Exception:
            pass
        rows.append(row)
    out = {"pattern": _pattern_info(num), "length": length, "channels": rows, "pattern_count": patterns.patternCount()}
    if pats is not None:
        out["patterns"] = pats
    return out


# ---------- instrument presets ----------

MAX_PRESETS = 3000


def _current_preset_name(idx):
    try:
        return plugins.getName(idx, -1, midi.FPN_Preset, -1)
    except Exception:
        return None


def op_presets(p):
    """Read-only: the preset list an instrument plugin exposes to FL (and its current preset, if FL reports it)."""
    idx = p.get("channel") if "expect_name" not in p else _channel_index(p)
    if not isinstance(idx, int) or not (0 <= idx < channels.channelCount()):
        raise ValueError("bad channel")
    if not plugins.isValid(idx, -1):
        return {"channel": idx, "plugin": None, "count": 0, "names": []}
    count = plugins.getPresetCount(idx, -1)
    names = []
    for i in range(min(count, MAX_PRESETS) if p.get("names", True) else 0):
        try:
            names.append(plugins.getName(idx, -1, midi.FPN_Preset, i))
        except Exception:
            names.append("")
    return {"channel": idx, "plugin": plugins.getPluginName(idx, -1), "count": count, "names": names,
            "current": _current_preset_name(idx)}


def op_step_preset(p):
    """Step an instrument's preset forward/backward n times (FL only offers next/previous), then report the current name."""
    idx = p.get("channel") if "expect_name" not in p else _channel_index(p)
    if not isinstance(idx, int) or not (0 <= idx < channels.channelCount()):
        raise ValueError("bad channel")
    n = p.get("steps")
    if not isinstance(n, int) or abs(n) > MAX_PRESETS:
        raise ValueError("steps must be an integer")
    if p.get("undo", True):
        general.saveUndo("Veloura: change sound", midi.UF_None)
    for _ in range(abs(n)):
        (plugins.nextPreset if n > 0 else plugins.prevPreset)(idx, -1)
    return {"current": _current_preset_name(idx)}


def op_rename_channel(p):
    """Give a channel a name (used to restore the name after FL renames a channel to its new preset)."""
    idx = p.get("channel")
    if not isinstance(idx, int) or not (0 <= idx < channels.channelCount()):
        raise ValueError("bad channel")
    name = p.get("name")
    if not isinstance(name, str) or not 0 < len(name) <= 120:
        raise ValueError("bad name")
    channels.setChannelName(idx, name)
    return {"name": channels.getChannelName(idx)}


def op_open_piano_roll(p):
    """Open (and focus) the Piano Roll for one channel, then report the focused window's caption so the
    caller can check it really shows that channel ("Piano roll - <channel name>")."""
    idx = _channel_index(p)
    channels.selectOneChannel(idx)
    # FL's own F7 command ("Piano roll") opens the Piano Roll for the selected channel; it is the same call
    # Native Instruments' bundled Komplete Kontrol script uses. F7 toggles, so close the window first.
    if ui.getVisible(midi.widPianoRoll):
        ui.hideWindow(midi.widPianoRoll)
    transport.globalTransport(midi.FPT_F7, 1)
    ui.showWindow(midi.widPianoRoll)
    try:
        ui.setFocused(midi.widPianoRoll)
    except Exception:
        pass
    try:
        caption = ui.getFocusedFormCaption()
    except Exception:
        caption = ""
    return {"channel": idx, "name": channels.getChannelName(idx), "caption": caption,
            "focused": bool(ui.getFocused(midi.widPianoRoll))}


def op_select_pattern(p):
    num = p.get("number")
    if not isinstance(num, int) or not (1 <= num <= patterns.patternCount()):
        raise ValueError("pattern %r does not exist" % (num,))
    patterns.jumpToPattern(num)
    return {"pattern": _pattern_info()}


def op_meters(p):
    """Read-only: transport state and the current peak of every mixer track that is making sound."""
    tracks = []
    for i in range(mixer.trackCount()):
        try:
            peak = mixer.getTrackPeaks(i, 2)
        except Exception:
            continue
        if peak > 0.0005:
            tracks.append({"track": i, "name": mixer.getTrackName(i), "peak": round(peak, 4)})
    feeds = {}
    for c in range(channels.channelCount()):
        try:
            feeds.setdefault(channels.getTargetFxTrack(c), []).append(channels.getChannelName(c))
        except Exception:
            pass
    return {"playing": bool(transport.isPlaying()), "tracks": tracks,
            "feeds": {str(k): v for k, v in feeds.items()}}


def op_transport(p):
    """Play or stop FL (used by Veloura's listen check). play rewinds to the start of the pattern/song first."""
    act = p.get("action")
    if act == "play":
        if not transport.isPlaying():
            transport.setSongPos(0)
            transport.start()
    elif act == "stop":
        if transport.isPlaying():
            transport.stop()
    else:
        raise ValueError("action must be play or stop")
    return {"playing": bool(transport.isPlaying())}


def op_rec_read(p):
    """Read-only: values of a channel's internal settings (to discover undocumented ones like Cut itself)."""
    idx = p.get("channel")
    base, count = int(p.get("base", 1024)), min(int(p.get("count", 64)), 256)
    if not isinstance(idx, int) or not (0 <= idx < channels.channelCount()):
        raise ValueError("bad channel")
    rid = channels.getRecEventId(idx)
    flag = getattr(midi, "REC_GetValue", None)
    if flag is None:
        raise ValueError("this FL can't read settings")
    out = {}
    for k in range(count):
        try:
            out[base + k] = general.processRECEvent(rid + base + k, 0, flag)
        except Exception as e:
            out[base + k] = None
    return {"channel": idx, "values": out}


def op_browser(p):
    """Drive FL's Browser the way hardware controllers do. actions: show, caption, step (direction 1/-1),
    toggle (open/close a folder node), filetype, select (load the highlighted item, e.g. into the selected channel)."""
    import ui
    act = p.get("action")
    out = {}
    if act == "show":
        ui.showWindow(midi.widBrowser)
        ui.setFocused(midi.widBrowser)
    elif act == "step":
        d = int(p.get("direction", 1))
        out["caption"] = ui.navigateBrowser(midi.FPT_Down if d > 0 else midi.FPT_Up, 0)
    elif act == "toggle":
        ui.toggleBrowserNode()
    elif act == "select":
        sel = p.get("channel")
        if isinstance(sel, int):
            channels.selectOneChannel(sel)
        ui.selectBrowserMenuItem()
    elif act == "menu_step":
        d = int(p.get("direction", 1))
        out["caption"] = ui.navigateBrowserMenu(midi.FPT_Down if d > 0 else midi.FPT_Up, 0)
    elif act == "enter":
        ui.enter()
    elif act == "escape":
        ui.escape()
    elif act == "preview":
        ui.previewBrowserMenuItem()
    elif act != "caption":
        raise ValueError("unknown browser action")
    try:
        out["in_menu"] = bool(ui.isInPopupMenu())
        out["hint"] = ui.getHintMsg()
    except Exception:
        pass
    try:
        out["focused"] = ui.getFocusedNodeCaption()
    except Exception:
        out["focused"] = None
    try:
        out["filetype"] = ui.getFocusedNodeFileType()
    except Exception:
        out["filetype"] = None
    return out


MAX_BROWSER_STEPS = 6000


def op_browser_goto(p):
    """Walk FL's Browser to a file: path = captions from a top-level folder down to the file,
    children = {"i": [names inside path[i]]} so Veloura knows when a folder is open and never wanders outside it.
    With "channel", selects that channel and opens the browser menu for the file (Veloura then picks the first item,
    "send to selected channel", in follow-up calls because the menu opens asynchronously)."""
    import ui
    path = p.get("path") or []
    kids = p.get("children") or {}
    if not path:
        raise ValueError("no path")
    ui.showWindow(midi.widBrowser)
    step = lambda d: ui.navigateBrowser(midi.FPT_Down if d > 0 else midi.FPT_Up, 0)
    cap = lambda: (ui.getFocusedNodeCaption() or "")
    n, prev = 0, None
    while n < MAX_BROWSER_STEPS:          # to the top of the tree
        c = step(-1)
        n += 1
        if c == prev:
            break
        prev = c
    inside = None                          # direct children of the folder being searched
    outer = set()                          # names in the folders above: reaching one means we left the folder
    for i, comp in enumerate(path):
        want = comp.lower()
        while True:
            c = cap()
            if c.lower() == want:
                break
            if inside is not None and c.lower() in outer and c.lower() not in inside:
                raise ValueError("%r isn't inside the folder in FL's browser" % comp)
            nc = step(1)
            n += 1
            if nc == c or n >= MAX_BROWSER_STEPS:
                raise ValueError("couldn't find %r in FL's browser" % comp)
        if i < len(path) - 1:
            children = set(x.lower() for x in kids.get(str(i), []))
            nxt = step(1)
            n += 1
            if (nxt or "").lower() not in children:      # folder closed: open it
                step(-1)
                ui.toggleBrowserNode()
                nxt = step(1)
                n += 1
                if (nxt or "").lower() not in children:
                    raise ValueError("couldn't open %r in FL's browser" % comp)
            if inside is not None:
                outer |= inside
            inside = children
    out = {"steps": n, "focused": cap(), "filetype": ui.getFocusedNodeFileType()}
    if out["focused"].lower() != path[-1].lower() or not isinstance(out["filetype"], int) or out["filetype"] < 0:
        raise ValueError("FL's browser is on %r, not the file; nothing was loaded" % out["focused"])
    if isinstance(p.get("channel"), int):
        if not (0 <= p["channel"] < channels.channelCount()):
            raise ValueError("bad channel")
        channels.selectOneChannel(p["channel"])
        ui.selectBrowserMenuItem()
    return out


def op_swing(p):
    """FL 2026+: read or set the Channel Rack's main swing (0..1). Returns before/now."""
    if not hasattr(channels, "setSwing"):
        raise ValueError("this FL version has no swing control for scripts")
    before = channels.getSwing()
    if "value" in p:
        v = p["value"]
        if not isinstance(v, (int, float)) or not 0 <= v <= 1:
            raise ValueError("swing must be 0..1")
        general.saveUndo("Veloura: swing", midi.UF_None)
        channels.setSwing(float(v))
    return {"before": before, "now": channels.getSwing()}


def op_eq_probe(p):
    """Read-only: the built-in EQ of a mixer track, raw and in display units where FL offers them."""
    t = int(p.get("track", 1))
    out = {"bands": mixer.getEqBandCount(), "track": t, "name": mixer.getTrackName(t), "eq": []}
    for b in range(mixer.getEqBandCount()):
        row = {"band": b}
        for key, fn in (("gain", mixer.getEqGain), ("freq", mixer.getEqFrequency), ("bw", mixer.getEqBandwidth)):
            for mode in (0, 1):
                try:
                    row["%s_%d" % (key, mode)] = fn(t, b, mode)
                except Exception as e:
                    row["%s_%d" % (key, mode)] = "err: %s" % e
        out["eq"].append(row)
    out["routing"] = [(i, channels.getChannelName(i), channels.getTargetFxTrack(i)) for i in range(channels.channelCount())]
    out["track_names"] = [(t2, mixer.getTrackName(t2)) for t2 in range(0, min(mixer.trackCount(), 14))]
    return out


def op_introspect(p):
    """Read-only: which functions FL's scripting modules offer on this FL version (to find what can be automated)."""
    import ui
    mods = {"channels": channels, "mixer": mixer, "plugins": plugins, "patterns": patterns, "transport": transport,
            "general": general, "ui": ui}
    try:
        import ilmcp
        mods["ilmcp"] = ilmcp
    except ImportError as e:
        mods["ilmcp_error"] = None
    try:
        import playlist
        mods["playlist"] = playlist
    except ImportError:
        pass
    try:
        import arrangement
        mods["arrangement"] = arrangement
    except ImportError:
        pass
    out = {name: sorted(n for n in dir(m) if not n.startswith("_")) for name, m in mods.items() if m is not None}
    out["midi_rec"] = {n: getattr(midi, n) for n in dir(midi) if n.startswith(("REC_Chan", "REC_Smp", "REC_Plug")) or "Cut" in n
                       or "Loop" in n}
    probe = {"channels": ["getSwing", "setSwing", "fillEachNSteps"], "patterns": ["setPatternLength", "clearPattern",
             "duplicatePatternData", "incrementPatternLength", "movePattern"], "general": ["getProjectTitle", "setNumerator"],
             "mixer": ["setPluginMixLevel", "getPluginMixLevel", "setCurrentTempo"], "ui": ["showPicker"]}
    out["docs26"] = {}
    for mname, fns in probe.items():
        m = mods.get(mname)
        for fn in fns:
            f = getattr(m, fn, None) if m else None
            out["docs26"]["%s.%s" % (mname, fn)] = (getattr(f, "__doc__", None) or "(no doc)")[:400] if f else "(missing)"
    if "ilmcp" in mods:
        im = mods["ilmcp"]
        out["ilmcp_docs"] = {n: (getattr(getattr(im, n), "__doc__", "") or "")[:300] for n in dir(im) if not n.startswith("_")}
    else:
        out["ilmcp_missing"] = True
    return out


OPS = {"transport": op_transport, "rec_read": op_rec_read, "swing": op_swing, "set_routing": op_set_routing, "mixer_setup": op_mixer_setup, "eq_probe": op_eq_probe, "browser_goto": op_browser_goto, "browser": op_browser, "introspect": op_introspect, "rename_channel": op_rename_channel, "presets": op_presets, "step_preset": op_step_preset, "rack_state": op_rack_state, "mix_state": op_mix_state, "set_mix": op_set_mix, "meters": op_meters, "hello": op_hello, "project": op_project, "set_tempo": op_set_tempo, "read_steps": op_read_steps,
       "write_steps": op_write_steps, "focus_piano_roll": op_focus_piano_roll, "open_piano_roll": op_open_piano_roll, "select_pattern": op_select_pattern}


# ---------- SysEx transport ----------

def _pack7(data):
    out = bytearray()
    for i in range(0, len(data), 7):
        group = data[i:i + 7]
        high = 0
        for j, b in enumerate(group):
            high |= ((b >> 7) & 1) << j
        out.append(high)
        out.extend(b & 0x7F for b in group)
    return bytes(out)


def _unpack7(data):
    out = bytearray()
    i = 0
    while i < len(data):
        high = data[i]
        i += 1
        n = min(7, len(data) - i)
        for j in range(n):
            out.append(data[i + j] | (((high >> j) & 1) << 7))
        i += n
    return bytes(out)


def _send(req_id, payload):
    packed = _pack7(json.dumps(payload).encode("utf-8"))
    total = max(1, (len(packed) + CHUNK - 1) // CHUNK)
    for seq in range(total):
        frame = bytearray([0xF0, MANUFACTURER, TAG, 1, (req_id >> 7) & 0x7F, req_id & 0x7F, seq, total])
        frame.extend(packed[seq * CHUNK:(seq + 1) * CHUNK])
        frame.append(0xF7)
        device.midiOutSysex(bytes(frame))


def _run_op(req):
    """Run one request. Raises only for FL's "unsafe at current time" (so OnIdle can retry); other errors become replies."""
    started = time.time()
    try:
        if req.get("protocol") != PROTOCOL:
            raise ValueError("protocol %r not supported" % req.get("protocol"))
        op = OPS.get(req.get("op"))
        if op is None:
            raise ValueError("unknown operation %r" % req.get("op"))
        result = op(req.get("params") or {})
        return {"ok": True, "result": result, "ms": int((time.time() - started) * 1000)}
    except Exception as e:
        if _unsafe(e):
            raise
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "ms": int((time.time() - started) * 1000)}


def _serve(req_id, req):
    started = time.time()
    try:
        if req.get("protocol") != PROTOCOL:
            raise ValueError("protocol %r not supported" % req.get("protocol"))
        op = OPS.get(req.get("op"))
        if op is None:
            raise ValueError("unknown operation %r" % req.get("op"))
        result = op(req.get("params") or {})
        _send(req_id, {"ok": True, "result": result, "ms": int((time.time() - started) * 1000)})
    except Exception as e:
        _send(req_id, {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "ms": int((time.time() - started) * 1000)})


def OnSysEx(event):
    try:
        raw = bytes(event.sysex)
    except Exception:
        return
    if len(raw) < 9 or raw[1] != MANUFACTURER or raw[2] != TAG or raw[3] != 0:
        return
    event.handled = True
    req_id, seq, total = (raw[4] << 7) | raw[5], raw[6], raw[7]
    entry = _inbox.setdefault(req_id, {"total": total, "chunks": {}})
    entry["chunks"][seq] = raw[8:-1]
    if len(entry["chunks"]) < entry["total"]:
        return
    del _inbox[req_id]
    try:
        req = json.loads(_unpack7(b"".join(entry["chunks"][i] for i in range(entry["total"]))).decode("utf-8"))
    except Exception as e:
        _send(req_id, {"ok": False, "error": "undecodable request: %s" % e})
        return
    # Try right away (FL 2024 allows it; reads always work). FL 2026 refuses edits inside the MIDI callback
    # ("Operation unsafe at current time"): then the request waits in a queue that OnIdle runs on FL's main thread.
    if _queue:
        _queue.append((req_id, req, time.time()))
        return
    try:
        reply = _run_op(req)
    except Exception:
        _queue.append((req_id, req, time.time()))
        return
    _send(req_id, reply)


_queue = []
QUEUE_TIMEOUT = 8.0


def _unsafe(err):
    return "unsafe" in str(err).lower()


_idle = {"ticks": 0}


def OnIdle():
    _idle["ticks"] += 1
    if not _queue:
        return
    try:
        if hasattr(general, "safeToEdit") and not general.safeToEdit():
            _idle["err"] = "safeToEdit() is False"
            if time.time() - _queue[0][2] < QUEUE_TIMEOUT:
                return                               # try again on the next idle tick
    except Exception:
        pass
    req_id, req, at = _queue[0]
    try:
        reply = _run_op(req)
    except Exception as e:
        _idle["err"] = "%s: %s" % (type(e).__name__, e)
        if _unsafe(e) and time.time() - at < QUEUE_TIMEOUT:
            return                                   # FL is busy (e.g. a dialog or playback edit lock): retry soon
        reply = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    _queue.pop(0)
    _send(req_id, reply)


def OnMidiMsg(event):
    event.handled = False  # never swallow normal MIDI


def OnInit():
    print("Veloura Controller %s ready (API %s)" % (SCRIPT_BUILD, _api_version()))


def OnDeInit():
    print("Veloura Controller stopped")
