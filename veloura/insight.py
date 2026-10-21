"""Beat insight: look at the notes and steps Veloura knows about and propose a few high-impact improvements.

Everything here is a STRUCTURAL estimate from MIDI data (notes, steps, registers, rhythm), never a claim
about audio (Veloura can't hear the mix). Each finding carries its evidence and, where Veloura can fix it,
a ready-made revised or new part so the user sees a before/after and can accept it with one click.
"""

import copy

from . import grooves, theory, variations

MAX_FINDINGS = 5


def _plan_like(plan, notes):
    p = copy.deepcopy(plan)
    p["notes"] = sorted(notes, key=lambda n: (n["start"], n["pitch"]))
    return p


def _melodic(parts):
    return {n: e for n, e in parts.items() if e.get("role") in ("melody", "chords", "other") and (e.get("plan") or {}).get("notes")
            and not all(x["pitch"] == 60 for x in e["plan"]["notes"])}


def _priority(name, e):
    return theory.ROLE_PRIORITY.get(theory.layer_role({"role": e.get("role"), "purpose": e.get("purpose")}), 5)


def analyze(parts, harmony_symbols=None, genre=None, seed=0):
    """parts: {name: {"role", "purpose"?, "plan"}}. Returns findings, most valuable first."""
    findings = []
    if not parts:
        return [{"id": "empty", "title": "Nothing to improve yet", "detail": "Make a beat first, then come back.",
                 "evidence": {}, "group": "beat", "fix": None}]
    any_plan = next(iter(parts.values()))["plan"]
    bars = max((e["plan"] or {}).get("bars") or 4 for e in parts.values())
    key = None
    for e in parts.values():
        key = theory.parse_key(e["plan"].get("key") or "")
        if key:
            break
    key = key or (5, "minor")
    pitched = [{"role": e["role"], "plan": e["plan"]} for e in parts.values() if e["role"] != "drums"]
    harmony = theory.harmony_from_symbols(harmony_symbols, bars) if harmony_symbols else None
    if not harmony:
        harm_src = [p for p in pitched if p["role"] != "bass"] or pitched
        harmony = theory.infer_harmony(harm_src, key, bars) if harm_src else theory.genre_harmony(key, bars, genre, seed)
    mel = _melodic(parts)
    bass = {n: e for n, e in parts.items() if e["role"] == "bass" and e["plan"]["notes"]}
    drum = {n: e for n, e in parts.items() if e["role"] == "drums" and e["plan"]["notes"]}
    kick_name = next((n for n in drum if grooves.lane_of(n) == "kick"), None)
    kick_steps = sorted({round(x["start"] * 4) for x in drum[kick_name]["plan"]["notes"]}) if kick_name else []

    # 1. the 808 against the chords
    for name, e in bass.items():
        notes = copy.deepcopy(e["plan"]["notes"])
        rep = []
        fixed = theory.fix_bass(notes, key, harmony, rep, name)
        changed = sum(1 for a, b in zip(sorted(e["plan"]["notes"], key=lambda x: (x["start"], x["pitch"])), fixed) if a["pitch"] != b["pitch"])
        if changed:
            findings.append({"id": "bass-harmony-" + name, "group": "bass", "part": name, "score": 9 + changed,
                             "title": "Make the %s follow the chords" % name,
                             "detail": "%d %s note%s fight the chords above. Root notes under each chord make the low end feel solid."
                                       % (changed, name, "" if changed == 1 else "s"),
                             "evidence": {"notes_off_root": changed, "chords": [s["symbol"] for s in harmony]},
                             "fix": {"type": "revise", "part": name, "role": "bass", "plan": _plan_like(e["plan"], fixed),
                                     "op": "Improve: 808 follows the chords"}})
        if kick_steps:
            b_on = {round(x["start"] * 4) for x in e["plan"]["notes"]}
            lock = len(b_on & set(kick_steps)) / max(1, len(b_on))
            if lock < 0.4 and len(b_on) >= bars:
                locked = theory.gen_bass(harmony, bars, kick_steps=kick_steps, style="locked", seed=seed)
                findings.append({"id": "bass-kick-" + name, "group": "bass", "part": name, "score": 8,
                                 "title": "Lock the %s to the kick" % name,
                                 "detail": "Only %d%% of %s hits land with the kick. Hitting together makes the low end punch."
                                           % (round(lock * 100), name),
                                 "evidence": {"hits_with_kick": round(lock, 2)},
                                 "fix": {"type": "revise", "part": name, "role": "bass", "plan": _plan_like(e["plan"], locked),
                                         "op": "Improve: 808 locked to the kick"}})

    # 2. melodic layers fighting (same register, same rhythm) or rubbing
    names = sorted(mel, key=lambda n: _priority(n, mel[n]))
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            na, nb = mel[a]["plan"]["notes"], mel[b]["plan"]["notes"]
            ro, oo = theory.register_overlap(na, nb), theory.onset_overlap(na, nb)
            if ro > 0.6 and oo > 0.55 and mel[b].get("purpose") not in ("double", "harmony"):
                shift = -12 if theory.median_pitch(nb) <= theory.median_pitch(na) else 12
                moved = [dict(x, pitch=x["pitch"] + shift) for x in nb if 0 <= x["pitch"] + shift <= 127]
                findings.append({"id": "fight-%s-%s" % (a, b), "group": "melody", "part": b, "score": 8,
                                 "title": "Give %s its own space" % b,
                                 "detail": "%s and %s play in the same range with the same rhythm, so they blur together. "
                                           "Moving %s an octave %s separates them." % (a, b, b, "down" if shift < 0 else "up"),
                                 "evidence": {"register_overlap": round(ro, 2), "rhythm_overlap": round(oo, 2)},
                                 "fix": {"type": "revise", "part": b, "role": mel[b]["role"], "plan": _plan_like(mel[b]["plan"], moved),
                                         "op": "Improve: %s an octave %s" % (b, "down" if shift < 0 else "up")}})
    layers = {n: e["plan"]["notes"] for n, e in list(mel.items()) + list(bass.items())}
    rubs = theory.clashes(layers, harmony)
    if rubs:
        loser = max({r[2] for r in rubs} | {r[0] for r in rubs}, key=lambda n: _priority(n, parts[n]))
        e = parts[loser]
        trial = [{"name": n, "role": theory.layer_role({"role": parts[n]["role"], "purpose": parts[n].get("purpose")}),
                  "notes": copy.deepcopy(v)} for n, v in layers.items()]
        theory.fix_clashes(trial, harmony, [])
        fixed = next(t["notes"] for t in trial if t["name"] == loser)
        findings.append({"id": "clash-" + loser, "group": "melody" if e["role"] != "bass" else "bass", "part": loser,
                         "score": 7 + len(rubs), "title": "Stop %s rubbing against the others" % loser,
                         "detail": "%d spot%s where held notes sit a half-step apart (sounds like a mistake, not tension)."
                                   % (len(rubs), "" if len(rubs) == 1 else "s"),
                         "evidence": {"rubs": len(rubs)},
                         "fix": {"type": "revise", "part": loser, "role": e["role"], "plan": _plan_like(e["plan"], fixed),
                                 "op": "Improve: fixed rubs in %s" % loser}})

    # 3. the lead: too repetitive, or no hook at all
    lead_name = next((n for n in names if theory.layer_role({"role": mel[n]["role"], "purpose": mel[n].get("purpose")}) == "lead"),
                     names[0] if names else None)
    if lead_name and bars >= 4:
        notes = mel[lead_name]["plan"]["notes"]
        rep = theory.repetition_score(notes, bars)
        if rep > 0.85:
            v = variations.develop_endings(mel[lead_name]["plan"], key, harmony, seed=seed)
            findings.append({"id": "repeat-" + lead_name, "group": "melody", "part": lead_name, "score": 6,
                             "title": "Answer the hook at the end of each phrase",
                             "detail": "%s repeats almost exactly every bar. Changing the end of bars 4 and 8 keeps the hook but adds a reply."
                                       % lead_name, "evidence": {"repetition": round(rep, 2)},
                             "fix": {"type": "revise", "part": lead_name, "role": mel[lead_name]["role"], "plan": v,
                                     "op": "Improve: new phrase endings"}})
        elif rep < 0.12 and len(notes) >= bars * 3:
            v = variations.motif_repeat(mel[lead_name]["plan"], key, harmony)
            findings.append({"id": "hook-" + lead_name, "group": "melody", "part": lead_name, "score": 6,
                             "title": "Turn %s into a hook" % lead_name,
                             "detail": "Every bar is different, so nothing sticks. Repeating the first idea, then answering it, makes it memorable.",
                             "evidence": {"repetition": round(rep, 2)},
                             "fix": {"type": "revise", "part": lead_name, "role": mel[lead_name]["role"], "plan": v,
                                     "op": "Improve: built a hook from bar 1"}})
        dens = theory.density(notes, bars)
        if dens > 11:
            thinned = theory.thin(copy.deepcopy(notes), 8, bars, [], lead_name)
            findings.append({"id": "dense-" + lead_name, "group": "melody", "part": lead_name, "score": 5,
                             "title": "Leave space in %s" % lead_name,
                             "detail": "%.0f notes a bar leaves no room for a vocal. Thinning the weakest notes keeps the shape." % dens,
                             "evidence": {"notes_per_bar": round(dens, 1)},
                             "fix": {"type": "revise", "part": lead_name, "role": mel[lead_name]["role"],
                                     "plan": _plan_like(mel[lead_name]["plan"], thinned), "op": "Improve: thinned the lead"}})

    # 4. drums that never change
    if kick_name and bars >= 4:
        sims = [theory.bar_similarity(drum[kick_name]["plan"]["notes"], b, 0) for b in range(1, bars)]
        hat = next((n for n in drum if grooves.lane_of(n) == "hat"), None)
        if sims and min(sims) > 0.95:
            lanes = {n: e["plan"]["notes"] for n, e in drum.items()}
            varied = variations.drum_fills(lanes, bars, genre=genre, seed=seed)
            target = hat or kick_name
            findings.append({"id": "drums-static", "group": "drums", "part": target, "score": 6,
                             "title": "Add movement to the drums",
                             "detail": "The drums repeat the same bar %d times. A fill at bar 4 and a dropout before the loop restarts keep the head nodding." % bars,
                             "evidence": {"min_bar_similarity": round(min(sims), 2)},
                             "fix": {"type": "group", "parts": [{"part": n, "role": "drums", "plan": _plan_like(drum[n]["plan"], v)}
                                                                for n, v in varied.items() if v != lanes[n]],
                                     "op": "Improve: drum fills and dropouts"}})

    # 5. missing layers that would add something
    if not mel and drum:
        lead = theory.compose_lead(key, harmony, bars, genre=genre, seed=seed)
        findings.append({"id": "add-melody", "group": "melody", "part": "Melody", "score": 8, "title": "Add a melody",
                         "detail": "Drums only so far. Here's a hook over %s to start from." % " – ".join(s["symbol"] for s in harmony[:4]),
                         "evidence": {"melodic_layers": 0},
                         "fix": {"type": "new", "part": "Melody", "role": "melody", "purpose": "lead", "plan": _plan_like(any_plan, lead),
                                 "op": "Improve: added a melody"}})
    if (mel or drum) and not bass:
        gen = theory.gen_bass(harmony, bars, kick_steps=kick_steps or None, style="locked" if kick_steps else "sustain", seed=seed)
        findings.append({"id": "add-808", "group": "bass", "part": "808", "score": 7, "title": "Add an 808",
                         "detail": "There's no low end yet. An 808 on the chord roots%s." % (", locked to the kick" if kick_steps else ""),
                         "evidence": {"bass_parts": 0},
                         "fix": {"type": "new", "part": "808", "role": "bass", "purpose": "bass", "plan": _plan_like(any_plan, gen),
                                 "op": "Improve: added an 808"}})
    if len(mel) == 1 and lead_name:
        ctr = theory.gen_counter(mel[lead_name]["plan"]["notes"], key, harmony, bars, center=(theory.median_pitch(mel[lead_name]["plan"]["notes"]) or 69) - 12, seed=seed)
        if ctr:
            findings.append({"id": "add-counter", "group": "melody", "part": "Counter", "score": 4,
                             "title": "Add a counter-melody",
                             "detail": "One melodic layer. A quiet reply in the gaps of %s adds depth without crowding it." % lead_name,
                             "evidence": {"melodic_layers": 1},
                             "fix": {"type": "new", "part": "Counter", "role": "melody", "purpose": "counter",
                                     "plan": _plan_like(mel[lead_name]["plan"], ctr), "op": "Improve: added a counter-melody"}})
    if not drum and (mel or bass):
        findings.append({"id": "add-drums", "group": "drums", "part": None, "score": 5, "title": "Add drums",
                         "detail": "No drums yet. Pick a groove in the Groove Lab, or ask for drums in the chat.",
                         "evidence": {"drum_parts": 0}, "fix": None})
    findings.sort(key=lambda f: -f["score"])
    for f in findings:
        f["kind"] = "structural estimate from the notes (Veloura can't hear the mix)"
    return findings[:MAX_FINDINGS]
