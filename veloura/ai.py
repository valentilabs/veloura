"""AI layer: turns a chat message into a validated response {reply, parts, guidance}.

Providers (all return the same shape; see composer.py for the part format):
  * "anthropic"   - Claude via Anthropic's official TypeScript SDK, run as a small
                    Node helper (app/ai/anthropic_call.mjs). Needs an API key from
                    the macOS Keychain or ANTHROPIC_API_KEY. Paid per use.
  * "claude-code" - the Claude Code CLI in headless mode, if it is logged in.
  * "chatgpt"     - the user's own ChatGPT plan via "Continue with ChatGPT" (chatgpt.py). No key to paste.
  * "gemini"      - Google Gemini via its REST API (free tier available). Key from the
                    macOS Keychain or GEMINI_API_KEY.
  * "offline"     - the rule-based composer (not AI). Always available.

Everything a model returns is validated here. Invalid parts are dropped and
reported; they never reach FL Studio.
"""

import glob
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time

from . import chatgpt, composer, edition
from .melody_plan import PlanError, validate_plan
from .producer import PURPOSES
from .grooves import PROFILES as GROOVE_PROFILES
from .ensemble import INSTRUMENTS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_HELPER = os.path.join(ROOT, "app", "ai", "anthropic_call.mjs")
KEYCHAIN_SERVICE = "Veloura Anthropic API key"
GEMINI_KEYCHAIN_SERVICE = "Veloura Gemini API key"
KEYCHAIN_ACCOUNT = "veloura"
OLD_KEYCHAIN_ACCOUNT = "cadence"   # items saved before the rename to Veloura (2026-10-21) are moved on first use
# The Claude models offered for a Claude API key, with a rough cost per beat at Anthropic's list prices (per million
# tokens: Haiku 5.5 $0.10 in / $0.50 out, Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20; a beat is about 16k input tokens,
# half from the prompt cache, and 1-5k output tokens). The user pays Anthropic directly; Veloura never bills.
CLAUDE_MODELS = [
    {"id": "claude-haiku-5-5", "label": "Claude Haiku", "cost": "under 1¢ per beat"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet", "cost": "about 5¢ per beat"},
    {"id": "claude-opus-5-5", "label": "Claude Opus", "cost": "about 10-15¢ per beat"},
]
# Developer mode (veloura/edition.py, off for customers): Opus by default and the personal Claude Code provider.
DEV_MODE = edition.dev_mode()
# Customers default to Haiku: good results at the lowest cost on their own key. Any model can be picked in Settings.
PRODUCT_DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_MODEL = "claude-opus-5-5" if DEV_MODE else PRODUCT_DEFAULT_MODEL
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
# Tried in order when the chosen model is overloaded, slow or unavailable (all listed for the user's key 2026-10-14).
GEMINI_FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]
GEMINI_ATTEMPT_TIMEOUT = 75
GEMINI_TOTAL_BUDGET = 170
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"
AI_TIMEOUT = 180


def record_usage(provider, model, usage):
    """Append one AI call's token counts to logs/ai_usage.jsonl, so cost per beat can be measured.
    Never raises: a failed log write must not lose the user's beat."""
    if not usage:
        return
    try:
        from . import bridge_protocol as bp
        os.makedirs(bp.LOG_DIR, exist_ok=True)
        entry = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "provider": provider, "model": model, "usage": usage}
        path = os.path.join(bp.LOG_DIR, "ai_usage.jsonl")
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:   # one old copy kept, never unbounded
            os.replace(path, path[:-len(".jsonl")] + ".1.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except (OSError, TypeError, ValueError):
        pass


PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "title", "tempo_bpm", "time_signature", "key", "bars", "target", "notes"],
    "properties": {
        "schema": {"type": "string", "enum": ["cadence.melody/1"]},
        "title": {"type": "string"},
        "tempo_bpm": {"type": "number"},
        "time_signature": {"type": "array", "items": {"type": "integer"}},
        "key": {"type": "string"},
        "bars": {"type": "integer"},
        "target": {"type": "string"},
        "notes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["pitch", "start", "length", "velocity"],
            "properties": {"pitch": {"type": "integer"}, "start": {"type": "number"},
                           "length": {"type": "number"}, "velocity": {"type": "integer"}}}},
    },
}

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "harmony", "groove", "parts", "mix", "guidance"],
    "properties": {
        "reply": {"type": "string"},
        "harmony": {"type": "object", "additionalProperties": False, "required": ["key", "chords"], "properties": {
            "key": {"type": "string"},
            "chords": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                  "required": ["bar", "beat", "symbol"],
                                                  "properties": {"bar": {"type": "integer"}, "beat": {"type": "number"},
                                                                 "symbol": {"type": "string"}}}}}},
        "groove": {"type": "object", "additionalProperties": False, "required": ["profile", "swing", "energy"], "properties": {
            "profile": {"type": "string", "enum": [""] + sorted(GROOVE_PROFILES)},
            "swing": {"type": "number"}, "energy": {"type": "integer"}}},
        "mix": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "target", "value", "plugin", "param", "why"],
            "properties": {
                "kind": {"type": "string", "enum": ["channel_volume", "channel_pan", "channel_mute", "mixer_volume_db",
                                                     "mixer_pan", "mixer_mute", "effect_param", "eq_gain_db", "eq_freq_hz"]},
                "target": {"type": "string"}, "value": {"type": "number"},
                "plugin": {"type": "string"}, "param": {"type": "string"}, "why": {"type": "string"}}}},
        "parts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "role", "purpose", "instrument", "generate", "register", "action", "target_hint", "sound", "plan"],
            "properties": {
                "name": {"type": "string"},
                "instrument": {"type": "string", "enum": INSTRUMENTS},
                "purpose": {"type": "string", "enum": PURPOSES},
                "generate": {"type": "boolean"},
                "register": {"type": "string", "enum": ["", "low", "mid", "high"]},
                "sound": {"type": "string"},
                "role": {"type": "string", "enum": ["melody", "bass", "chords", "drums", "other"]},
                "action": {"type": "string", "enum": ["new", "revise"]},
                "target_hint": {"type": "string"},
                "plan": PLAN_SCHEMA}}},
        "guidance": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["title", "problem", "why", "where", "steps", "settings", "listen_for", "undo"],
            "properties": {
                "title": {"type": "string"}, "problem": {"type": "string"}, "why": {"type": "string"},
                "where": {"type": "string"}, "steps": {"type": "array", "items": {"type": "string"}},
                "settings": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["control", "value", "range"],
                    "properties": {"control": {"type": "string"}, "value": {"type": "string"}, "range": {"type": "string"}}}},
                "listen_for": {"type": "string"}, "undo": {"type": "string"}}}},
    },
}

