"""Music intelligence tests: harmony, validation/repair, layering, feel controls, genre grooves."""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import drums, grooves, producer, theory  # noqa: E402
from veloura.melody_plan import validate_plan  # noqa: E402

FM = theory.parse_key("F minor")


def n(p, s, l=0.5, v=100):
    return {"pitch": p, "start": s, "length": l, "velocity": v}


def part(name, role, notes, purpose=None, bars=4):
    return {"name": name, "role": role, "purpose": purpose, "plan": {"schema": "cadence.melody/1", "title": name, "tempo_bpm": 140,
                                                                     "time_signature": [4, 4], "key": "F minor", "bars": bars,
                                                                     "target": name, "notes": notes}}


class TheoryTests(unittest.TestCase):
    def test_keys_and_chords(self):
        self.assertEqual(theory.parse_key("C# minor"), (1, "minor"))
        self.assertEqual(theory.parse_key("Bb major"), (10, "major"))
        self.assertEqual(theory.parse_chord("Fm7")["pcs"], [0, 3, 5, 8])
        self.assertEqual(theory.parse_chord("Ebmaj7/G")["bass"], 7)
        self.assertEqual(theory.degree_chord(FM, 0)["symbol"], "Fm")
        self.assertEqual(theory.degree_chord(FM, 5)["symbol"], "Db")

    def test_every_genre_progression_and_lead_is_in_key(self):
        for genre in theory.GENRE_PROGRESSIONS:
            for seed in range(6):
                h = theory.genre_harmony(FM, 8, genre, seed=seed)
                self.assertAlmostEqual(sum(s["length"] for s in h), 32)
                lead = theory.compose_lead(FM, h, 8, genre=genre, seed=seed)
                self.assertEqual(theory.in_key_ratio(lead, FM, h), 1.0, (genre, seed))
                validate_plan(part("L", "melody", lead, bars=8)["plan"])

    def test_lead_is_motif_based_and_resolves(self):
        h = theory.genre_harmony(FM, 8, "trap", seed=1)
        lead = theory.compose_lead(FM, h, 8, feel={"variation": 20}, genre="trap", seed=3)
        self.assertGreater(theory.repetition_score(lead, 8), 0.35)       # ideas come back
        last = max(lead, key=lambda x: x["start"])
        self.assertIn(last["pitch"] % 12, theory.chord_at(h, last["start"])["pcs"])   # ends on a chord tone
        varied = theory.compose_lead(FM, h, 8, feel={"variation": 95}, genre="trap", seed=3)
        self.assertLess(theory.repetition_score(varied, 8), theory.repetition_score(lead, 8) + 1e-9)

    def test_feel_changes_the_notes(self):
        h = theory.genre_harmony(FM, 4, "trap", seed=2)
        sparse = theory.compose_lead(FM, h, 4, feel={"fullness": 5, "complexity": 5}, seed=1)
        full = theory.compose_lead(FM, h, 4, feel={"fullness": 95, "complexity": 95}, seed=1)
        self.assertLess(len(sparse), len(full))
        smooth = theory.compose_lead(FM, h, 4, feel={"angular": 0}, seed=4)
        angular = theory.compose_lead(FM, h, 4, feel={"angular": 100}, seed=4)
        self.assertLessEqual(theory.max_leap(smooth), theory.max_leap(angular) + 2)
        airy = theory.compose_lead(FM, h, 4, feel={"atmosphere": 95}, seed=4)
        self.assertGreater(sum(x["length"] for x in airy) / len(airy), sum(x["length"] for x in full) / len(full))


