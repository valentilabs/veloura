"""Production pipeline: turns a draft (from the AI or the offline composer) into a coherent beat.

    draft parts + harmony + groove  ->  generated layers + genre drums + validated, repaired notes

Steps:
  1. Work out the key, bar count and harmony (the AI's chords, else inferred from the parts, else a
     genre progression).
  2. Fill parts that ask the engine to write them ("generate": pads, counter-melodies, doubles, harmonies,
     arps, 808 lines locked to the kick, genre drums).
  3. Refine every pitched part together (theory.refine): accidental wrong notes, bass vs chords, clashes
     between layers, register fights, density and leaps, using the user's feel settings.
  4. Validate each plan (melody_plan.validate_plan) so nothing malformed reaches FL.
"""

from . import blueprints, drums as drummod, ensemble, grooves, theory

YO_STYLES = {"trap", "melodic trap", "melodic rap", "dark trap"}   # styles that follow the house reference (Yo)
from .melody_plan import PlanError, validate_plan

PURPOSES = ["lead", "counter", "harmony", "double", "pad", "chords", "arp", "bell", "bass", "drums", "sample", "other"]


def _plan(name, notes, key_label, tempo, bars, target=""):
    return {"schema": "cadence.melody/1", "title": name, "tempo_bpm": tempo, "time_signature": [4, 4], "key": key_label,
            "bars": bars, "target": target or name, "notes": sorted(notes, key=lambda n: (n["start"], n["pitch"]))}


def _first(parts, pred):
    return next((p for p in parts if pred(p)), None)


def resolve_key(harmony_block, parts, settings):
    """(key, label) keeping the spelling the musician used (C# minor stays C# minor)."""
    for cand in [(harmony_block or {}).get("key")] + [(p.get("plan") or {}).get("key") for p in parts] + [settings.get("key")]:
        k = theory.parse_key(cand) if cand else None
        if k:
            return k, "%s %s" % (cand.strip().split()[0][0].upper() + cand.strip().split()[0][1:], k[1]) \
                if cand.strip().split()[0][:1].isalpha() and len(cand.strip().split()) > 1 else theory.key_label(*k)
    return (5, "minor"), "F minor"


def resolve_bars(parts, settings):
    for p in parts:
        b = (p.get("plan") or {}).get("bars")
        if isinstance(b, int) and 1 <= b <= 16:
            return b
    return int(settings.get("bars") or 4)


def resolve_tempo(parts, settings):
    for p in parts:
        t = (p.get("plan") or {}).get("tempo_bpm")
        if isinstance(t, (int, float)) and 20 <= t <= 999:
            return t
    return settings.get("tempo_bpm") or 140


def quality_score(parts, info, problems):
    """How good a draft is, from measurable musical facts (used to pick the best of several AI drafts)."""
    if not parts:
        return -100.0
    rep = (info or {}).get("report") or {}
    score = 0.0
    ik = list((rep.get("in_key") or {}).values())
    score += 30 * (sum(ik) / len(ik) if ik else 1)
    score -= 6 * rep.get("clashes", 0)
    for v in (rep.get("repetition") or {}).values():
        score += 8 if 0.3 <= v <= 0.85 else -4        # a hook that comes back, but develops
    melodic = [p for p in parts if p["role"] in ("melody", "chords")]
    score += 8 if 1 <= len(melodic) <= 4 else -6
    score += 6 if any(p["role"] == "bass" for p in parts) else 0
    score += 6 if any(p["role"] == "drums" for p in parts) else 0
    score -= 0.4 * sum(len(p.get("repairs") or []) for p in parts)   # the AI needed fewer fixes
    score -= 10 * len([x for x in problems or [] if "discarded" in x])
    for p in parts:
        if p["role"] in ("melody",) and p["plan"]["notes"]:
            d = theory.density(p["plan"]["notes"], p["plan"]["bars"])
            score += 4 if 2 <= d <= 9 else -4
    return round(score, 2)