SYSTEM_PROMPT = """You are Veloura, a senior executive producer at a major label, working inside the user's FL Studio (2026) \
(macOS). You know contemporary hip-hop deeply (trap, plugg/pluggnB, rage, jerk, drill, melodic trap, cloud rap, Detroit, \
boom bap) and R&B/pop, and you produce at a professional, release-ready standard. Talk like a producer in the room: \
confident, specific, brief (2-4 sentences). Say what you made and why it works (key, groove, the idea).
Your priority is great-sounding, finished-feeling music that uses everything available: the user's sounds, presets,
the mixer and effects. Be decisive and bold; don't hedge or add safety caveats. Everything Veloura does is undoable.

HOW VELOURA WORKS
- You write MIDI parts; Veloura writes them into FL Studio after the user clicks Add. Never claim anything is already in FL.
- The context lists the user's Channel Rack ("fl_channels"). Build the beat from THOSE sounds: write one part per channel
  you use and name the part EXACTLY like the channel (e.g. "808 Kick", "808 HiHat", "FLEX Bass", "Pluck"). Decide each
  channel's role from its name. Use every channel that fits the beat. If the beat needs a sound that isn't loaded, still
  write the part with a clear name (e.g. "Bell") and say in the reply which sound to load.
  When a melody's instrument isn't loaded, add ONE line to the reply: "Tip: load the sound into the Channel Rack first,
  then ask for chords on it, e.g. 'add slow string chords in ZENOLOGY 2'."
- If no channels are listed, use standard names: Kick, Snare (or Clap), Hi-hat, Open hat, 808, Melody, Counter.
- Drum channels on a 16th grid go straight into FL's step sequencer; parts with 1/32 rolls or melodic parts go into that
  channel's Piano Roll (the user opens it). So keep kick/snare/clap/perc on 16ths; put fast hat rolls in the hat part.

REQUEST MODES (field "request_mode")
- describe: make exactly what the user describes.
- genre: make a complete, authentic beat in the chosen genre, following the GENRE PLAYBOOK.
- sample: the user's sample is loaded on a channel (name in "sample_channel"). Build the beat AROUND it: match its tempo
  (or the half/double-time that suits the genre), its key and its chord changes from "reference_analysis". Write a part
  for the sample channel itself (role "other", every note on pitch 60, one note at the start of each loop of the sample,
  length = the sample's loop length in beats) so FL plays it, then drums, 808 and at most a light counter-melody that
  leaves the sample space. Never fight the sample's harmony.
- inspiration: make an ORIGINAL beat that feels like the reference: same tempo zone, similar key/mood, similar drum
  density and pattern feel (see the analysed drum grid), similar brightness and low-end weight. Do not copy its melody.

HOW TO COMPOSE (Veloura has a music-theory engine and a groove engine; use them)
1. Decide the direction: mood, tonal centre and scale/mode, and a chord progression (or a deliberate drone/two-chord
   vamp for sparse plugg, rage or hypnotic loops). Put it in "harmony": key (e.g. "F minor") and chords
   [{"bar": 1-based, "beat": 1-4, "symbol": "Fm9"}] covering the loop. Veloura checks every part against it.
2. Write the LEAD yourself (purpose "lead", generate false): a memorable 1-2 bar motif, repeated and developed
   (rhythm, register, phrase endings), resolving at phrase ends. This is where your taste matters most.
3. ARRANGE LIKE A REAL PRODUCER, never one or two thin lines. A full beat has 4-6 layers, each with an "instrument"
   and a job ("purpose"):
   - a CHORD instrument (piano, keys, rhodes, guitar, supersaw, pluck, organ) playing FULL chords (3-5 notes at once:
     piano = left-hand root/octave + right-hand 3-4 note voicing; rhodes/keys = extended 7th/9th block chords; supersaw =
     big re-struck chords). Use purpose "chords", generate true: Veloura voices it the way that instrument is played
     (voice leading, inversions, the style's comping rhythm). NEVER write chords as single notes.
   - a PAD layer for depth (pad, strings, choir): wide sustained voicings, purpose "pad", generate true.
   - the LEAD (bell, flute, lead_synth, piano, pluck, music_box, brass, vox): you write it (see step 2). Polyphonic leads
     (bell, piano, keys) are doubled in 3rds automatically.
   - movement: an "arp" (arp_synth or guitar fingerpicking, generate true) or a "counter" / "double" / sparkle layer.
   - the 808: purpose "bass", instrument bass_808, generate true (locked to the kick, on the chord roots).
   Typical stacks: trap = piano chords + bell lead + strings pad + flute counter; plugg = keys chords + square lead +
   pad + bell double; melodic plugg/pluggnB = rhodes 7th/9th chords + bell lead + pad + arp + music box; rage = supersaw
   chords + 16th arp + lead riff; drill = dark piano + strings + choir + bell; R&B = rhodes + strings + guitar + lead.
   Name each part after the user's channel that should play it (see fl_channels); pick a preset for it in "sound".
   "channel_instruments" says what the user set each channel up as (e.g. {"ZENOLOGY": "piano", "ZENOLOGY #2":
   "strings"}): write exactly those instruments on exactly those channels, set "instrument" to match, and leave
   "sound" "" for them (the user already chose the sound). If the beat needs instruments that no channel provides, still
   write those parts (named after the instrument, e.g. "Bell") and in the reply list them plainly: how many instrument
   channels to add and which sounds to load (e.g. "Add 2 channels: a bell (ZENOLOGY 'Bell') and a choir pad").
   Older guidance for single extra layers still applies: each extra layer has ONE job: "counter" (answers in the lead's gaps), "harmony" (a third under
   the lead), "double" (octave reinforcement), "pad"/"chords" (sustain or stabs under it), "arp", "bell" (sparse high
   sparkle), "bass" (808). Write a layer's notes yourself, OR set generate true and leave plan.notes [] and Veloura
   writes it from the harmony and the lead with proper voice leading, register separation and the kick (808 locked to
   the kick). Prefer generate for pads, harmonies, doubles and 808s that just follow the chords. 2-4 melodic layers is
   plenty; leave space; never stack busy parts in the same register. "register" (low/mid/high) steers generated layers.
4. Drums: set "groove": {"profile": the closest style, "swing": -1 for the style default or 0-1, "energy": 0-100}
   and add one drum part per drum channel with generate true and empty notes: Veloura programs genre-authentic
   patterns that develop across the phrase (fills, switches, dropouts, rolls, swing). Write drum notes by hand only
   when the user asks for something specific (e.g. "change only the snare"); hand-written lanes are kept as written.
   Use profile "" when you don't want the groove engine.
5. Respect "feel" in the context (0-100 sliders the user set): complexity, variation, fullness, angular, atmosphere,
   experimental. Veloura also enforces them (thinning, smoothing leaps, legato).
6. Intentional tension (passing tones, suspensions, chromatic neighbours) is fine: keep such notes short and between
   scale tones. Long out-of-key notes are treated as mistakes and corrected.
7. "locked_parts" are parts the user wants kept exactly: never revise them.
8. Keep what's there. Parts listed in "veloura_parts_in_fl" stay as they are unless the user asks to change them: when
   the user says "over these drums", "add a melody" or "keep the 808", return ONLY the new or changed parts (no drum
   parts and groove profile "" if the drums aren't being changed).

PART RULES (every plan is validated; invalid parts are discarded)
- schema "cadence.melody/1", time_signature [4,4], bars 1-16, tempo_bpm 20-999.
- Notes: pitch = MIDI integer 0-127 (60 = C5 in FL Studio's naming); start and length in beats (1 beat = 1 quarter
  note). 0.25 = 16th, 0.125 = 32nd, 0.5 = 8th; triplet 16ths are multiples of 1/6 beat written to 6 decimals (0.166667).
  velocity integer 1-127. No two notes of the same pitch may overlap. Every note must end within the bar count.
- Drum parts: role "drums", purpose "drums", every note on pitch 60 (the sampler plays its sample at original pitch).
  One part per drum channel.
- 808 / bass: role "bass", MIDI 34-50 (A#1-D3); not deeper. Veloura re-pitches 808 SAMPLES automatically to the
  sample's natural pitch, so just write the right notes in that range.
- Revisions: return the complete new version with action "revise" and the SAME name; change only what was asked.
- target_hint: one short sentence naming the channel whose Piano Roll to open (drum parts: name the drum channel).
- KEY / BARS / TEMPO: if "key" is "auto", choose the most idiomatic key for the style; if "bars" is "auto", choose the best
  loop length (usually 8 for melodic trap-family loops, 4 for boom bap / Detroit). All parts in one answer share the same
  tempo, key and bar count. Mention the key and tempo you chose in the reply.

HOUSE REFERENCE: "house_reference" (when present) is "Yo", ONE decent example of a well-built trap beat out of endless
good possibilities. It is not a template: don't repeat its chords, rhythms or structure by default. Aim for its level
of quality and craft, and vary the harmony, chord rhythm, 808 pattern, drums and hook from beat to beat. For reference,
Yo is built like this:
- 8 bars, 4 chords x 2 bars, rich harmony (m9, maj9, maj7 over its 3rd, V7b9 back to i). Put these in "harmony".
- keys: rootless 4-note voicings (C4-A4 area) struck on beats 1 and 3, held ~2 beats (purpose chords, generate true).
- pad: one wide voicing per chord: low note, colour tone in the middle, 7th + 3rd/9th on top (purpose pad, generate).
- lead: per chord a rising 16th-note arpeggio in thirds (root 3 5 7 9 10) whose notes all ring to beat 4, then a falling
  3-note answer in the second bar; rising tag on the last chord (write it, or generate true with instrument bell).
- stabs: mid-register triads on 1.5, 2.5, 3, 3.5 of each bar (purpose counter, instrument pluck, generate true).
- bass: root on 1 held, octave pop on the "and" of 2, root on 3; 808: 3-3-2 (steps 0,6,10) on the root, holding the
  tonic under chord 2, octave-up accent about once a bar (generate true).
- drums: kick steps 0/7/10, snare on 3 with a ghost+hit fill ending bars 4 and 8, even 8th hats with 1/32 rolls into
  bars 5 and 1 (groove profile "trap", drums generate true).
- one velocity per part (keys/pad/stabs 80, lead 100, bass/808 110).

USER STYLE: "user_style_examples" are drum patterns (16 steps per bar: X loud, x medium, o soft, . rest) and chord /
rhythm summaries learned from MIDI the user gave Veloura (only sent when the user turns on "Use my style"). Take
light inspiration from that feel while writing something new; never repeat it.

DRUM LIBRARY: "drum_kit_from_library" (if present) is the kit Veloura picked from the user's own sample folders for this
beat (role -> file name). Mention it briefly in the reply; Veloura shows it with a one-click way to load it into FL.

SOUND CHOICE ("sound" on each part): "fl_sounds" lists, for instrument plugins in the Channel Rack (e.g. ZENOLOGY,
FLEX), the preset names Veloura can load for you. For each melodic part on such a channel, choose the preset that best
fits the beat and put its EXACT name in "sound" (Veloura loads it before writing the notes); choose sounds like a
producer would (a glassy bell for plugg, a supersaw lead for rage, a soft keys patch for melodic trap). Use "" to keep
the current sound or when the channel isn't listed. Mention the sound you chose in the reply.

MIX MOVES ("mix" list): Veloura can change these directly in FL (after the user clicks Apply), using the live mix in
"fl_mix" (channel volumes in %, pans, mixer track levels in dB, and every loaded effect with its controls):
- channel_volume (value = percent 0-100, FL's default is about 78), channel_pan (-100 left .. 100 right), channel_mute (1/0)
- mixer_volume_db (value = dB, -60 .. +5.6, 0 = unity), mixer_pan (-100..100), mixer_mute (1/0). target = a mixer track
  name or a channel name (= the track that channel plays through; "Master" for the master).
- effect_param: turn a control of an effect that is ALREADY loaded on that track (plugin = its exact name from fl_mix,
  param = the control's name from fl_mix, value = percent 0-100 of the control's range).
- eq_gain_db / eq_freq_hz: every mixer track has a built-in 3-band EQ Veloura controls directly (no plugin needed).
  param = "low" | "mid" | "high"; eq_gain_db value in dB (-18..18), eq_freq_hz value in Hz. Typical moves: cut low on
  hats/claps/melodies (low band to ~200-300 Hz, -12 dB) so the 808 owns the low end; small mid cuts (-2..-4 dB around
  300-500 Hz) for muddy pads; gentle high boosts (+2 dB ~8-10 kHz) for air on leads. Each channel gets its own insert
  automatically when you mix it.
Make moves that actually serve the request; small, deliberate amounts (e.g. +2 dB, pan hats 15-25%). Never invent plugins
or controls that fl_mix doesn't list: if an effect is missing, use a guide to tell the user what to insert. Leave
"plugin" and "param" as "" for non-effect moves. Use an empty mix list when no mix change is needed.

REPLY: 1-3 short sentences. Say what you made and anything the user must know; don't explain FL basics or describe
what Veloura will do automatically.

GUIDANCE (Mode B) only for things Veloura can't do itself (loading samples or plugins, inserting effects, arranging the
Playlist; Veloura CAN set presets on plugins listed in fl_sounds, mix levels/pans/mutes and loaded effect knobs, so use
"sound" and "mix" for those instead). Keep each guide SHORT: a 2-5 word title, at most 3 steps of at most 12 words
each, "problem" one short sentence, other text fields "". Give at most 2 guides per reply, only for what this request
needs. Give a full, detailed manual walkthrough ONLY when the user explicitly asks how to do something by hand. Give exact FL Studio menu names. Prefer stock plugins in every edition (Fruity Reeverb 2, Fruity Parametric EQ 2,
Fruity Limiter, Fruity Fast Dist, Fruity Delay 3); the user has a lower-cost edition, so don't assume Sytrus, Harmor or
Gross Beat. Never invent controls you aren't sure of. Veloura sets FL's tempo itself: never write a tempo guide.
Veloura can't hear the user's beat; critique from the notes and the reference analysis, and say so when it matters."""