class RefineTests(unittest.TestCase):
    def test_wrong_notes_fixed_but_passing_tones_kept(self):
        h = theory.harmony_from_symbols([{"bar": 1, "beat": 1, "symbol": "Fm"}], 1)
        lead = [n(65, 0, 1), n(66, 1, 1.5),                 # Gb held for 1.5 beats over Fm: a mistake
                n(67, 2.5, 0.25), n(68, 2.75, 0.25), n(69, 3.0, 0.25)]
        p = part("Lead", "melody", lead, "lead", bars=1)
        lead2 = [n(67, 0, 0.5), n(66, 0.75, 0.25), n(65, 1.0, 1)]   # E-flat? no: Gb passing between G and F
        q = part("Lead2", "melody", lead2, "lead", bars=1)
        theory.refine([p], FM, h, 1)
        pitches = [x["pitch"] for x in p["plan"]["notes"]]
        self.assertNotIn(66, pitches)
        theory.refine([q], FM, h, 1, feel={"angular": 100})
        self.assertIn(66, [x["pitch"] for x in q["plan"]["notes"]])   # short off-beat step between scale tones survives

    def test_bass_supports_chords(self):
        h = theory.harmony_from_symbols([{"bar": 1, "beat": 1, "symbol": "Fm"}, {"bar": 2, "beat": 1, "symbol": "Db"}], 2)
        bass = part("808", "bass", [n(39, 0, 3), n(36, 4, 3)])    # Eb under Fm and C under Db
        theory.refine([bass], FM, h, 2)
        self.assertEqual([x["pitch"] % 12 for x in bass["plan"]["notes"]], [5, 1])

    def test_clashing_layers_resolved_and_registers_separated(self):
        h = theory.harmony_from_symbols([{"bar": 1, "beat": 1, "symbol": "Fm"}], 1)
        lead = part("Lead", "melody", [n(72, 0, 2), n(68, 2, 2)], "lead", bars=1)
        pad = part("Pad", "chords", [n(73, 0, 2), n(67, 2, 2)], "pad", bars=1)   # Db/G rub against C/Ab
        theory.refine([lead, pad], FM, h, 1)
        self.assertEqual(theory.clashes({"a": lead["plan"]["notes"], "b": pad["plan"]["notes"]}, h), [])
        self.assertEqual([x["pitch"] for x in lead["plan"]["notes"]], [72, 68])   # the lead is never the one moved
        a = part("A", "melody", [n(70 + (i % 3), i * 0.5, 0.5) for i in range(8)], "lead", bars=1)
        b = part("B", "melody", [n(69 + (i % 3), i * 0.5, 0.5) for i in range(8)], "counter", bars=1)
        out = theory.refine([a, b], FM, h, 1)
        self.assertTrue(any("octave" in r for r in out["repairs"]), out["repairs"])
        self.assertLess(theory.register_overlap(a["plan"]["notes"], b["plan"]["notes"]), 0.6)


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.h = theory.genre_harmony(FM, 4, "trap", seed=5)
        self.lead = theory.compose_lead(FM, self.h, 4, genre="trap", seed=5)

    def test_generated_layers_fit(self):
        for kind in ("pad", "chords", "counter", "harmony", "double", "arp", "bell", "bass"):
            notes = theory.generate_layer(kind, FM, self.h, 4, lead=self.lead, kick_steps=[0, 7, 10, 16, 23, 26, 32, 48])
            self.assertTrue(notes, kind)
            self.assertGreaterEqual(theory.in_key_ratio(notes, FM, self.h), 0.9, kind)
            validate_plan(part(kind, "melody", notes)["plan"])

    def test_counter_answers_in_the_gaps(self):
        sparse_lead = [n(72, b * 4, 1.5) for b in range(4)]
        ctr = theory.generate_layer("counter", FM, self.h, 4, lead=sparse_lead)
        lead_on = {round(x["start"] * 4) for x in sparse_lead}
        self.assertFalse(lead_on & {round(x["start"] * 4) for x in ctr})

    def test_808_locks_to_the_kick(self):
        kicks = [0, 7, 10, 16, 23, 26, 32, 39, 42, 48, 55, 58]
        bass = theory.gen_bass(self.h, 4, kick_steps=kicks, style="locked")
        starts = {round(x["start"] * 4) for x in bass}
        chord_starts = {round(s["start"] * 4) for s in self.h}
        self.assertTrue(starts <= set(kicks) | chord_starts)

    def test_voice_leading_moves_little(self):
        a = theory.voice_chord(theory.parse_chord("Fm")["pcs"], 62)
        b = theory.voice_chord(theory.parse_chord("Db")["pcs"], 62, prev=a)
        self.assertLessEqual(sum(min(abs(x - y) for y in a) for x in b), 6)