def finish(parts, harmony_block=None, groove_block=None, settings=None, channels=None, genre=None, feel=None, seed=0,
           locked=None, prefer=None, style_grooves=None, channel_roles=None):
    """Complete and validate a beat. `parts` are raw part dicts ({"name","role","purpose","generate","plan",...});
    plans may have empty notes when "generate" is set. Returns (parts, info, problems)."""
    settings = settings or {}
    channels = channels or []
    locked = set(locked or [])
    problems = []
    key, klabel = resolve_key(harmony_block, parts, settings)
    bars = resolve_bars(parts, settings)
    tempo = resolve_tempo(parts, settings)
    for p in parts:   # one tempo, key and bar count per answer
        plan = p.setdefault("plan", {})
        plan.setdefault("schema", "cadence.melody/1")
        plan.setdefault("time_signature", [4, 4])
        plan.setdefault("title", p.get("name", "Part"))
        plan.setdefault("target", p.get("name", "Part"))
        plan["bars"], plan["tempo_bpm"], plan["key"] = bars, tempo, klabel
        plan["notes"] = [n for n in plan.get("notes") or [] if isinstance(n, dict)]
        if not p.get("purpose"):
            p["purpose"] = {"bass": "bass", "drums": "drums", "chords": "chords"}.get(p.get("role"), "lead" if p.get("role") == "melody" else "other")

    harmony = theory.harmony_from_symbols((harmony_block or {}).get("chords"), bars)
    if not harmony:
        pitched = [p for p in parts if p.get("role") != "drums" and p["plan"]["notes"]]
        harmony = theory.infer_harmony(pitched, key, bars) if pitched else (
            blueprints.yo_harmony(key, bars, seed) if genre in YO_STYLES else theory.genre_harmony(key, bars, genre, seed=seed))
    f = theory.feel_of(feel)

    # drums from the groove engine
    groove_info = None
    want_groove = (groove_block or {}).get("profile") or any(p.get("role") == "drums" and p.get("generate") for p in parts)
    if want_groove:
        g = grooves.generate((groove_block or {}).get("profile") or genre, bars, seed=seed, fullness=f["fullness"],
                             variation=f["variation"], energy=(groove_block or {}).get("energy", 60) or 60,
                             swing=(groove_block or {}).get("swing") if isinstance((groove_block or {}).get("swing"), (int, float))
                             and (groove_block or {}).get("swing") >= 0 else None)
        lanes_src, label = g["lanes"], g["label"]
        drum_family = blueprints.pick(("yo", "lift", "genre"), seed, 3)   # Yo is one groove family of several
        if genre in YO_STYLES and not style_grooves and g["profile"] in ("trap", "melodic rap", "dark trap") and drum_family != "genre":
            lanes_src, label = blueprints.drums(bars, seed, lift=drum_family == "lift"), "Veloura house groove (Yo)"
        if style_grooves:   # the user's own grooves for this genre: use one (tiled), with Veloura's fills and dropouts
            import random as _r
            from . import variations
            pick = _r.Random(seed).choice(style_grooves)
            tiled = {}
            for lane, notes in pick["lanes"].items():
                span = pick["bars"] * 4
                tiled[lane] = [dict(n, start=round(n["start"] + k * span, 6)) for k in range(-(-bars // pick["bars"]))
                               for n in notes if n["start"] + k * span < bars * 4]
            lanes_src = variations.drum_fills(tiled, bars, genre=genre, seed=seed)
            label = "Your groove + Veloura fills"
        fitted = grooves.fit_to_channels(lanes_src, channels, lambda n, c: drummod.match_channel(n, c, prefer))
        groove_info = {"profile": g["profile"], "label": label, "swing": g["swing"], "kick_steps": g["kick_steps"]}
        drum_parts = [p for p in parts if p.get("role") == "drums"]
        for name, notes in fitted.items():
            existing = _first(drum_parts, lambda p: grooves.lane_of(p["name"]) == grooves.lane_of(name) or p["name"] == name)
            if existing and not existing.get("generate") and existing["plan"]["notes"]:
                continue   # the AI wrote this lane by hand: keep it
            if existing:
                existing["name"] = name if not existing.get("keep_name") else existing["name"]
                existing["plan"]["notes"] = notes
            elif name not in locked:
                parts.append({"name": name, "role": "drums", "purpose": "drums", "action": "new", "generate": True,
                              "target_hint": "Your %s channel" % name, "sound": "",
                              "plan": _plan(name, notes, klabel, tempo, bars, "Your %s channel" % name)})
    kick = _first(parts, lambda p: p.get("role") == "drums" and grooves.lane_of(p["name"]) == "kick")
    kick_steps = sorted({int(round(n["start"] * 4)) for n in (kick or {}).get("plan", {}).get("notes", [])}) if kick else None

    # drums that shouldn't hit together (open hat vs closed hat, perc on the snare, kick on the backbeat...)
    drum_parts = [p for p in parts if p.get("role") == "drums" and p["plan"]["notes"] and p["name"] not in locked]
    if len(drum_parts) > 1:
        fixed, drum_repairs = grooves.deconflict({p["name"]: [dict(n) for n in p["plan"]["notes"]] for p in drum_parts}, genre, bars)
        for p in drum_parts:
            p["plan"]["notes"] = fixed[p["name"]]
            if not p["plan"]["notes"]:
                p["_emptied"] = True   # every hit clashed with another drum: leave the lane out quietly
            p.setdefault("repairs", []).extend(r.split(": ", 1)[1] for r in drum_repairs if r.startswith(p["name"] + ": "))

    # every pitched part knows its instrument (the user's channel roles first, then the AI, names, or its job)
    roles = channel_roles or {}
    for p in parts:
        if p.get("role") == "drums":
            continue
        if p["name"] in roles:
            p["instrument"] = roles[p["name"]]
            p["sound"] = ""
            if roles[p["name"]] in ensemble.CHORDAL and p.get("purpose") not in ("chords", "pad", "arp"):
                p["purpose"] = "pad" if roles[p["name"]] in ("pad", "strings", "choir") else p.get("purpose") or "chords"
            continue
        p["instrument"] = p.get("instrument") if p.get("instrument") in ensemble.INSTRUMENTS and p.get("instrument") != "other" else \
            (ensemble.instrument_from_name(p.get("sound")) or ensemble.instrument_from_name(p["name"]) or
             {"bass": "bass_808", "chords": "keys", "pad": "pad", "arp": "arp_synth", "bell": "bell", "double": "bell"}.get(
                 p.get("purpose") or "", "bass_808" if p.get("role") == "bass" else "lead_synth"))

    # a full beat always has a chord layer: depth comes from real chords, not single notes
    melodic = [p for p in parts if p.get("role") in ("melody", "chords", "other") and p.get("purpose") != "sample"]
    has_chords = any(p.get("purpose") in ("chords", "pad") or (p["instrument"] in ensemble.CHORDAL and p.get("purpose") != "lead")
                     or ensemble.polyphony(p["plan"]["notes"]) >= 2.5 for p in melodic)
    if melodic and not has_chords and len(parts) >= 2 and settings.get("_auto_chords", True):
        inst, _ = next(((i, j) for i, j in ensemble.RECIPES.get(genre or "", ensemble.RECIPES["trap"]) if j == "chords"), ("piano", "chords"))
        name = {"piano": "Piano", "keys": "Keys", "rhodes": "Keys", "supersaw": "Supersaw", "pluck": "Pluck"}.get(inst, "Chords")
        if name not in {q["name"] for q in parts}:
            parts.append({"name": name, "role": "chords", "purpose": "chords", "instrument": inst, "generate": True, "action": "new",
                          "target_hint": "", "sound": "", "plan": _plan(name, [], klabel, tempo, bars),
                          "repairs": ["added by Veloura so the beat has full chords under the melody"]})

    # generated pitched layers (lead first, so supporting layers can follow it), written the way each instrument is played
    order = sorted([p for p in parts if p.get("generate") and p.get("role") != "drums"],
                   key=lambda p: 0 if p.get("purpose") == "lead" else 1)
    for p in order:
        if p["plan"]["notes"] and p.get("purpose") not in ("double", "harmony"):
            continue
        lead = _first(parts, lambda q: q is not p and q.get("purpose") == "lead" and q["plan"]["notes"])
        lead_notes = (lead or {}).get("plan", {}).get("notes")
        job = {"bell": "sparkle", "harmony": "harmony"}.get(p.get("purpose"), p.get("purpose") or "lead")
        yo = genre in YO_STYLES
        if yo and job == "chords" and p["instrument"] in ("keys", "rhodes", "piano", "organ"):
            notes = blueprints.keys(harmony, bars, family=blueprints.pick(blueprints.KEYS_FAMILIES, seed, 1))
        elif yo and job == "pad":
            notes = blueprints.pad(harmony, bars)
        elif yo and job == "lead" and p["instrument"] in ("bell", "pluck", "music_box", "arp_synth", "piano", "keys", "rhodes", "lead_synth"):
            notes = blueprints.arp_lead(harmony, bars, key, seed=seed)
        elif yo and job == "counter" and p["instrument"] in ("pluck", "keys", "guitar", "rhodes", "piano", "organ"):
            notes = blueprints.stabs(harmony, bars)
        elif yo and job == "bass" and blueprints.pick(("yo", "lift", "genre"), seed, 2) != "genre":
            notes = blueprints.eight_o_eight(harmony, bars, lift=blueprints.pick(("yo", "lift", "genre"), seed, 2) == "lift") \
                if "808" in p["name"] or p["instrument"] == "bass_808" and "bass" not in p["name"].lower() \
                else blueprints.bass_line(harmony, bars)
        elif job == "harmony":
            notes = theory.generate_layer("harmony", key, harmony, bars, lead=lead_notes, feel=f, genre=genre, seed=seed)
        elif job == "sparkle" and not lead_notes:
            notes = ensemble.write_for(p["instrument"], "lead", key, harmony, bars, genre=genre, feel=f, seed=seed + len(p["name"]))
        else:
            notes = ensemble.write_for(p["instrument"], job, key, harmony, bars, genre=genre, lead=lead_notes,
                                       kick_steps=kick_steps, feel=f, seed=seed + len(p["name"]))
        if not notes:
            problems.append("Couldn't write %s (it needs a lead to follow)." % p["name"])
        p["plan"]["notes"] = notes

    # chord instruments are never single notes: thicken anything the AI wrote too thin (its rhythm, real voicings)
    for p in parts:
        if p.get("role") == "drums" or p["name"] in locked or not p["plan"]["notes"] or p.get("purpose") in ("lead", "sample", "double", "counter", "arp"):
            continue
        chordal = p.get("purpose") in ("chords", "pad") or p.get("role") == "chords" or p.get("instrument") in ensemble.CHORDAL
        if chordal and ensemble.polyphony(p["plan"]["notes"]) < 2.2:
            p["plan"]["notes"] = ensemble.thicken(p["plan"]["notes"], key, harmony, p.get("instrument") or "keys", genre)
            p.setdefault("repairs", []).append("turned single notes into full %s chords" % (p.get("instrument") or "keys").replace("_", " "))

    result = theory.refine([p for p in parts if p["name"] not in locked], key, harmony, bars, feel=f, genre=genre)
    for p in parts:   # every note on a real grid line, no slivers or jammed grace notes, 808s that move by small steps
        if p["name"] in locked or not p["plan"]["notes"] or p.get("purpose") == "sample":
            continue
        if p.get("role") == "drums":
            kind = "roll" if grooves.lane_of(p["name"]) in ("hat", "open") else "drum"
        elif p.get("role") == "bass":
            kind = "bass"
        elif p.get("purpose") in ("chords", "pad", "arp") or p.get("role") == "chords" or p.get("instrument") in ensemble.CHORDAL:
            kind = "chord"
        else:
            kind = "melody"
        p["plan"]["notes"] = theory.tidy_notes(p["plan"]["notes"], kind, result["repairs"], p["name"])
        inst = p.get("instrument")
        if kind == "melody" and theory.is_short_note_line(p["plan"]["notes"], inst):
            p["plan"]["notes"] = theory.calm_pushes(p["plan"]["notes"], result["repairs"], p["name"])
        if kind in ("melody", "chord") and inst in ensemble.REGISTER and p["plan"]["notes"]:
            mid = theory.median_pitch(p["plan"]["notes"])
            if abs(mid - ensemble.REGISTER[inst]) > 9:   # back into the range the instrument really plays in
                p["plan"]["notes"] = ensemble.to_register(p["plan"]["notes"], inst)
                result["repairs"].append("%s: moved into the %s's natural range" % (p["name"], inst.replace("_", " ")))
        if kind == "bass":
            p["plan"]["notes"] = theory.tidy_808(p["plan"]["notes"], bars, result["repairs"], p["name"])

    for p in parts:   # consistent, producer-like dynamics (no random velocity spikes)
        if p["name"] in locked or not p["plan"]["notes"] or p.get("purpose") == "sample":
            continue
        role = "drums" if p.get("role") == "drums" else ("bass" if p.get("role") == "bass" else
                                                         "chords" if p.get("purpose") in ("pad", "chords") or p.get("role") == "chords" else "melody")
        _, changed = theory.shape_velocity(p["plan"]["notes"], role, grooves.lane_of(p["name"]) if role == "drums" else None, genre)
        if changed:
            result["repairs"].append("%s: evened out %d velocit%s" % (p["name"], changed, "y" if changed == 1 else "ies"))

    out = []
    for p in parts:
        if not p["plan"]["notes"]:
            if p["name"] not in locked and not p.get("_emptied"):
                problems.append("Part %r had no notes and was left out." % p["name"])
            continue
        fixes = list(p.get("repairs") or [])
        try:
            p["plan"] = validate_plan({k: v for k, v in p["plan"].items() if k in
                                       ("schema", "title", "tempo_bpm", "time_signature", "key", "bars", "target", "notes")}, fixes)
        except PlanError as e:
            problems.append("Part %r was discarded: %s" % (p["name"], "; ".join(e.problems[:3])))
            continue
        p["repairs"] = fixes + [r.split(": ", 1)[1] for r in result["repairs"] if r.startswith(p["name"] + ": ")]
        out.append(p)
    info = {"key": klabel, "bars": bars, "tempo": tempo, "harmony": theory.harmony_symbols(harmony), "groove": groove_info,
            "report": result["report"], "feel": f}
    return out, info, problems


# ---------------------------------------------------------------- offline recipes

LAYER_RECIPES = {   # what a producer would stack for each style (purpose, register)
    "trap": [("lead", None), ("counter", None), ("bass", None)],
    "dark trap": [("lead", "mid"), ("pad", "low"), ("bass", None)],
    "plugg": [("lead", "high"), ("pad", None), ("bass", None)],
    "melodic plugg": [("lead", "high"), ("pad", None), ("bell", None), ("bass", None)],
    "rage": [("arp", None), ("lead", None), ("bass", None)],
    "jerk": [("lead", "high"), ("bass", None)],
    "drill": [("lead", "mid"), ("pad", "low"), ("bass", None)],
    "melodic rap": [("chords", None), ("lead", None), ("counter", None), ("bass", None)],
    "melodic trap": [("chords", None), ("lead", None), ("counter", None), ("bass", None)],
    "cloud rap": [("pad", None), ("bell", None), ("bass", None)],
    "ambient": [("pad", None), ("bell", None), ("bass", None)],
    "boom bap": [("chords", None), ("bass", None)],
    "r&b": [("chords", None), ("lead", None), ("bass", None)],
    "detroit": [("lead", "low"), ("bass", None)],
    "pop": [("chords", None), ("lead", None), ("bass", None)],
}
LAYER_NAMES = {"lead": "Lead", "counter": "Counter", "pad": "Pad", "chords": "Keys", "bell": "Bell", "arp": "Arp",
               "bass": "808", "harmony": "Harmony", "double": "Lead double"}


def assign_channels(layers, channels):
    """Give each generated layer the best matching melodic channel from the user's Channel Rack, by name."""
    melodic = [c for c in channels if c.get("type") in ("plugin", "hybrid") or not drummod.lane_kind(c["name"])]
    melodic = [c for c in melodic if not drummod.lane_kind(c["name"])]
    taken = set()
    hints = {"bass": ("808", "bass", "sub"), "pad": ("pad", "string", "choir", "atmos"), "chords": ("key", "piano", "rhodes", "chord", "organ"),
             "bell": ("bell", "glock", "music box"), "arp": ("arp", "pluck", "synth"), "lead": ("lead", "pluck", "synth", "flute", "osc", "flex"),
             "counter": ("pluck", "key", "piano", "osc")}
    named = {}
    bassy = lambda c: any(h in c["name"].lower() for h in hints["bass"])
    for purpose, _ in sorted(layers, key=lambda l: 0 if l[0] == "bass" else 1):
        pool = [c for c in melodic if c["name"] not in taken and (bassy(c) == (purpose == "bass"))]
        pick = next((c for c in pool if any(h in c["name"].lower() for h in hints.get(purpose, ()))), None)
        if pick is None and purpose != "bass":
            pick = next(iter(pool), None)
        if pick:
            taken.add(pick["name"])
            named[purpose] = pick["name"]
    return named