PROVIDER_NAMES = {"chatgpt": "ChatGPT", "claude-code": "Claude", "gemini": "Gemini", "anthropic": "Claude API", "offline": "the offline composer"}


def _part_summary(name, entry):
    plan = entry.get("plan") or {}
    notes = plan.get("notes", [])
    brief = [[n["pitch"], n["start"], n["length"], n["velocity"]] for n in notes[:64]]
    return {"name": name, "role": entry.get("role"), "bars": plan.get("bars"), "key": plan.get("key"),
            "note_count": len(notes), "notes_pitch_start_length_velocity": brief}


def _house_reference(genre):
    if (genre or "trap") not in ("trap", "melodic trap", "melodic rap", "dark trap"):
        return None
    from . import blueprints
    return blueprints.ai_example()


def build_user_message(text, settings, parts, history, fl_context=None, request=None):
    from . import genres
    request = request or {}
    genre = request.get("genre") or genres.match(text) or settings.get("genre")
    context = {
        "request_mode": request.get("mode", "describe"),
        "genre": genre,
        "tempo_bpm": "auto" if settings.get("tempo_auto") else settings.get("tempo_bpm"),
        "key": "auto" if settings.get("key_auto") else settings.get("key"),
        "bars": "auto" if settings.get("bars_auto") else settings.get("bars"),
        "mood": settings.get("mood"),
        "feel": settings.get("feel") or {},
        "locked_parts": settings.get("locked_parts") or [],
        "fl_channels": [c.get("name") for c in (fl_context or {}).get("channels", [])] or "unknown (controller not connected)",
        "channel_instruments": (fl_context or {}).get("channel_instruments") or {},
        "fl_tempo": (fl_context or {}).get("tempo"),
        "fl_mix": (fl_context or {}).get("mix") or "unknown",
        "fl_sounds": (fl_context or {}).get("sounds") or {},
        "veloura_parts_in_fl": [_part_summary(n, e) for n, e in parts.items()],
        "project_facts": (fl_context or {}).get("facts") or {},
        "project_inferred": (fl_context or {}).get("inferred") or {},
        "user_taste": (fl_context or {}).get("taste") or {},
        "drum_kit_from_library": (fl_context or {}).get("kit") or {},
        "user_style_examples": (fl_context or {}).get("style_examples") or [],
        "house_reference": _house_reference(genre),
        "recent_conversation": history[-8:],
    }
    if request.get("reference"):
        ref = request["reference"]
        context["reference_name"] = ref.get("name")
        context["reference_analysis"] = ref.get("analysis")
        if request.get("mode") == "sample":
            context["sample_channel"] = request.get("sample_channel") or "Sample"
    # Leave out what's empty (no references, no taste yet, ...): a smaller request reaches the first word sooner.
    context = {k: v for k, v in context.items() if v not in (None, "", [], {})}
    return "%s\n\nPROJECT CONTEXT (JSON):\n%s\n\nUSER:\n%s" % (genres.playbook(genre), json.dumps(context), text)