class GrooveTests(unittest.TestCase):
    def test_profiles_are_meaningfully_different(self):
        sigs = {name: grooves.generate(name, 4, seed=0)["signature"] for name in grooves.PROFILES}
        names = list(sigs)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                self.assertGreater(grooves.distance(sigs[a], sigs[b]), 0.1, (a, b))

    def test_genre_conventions(self):
        trap = grooves.generate("trap", 4, seed=1)["lanes"]
        boom = grooves.generate("boom bap", 4, seed=1)["lanes"]
        self.assertIn(2.0, [x["start"] for x in trap["Snare"]])            # half-time snare on beat 3
        self.assertTrue({1.0, 3.0} <= {x["start"] for x in boom["Snare"]})  # backbeat on 2 and 4
        self.assertGreater(grooves.generate("boom bap", 4, seed=1)["swing"], 0.3)
        drill = grooves.generate("drill", 8, seed=3)["lanes"]["Hi-hat"]
        self.assertTrue(any(abs(x["start"] * 6 - round(x["start"] * 6)) < 1e-4 and abs(x["start"] * 4 - round(x["start"] * 4)) > 1e-4
                            for x in drill))                              # triplet bursts

    def test_phrases_develop(self):
        lanes = grooves.generate("trap", 8, seed=2)["lanes"]
        bars = [tuple(round(x["start"] - b * 4, 3) for x in lanes["Kick"] if b * 4 <= x["start"] < b * 4 + 4) for b in range(8)]
        self.assertGreater(len(set(bars)), 1)                              # not one bar copied 8 times
        self.assertFalse([x for x in lanes["Kick"] if x["start"] >= 31])   # drop before the loop comes back

    def test_lab_actions(self):
        lanes = grooves.generate("plugg", 4, seed=1)["lanes"]
        spaced = grooves.transform(lanes, "space", "plugg", 4)
        self.assertLess(sum(map(len, spaced.values())), sum(map(len, lanes.values())))
        bounced = grooves.transform(lanes, "bounce", "plugg", 4)
        self.assertGreater(len(bounced["Kick"]), len(lanes["Kick"]))
        newg = grooves.transform(lanes, "new", "plugg", 4, seed=4)
        self.assertNotEqual(newg["Kick"], lanes["Kick"])

    def test_swung_and_rolled_lanes_need_the_piano_roll(self):
        plan = part("Hat", "drums", [n(60, 0, 0.25), n(60, 0.25 + 0.02, 0.2)], bars=1)["plan"]
        self.assertIsNotNone(drums.plan_to_steps(plan)[1])   # step shift isn't reliable in FL 2024
        roll = part("Hat", "drums", [n(60, 3 + i * 0.125, 0.125) for i in range(4)], bars=1)["plan"]
        self.assertIsNotNone(drums.plan_to_steps(roll)[1])

    def test_deswing_for_fl_swing(self):
        hats = grooves.apply_swing([n(60, s / 4, 0.25) for s in range(8)], 0.3)
        straight, amount = drums.deswing(part("Hat", "drums", hats, bars=1)["plan"])
        self.assertAlmostEqual(amount, 0.3, places=2)
        self.assertIsNone(drums.plan_to_steps(straight)[1])

    def test_drums_dont_pile_up(self):
        lanes = {"Kick": [n(60, 0, 0.25), n(60, 2.0, 0.25), n(60, 2.75, 0.25)],
                 "Snare": [n(60, 2.0, 0.25), n(60, 3.75, 0.25, 60)],
                 "Clap": [n(60, 2.0, 0.25), n(60, 3.75, 0.25)],
                 "Hi-hat": [n(60, s / 2, 0.25) for s in range(8)],
                 "Open hat": [n(60, 1.5, 0.5)],
                 "Perc": [n(60, 0, 0.25), n(60, 1.25, 0.25), n(60, 2.0, 0.25)]}
        out, repairs = grooves.deconflict(lanes, "trap", 1)
        self.assertEqual([x["start"] for x in out["Kick"]], [0, 2.75])         # kick off the backbeat snare
        self.assertEqual([x["start"] for x in out["Clap"]], [2.0])             # stacks on the backbeat, not on the ghost
        self.assertNotIn(1.5, [x["start"] for x in out["Hi-hat"]])             # open hat replaces the closed hat
        self.assertEqual([x["start"] for x in out["Perc"]], [1.25])           # perc fills the gaps
        jerk, _ = grooves.deconflict({"Kick": [n(60, 1.0, 0.25)], "Clap": [n(60, 1.0, 0.25)]}, "jerk", 1)
        self.assertEqual(len(jerk["Kick"]), 1)                                 # jerk keeps the kick with the clap

    def test_808_moves_by_small_steps(self):
        line = [n(41, 0, 1), n(53, 1, 1), n(41, 2, 1), n(53, 3, 1), n(48, 4, 2)]
        out = theory.tidy_808([dict(x) for x in line], 8)
        jumps = [abs(out[i + 1]["pitch"] - out[i]["pitch"]) for i in range(len(out) - 1)]
        self.assertLessEqual(max(jumps), 7)
        bass = theory.gen_bass(theory.genre_harmony(FM, 8, "trap", seed=1), 8, kick_steps=list(range(0, 128, 6)), style="locked", seed=2)
        self.assertLessEqual(max(abs(bass[i + 1]["pitch"] - bass[i]["pitch"]) for i in range(len(bass) - 1)), 12)
        self.assertTrue(all(x["pitch"] >= 34 for x in bass))

    def test_everything_on_the_grid_and_no_jammed_notes(self):
        messy = [n(60, 0.03, 0.5), n(64, 0.98, 0.05), n(62, 1.1, 0.24)]
        out = theory.tidy_notes([dict(x) for x in messy], "melody")
        self.assertTrue(all(abs(x["start"] * 4 - round(x["start"] * 4)) < 1e-6 for x in out))
        self.assertNotIn(64, [x["pitch"] for x in out])                  # the sliver is gone
        chords = [n(p, 1.0, 1.0) for p in (60, 64, 67)] + [n(72, 0.875, 0.125), n(74, 0.8, 0.1)]
        out = theory.tidy_notes([dict(x) for x in chords], "chord")
        self.assertEqual(sorted(x["pitch"] for x in out), [60, 64, 67])  # grace notes in front of the chord removed
        roll = [n(60, 3 + i / 8, 0.125) for i in range(8)]
        self.assertEqual(len(theory.tidy_notes([dict(x) for x in roll], "roll")), 8)   # hat rolls keep their 1/32s

    def test_fit_to_channels(self):
        lanes = grooves.generate("trap", 2, seed=0)["lanes"]
        chans = [{"name": "808 Kick"}, {"name": "808 Snare"}, {"name": "808 HiHat"}]
        fitted = grooves.fit_to_channels(lanes, chans, drums.match_channel)
        self.assertEqual(set(fitted), {"808 Kick", "808 Snare", "808 HiHat"})   # clap merged into snare, no stray lanes


