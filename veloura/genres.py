"""Genre playbooks: the production knowledge Veloura gives the AI for the style being made.

Only the relevant playbook is sent with a request (keeps prompts small and focused).
Each playbook is written the way a senior producer would brief a session: tempo and
feel, idiomatic keys, drums, 808/bass, harmony and melody, sound palette, arrangement,
and what makes a beat sound dated or lazy in that style. Tempo ranges are in FL's BPM
(trap-family styles are counted at full tempo, felt in half-time).
"""

GENRES = {
    "trap": {
        "label": "Trap",
        "tempo": (130, 160), "default_tempo": 158, "bars": 8,   # 158 = the house reference (Yo)
        "keys": ["C# minor", "F minor", "G# minor", "D# minor", "A minor", "B minor"],
        "brief": """Modern trap (2020s). Felt in half-time: clap/snare on beat 3 of every bar (step 9), kick on 1 and placed
syncopated around it (common anchors: steps 1, 8, 11, 15; never a four-on-the-floor kick). Hi-hats carry the groove:
an 1/8 or 1/16 base with velocity accents (on-beats ~100, off-beats 65-80) and rolls at phrase ends: 1/16 triplets,
1/32 bursts, occasionally pitched. One open hat or perc per bar at most. 808: long notes that follow or answer the kick,
root on the downbeat, octave jumps and fifths for movement, leave gaps before the snare; the 808 changes with the
chord. Harmony: natural or harmonic minor; progressions like i-VI-III-VII, i-iv-VI-v, i-VI with a harmonic-minor V
for tension. Melody: a 1-2 bar motif (bells, plucks, piano, flute, choir) repeated with a variation in bar 4 and 8;
mostly mid register (C4-C6), sparse enough to leave a pocket for vocals; a counter-melody or octave layer in the second
half. Arrangement: change something every 4 bars (hat pattern, 808 rhythm, a dropout before bar 5 or 9).
Dated or lazy: 2016-style constant triplet hats, the same 808 note on every kick, melodies that only climb a scale.""",
    },
    "plugg": {
        "label": "Plugg / PluggnB",
        "tempo": (140, 165), "default_tempo": 150, "bars": 8,
        "keys": ["E major", "C# minor", "A major", "F# minor", "D major", "B major"],
        "brief": """Plugg and pluggnB. Bouncy, airy and melodic; brighter than trap. Drums: simple and punchy, clap on beat 3,
kick patterns with bounce (steps 1, 4, 7, 11 style syncopation), sparse 1/8 hats with a little swing and the signature
plugg snare roll (1/16 snare pickups into the next bar). 808: smooth, sustained, sliding, often melodic and following
the chord roots. Harmony: lush and R&B-leaning (maj7, min9, add9; ii-V-I in major, IVmaj7-iii7-vi7, i-VII-VI in minor);
major keys are common. Melody: square/sine 'video-game' leads, glassy synths, airy pads, sometimes vocal chops; short
catchy motifs with call and response; high register sparkle (C5-C7). Arrangement: 8-bar loops, a melody variation in
bars 5-8, drum dropouts for breathing room. Dated or lazy: dark trap melodies, aggressive 808 distortion, busy hats.""",
    },
    "rage": {
        "label": "Rage",
        "tempo": (150, 175), "default_tempo": 160, "bars": 8,
        "keys": ["F# minor", "C minor", "D minor", "G minor", "A minor", "E minor"],
        "brief": """Rage (Playboi Carti / Ken Carson / Trippie Redd era sound). High energy, bright and aggressive. Lead: detuned
supersaw or distorted synth playing a driving 1-bar riff in 1/8 or 1/16 notes, often an arpeggio over minor/pentatonic
notes, sometimes with an octave jump hook; big and simple. Drums: hard clap/snare on 3, punchy kicks that lock with the
808, busy 1/16 hats with frequent rolls and stutters; occasional crash/impact on bar 1 and 5. 808: distorted, punchy,
short-to-medium notes that hit with the kick, quick octave and fifth jumps, a fill every 4th bar. Harmony: minor, often
just i-VI or i-iv drones under the riff. Arrangement: drop the drums for 1 bar before bar 5 or 9, then slam back.
Dated or lazy: soft piano melodies, slow chords, sparse hats.""",
    },
    "jerk": {
        "label": "Jerk",
        "tempo": (150, 175), "default_tempo": 160, "bars": 8,
        "keys": ["C major", "A minor", "G major", "E minor", "D major", "B minor"],
        "brief": """Jerk (2020s underground: bouncy, chaotic, playful). Drums are the star: heavily syncopated kicks off the beat,
claps on 2 and 4 or on 3 with extra off-beat claps, choppy percs and rimshots, 1/16 hat movement with accents and
open-hat lifts; small rhythmic surprises every 2 bars. 808: short, choppy, bouncing between root and octave, rhythmic
rather than sustained. Melody: bright, catchy, slightly off-kilter leads (bells, plucks, ringtone-like synths, pitched
vocal chops), short motifs repeated with rhythmic displacement; mid-high register. Harmony: simple, often major or
modal; two chords is plenty. Arrangement: constant motion; switch the drum pattern every 4 bars.
Dated or lazy: straight trap drums, long sustained 808s, slow emotional melodies.""",
    },
    "drill": {
        "label": "Drill (UK / NY)",
        "tempo": (138, 146), "default_tempo": 142, "bars": 8,
        "keys": ["E minor", "F minor", "C# minor", "G minor", "B minor", "D minor"],
        "brief": """UK / NY drill. Drums: snare on beat 3 plus syncopated off-beat snares (steps 4, 12, 14 style ghost snares),
kicks sparse and off-grid-feeling; hats in a distinctive skippy pattern with triplet bursts (1/16 triplets) and gaps,
not a constant stream. 808: sliding/gliding is essential: long notes that slide up or down to the next root, rhythmic
patterns that syncopate against the kick; NY drill bounces more, UK is darker. Harmony: dark minor (harmonic minor and
phrygian colour), slow chord changes (one chord per 1-2 bars). Melody: eerie piano, strings, choirs or flutes; simple
minor motifs with chromatic passing notes; low-mid register. Arrangement: 8-bar phrases, hat pattern variations, short
drum dropouts. Dated or lazy: trap half-time hats, happy major melodies.""",
    },
    "melodic trap": {
        "label": "Melodic trap",
        "tempo": (130, 150), "default_tempo": 140, "bars": 8,
        "keys": ["A minor", "C# minor", "F# minor", "E minor", "D minor", "B minor"],
        "brief": """Melodic / emotional trap. Piano, guitar or soft synth carries an expressive chord progression (i-VI-III-VII,
vi-IV-I-V in relative major, i-iv-VII-III) with a top-line melody that sings; use suspensions and 7ths sparingly.
Drums: clap on 3, gentle syncopated kick, 1/8 hats with tasteful rolls; less aggressive than trap. 808: follows chord
roots with sustained notes and occasional slides. Melody register C4-C6; leave room for a vocal. Arrangement: intro with
chords only, drums enter at bar 5. Dated or lazy: one chord the whole loop, no melodic movement.""",
    },
    "cloud rap": {
        "label": "Cloud rap",
        "tempo": (120, 145), "default_tempo": 130, "bars": 8,
        "keys": ["D major", "F major", "Bb major", "G minor", "E minor", "A major"],
        "brief": """Cloud rap. Dreamy, hazy, spacious. Long pad chords (maj7, add9, min9) with slow changes; a soft, sparse bell or
synth melody with lots of space; airy textures. Drums: minimal: soft kick, clap on 3, light 1/8 hats, no busy rolls.
808: soft and long, mostly roots. Arrangement: slow evolution, melody variations rather than drum changes.
Dated or lazy: hard aggressive drums, dense busy melodies.""",
    },
    "boom bap": {
        "label": "Boom bap",
        "tempo": (84, 96), "default_tempo": 90, "bars": 4,
        "keys": ["D minor", "A minor", "G minor", "C minor", "F major", "Eb major"],
        "brief": """Boom bap. Swung 1/16 feel (about 55-62% swing). Drums: kick on 1 and the 'and' of 2 (steps 1, 7/8, 11),
snare on 2 and 4 (steps 5 and 13), 1/8 hats with ghost notes; kick and snare carry the head-nod. Bass: warm, short to
medium notes following the sample/chords. Harmony: jazzy/soulful: min7, min9, maj7, dominant 7ths; ii-V movement.
Melody: sample-style chord stabs, Rhodes, horns or a filtered loop feel; 2-4 bar phrases. Arrangement: 4-bar loop with
small drum variations and a fill at bar 4. Dated or lazy: rigid unswung drums, trap hats.""",
    },
    "r&b": {
        "label": "R&B",
        "tempo": (60, 80), "default_tempo": 70, "bars": 8,
        "keys": ["Eb major", "Ab major", "Db major", "F minor", "Bb minor", "C minor"],
        "brief": """Contemporary R&B. Lush extended chords (maj9, min11, dom13, slash chords) with smooth voice leading; neo-soul
movement (IVmaj7-iii7-vi7-ii7-V). Drums: laid-back, slightly swung; kick on 1 with syncopated pickups, snare/clap on 2
and 4 (or 3 if half-time at double tempo), shakers/percs for movement, hats with ghost notes. Bass: melodic, sustained,
gliding between roots. Melody: sparse counter-lines (keys, guitar) that answer the vocal. Dated or lazy: triads only,
stiff quantised drums.""",
    },
    "detroit": {
        "label": "Detroit / Flint",
        "tempo": (95, 110), "default_tempo": 100, "bars": 4,
        "keys": ["F minor", "C minor", "G minor", "Bb minor", "Eb minor", "D minor"],
        "brief": """Detroit / Flint rap. Bouncy, off-kilter piano loops: short, repetitive, slightly dissonant minor riffs in the
low-mid register, often with chromatic notes. Drums: punchy kick patterns with lots of syncopation, claps on 2 and 4,
1/16 hats with accents. Bass: short punchy 808s locked to the kick. Arrangement: a 2-4 bar loop with drum variation.
Dated or lazy: long pads, slow trap feel.""",
    },
    "pop": {
        "label": "Pop / crossover",
        "tempo": (95, 128), "default_tempo": 110, "bars": 8,
        "keys": ["C major", "G major", "D major", "A minor", "E minor", "F major"],
        "brief": """Pop / crossover hip-hop. Strong, simple, memorable: I-V-vi-IV or vi-IV-I-V progressions, a clear hook melody
with repetition and a lift in the second half. Drums: kick on 1 and 3 with pickups, snare/clap on 2 and 4, 1/8 hats.
Bass follows the roots. Arrangement: obvious 4-bar phrases, build into bar 8. Dated or lazy: no hook, random notes.""",
    },
}