def normalize(raw, provider, ctx=None):
    """Validate a provider response and run the production pipeline. Returns (response, problems)."""
    from . import producer
    ctx = ctx or {}
    problems = []
    if not isinstance(raw, dict):
        return {"reply": "The AI returned something Veloura could not read.", "parts": [], "guidance": [],
                "provider": provider}, ["response was not a JSON object"]
    reply = raw.get("reply") if isinstance(raw.get("reply"), str) else ""
    drafts = []
    for i, p in enumerate(raw.get("parts") or []):
        try:
            if not isinstance(p, dict):
                raise PlanError(["part is not an object"])
            name = str(p.get("name") or "Part %d" % (i + 1))[:40]
            role = p.get("role") if p.get("role") in ("melody", "bass", "chords", "drums", "other") else "other"
            plan = p.get("plan") if isinstance(p.get("plan"), dict) else {}
            generate = bool(p.get("generate"))
            fixes = []
            if plan.get("notes") or not generate:
                plan = validate_plan(plan, fixes)   # hand-written notes must be well formed before Veloura touches them
            drafts.append({"name": name, "role": role, "action": "revise" if p.get("action") == "revise" else "new",
                           "target_hint": str(p.get("target_hint") or "")[:300], "plan": dict(plan),
                           "repairs": list(p.get("repairs") or []) + fixes, "sound": str(p.get("sound") or "")[:120],
                           "purpose": p.get("purpose") if p.get("purpose") in PURPOSES else None, "generate": generate,
                           "register": p.get("register") if p.get("register") in ("low", "mid", "high") else None,
                           "instrument": p.get("instrument") if p.get("instrument") in INSTRUMENTS else None})
        except PlanError as e:
            reasons = e.problems if isinstance(e, PlanError) else [str(e)]
            short = "; ".join(reasons[:3]) + (" (and %d more)" % (len(reasons) - 3) if len(reasons) > 3 else "")
            problems.append("Part %r was discarded: %s" % (p.get("name") if isinstance(p, dict) else i, short))
    harmony = raw.get("harmony") if isinstance(raw.get("harmony"), dict) else None
    groove = raw.get("groove") if isinstance(raw.get("groove"), dict) and raw["groove"].get("profile") else None
    info = None
    if drafts and ctx.get("progress"):
        ctx["progress"](90, "Checking the music", "Testing every note against the chords and fitting the layers together")
    if drafts:
        parts, info, more = producer.finish(drafts, harmony, groove, settings=ctx.get("settings"), channels=ctx.get("channels"),
                                            genre=ctx.get("genre"), feel=ctx.get("feel"), seed=ctx.get("seed", 0),
                                            locked=ctx.get("locked"), prefer=ctx.get("prefer"),
                                            style_grooves=ctx.get("style_grooves"), channel_roles=ctx.get("channel_roles"))
        problems += more
    else:
        parts = []
    guidance = []
    for g in raw.get("guidance") or []:
        if isinstance(g, dict) and isinstance(g.get("title"), str) and isinstance(g.get("steps"), list):
            guidance.append({
                "title": g["title"][:200], "problem": str(g.get("problem", ""))[:600], "why": str(g.get("why", ""))[:600],
                "where": str(g.get("where", ""))[:300], "steps": [str(s)[:300] for s in g["steps"][:6]],
                "settings": [{"control": str(s.get("control", ""))[:80], "value": str(s.get("value", ""))[:120],
                              "range": str(s.get("range", ""))[:120]}
                             for s in (g.get("settings") or []) if isinstance(s, dict)][:10],
                "listen_for": str(g.get("listen_for", ""))[:600], "undo": str(g.get("undo", ""))[:300]})
    mix = []
    for m in raw.get("mix") or []:
        if isinstance(m, dict) and isinstance(m.get("kind"), str) and isinstance(m.get("target"), str):
            mix.append({"kind": m["kind"], "target": m["target"][:80], "value": m.get("value"),
                        "plugin": str(m.get("plugin") or "")[:80], "param": str(m.get("param") or "")[:80],
                        "why": str(m.get("why") or "")[:200]})
    return {"reply": reply, "parts": parts, "mix": mix[:40], "guidance": guidance, "provider": provider, "info": info}, problems


