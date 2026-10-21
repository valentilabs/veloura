"""Mix moves: turn the AI's "mix" suggestions into exact FL controller changes, with previews and undo.

The AI speaks in friendly units; FL's controller works in 0..1 values:
  channel_volume   percent 0-100 (FL's channel volume knob; default about 78%)
  channel_pan      -100 (left) .. 100 (right)
  channel_mute     1 = mute, 0 = unmute
  mixer_volume_db  decibels, -60 .. +5.6 (0 dB = FL's default fader position)
  mixer_pan        -100 .. 100
  mixer_mute       1 / 0
  effect_param     percent 0-100 of an already-loaded plugin's control (found by plugin and control name)
  eq_gain_db       the mixer track's built-in EQ: param = low | mid | high, value = dB (-18 .. +18)
  eq_freq_hz       the built-in EQ band's frequency: param = low | mid | high, value = Hz
Targets are channel names or mixer track names; a channel name used with a mixer_* or effect_param move means
the mixer track that channel plays through.
"""

import re

KINDS = ("channel_volume", "channel_pan", "channel_mute", "mixer_volume_db", "mixer_pan", "mixer_mute", "effect_param",
         "eq_gain_db", "eq_freq_hz")
BANDS = {"low": 0, "mid": 1, "high": 2, "0": 0, "1": 1, "2": 2}


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def compact_state(state):
    """A small summary of the mix for the AI prompt."""
    chans = [{"name": c["name"], "volume_pct": round(c["volume"] * 100), "pan": round(c["pan"] * 100), "muted": c["muted"],
              "mixer_track": c["mixer_track"]} for c in state.get("channels", [])]
    tracks = []
    for t in state.get("tracks", []):
        tracks.append({"track": t["track"], "name": t["name"], "volume_db": t.get("volume_db"), "pan": round(t["pan"] * 100),
                       "muted": t["muted"], "eq": [{"band": ("low", "mid", "high")[e["band"]], "gain_db": e["gain_db"],
                                                    "freq_hz": e["freq_hz"]} for e in t.get("eq") or []], "effects": [{"plugin": fx["name"], "controls": [
                           {"name": p["name"], "pct": round(p["value"] * 100), "shows": p.get("text", "")} for p in fx["params"]]}
                           for fx in t.get("effects", [])]})
    return {"channels": chans, "mixer_tracks": tracks}


def _find_channel(state, name):
    n = _norm(name)
    hits = [c for c in state.get("channels", []) if _norm(c["name"]) == n]
    return hits[0] if len(hits) == 1 else None


def _find_track(state, name):
    n = _norm(name)
    hits = [t for t in state.get("tracks", []) if _norm(t["name"]) == n]
    if len(hits) == 1:
        return hits[0]
    if n in ("master", "mastertrack"):
        return next((t for t in state.get("tracks", []) if t["track"] == 0), None)
    ch = _find_channel(state, name)
    if ch:
        return next((t for t in state.get("tracks", []) if t["track"] == ch["mixer_track"]), None)
    return None


def _find_param(params, name):
    n = _norm(name)
    exact = [p for p in params if _norm(p["name"]) == n]
    if exact:
        return exact[0]
    part = [p for p in params if n and n in _norm(p["name"])]
    return part[0] if len(part) == 1 else None