GENRES["dark trap"] = {
    "label": "Dark trap",
    "tempo": (130, 160), "default_tempo": 140, "bars": 8,
    "keys": ["F minor", "C# minor", "E minor", "G minor", "B minor", "D minor"],
    "brief": """Dark underground trap. Menacing and sparse: a low, eerie motif (detuned bells, dark piano, choirs, horror
strings) built on minor or phrygian colour (b2) and tritone tension; long gaps. Drums: hard but spacious: kick and clap
with lots of air, sparse 8th hats with occasional triplet stutters, rimshot ghosts; dropouts are part of the groove.
808: long, distorted, sliding feel, often holding one note under changing melody. Harmony: one or two chords, i-bII or
a drone. Dated or lazy: bright major melodies, busy constant hats.""",
}
GENRES["melodic plugg"] = dict(GENRES["plugg"], label="Melodic plugg", default_tempo=148, brief=GENRES["plugg"]["brief"] + """
Melodic plugg leans even more on lush chords (maj7/9 pads, bells and glassy plucks layered an octave apart), softer drums
with fewer hits, and longer, sweeter melodies with call and response between two sounds.""")
GENRES["melodic rap"] = dict(GENRES["melodic trap"], label="Melodic rap")
GENRES["ambient"] = {
    "label": "Ambient / atmospheric",
    "tempo": (60, 140), "default_tempo": 120, "bars": 8,
    "keys": ["D major", "F major", "A minor", "E minor", "C major", "G minor"],
    "brief": """Ambient / atmospheric hip-hop. Space is the instrument: wide sustained pads (maj7, add9, sus2), slow chord
changes, a sparse bell or piano motif with long notes and lots of rests, textures. Drums: minimal and soft: kick, a gentle
clap or rim on 3, light hats with swing; no rolls. 808 or sub: soft, long roots. Arrangement: slow evolution; layers enter
one at a time. Dated or lazy: busy drums, dense melodies, hard 808s.""",
}