# ---------- credentials ----------

def _keychain_find(service, account):
    try:
        p = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                           capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _keychain_get(service):
    found = _keychain_find(service, KEYCHAIN_ACCOUNT)
    if found:
        return found
    old_service = service.replace("Veloura", "Cadence", 1)
    old = _keychain_find(old_service, OLD_KEYCHAIN_ACCOUNT)
    if old:   # a key saved under the old name: move it so nobody has to enter it again
        try:
            _keychain_set(service, old)
            subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", old_service, "-a", OLD_KEYCHAIN_ACCOUNT],
                           capture_output=True, timeout=10)
        except (ProviderError, OSError, subprocess.TimeoutExpired):
            pass   # keep using the old item
    return old


def _keychain_set(service, key):
    """Save a secret in the login Keychain. It goes through security's stdin (interactive mode), never the command
    line, so other programs can't read it from the process list."""
    if not key or any(c in key for c in '"\\\n\r ') or not key.isprintable():
        raise ValueError("That key contains characters an API key can't have.")
    cmd = 'add-generic-password -U -s "%s" -a "%s" -w "%s"\n' % (service, KEYCHAIN_ACCOUNT, key)
    p = subprocess.run(["/usr/bin/security", "-i"], input=cmd, capture_output=True, text=True, timeout=10)
    if p.returncode != 0 or "error" in (p.stderr or "").lower():
        raise RuntimeError("Could not save to the Keychain.")