class VelocityTests(unittest.TestCase):
    def test_even_dynamics_unless_there_is_a_reason(self):
        import random
        rnd = random.Random(3)
        hats = [n(60, s / 4, 0.25, rnd.randint(20, 127)) for s in range(12)] + [n(60, 3 + i / 8, 0.125, rnd.randint(20, 127)) for i in range(8)]
        theory.shape_velocity(hats, "drums", "hat", "trap")
        main = [h for h in hats if h["length"] == 0.25]
        self.assertEqual(len({h["velocity"] for h in main}), 1)                  # trap hats: one even level
        roll = sorted([h for h in hats if h["length"] == 0.125], key=lambda h: h["start"])
        self.assertEqual([h["velocity"] for h in roll], sorted(h["velocity"] for h in roll))   # rolls ramp up
        boom = [n(60, s / 4, 0.25, 100) for s in range(8)]
        theory.shape_velocity(boom, "drums", "hat", "boom bap")
        self.assertGreater(len({h["velocity"] for h in boom}), 1)               # humanized styles accent the beat
        kicks = [n(60, s, 0.25, v) for s, v in ((0, 127), (1.75, 40), (2.5, 127))]
        theory.shape_velocity(kicks, "drums", "kick")
        self.assertEqual(len({k["velocity"] for k in kicks}), 1)
        lead = [n(70, i * 0.5, 0.5, v) for i, v in enumerate([127, 90, 120, 95])]
        theory.shape_velocity(lead, "melody")
        self.assertEqual(len({x["velocity"] for x in lead}), 1)