GENERAL = """Senior producer standards (apply to every beat):
- Be original. Draw on the style's language, never copy a known song's melody.
- Parts must interlock: 808/bass with the kick, a backbeat snare/clap, hats with velocity accents and movement.
- Use velocity on purpose: accents vs ghost notes (hats 55-105, ghost snares 40-70, main hits 100-120).
- Build in variation: something must change at bar 4 and bar 8 (fill, roll, dropout, melody answer, 808 rhythm).
- Melodies are motif-based (a 1-2 bar idea, repeated, varied, answered), not scales or random notes. Stay in key.
- Choose the key, tempo and bar count that suit the style unless the user fixed them. Use a full loop (4 or 8 bars).
- Leave space: not every instrument plays all the time; the top line leaves a pocket for vocals."""


MODERN_RAP = """MODERN RAP PRODUCTION (2020s), how working producers actually build loops:
LAYERING WITH REAL INSTRUMENTS
- Build the melody from 2-3 sounds with distinct jobs: a main lead (bell, pluck, piano, flute, guitar, synth), a
  supporting layer (pad, choir, strings or a softer keys an octave below that holds the chords), and optionally a
  sparkle/ear-candy layer (music box, glock, high arp) that only plays every other bar or in bars 5-8.
- Octave-stacking is the most common "big" sound: the same motif on two sounds an octave apart, the upper one quieter.
- Keep each layer in its own register: 808 (F1-C3), chords/pad (C3-C5), lead (C4-C6), sparkle (C6+).
- Real-instrument logic: piano chords are voiced with 3-4 notes in one hand-span (no huge spreads); guitar parts use
  open-position chord shapes and arpeggiated plucks; strings hold long notes and move by step; flutes and bells play
  single-note lines; choirs sustain roots and fifths.
FLOW AND STRUCTURE
- A loop is 8 bars: a 2-bar idea stated (bars 1-2), repeated (3-4), developed with a different ending (5-6), and a
  turnaround (7-8) that pulls back to bar 1. Something new enters or drops out at bar 5.
- Leave the vocal pocket: the lead is busiest in gaps between vocal phrases; avoid constant 16th-note melodies.
- Tension/release: hold the most tension (V chord, b2, suspended note, drum fill) in bar 8 so the loop restart feels good.
808 RULES
- Trap/rap 808 lines move by SMALL steps: root, 4th, 5th, maybe a 2nd. No octave leaps as a habit (F2 to F3 back and
  forth is wrong); at most one short octave accent per 8 bars.
- The 808 plays the chord root on the downbeat of each chord change, hits WITH the kick (or right after it), and
  leaves space before the snare. Octave jumps and fifths add bounce; slides (portamento) go between notes a 4th-5th apart.
- One sustained 808 note per kick hit in trap/drill; short, bouncy notes in jerk, rage and Detroit.
GRID: every note starts on a real grid line (1/16 notes, or 8th-note triplets in triplet passages); only hi-hat rolls
  use 1/32 or 16th triplets. No tiny grace notes jammed in front of chords, no slivers: lengths are whole 16ths.
DRUM OVERLAPS: snare and clap may stack on the backbeat (a layer), but don't double ghost snares with claps; an open
  hat replaces the closed hat on that step; percussion fills the gaps instead of landing on kick/snare hits; keep the
  kick off the snare's backbeat (except jerk/Detroit/boom bap idioms); the 808 should hit with the kick.
DYNAMICS ARE DIGITAL: trap, plugg, rage, drill, jerk and other rap made in a DAW do NOT imitate human players. Keep
  every part at one even velocity (kicks ~110, snares/claps ~112, hats ~96, 808 ~110, melodies ~100, chords ~80) and
  perfectly on the grid. Only hi-hat rolls ramp up (70->100) and deliberate ghost snares are soft (~60). Human
  velocity variation is only for music played by real musicians (live-band R&B, sample-based boom bap).
STYLE REFERENCES (describe the sound, never copy a song): plugg (bright square leads, airy pads, bouncy kick,
  plugg snare rolls); melodic plugg/pluggnB (maj7/9 chords, sweet two-sound call-and-response); rage (detuned supersaw
  riff, distorted 808, relentless 16th hats); jerk (playful chopped leads, off-beat kicks, claps on 2 and 4, rimshots);
  NY/UK drill (sliding 808s, skippy triplet hats, syncopated snares, dark piano/strings); dark/underground trap
  (sparse menace, b2 colour, distorted 808, space); Detroit/Flint (off-kilter piano riffs, punchy short 808s);
  melodic rap (expressive piano/guitar progressions, singable top line, room for vocals)."""