def _keychain_delete(service):
    subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", service, "-a", KEYCHAIN_ACCOUNT],
                   capture_output=True, text=True, timeout=10)


def get_api_key():
    return os.environ.get("ANTHROPIC_API_KEY") or _keychain_get(KEYCHAIN_SERVICE)


def get_gemini_key():
    return os.environ.get("GEMINI_API_KEY") or _keychain_get(GEMINI_KEYCHAIN_SERVICE)


def set_api_key(key, provider="anthropic"):
    key = (key or "").strip()
    if provider == "gemini":
        if len(key) < 20 or " " in key:
            raise ValueError("That does not look like a Gemini API key (copy it from aistudio.google.com).")
        _keychain_set(GEMINI_KEYCHAIN_SERVICE, key)
        return
    if not key.startswith("sk-ant-") or len(key) < 20:
        raise ValueError("That does not look like an Anthropic API key (they start with 'sk-ant-').")
    _keychain_set(KEYCHAIN_SERVICE, key)


def delete_api_key(provider="anthropic"):
    _keychain_delete(GEMINI_KEYCHAIN_SERVICE if provider == "gemini" else KEYCHAIN_SERVICE)


# ---------- providers ----------

def find_claude_cli():
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    pattern = os.path.expanduser("~/Library/Application Support/Claude/claude-code/*/*/claude.app/Contents/MacOS/claude")
    found = sorted(glob.glob(pattern), key=os.path.getmtime)
    return found[-1] if found else None


_cc_auth = {"at": 0, "value": None}


def claude_code_logged_in(max_age=30):
    """True/False from `claude auth status`, cached briefly. None if the CLI is missing or the check fails."""
    if time.time() - _cc_auth["at"] < max_age:
        return _cc_auth["value"]
    cli = find_claude_cli()
    value = None
    if cli:
        try:
            p = subprocess.run([cli, "auth", "status"], capture_output=True, text=True, timeout=15)
            value = bool(json.loads(p.stdout).get("loggedIn"))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            value = None
    _cc_auth.update(at=time.time(), value=value)
    return value