def resolve(moves, state, name_map=None):
    """AI moves -> (changes for the controller, preview rows, problems).
    name_map: {name the AI used (lower case): actual channel name} from the beat's routing."""
    changes, preview, problems = [], [], []
    name_map = name_map or {}
    for m in moves or []:
        kind, target, value = m.get("kind"), m.get("target", ""), m.get("value")
        target = name_map.get((target or "").strip().lower(), target)
        why = (m.get("why") or "")[:200]
        if kind not in KINDS or not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append("Skipped a mix move I couldn't read (%r on %r)." % (kind, target))
            continue
        try:
            if kind.startswith("channel_"):
                ch = _find_channel(state, target)
                if not ch:
                    raise LookupError("no channel called %r" % target)
                base = {"channel": ch["index"], "expect_name": ch["name"]}
                if kind == "channel_volume":
                    v = max(0.0, min(100.0, float(value))) / 100.0
                    changes.append(dict(base, kind=kind, value=v)); before, after, what = ch["volume"], v, "Volume"
                    fmt = lambda x: "%d%%" % round(x * 100)
                elif kind == "channel_pan":
                    v = max(-100.0, min(100.0, float(value))) / 100.0
                    changes.append(dict(base, kind=kind, value=v)); before, after, what = ch["pan"], v, "Pan"
                    fmt = _pan
                else:
                    v = bool(value)
                    changes.append(dict(base, kind=kind, value=v)); before, after, what = ch["muted"], v, "Mute"
                    fmt = lambda x: "muted" if x else "on"
                label = ch["name"]
                undo = dict(base, kind=kind, value=before)
            elif kind in ("eq_gain_db", "eq_freq_hz"):
                t = _find_track(state, target)
                if not t:
                    raise LookupError("no mixer track for %r" % target)
                if t["track"] == 0 and _norm(target) not in ("master", "mastertrack"):
                    raise LookupError("%r plays straight into Master; route it to its own insert first" % target)
                band = BANDS.get(str(m.get("param") or "").lower())
                if band is None:
                    raise LookupError("EQ band must be low, mid or high")
                eq = (t.get("eq") or [{}, {}, {}])[band]
                if kind == "eq_gain_db":
                    v = max(-18.0, min(18.0, float(value)))
                    before, what, fmt = eq.get("gain_db"), "EQ %s gain" % ("low", "mid", "high")[band], lambda x: "%+.1f dB" % x if x is not None else "?"
                    undo = {"kind": "eq_gain", "track": t["track"], "band": band, "value": eq.get("gain", 0.5)}
                else:
                    v = max(20.0, min(20000.0, float(value)))
                    before, what, fmt = eq.get("freq_hz"), "EQ %s frequency" % ("low", "mid", "high")[band], lambda x: "%d Hz" % x if x is not None else "?"
                    undo = {"kind": "eq_freq", "track": t["track"], "band": band, "value": eq.get("freq", 0.5)}
                changes.append({"kind": kind, "track": t["track"], "band": band, "value": v})
                after = v
                label = "Mixer %d · %s" % (t["track"], t["name"])
            elif kind.startswith("mixer_"):
                t = _find_track(state, target)
                if not t:
                    raise LookupError("no mixer track for %r" % target)
                if kind == "mixer_volume_db":
                    v = max(-60.0, min(5.6, float(value)))
                    changes.append({"kind": kind, "track": t["track"], "value": v})
                    before, after, what, fmt = t.get("volume_db"), v, "Mixer level", lambda x: "%+.1f dB" % x if x is not None else "?"
                    undo = {"kind": "mixer_volume", "track": t["track"], "value": t["volume"]}
                elif kind == "mixer_pan":
                    v = max(-100.0, min(100.0, float(value))) / 100.0
                    changes.append({"kind": kind, "track": t["track"], "value": v})
                    before, after, what, fmt = t["pan"], v, "Mixer pan", _pan
                    undo = {"kind": kind, "track": t["track"], "value": t["pan"]}
                else:
                    v = bool(value)
                    changes.append({"kind": kind, "track": t["track"], "value": v})
                    before, after, what, fmt = t["muted"], v, "Mixer mute", lambda x: "muted" if x else "on"
                    undo = {"kind": kind, "track": t["track"], "value": t["muted"]}
                label = "Mixer %d · %s" % (t["track"], t["name"])
            else:  # effect_param
                t = _find_track(state, target)
                plugin_name, param_name = m.get("plugin", ""), m.get("param", "")
                fx = None
                if t:
                    fx = next((f for f in t.get("effects", []) if _norm(f["name"]) == _norm(plugin_name)), None) or \
                        next((f for f in t.get("effects", []) if _norm(plugin_name) and _norm(plugin_name) in _norm(f["name"])), None)
                if not fx:
                    raise LookupError("%r isn't loaded on %r's mixer track" % (plugin_name, target))
                p = _find_param(fx["params"], param_name)
                if not p:
                    raise LookupError("%s has no control called %r" % (fx["name"], param_name))
                v = max(0.0, min(100.0, float(value))) / 100.0
                changes.append({"kind": "plugin_param", "index": t["track"], "slot": fx["slot"], "param": p["i"], "value": v,
                                "expect_plugin": fx["name"]})
                before, after, what = p["value"], v, "%s · %s" % (fx["name"], p["name"])
                fmt = lambda x: "%d%%" % round(x * 100)
                label = "Mixer %d · %s" % (t["track"], t["name"])
                undo = {"kind": "plugin_param", "index": t["track"], "slot": fx["slot"], "param": p["i"], "value": p["value"],
                        "expect_plugin": fx["name"]}
            preview.append({"target": label, "what": what, "before": fmt(before), "after": fmt(after), "why": why})
            changes[-1]["_undo"] = undo
        except LookupError as e:
            problems.append("Skipped: %s." % e)
    return changes, preview, problems


def _pan(x):
    if x is None:
        return "?"
    v = round(x * 100)
    return "center" if v == 0 else ("%d%% L" % -v if v < 0 else "%d%% R" % v)


def split_undo(changes):
    """Separate the controller payload from the stored undo values."""
    send, undo = [], []
    for c in changes:
        c = dict(c)
        undo.append(c.pop("_undo"))
        send.append(c)
    return send, undo