def match(text):
    """Find the genre a request is about (or None)."""
    t = (text or "").lower()
    aliases = [("melodic plugg", "melodic plugg"), ("pluggnb", "melodic plugg"), ("plugg", "plugg"),
               ("dark trap", "dark trap"), ("underground", "dark trap"), ("melodic rap", "melodic rap"),
               ("ambient", "ambient"), ("atmospheric", "ambient"), ("rage", "rage"), ("jerk", "jerk"), ("drill", "drill"),
               ("melodic trap", "melodic trap"), ("emotional", "melodic trap"), ("cloud", "cloud rap"),
               ("boom bap", "boom bap"), ("boombap", "boom bap"), ("r&b", "r&b"), ("rnb", "r&b"), ("detroit", "detroit"),
               ("flint", "detroit"), ("pop", "pop"), ("trap", "trap")]
    for a, g in aliases:
        if a in t:
            return g
    return None


def playbook(genre):
    g = GENRES.get(genre)
    if not g:
        return GENERAL + "\n\n" + MODERN_RAP
    return "GENRE PLAYBOOK: %s (typical tempo %d-%d BPM; idiomatic keys: %s; usual loop: %d bars)\n%s\n\n%s\n\n%s" % (
        g["label"], g["tempo"][0], g["tempo"][1], ", ".join(g["keys"]), g["bars"], g["brief"], GENERAL, MODERN_RAP)


def defaults(genre):
    """Auto choices for the UI: tempo, key and bars that suit the genre."""
    g = GENRES.get(genre) or GENRES["trap"]
    return {"tempo_bpm": g["default_tempo"], "key": g["keys"][0], "bars": g["bars"], "keys": g["keys"],
            "tempo_range": list(g["tempo"])}