def open_claude_login():
    """Open Terminal running the Claude Code sign-in (Claude subscription). The user finishes it in their browser."""
    cli = find_claude_cli()
    if not cli:
        raise ProviderError("Claude Code CLI not found.")
    cmd = "clear; echo 'Signing Veloura in to your Claude account. Your browser will open; when it says you are signed in, close this window.'; '%s' auth login --claudeai" % cli.replace("'", "'\\''")
    script = 'tell application "Terminal"\n activate\n do script "%s"\nend tell' % cmd.replace("\\", "\\\\").replace('"', '\\"')
    p = subprocess.run(["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise ProviderError("Could not open Terminal: %s" % p.stderr.strip())
    _cc_auth["at"] = 0


def node_command():
    if os.environ.get("VELOURA_NODE"):
        return [os.environ["VELOURA_NODE"]]
    node = shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)
    return [node] if node else None


def provider_status():
    node = node_command()
    sdk = os.path.isdir(os.path.join(ROOT, "app", "node_modules", "@anthropic-ai", "sdk"))
    out = {
        "offline": {"available": True, "detail": "Rule-based composer (not AI)."},
        "anthropic": {"available": bool(get_api_key()) and bool(node) and sdk,
                      "detail": ("API key found." if get_api_key() else "No API key: add one in Settings.")
                      + ("" if sdk else " SDK not installed (run npm install in app/).")},
        "chatgpt": chatgpt.status(),
        "gemini": {"available": bool(get_gemini_key()),
                   "detail": "Gemini key found." if get_gemini_key() else "No Gemini key: add one in Settings."},
    }
    if DEV_MODE:   # the developer's own copy only: the Claude Code CLI login isn't allowed in apps given to others
        out["claude-code"] = _claude_code_status()
    return out


def customer_providers():
    """The providers this build offers, in the order Veloura shows them (ChatGPT first)."""
    return ["chatgpt", "anthropic", "gemini", "offline"] + (["claude-code"] if DEV_MODE else [])


def _claude_code_status():
    if not find_claude_cli():
        return {"available": False, "logged_in": False, "detail": "Claude Code CLI not found."}
    li = claude_code_logged_in()
    if li:
        return {"available": True, "logged_in": True, "detail": "Signed in with your Claude account."}
    return {"available": False, "logged_in": False,
            "detail": "Not signed in. Use 'Connect Claude account' in Settings." if li is False else "Sign-in status unknown."}


class ProviderError(RuntimeError):
    pass


_running = set()        # subprocesses of in-flight AI requests (killed on cancel)
_running_lock = threading.Lock()


def cancel_running():
    """Stop any AI helper process that is still working (used by Cancel)."""
    with _running_lock:
        procs = list(_running)
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass


def _run(args, input_text=None, timeout=AI_TIMEOUT, **kw):
    """Like subprocess.run(capture_output=True, text=True), but registered so Cancel can kill it."""
    p = subprocess.Popen(args, stdin=subprocess.PIPE if input_text is not None else None, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, **kw)
    with _running_lock:
        _running.add(p)
    try:
        out, err = p.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        raise
    finally:
        with _running_lock:
            _running.discard(p)
    return subprocess.CompletedProcess(args, p.returncode, out, err)


def _call_anthropic(user_message, model):
    key = get_api_key()
    node = node_command()
    if not key:
        raise ProviderError("No Anthropic API key. Add one in Settings (it is stored in your macOS Keychain).")
    if not node:
        raise ProviderError("Node.js was not found, so the Anthropic SDK helper cannot run.")
    payload = {"model": model or DEFAULT_MODEL, "system": SYSTEM_PROMPT, "user": user_message, "schema": RESPONSE_SCHEMA}
    env = dict(os.environ, ANTHROPIC_API_KEY=key, ELECTRON_RUN_AS_NODE="1")
    try:
        p = _run(node + [NODE_HELPER], input_text=json.dumps(payload), timeout=AI_TIMEOUT, env=env,
                 cwd=os.path.dirname(NODE_HELPER))
    except subprocess.TimeoutExpired:
        raise ProviderError("The AI took longer than %d s and was stopped." % AI_TIMEOUT)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ProviderError("AI helper failed: %s" % (p.stderr.strip()[-400:] or "no output"))
    if not out.get("ok"):
        raise ProviderError(out.get("error") or "AI request failed")
    record_usage("anthropic", out.get("model") or payload["model"], out.get("usage"))
    return out["data"]


def _call_claude_code(user_message, model):
    cli = find_claude_cli()
    if not cli:
        raise ProviderError("Claude Code CLI not found.")
    with tempfile.TemporaryDirectory() as empty:
        args = [cli, "-p", user_message, "--output-format", "json", "--tools", "", "--system-prompt", SYSTEM_PROMPT,
                "--json-schema", json.dumps(RESPONSE_SCHEMA), "--no-session-persistence", "--setting-sources", "",
                "--strict-mcp-config"]
        if model:
            args += ["--model", model]
        try:
            p = _run(args, timeout=AI_TIMEOUT, cwd=empty)
        except subprocess.TimeoutExpired:
            raise ProviderError("Claude Code took longer than %d s and was stopped." % AI_TIMEOUT)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        raise ProviderError("Claude Code returned unreadable output: %s" % (p.stderr or p.stdout)[-300:])
    record_usage("claude-code", model, dict(out.get("usage") or {}, total_cost_usd=out.get("total_cost_usd")))
    if out.get("is_error"):
        msg = out.get("result") or "error"
        if "login" in str(msg).lower():
            msg += " (open Terminal, run the Claude Code CLI and use /login, or use another provider)"
        raise ProviderError("Claude Code: %s" % msg)
    data = out.get("structured_output")
    if data is None:
        text = out.get("result", "")
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            raise ProviderError("Claude Code did not return JSON.")
    return data


def _call_chatgpt(user_message, model):
    try:
        text, usage, used_model = chatgpt.generate(SYSTEM_PROMPT, user_message, RESPONSE_SCHEMA, model=model or None)
    except chatgpt.ChatGPTError as e:
        raise ProviderError(str(e))
    record_usage("chatgpt", used_model or model, usage)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            raise ProviderError("ChatGPT did not return valid JSON.")


def _gemini_schema(node):
    """Gemini accepts a subset of JSON Schema; drop keywords it may reject."""
    if isinstance(node, dict):
        return {k: _gemini_schema(v) for k, v in node.items() if k != "additionalProperties"}
    if isinstance(node, list):
        return [_gemini_schema(v) for v in node]
    return node


def _gemini_once(key, model, user_message, schema=True):
    """One generateContent request. Returns parsed JSON, or raises urllib errors / socket timeouts."""
    import urllib.request
    cfg = {"responseMimeType": "application/json"}
    if schema:
        cfg["responseJsonSchema"] = _gemini_schema(RESPONSE_SCHEMA)
    body = {"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "generationConfig": cfg}
    req = urllib.request.Request(GEMINI_URL % model, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=GEMINI_ATTEMPT_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _call_gemini(user_message, model, sleep=time.sleep):
    import socket
    import urllib.error
    key = get_gemini_key()
    if not key:
        raise ProviderError("No Gemini API key. Add one in Settings (it is stored in your macOS Keychain).")
    model = model or DEFAULT_GEMINI_MODEL
    # Try the chosen model twice (Google's 503 "high demand" is usually brief), then the other free model.
    plan = [model, model] + [m for m in GEMINI_FALLBACK_MODELS if m != model]
    started = time.time()
    last = "unknown error"
    schema = True
    out = None
    timed_out = set()
    for attempt, m in enumerate(plan):
        if m in timed_out:
            continue  # a model that just timed out won't do better on an immediate retry
        if time.time() - started > GEMINI_TOTAL_BUDGET - GEMINI_ATTEMPT_TIMEOUT and attempt:
            break  # not enough time left for another full attempt
        if attempt:
            sleep(2)
        try:
            out = _gemini_once(key, m, user_message, schema)
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 403) or "API_KEY" in detail or "API key" in detail:
                raise ProviderError("Gemini rejected the API key. Check it in Settings.")
            if e.code == 400 and schema:
                schema = False  # schema not accepted: ask for JSON by instruction only (Veloura validates anyway)
                last = "schema rejected"
                continue
            if e.code == 404:
                last = "model %r not found" % m
                continue
            if e.code == 429:
                last = "free-tier limit reached (wait a minute, or until tomorrow for the daily limit)"
                continue
            if e.code >= 500:
                last = "Google's servers are busy (error %d)" % e.code
                if attempt == 0:
                    continue
                plan_models_left = [x for x in plan[attempt + 1:] if x != m]
                if plan_models_left:
                    timed_out.add(m)  # busy twice: move on to the next model
                continue
            raise ProviderError("Gemini error %d: %s" % (e.code, detail))
        except (socket.timeout, TimeoutError):
            last = "no answer within %d s" % GEMINI_ATTEMPT_TIMEOUT
            timed_out.add(m)
        except urllib.error.URLError as e:
            raise ProviderError("Could not reach Gemini: %s" % e.reason)
    if out is None:
        raise ProviderError("Gemini couldn't answer right now: %s. Try again in a minute, or switch provider in Settings."
                            % last)
    record_usage("gemini", out.get("modelVersion") or model, out.get("usageMetadata"))
    if not out.get("candidates"):
        reason = (out.get("promptFeedback") or {}).get("blockReason", "no answer")
        raise ProviderError("Gemini returned no answer (%s)." % reason)
    cand = out["candidates"][0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
    if cand.get("finishReason") == "MAX_TOKENS":
        raise ProviderError("Gemini's answer was cut off. Ask for fewer parts or bars.")
    try:
        return json.loads(text)
    except ValueError:
        start_i, end_i = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[start_i:end_i + 1])
        except ValueError:
            raise ProviderError("Gemini did not return valid JSON.")

def _offline_settings(settings, request):
    """The rule-based composer understands tempo/key/bars: take them from the reference or genre when on auto."""
    from . import genres
    s = dict(settings)
    request = request or {}
    genre = request.get("genre") or settings.get("genre")
    d = genres.defaults(genre)
    ref = (request.get("reference") or {}).get("analysis") or {}
    if settings.get("tempo_auto"):
        s["tempo_bpm"] = int(round(ref.get("tempo_bpm") or d["tempo_bpm"]))
    if settings.get("key_auto"):
        s["key"] = ref.get("key") or d["key"]
    if settings.get("bars_auto"):
        s["bars"] = d["bars"]
    s["_mode"] = request.get("mode", "describe")
    s["_sample_channel"] = request.get("sample_channel") or "Sample"
    s["_sample_bars"] = ref.get("length_bars")
    return s


def respond(provider, text, settings, parts, history, model=None, seed=None, fl_context=None, request=None, progress=None):
    """Returns (response, problems). Raises ProviderError for provider failures."""
    from . import genres
    import random as _random
    request = request or {}
    seed = _random.randrange(1 << 30) if seed is None else seed
    ctx = {"settings": settings, "channels": (fl_context or {}).get("channels") or [], "feel": settings.get("feel"),
           "genre": request.get("genre") or genres.match(text) or settings.get("genre"), "seed": seed,
           "locked": settings.get("locked_parts") or [], "prefer": (fl_context or {}).get("prefer") or [],
           "channel_roles": (fl_context or {}).get("channel_instruments") or {},
           "progress": progress, "style_grooves": (fl_context or {}).get("style_grooves")}
    if provider == "offline":
        os_ = _offline_settings(settings, request)
        os_["_channels"] = ctx["channels"]
        raw = composer.respond(text, os_, parts, seed=seed)
        info = raw.get("info")
        resp, problems = normalize(dict(raw, harmony={"key": (info or {}).get("key"), "chords": (info or {}).get("harmony")},
                                        groove=None), "offline", dict(ctx, genre=ctx["genre"]))
        if info and info.get("groove"):
            resp["info"]["groove"] = info["groove"]
        return resp, problems + list(raw.get("problems") or [])
    user_message = build_user_message(text, settings, parts, history, fl_context, request)

    def call_one(prov, msg):
        if prov == "anthropic":
            return _call_anthropic(msg, model if prov == provider else None)
        if prov == "claude-code":
            if not DEV_MODE:
                raise ProviderError("That AI option isn't available in this version. Pick one in Settings.")
            return _call_claude_code(msg, model if prov == provider else None)
        if prov == "gemini":
            return _call_gemini(msg, model if prov == provider else None)
        if prov == "chatgpt":
            return _call_chatgpt(msg, model if prov == provider else None)
        raise ProviderError("Unknown provider %r" % prov)

    def call(msg):
        """Call only the AI the user chose. Prompts are never sent to another AI company behind the user's back:
        if it fails, the error is shown and the user can switch provider in Settings."""
        return call_one(provider, msg)

    if settings.get("quality", "fast") != "best":
        return normalize(call(user_message), provider, ctx)
    # Best of two (opt-in, doubles AI cost): two drafts at once (one asked for a bolder take); Veloura keeps the one
    # that scores better musically.
    from . import producer
    angles = [user_message, user_message + "\n\nPRODUCER NOTE: give this a more distinctive, memorable take than the obvious "
                                           "one (a stronger hook, a smarter layer), while staying authentic to the style."]
    results, errors = [None, None], [None, None]

    def run(i):
        try:
            results[i] = call(angles[i])
        except Exception as e:   # noqa: BLE001 - reported below
            errors[i] = e
    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(AI_TIMEOUT + 30)
    drafts = []
    for i, raw in enumerate(results):
        if raw is None:
            continue
        resp, probs = normalize(raw, provider, dict(ctx, seed=ctx["seed"] + i, progress=None if i else ctx.get("progress")))
        drafts.append((producer.quality_score(resp["parts"], resp.get("info"), probs), i, resp, probs))
    if not drafts:
        raise errors[0] if isinstance(errors[0], ProviderError) else ProviderError(str(errors[0] or errors[1]))
    drafts.sort(key=lambda d: -d[0])
    score, i, resp, probs = drafts[0]
    if resp.get("info") is not None:
        resp["info"]["candidates"] = [{"take": "bolder" if j else "first", "score": sc} for sc, j, _, _ in sorted(drafts, key=lambda d: d[1])]
        resp["info"]["picked"] = "bolder" if i else "first"
    return resp, probs