class ProducerTests(unittest.TestCase):
    def test_generate_requests_and_locks(self):
        parts = [part("Lead", "melody", [], "lead"), part("Pad", "chords", [], "pad"), part("808", "bass", [], "bass"),
                 part("Kick", "drums", [], "drums"), part("Snare", "drums", [n(60, 1.0, 0.25)], "drums")]
        for p in parts:
            p["generate"] = p["name"] != "Snare"
        out, info, problems = producer.finish(parts, {"key": "F minor", "chords": [{"bar": 1, "beat": 1, "symbol": "Fm"},
                                                                                    {"bar": 3, "beat": 1, "symbol": "Db"}]},
                                              {"profile": "trap"}, settings={"bars": 4}, genre="trap", seed=3)
        names = {p["name"]: p for p in out}
        self.assertEqual(problems, [])
        self.assertTrue({"Lead", "Pad", "808", "Kick", "Snare", "Hi-hat"} <= set(names))
        self.assertEqual(len(names["Snare"]["plan"]["notes"]), 1)            # hand-written lane kept as written
        self.assertEqual([c["symbol"] for c in info["harmony"]], ["Fm", "Db"])
        self.assertEqual(info["report"]["clashes"], 0)
        self.assertTrue(all(v >= 0.9 for v in info["report"]["in_key"].values()))
        kick = {round(x["start"] * 4) for x in names["Kick"]["plan"]["notes"]}
        bass = {round(x["start"] * 4) for x in names["808"]["plan"]["notes"]}
        self.assertTrue(bass & kick)


if __name__ == "__main__":
    unittest.main()


