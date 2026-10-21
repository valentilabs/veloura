"""Beat Workspace engine features against FAKE FL: improve, variations, Groove Lab, versions, arrangement, progress.
Simulations, not FL verification."""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_fl_midi import FakeFL  # noqa: E402
from test_controller import FakeTrigger, make_link  # noqa: E402
from veloura import bridge_protocol as bp, grooves, insight, theory  # noqa: E402
from veloura.engine import Engine  # noqa: E402


def plan(notes, bars=4, key="F minor"):
    return {"schema": "cadence.melody/1", "title": "x", "tempo_bpm": 140, "time_signature": [4, 4], "key": key, "bars": bars,
            "target": "", "notes": notes}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_patch = mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs"))
        self.log_patch.start()
        self.fl = FakeFL()
        self.engine = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=FakeTrigger(),
                             controller=make_link(self.fl))

    def tearDown(self):
        self.log_patch.stop()
        self.tmp.cleanup()

    def write_drums(self, genre="trap", bars=4):
        lanes = grooves.generate(genre, bars, seed=1)["lanes"]
        parts = [{"name": n, "role": "drums", "plan": plan([x for x in v if abs(x["start"] * 4 - round(x["start"] * 4)) < 1e-6], bars)}
                 for n, v in lanes.items() if n in ("Kick", "Snare", "Clap")]
        out = self.engine._make_proposal(parts, "test", "drums", "drums")
        for i in range(len(parts)):
            self.assertTrue(self.engine.apply(out["proposal"]["id"], i)["ok"])

    def test_groove_lab_proposes_and_applies_and_versions_restore(self):
        self.write_drums()
        before = sorted(s for (c, p, s) in self.fl.grid if c == 0)
        out = self.engine.groove_action("space")
        prop = out["proposal"]
        self.assertTrue(prop["parts"])
        idx = next(i for i, p in enumerate(prop["parts"]) if p["name"] == "Kick")
        self.assertTrue(self.engine.apply(prop["id"], idx)["ok"])
        after = sorted(s for (c, p, s) in self.fl.grid if c == 0)
        self.assertLess(len(after), len(before))
        versions = self.engine.state["parts"]["Kick"]["versions"]
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[1]["op"], "Groove: More space")
        self.assertEqual(versions[1]["parent"], versions[0]["id"])
        res = self.engine.restore_version("Kick", versions[0]["id"])     # branch back to v1, nothing lost
        self.assertTrue(res["ok"], res)
        self.assertEqual(sorted(s for (c, p, s) in self.fl.grid if c == 0), before)
        self.assertEqual(len(self.engine.state["parts"]["Kick"]["versions"]), 3)

    def test_keep_this_feel_locks_drums(self):
        self.write_drums()
        self.engine.groove_action("keep")
        self.assertIn("Kick", self.engine.state["settings"]["locked_parts"])
        self.engine.groove_action("unlock")
        self.assertNotIn("Kick", self.engine.state["settings"]["locked_parts"])

    def test_variations_are_distinct_and_in_key(self):
        key = theory.parse_key("F minor")
        h = theory.genre_harmony(key, 4, "trap", seed=2)
        lead = theory.compose_lead(key, h, 4, seed=2)
        self.engine.state["parts"]["Lead"] = {"role": "melody", "purpose": "lead", "channel_name": "Pluck", "plan": plan(lead)}
        out = self.engine.variations("Lead")
        opts = out["proposal"]["parts"]
        self.assertEqual(len(opts), 3)
        self.assertEqual(len({tuple((n["pitch"], n["start"]) for n in o["plan"]["notes"]) for o in opts}), 3)
        for o in opts:
            self.assertGreaterEqual(theory.in_key_ratio(o["plan"]["notes"], key), 0.95)
            self.assertEqual(o["action"], "revise")
            self.assertTrue(o["option_label"] and o["description"])

    def test_improve_finds_real_problems_with_fixes(self):
        self.engine.state["parts"]["808"] = {"role": "bass", "channel_name": "Pluck", "plan": plan([{"pitch": 39, "start": b * 4, "length": 3, "velocity": 110}
                                                                           for b in range(4)])}       # Eb under everything
        self.engine.state["parts"]["Pad"] = {"role": "chords", "purpose": "pad", "channel_name": "Hat", "plan": plan(
            [{"pitch": p, "start": b * 4, "length": 4, "velocity": 70} for b in range(4) for p in (65, 68, 72)])}   # Fm
        out = self.engine.improve()
        prop = out["proposal"]
        ids = [f["id"] for f in prop["findings"]]
        self.assertIn("bass-harmony-808", ids)
        fix = next(p for p in prop["parts"] if p["finding"] == "bass-harmony-808")
        self.assertTrue(all(n["pitch"] % 12 == 5 for n in fix["plan"]["notes"]))       # roots of Fm
        self.assertTrue(all("structural" in f["kind"] for f in prop["findings"]))

    def test_insight_on_empty_and_missing_layers(self):
        self.assertEqual(insight.analyze({})[0]["id"], "empty")
        key = theory.parse_key("F minor")
        h = theory.genre_harmony(key, 4, "trap", seed=2)
        f = insight.analyze({"Lead": {"role": "melody", "purpose": "lead", "plan": plan(theory.compose_lead(key, h, 4, seed=1))}})
        self.assertIn("add-808", [x["id"] for x in f])

    def test_beat_is_scoped_to_the_open_project(self):
        self.engine.state["parts"]["Old song lead"] = {"role": "melody", "channel_name": "Not In This Project", "plan": plan([])}
        self.engine.state["parts"]["Here"] = {"role": "melody", "channel_name": "Pluck", "plan": plan([])}
        self.assertEqual(set(self.engine.current_parts()), {"Here"})

    def test_each_project_has_its_own_chat_and_start_fresh(self):
        current = {"name": "Song A"}
        self.engine.trigger.fl_project_name = lambda: current["name"]
        self.engine.check_project(force=True)
        self.engine.state["messages"].append({"id": "1", "role": "user", "text": "song A idea"})
        self.engine.state["parts"]["Lead"] = {"role": "melody", "plan": plan([])}
        self.engine.save()
        current["name"] = "Song B"
        self.engine.check_project(force=True)
        self.assertEqual(self.engine.project, "Song B")
        self.assertEqual(self.engine.state["messages"], [])
        self.assertEqual(self.engine.state["parts"], {})
        current["name"] = "Song A"
        self.engine.check_project(force=True)
        self.assertEqual(self.engine.state["messages"][0]["text"], "song A idea")
        self.engine.start_fresh()
        self.assertEqual(self.engine.state["messages"], [])
        self.assertIn("Lead", self.engine.state["parts"])          # parts in FL stay tracked so they can still be undone
        names = {p["name"] for p in self.engine.list_projects()["projects"]}
        self.assertTrue({"Song A", "Song B"} <= names)

    def test_routing_is_explicit_remembered_and_never_guesses(self):
        lead = {"name": "Counter", "role": "melody", "plan": plan([{"pitch": 72, "start": 0, "length": 1, "velocity": 90}])}
        hat = {"name": "Hi-hat", "role": "drums", "plan": plan([{"pitch": 60, "start": s / 4, "length": 0.25, "velocity": 80} for s in range(0, 16, 2)])}
        out = self.engine._make_proposal([lead, hat], "test", "t", "t")
        pid = out["proposal"]["id"]
        d0 = out["proposal"]["parts"][0]["destination"]
        self.assertTrue(d0.get("missing") and d0["fix"])                 # no instrument called Counter: held back with a fix
        res = self.engine.apply(pid, 0)
        self.assertEqual(res["code"], "no_target")                       # never written into whatever Piano Roll is open
        self.assertEqual(out["proposal"]["parts"][1]["destination"]["channel"], "Hat")
        self.engine.set_route(pid, 1, 3)                                 # user says: hats go on channel 3 ("Snare") here
        self.assertTrue(self.engine.apply(pid, 1)["ok"])
        self.assertTrue(any(c == 3 for (c, p, s) in self.fl.grid))
        # remembered for this project: the next hat part routes the same way
        again = self.engine._make_proposal([{k: v for k, v in hat.items() if k not in ("route", "destination", "status", "result")}],
                                           "test", "t", "t")["proposal"]["parts"][0]["destination"]
        self.assertEqual((again["channel"], again["how"]), ("Snare", "remembered"))

    def test_reapply_moves_a_part_out_of_the_wrong_channel(self):
        hat = {"name": "Hi-hat", "role": "drums", "plan": plan([{"pitch": 60, "start": s / 4, "length": 0.25, "velocity": 80} for s in (0, 4, 8)], bars=1)}
        out = self.engine._make_proposal([hat], "test", "t", "t")
        pid = out["proposal"]["id"]
        self.engine.set_route(pid, 0, 1, remember=False)                 # oops: went to Clap
        self.assertTrue(self.engine.apply(pid, 0)["ok"])
        self.assertEqual(sorted(s for (c, p, s) in self.fl.grid if c == 1), [0, 4, 8])
        res = self.engine.reapply(pid, 0, channel_index=2)                      # move it to Hat
        self.assertTrue(res["ok"], res)
        self.assertEqual(sorted(s for (c, p, s) in self.fl.grid if c == 1), [])      # Clap back as it was
        self.assertEqual(sorted(s for (c, p, s) in self.fl.grid if c == 2), [0, 4, 8])
        self.assertTrue(self.engine.reapply(pid, 0)["ok"])               # plain re-apply works too

    def test_undo_everything_veloura_did(self):
        self.fl.grid[(0, 1, 4)] = 90                                   # the user's own kick
        self.write_drums()
        self.engine.set_fl_tempo(150)
        self.engine.rack_mute(1, "Clap", True)
        plan_ = self.engine.undo_all_plan()
        kinds = [i["kind"] for i in plan_]
        self.assertIn("part", kinds)
        self.assertIn("tempo", kinds)
        res = self.engine.undo_all()
        self.assertTrue(res["ok"], res)
        self.assertEqual(sorted(s for (c, p, s) in self.fl.grid if c in (0, 1, 3)), [4])   # only the user's step is left
        self.assertAlmostEqual(self.fl.tempo, 140.0)
        self.assertEqual(self.engine.undo_all_plan(), [])

    def test_mixer_setup_and_builtin_eq_moves(self):
        from veloura import mix
        self.fl.route.update({0: 0, 2: 0})                         # Kick and Hat play straight into Master
        res = self.engine.mixer_setup()
        self.assertEqual({r["channel"] for r in res["routed"]}, {0, 2})
        self.assertNotIn(0, [self.fl.route.get(i, i + 1) for i in range(5)])
        self.assertEqual(self.fl.track_names[self.fl.route[0]], "Kick")
        state = self.engine.controller.request("mix_state")
        moves = [{"kind": "eq_gain_db", "target": "Hat", "value": -12, "plugin": "", "param": "low", "why": "room for the 808"},
                 {"kind": "eq_freq_hz", "target": "Hat", "value": 300, "plugin": "", "param": "low", "why": ""}]
        changes, preview, problems = mix.resolve(moves, state)
        self.assertEqual(problems, [])
        send, undo = mix.split_undo(changes)
        out = self.engine.controller.request("set_mix", {"changes": send})["results"]
        self.assertAlmostEqual(out[0]["now"]["gain_db"], -12, delta=0.2)
        self.assertAlmostEqual(out[1]["now"]["freq_hz"], 300, delta=3)
        self.engine.controller.request("set_mix", {"changes": undo})
        t = self.fl.route[2]
        self.assertAlmostEqual(self.fl.eq[(t, 0)][0], 0.5)
        plan_ = self.engine.undo_all_plan()
        self.assertIn("routing", [i["kind"] for i in plan_])
        self.engine.undo_all()
        self.assertEqual((self.fl.route[0], self.fl.route[2]), (0, 0))

    def test_waiting_parts_update_when_a_channel_is_added(self):
        lead = {"name": "Counter", "role": "melody", "plan": plan([{"pitch": 72, "start": 0, "length": 1, "velocity": 90}])}
        prop = self.engine._make_proposal([lead], "test", "t", "t")["proposal"]
        self.assertTrue(prop["parts"][0]["destination"].get("missing"))
        self.fl.names.append("Counter")                               # the user adds the channel in FL
        self.engine._ctl_cache = (0, None)
        self.engine.status()
        self.assertEqual(prop["parts"][0]["destination"]["channel"], "Counter")

    def test_mix_moves_find_the_real_channels(self):
        state = self.engine.controller.request("mix_state")
        prop = {"parts": [], "mix": {"moves": [{"kind": "channel_pan", "target": "808 HiHat", "value": 20}]}}
        m = self.engine._mix_name_map(prop, state)
        self.assertEqual(m["808 hihat"], "Hat")

    def test_saving_untitled_keeps_its_chat(self):
        current = {"name": "Untitled"}
        self.engine.trigger.fl_project_name = lambda: current["name"]
        self.engine.check_project(force=True)
        self.engine.state["messages"].append({"id": "1", "role": "user", "text": "idea"})
        current["name"] = "My Song"
        self.engine.check_project(force=True)
        self.assertEqual(self.engine.project, "My Song")
        self.assertEqual(self.engine.state["messages"][0]["text"], "idea")

    def test_new_project_and_delete(self):
        tpl = os.path.join(self.tmp.name, "Empty.flp")
        with open(tpl, "wb") as f:
            f.write(b"FLhd")
        with mock.patch.object(Engine, "FL_PROJECTS", os.path.join(self.tmp.name, "Projects")), \
                mock.patch("subprocess.run") as run:
            res = self.engine.new_fl_project("My Song", template=tpl)
            self.assertTrue(os.path.isfile(res["path"]))
            self.assertIn("com.image-line.flstudio", run.call_args[0][0])      # works with FL 2024 and 2026
            with self.assertRaises(Exception):
                self.engine.new_fl_project("My Song", template=tpl)          # never overwrites
        current = {"name": "A"}
        self.engine.trigger.fl_project_name = lambda: current["name"]
        self.engine.check_project(force=True)
        self.engine.save()
        current["name"] = "B"
        self.engine.check_project(force=True)
        self.assertTrue(self.engine.delete_project("A")["ok"])
        self.assertNotIn("A", {p["name"] for p in self.engine.list_projects()["projects"]})
        with self.assertRaises(Exception):
            self.engine.delete_project("B")                                  # the open project can't be deleted

    def test_channel_roles_from_the_prompt_route_parts_and_protect_sounds(self):
        from veloura import ensemble
        self.fl.names[:] = ["Kick", "Clap", "Hat", "ZENOLOGY", "ZENOLOGY #2"]
        self.engine._ctl_cache = (0, None)
        roles = ensemble.parse_channel_roles("Zenology is a piano sound, Zenology 2 is a string", self.engine.controller_status()["channels"])
        self.assertEqual(roles, {"ZENOLOGY": "piano", "ZENOLOGY #2": "strings"})
        piano = {"name": "Piano chords", "role": "chords", "instrument": "piano", "_roles": roles, "plan": plan([{"pitch": 60, "start": 0, "length": 1, "velocity": 90}])}
        strings = {"name": "Strings", "role": "chords", "instrument": "strings", "_roles": roles, "plan": plan([{"pitch": 60, "start": 0, "length": 1, "velocity": 90}])}
        prop = self.engine._make_proposal([piano, strings], "test", "t", "t")["proposal"]
        self.assertEqual(prop["parts"][0]["destination"]["channel"], "ZENOLOGY")
        self.assertEqual(prop["parts"][1]["destination"]["channel"], "ZENOLOGY #2")
        self.fl.presets[3] = {"plugin": "ZENOLOGY", "names": ["My Fave Keys", "Init Tone", "Concert Piano"], "cur": 0}
        self.assertIsNone(self.engine._auto_sound({"index": 3, "name": "ZENOLOGY", "type": "plugin"}, "piano"))   # user's sound kept

    def test_use_flex_for_me(self):
        self.fl.names[:] = ["Kick", "Clap", "Hat", "FLEX"]
        self.fl.presets[3] = {"plugin": "FLEX", "names": ["Init", "Dark Pad", "Glass Bell", "Big Lead"], "cur": 0}
        self.engine._ctl_cache = (0, None)
        self.fl.modules["channels"].getChannelType = lambda i, *a: 2 if i == 3 else 0
        bell = {"name": "Bell", "role": "melody", "instrument": "bell", "plan": plan([{"pitch": 84, "start": 0, "length": 1, "velocity": 90}])}
        prop = self.engine._make_proposal([bell], "test", "t", "t")["proposal"]
        self.assertTrue(prop["parts"][0]["destination"].get("missing"))
        res = self.engine.auto_instrument(prop["id"], 0)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.fl.presets[3]["names"][self.fl.presets[3]["cur"]], "Glass Bell")
        self.assertEqual(prop["parts"][0]["destination"]["channel"], "FLEX")
        self.assertNotIn("channel_roles", self.engine.state)                # nothing is made permanent

    def test_roles_are_detected_from_the_loaded_sound(self):
        self.fl.names[:] = ["Kick", "Clap", "Hat", "ZENOLOGY"]
        self.fl.presets[3] = {"plugin": "ZENOLOGY", "names": ["Concert Grand Piano", "Warm Pad"], "cur": 0}
        self.fl.modules["channels"].getChannelType = lambda i, *a: 2 if i == 3 else 0
        self.engine._ctl_cache = (0, None)
        chans = self.engine.controller_status()["channels"]
        self.assertEqual(self.engine.detect_channel_roles(chans), {"ZENOLOGY": "piano"})
        self.fl.presets[3]["cur"] = 1                                        # next week it's a pad
        self.assertEqual(self.engine.detect_channel_roles(chans), {"ZENOLOGY": "pad"})

    def test_fl2026_swing_keeps_swung_hats_in_the_step_sequencer(self):
        from veloura import grooves
        self.fl.swing = 0.0
        self.fl.modules["channels"].getSwing = lambda: self.fl.swing
        self.fl.modules["channels"].setSwing = lambda v: setattr(self.fl, "swing", v)
        self.fl.modules["patterns"].setPatternLength = lambda pat, n: setattr(self.fl, "pattern_len", n)
        self.engine.controller.close() if hasattr(self.engine.controller, "close") else None
        self.engine.controller = make_link(self.fl)
        hats = grooves.apply_swing([{"pitch": 60, "start": s / 4, "length": 0.25, "velocity": 96} for s in range(32)], 0.3)
        part = {"name": "Hat", "role": "drums", "plan": plan(hats, bars=2)}
        out = self.engine._make_proposal([part], "test", "t", "t")["proposal"]
        self.assertEqual(out["parts"][0]["destination"]["kind"], "pianoroll")   # destination preview is version-agnostic
        res = self.engine.apply(out["id"], 0)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["mode"], "steps")                                   # FL 2026: swing via FL, steps kept
        self.assertAlmostEqual(self.fl.swing, 0.3, delta=0.06)               # 1/96-beat grid rounding
        self.assertIn("swing", [c["type"] for c in self.engine.state["changes"]])

    def test_untitled_project_detected_on_any_fl_version(self):
        import re as _re
        for t in ("FL Studio 2026", "FL Studio 2024", "FL Studio"):
            self.assertTrue(_re.match(r"^FL Studio( \d{4})?$", t))

    def test_808_samples_play_at_their_natural_pitch(self):
        self.engine.library.data["samples"]["x"] = {"id": "x", "name": "Dark 808 (F)", "path": "/nope.wav", "category": "808", "kit": "k", "folder": "f"}
        line = plan([{"pitch": 41, "start": 0, "length": 2, "velocity": 110}, {"pitch": 44, "start": 2, "length": 2, "velocity": 110}])  # F2, Ab2
        moved, note = self.engine._pitch_808(line, {"index": 0, "name": "808 - Dark 808 (F)", "type": "sampler"})
        self.assertEqual([n["pitch"] for n in moved["notes"]], [60, 63])     # F plays on C5 (the sample's F), Ab 3 up
        self.assertIn("F", note)
        unknown, _ = self.engine._pitch_808(line, {"index": 0, "name": "Mystery 808", "type": "sampler"})
        self.assertTrue(all(54 <= n["pitch"] <= 70 for n in unknown["notes"]))   # near C5, never 3 octaves down

    def test_listen_check_finds_clipping_and_silence(self):
        meters = {"n": 0}

        def fake(op, params=None, timeout=None):
            if op == "meters":
                return {"playing": False, "tracks": [{"track": 0, "name": "Master", "peak": 1.3}, {"track": 1, "name": "Insert 1", "peak": 0.5}], "feeds": {}}
            if op == "mix_state":
                return {"channels": [{"name": "Kick", "mixer_track": 1}, {"name": "Clap", "mixer_track": 2}], "tracks": []}
            return {"playing": False}
        self.engine.controller.request = fake
        self.engine.state["parts"]["Clap"] = {"role": "drums", "channel_name": "Clap", "plan": plan([])}
        self.engine.current_parts = lambda: {"Clap": self.engine.state["parts"]["Clap"]}
        self.engine.sound_after_stop = lambda seconds=2.5: {"tracks": []}
        res = self.engine.listen_check(seconds=0.3)
        ids = [f["id"] for f in res["findings"]]
        self.assertIn("clip", ids)
        self.assertIn("silent", ids)

    def test_arrangement(self):
        self.write_drums()
        arr = self.engine.arrangement("trap")
        self.assertGreater(arr["total_bars"], 32)
        self.assertEqual(arr["sections"][0]["name"], "Intro")
        hook = next(s for s in arr["sections"] if s["name"] == "Hook")
        self.assertEqual(hook["groups"]["drums"], "full")

    def test_progress_estimate_never_claims_done(self):
        import time
        self.engine.set_progress(12, "Composing", "x", estimate={"from": 12, "to": 88, "seconds": 0.01, "since": time.time() - 5})
        p = self.engine.get_progress()
        self.assertTrue(p["active"] and p["estimated"])
        self.assertLessEqual(p["pct"], 88)
        self.engine.clear_progress()
        self.assertFalse(self.engine.get_progress()["active"])


if __name__ == "__main__":
    unittest.main()