class EnsembleTests(unittest.TestCase):
    def setUp(self):
        from veloura import ensemble
        self.e = ensemble
        self.h = theory.genre_harmony(FM, 4, "trap", seed=2)

    def test_chord_instruments_play_full_chords_with_voice_leading(self):
        for inst in ("piano", "keys", "rhodes", "pad", "strings", "choir", "supersaw"):
            notes = self.e.write_for(inst, "chords", FM, self.h, 4, genre="r&b")
            self.assertGreaterEqual(self.e.polyphony(notes), 3, inst)
            self.assertGreaterEqual(theory.in_key_ratio(notes, FM, self.h), 0.95, inst)
        piano = self.e.write_piano(self.h, 4, "trap")
        first = sorted(x["pitch"] for x in piano if x["start"] == 0)
        self.assertLess(first[0], 52)                    # left hand root low
        self.assertGreaterEqual(len([p for p in first if p >= 55]), 3)    # right hand voicing on top

    def test_guitar_is_picked_not_blocked(self):
        g = self.e.write_guitar(self.h, 4, "r&b")
        self.assertLess(self.e.polyphony(g), 1.5)

    def test_thin_ai_chords_are_thickened(self):
        thin = part("Keys", "chords", [n(72, b * 4, 4, 90) for b in range(4)], "chords")
        thin["instrument"] = "keys"
        thin["generate"] = False
        out, info, _ = producer.finish([thin], {"key": "F minor", "chords": [{"bar": 1, "beat": 1, "symbol": "Fm"}]},
                                       None, settings={"bars": 4}, genre="plugg")
        self.assertGreaterEqual(self.e.polyphony(out[0]["plan"]["notes"]), 3)

    def test_every_style_gets_a_real_arrangement(self):
        for g in ("trap", "plugg", "melodic plugg", "rage", "drill", "r&b"):
            out, info, problems = producer.finish(
                [dict(part(n, "chords" if j in ("chords", "pad") else "bass" if j == "bass" else "melody", [], j), instrument=i, generate=True)
                 for i, j in self.e.RECIPES[g] for n in [i + j]], {"key": "F minor"}, None, settings={"bars": 4}, genre=g, seed=1)
            melodic = [p for p in out if p["role"] != "bass"]
            self.assertGreaterEqual(len(melodic), 3, g)
            self.assertTrue(any(self.e.polyphony(p["plan"]["notes"]) >= 3 for p in melodic), g)
            self.assertEqual(info["report"]["clashes"], 0, g)


class BlueprintTests(unittest.TestCase):
    def test_yo_blueprint_reproduces_the_reference(self):
        import json, os
        from veloura import blueprints
        ref = json.load(open(os.path.join(ROOT, "veloura", "references", "yo.json")))
        parts, h = blueprints.yo_beat(FM, 8, seed=0)
        self.assertEqual([c["symbol"] for c in h], ref["chords"])
        first = lambda notes: sorted(n["pitch"] for n in notes if n["start"] == 0)
        self.assertEqual(first(parts["Keys"][3]), first(ref["layers"]["keys (FL Keys)"]))
        self.assertEqual([n["pitch"] for n in parts["Arp Lead"][3] if n["start"] < 2],
                         [n["pitch"] for n in ref["layers"]["arp lead (ZENOLOGY #3)"] if n["start"] < 2])
        self.assertEqual([(n["pitch"], n["start"]) for n in parts["Bass"][3] if n["start"] < 8],
                         [(n["pitch"], n["start"]) for n in ref["layers"]["bass (FLEX Acoustic Bass)"] if n["start"] < 8])
        self.assertEqual(sorted(round(n["start"] * 4) for n in parts["Kick"][3] if n["start"] < 16),
                         [s for s in ref["drums_steps_bar1to4"]["Kick"]])
        self.assertEqual([round(n["start"] * 4) % 16 for n in parts["808"][3] if n["start"] < 4], [0, 6, 10])

    def test_yo_style_in_every_key(self):
        from veloura import blueprints
        for k in ("A minor", "C# minor", "G minor", "E major"):
            key = theory.parse_key(k)
            parts, h = blueprints.yo_beat(key, 8, seed=2)
            for name, (role, inst, purpose, notes) in parts.items():
                if role != "drums":
                    self.assertEqual(theory.in_key_ratio(notes, key, h), 1.0, (k, name))

    def test_trap_requests_use_the_house_blueprint(self):
        from veloura import ai
        r, _ = ai.respond("offline", "make me a trap beat", {"tempo_bpm": 158, "key": "F minor", "bars": 8, "genre": "trap"}, {}, [], seed=0)
        names = {p["name"] for p in r["parts"]}
        self.assertTrue({"Keys", "Pad", "Melody", "Pluck", "808"} <= names or len(names) >= 8, names)
        self.assertEqual(r["info"]["groove"]["label"], "Veloura house groove (Yo)")
        self.assertEqual(len(r["info"]["harmony"]), 4)
