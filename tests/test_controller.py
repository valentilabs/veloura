"""Offline tests for the Veloura Controller (SysEx protocol, step writes, tempo) and the engine's drum path.
These run the real device_VelouraController.py against FAKE FL modules: simulations, not FL verification.
"""

import os
import runpy
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_fl_midi import FakeFL, LoopbackTransport  # noqa: E402
from unittest import mock  # noqa: E402
from veloura import bridge_protocol as bp, drums  # noqa: E402
from veloura.engine import Engine  # noqa: E402
from veloura.fl_controller import ControllerError, ControllerLink  # noqa: E402

SCRIPT = os.path.join(ROOT, "fl_scripts", "device_VelouraController.py")


def make_link(fl):
    saved = {k: sys.modules.get(k) for k in fl.modules}
    sys.modules.update(fl.modules)
    try:
        ns = runpy.run_path(SCRIPT)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return ControllerLink(transport_factory=lambda: LoopbackTransport(fl, ns))


class ControllerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.fl = FakeFL()
        self.link = make_link(self.fl)

    def test_hello_and_project(self):
        self.assertEqual(self.link.request("hello")["ppq"], 96)
        proj = self.link.request("project")
        self.assertEqual([c["name"] for c in proj["channels"]], ["Kick", "Clap", "Hat", "Snare", "Pluck"])
        self.assertEqual(proj["pattern"]["number"], 1)

    def test_large_response_is_chunked(self):
        self.fl.names = ["Channel with a long name %03d" % i for i in range(120)]
        proj = self.link.request("project")
        self.assertEqual(len(proj["channels"]), 120)

    def test_write_and_read_steps_with_undo_point(self):
        steps = [{"step": s, "on": s in (0, 7, 10), "velocity": 110 if s in (0, 7, 10) else None} for s in range(16)]
        res = self.link.request("write_steps", {"channel": 0, "expect_name": "Kick", "steps": steps})
        self.assertTrue(drums.steps_equal(steps, res["steps"]))
        self.assertEqual(self.fl.undo_points, ["Veloura: Kick steps"])

    def test_wrong_channel_name_refused(self):
        with self.assertRaises(ControllerError):
            self.link.request("write_steps", {"channel": 0, "expect_name": "Snare", "steps": [{"step": 0, "on": True}]})
        self.assertEqual(self.fl.grid, {})

    def test_wrong_pattern_refused(self):
        with self.assertRaises(ControllerError):
            self.link.request("write_steps", {"channel": 0, "pattern": 2, "steps": [{"step": 0, "on": True}]})
        self.assertEqual(self.fl.grid, {})

    def test_unknown_op_and_bad_params(self):
        with self.assertRaises(ControllerError):
            self.link.request("delete_everything")
        with self.assertRaises(ControllerError):
            self.link.request("set_tempo", {"bpm": "fast"})

    def test_set_tempo(self):
        self.assertEqual(self.link.request("set_tempo", {"bpm": 145})["tempo"], 145.0)


class FakeTrigger:
    """Stands in for fl_trigger: FL running, Accessibility on, never used for drum steps."""
    def fl_running(self): return True
    def accessibility_enabled(self): return True
    def preflight(self): return []
    def restore_previous(self): pass


def drum_plan(name, starts, bars=1):
    return {"schema": "cadence.melody/1", "title": name, "tempo_bpm": 140, "time_signature": [4, 4], "key": "F minor",
            "bars": bars, "target": "", "notes": [{"pitch": 60, "start": s, "length": 0.25, "velocity": 100} for s in starts]}


class EngineDrumTests(unittest.TestCase):
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

    def propose(self, name, starts):
        pid = "p%d" % len(self.engine.state["proposals"])
        self.engine.state["proposals"][pid] = {"id": pid, "parts": [
            {"name": name, "role": "drums", "action": "new", "target_hint": "", "plan": drum_plan(name, starts),
             "status": "proposed", "result": None}], "guidance": [], "problems": []}
        return pid

    def kick_steps(self):
        return sorted(s for (c, p, s) in self.fl.grid if c == 0 and p == 1)

    def test_write_revise_revert_remove(self):
        out = self.engine.apply(self.propose("Kick", [0, 1.75, 2.5]), 0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["mode"], "steps")
        self.assertEqual(self.kick_steps(), [0, 7, 10])
        out = self.engine.apply(self.propose("Kick", [0, 0.75, 2.5]), 0)  # revision
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.kick_steps(), [0, 3, 10])
        self.assertTrue(self.engine.revert("Kick")["ok"])
        self.assertEqual(self.kick_steps(), [0, 7, 10])
        self.assertTrue(self.engine.remove("Kick")["ok"])
        self.assertEqual(self.kick_steps(), [])

    def test_fast_mode_writes_over_and_revises_after_user_edits(self):
        self.fl.grid[(0, 1, 4)] = 90  # the user's own kick: by default Veloura just makes the beat
        out = self.engine.apply(self.propose("Kick", [0]), 0)
        self.assertTrue(out["ok"], out)
        self.assertTrue(self.engine.remove("Kick")["ok"])
        self.assertEqual(self.kick_steps(), [4])   # Undo still restores the user's step exactly
        self.engine.apply(self.propose("Kick", [0, 2]), 0)
        self.fl.grid[(0, 1, 12)] = 100
        self.assertTrue(self.engine.apply(self.propose("Kick", [1]), 0)["ok"])

    def test_sound_switch_steps_to_the_named_preset(self):
        from veloura import sounds
        sounds.STEP_PAUSE = 0
        self.fl.presets[4] = {"plugin": "ZENOLOGY", "names": ["Init", "Glass Bell", "Dark Pad", "Supersaw", "Soft Keys"],
                              "cur": 0}
        chan = {"index": 4, "name": "Pluck"}
        ok, msg, prev = sounds.switch(self.engine.controller, chan, "Soft Keys")
        self.assertTrue(ok, msg)
        self.assertEqual(prev, "Init")
        self.assertEqual(self.fl.presets[4]["cur"], 4)        # went backwards: 1 step instead of 4
        self.assertEqual(self.fl.names[4], "Pluck")            # channel name restored after FL renamed it
        self.assertIn("Veloura: change sound", self.fl.undo_points)
        ok, msg, _ = sounds.switch(self.engine.controller, chan, "Not A Preset")
        self.assertFalse(ok)
        menu = self.engine._sound_menu([{"index": 4, "name": "Pluck", "type": "plugin"}], "bell melody")
        self.assertEqual(menu["Pluck"]["current"], "Soft Keys")
        self.assertIn("Glass Bell", menu["Pluck"]["choices"])

    def test_rack_shows_every_pattern_and_edits_any_of_them(self):
        self.fl.grid[(0, 2, 3)] = 100                      # a kick in pattern 2 while FL shows pattern 1
        st = self.engine.rack_state(all_patterns=True)
        self.assertEqual([p["number"] for p in st["patterns"]], [1, 2, 3])
        self.assertEqual(st["patterns"][1]["steps"][0], [3])
        self.assertEqual(self.fl.pattern, 1)                # FL is back on the user's pattern
        self.assertTrue(self.engine.rack_toggle(1, "Clap", 5, True, pattern=3)["ok"])
        self.assertIn((1, 3, 5), self.fl.grid)
        self.assertEqual(self.fl.pattern, 1)
        self.fl.playing = True                              # never jump patterns during playback
        self.assertNotIn("patterns", self.engine.rack_state(all_patterns=True))
        self.fl.playing = False
        self.engine.rack_select_pattern(2)
        self.assertEqual(self.fl.pattern, 2)

    def test_auto_sound_picks_a_preset_that_fits_the_instrument(self):
        self.fl.presets[4] = {"plugin": "FLEX", "names": ["Init", "Big Saw Lead", "Soft Grand Piano", "Warm Pad"], "cur": 0}
        chan = {"index": 4, "name": "Pluck", "type": "plugin"}
        self.assertEqual(self.engine._auto_sound(chan, "piano"), "Soft Grand Piano")
        self.assertEqual(self.engine._auto_sound(chan, "pad"), "Warm Pad")
        self.fl.presets[4]["cur"] = 2
        self.assertIsNone(self.engine._auto_sound(chan, "piano"))          # already a piano: leave it

    def test_existing_steps_protected(self):
        self.engine.state["settings"]["careful"] = True
        self.fl.grid[(0, 1, 4)] = 90  # the user's own kick on step 4
        out = self.engine.apply(self.propose("Kick", [0]), 0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "not_empty")
        self.assertEqual(self.kick_steps(), [4])
        out = self.engine.apply(self.propose("Kick", [0]), 0, allow_existing=True)
        self.assertTrue(out["ok"])
        self.assertTrue(self.engine.remove("Kick")["ok"])
        self.assertEqual(self.kick_steps(), [4])  # restored exactly
        self.assertEqual(self.fl.grid[(0, 1, 4)], 90)

    def test_user_edit_blocks_revision(self):
        self.engine.state["settings"]["careful"] = True
        self.engine.apply(self.propose("Kick", [0, 2]), 0)
        self.fl.grid[(0, 1, 12)] = 100  # user adds a kick
        out = self.engine.apply(self.propose("Kick", [1]), 0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["code"], "replace_failed")
        self.assertEqual(self.kick_steps(), [0, 8, 12])

    def test_undo_in_fl_is_noticed(self):
        self.engine.apply(self.propose("Kick", [0, 2]), 0)
        for st in (0, 8):  # user presses Cmd+Z in FL: the channel is back to empty
            self.fl.grid.pop((0, 1, st), None)
        out = self.engine.apply(self.propose("Kick", [1]), 0)
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.kick_steps(), [4])
        self.assertTrue(self.engine.remove("Kick")["ok"])
        self.assertEqual(self.kick_steps(), [])

    def test_kit_swap_writes_fresh_and_keeps_old_part(self):
        self.engine.apply(self.propose("Kick", [0, 2]), 0)
        self.fl.names[0] = "KICK - new kit"   # user swaps the kick sample/channel name
        self.fl.names.append("Kick")         # and a different channel is now the exact match
        out = self.engine.apply(self.propose("Kick", [1]), 0)
        self.assertTrue(out["ok"], out)
        self.assertIn("Kick · Kick (ch 1)", self.engine.state["parts"])
        self.assertEqual(self.engine.state["parts"]["Kick"]["channel"], len(self.fl.names) - 1)
        self.assertEqual(self.engine.state["parts"]["Kick"]["history"], [])

    def test_sound_after_stop_names_the_track(self):
        self.fl.peaks = {0: 0.2, 3: 0.4}
        res = self.engine.sound_after_stop(seconds=0.4)
        self.assertIn("Insert 3", res["message"])
        self.fl.peaks = {}
        self.assertIn("Silent", self.engine.sound_after_stop(seconds=0.3)["message"])

    def test_sound_prep_checklist(self):
        self.fl.names = ["808 Kick", "808 Bass", "FLEX Bass", "Hat"]
        prep = self.engine.sound_prep()
        by = {i["channel"]: [t["id"] for t in i["tasks"]] for i in prep["items"]}
        self.assertEqual(by["808 Bass"], ["loop", "cut"])
        self.assertEqual(by["FLEX Bass"], ["cut"])          # plugin: mono, no loop points
        self.assertEqual(by["Hat"], ["loop"])
        before = prep["pending"]
        after = self.engine.set_prep("Hat", "loop", True)["pending"]
        self.assertEqual(after, before - 1)

    def test_open_piano_roll_for_a_channel(self):
        res = self.engine.controller.request("open_piano_roll", {"channel": 4, "expect_name": "Pluck"})
        self.assertEqual(res["caption"], "Piano roll - Pluck")
        ok, detail = self.engine._open_target({"index": 4, "name": "Pluck"})
        self.assertTrue(ok, detail)

    def test_wrong_piano_roll_blocks_the_write(self):
        self.fl.roll_caption_override = "Piano roll -"            # FL's real scripting caption has no channel name
        self.fl.modules["channels"].selectOneChannel = lambda i, *a: setattr(self.fl, "selected", 0)  # selection didn't move
        self.fl.modules["channels"].isChannelSelected = lambda i, *a: i == self.fl.selected
        ok, detail = self.engine._open_target({"index": 4, "name": "Pluck"})
        self.assertFalse(ok)
        self.assertIn("Kick", detail)

    def test_target_channel_for_parts(self):
        chan = self.engine._target_channel({"name": "Pluck", "role": "melody", "destination": {}})
        self.assertEqual(chan["name"], "Pluck")
        self.assertIsNone(self.engine._target_channel({"name": "Bell", "role": "melody", "destination": {}}))
        self.assertEqual(self.engine._target_channel({"name": "Hi-hat", "role": "drums", "destination": {}})["name"], "Hat")

    def test_caption_matching(self):
        self.assertTrue(Engine._caption_matches("Piano roll - 808 favv @starfinesse_", "808 favv @starfinesse_"))
        self.assertFalse(Engine._caption_matches("Piano roll - 808 Kick", "808 Snare"))

    def test_mix_state_and_moves_round_trip(self):
        from veloura import mix
        state = self.engine.controller.request("mix_state")
        self.assertEqual(state["tracks"][2]["effects"][0]["name"], "Fruity Reeverb 2")   # Clap plays through track 2
        moves = [{"kind": "channel_volume", "target": "Kick", "value": 90, "plugin": "", "param": "", "why": "punch"},
                 {"kind": "channel_pan", "target": "Hat", "value": -20, "plugin": "", "param": "", "why": "width"},
                 {"kind": "mixer_volume_db", "target": "Clap", "value": -3, "plugin": "", "param": "", "why": "tame"},
                 {"kind": "effect_param", "target": "Clap", "value": 35, "plugin": "Fruity Reeverb 2", "param": "wet", "why": "space"},
                 {"kind": "effect_param", "target": "Kick", "value": 50, "plugin": "Sytrus", "param": "x", "why": "nope"}]
        changes, preview, problems = mix.resolve(moves, state)
        self.assertEqual(len(changes), 4)
        self.assertEqual(len(problems), 1)          # Sytrus isn't loaded: skipped, not invented
        send, undo = mix.split_undo(changes)
        res = self.engine.controller.request("set_mix", {"changes": send})["results"]
        self.assertTrue(all(r["ok"] for r in res), res)
        self.assertAlmostEqual(self.fl.ch_vol[0], 0.9)
        self.assertAlmostEqual(self.fl.ch_pan[2], -0.2)
        self.assertAlmostEqual(res[2]["now"], -3.0, delta=0.05)   # dB found by bisection on FL's curve
        self.assertAlmostEqual(self.fl.fx[(2, 0)]["params"][0][1], 0.35)
        self.assertIn("Veloura: mix changes", self.fl.undo_points)
        self.engine.controller.request("set_mix", {"changes": undo})   # undo restores the exact values
        self.assertAlmostEqual(self.fl.ch_vol[0], 0.78125)
        self.assertAlmostEqual(self.fl.fx[(2, 0)]["params"][0][1], 0.2)
        self.assertAlmostEqual(self.fl.tr_vol[2], 0.8)

    def test_engine_apply_and_undo_mix(self):
        self.engine.state["proposals"]["m1"] = {"id": "m1", "parts": [], "guidance": [], "problems": [], "mix": {
            "moves": [{"kind": "mixer_volume_db", "target": "Kick", "value": 2, "plugin": "", "param": "", "why": ""},
                      {"kind": "channel_mute", "target": "Snare", "value": 1, "plugin": "", "param": "", "why": ""}],
            "preview": [], "problems": [], "status": "proposed", "result": None}}
        r = self.engine.apply_mix("m1")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["applied"], 2)
        self.assertIn(3, self.fl.ch_mute)                                  # Snare is channel 3
        self.assertEqual(self.engine.state["proposals"]["m1"]["mix"]["status"], "applied")
        self.assertTrue(self.engine.undo_mix("m1")["ok"])
        self.assertNotIn(3, self.fl.ch_mute)
        self.assertAlmostEqual(self.fl.tr_vol[1], 0.8)                     # Kick's track back to its exact level

    def test_veloura_rack_mirror_and_clicks(self):
        self.fl.grid[(0, 1, 4)] = 100
        rack = self.engine.rack_state()
        self.assertTrue(rack["connected"])
        self.assertEqual(rack["channels"][0]["steps"], [4])
        self.assertTrue(self.engine.rack_toggle(0, "Kick", 8, True)["ok"])
        self.assertEqual(sorted(s for (c, p, s) in self.fl.grid if c == 0), [4, 8])
        self.assertTrue(self.engine.rack_toggle(0, "Kick", 4, False)["ok"])
        self.assertEqual(sorted(s for (c, p, s) in self.fl.grid if c == 0), [8])
        with self.assertRaises(Exception):
            self.engine.rack_toggle(0, "Snare", 1, True)          # channel renamed/moved: refused
        self.assertTrue(self.engine.rack_mute(1, "Clap", True)["muted"])

    def test_rolls_fall_back_from_steps(self):
        steps, problem = drums.plan_to_steps(drum_plan("Hi-hat", [0, 0.125]))
        self.assertIsNone(steps)
        self.assertIn("between 16ths", problem)


if __name__ == "__main__":
    unittest.main()


class SetupAndDestinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_patch = mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs"))
        self.log_patch.start()
        self.fl = FakeFL(names=("808 Kick", "808 Snare", "808 HiHat", "Pluck"))
        self.engine = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=FakeTrigger(),
                             controller=make_link(self.fl))

    def tearDown(self):
        self.log_patch.stop()
        self.tmp.cleanup()

    def test_destinations(self):
        chans = self.engine.controller_status()["channels"]
        kick = {"name": "Kick", "role": "drums", "plan": drum_plan("Kick", [0, 1])}
        hats = {"name": "Hi-hat", "role": "drums", "plan": drum_plan("Hi-hat", [0, 0.125])}
        mel = {"name": "Melody", "role": "melody", "plan": drum_plan("Melody", [0])}
        d = self.engine._destination(kick, chans)
        self.assertEqual((d["kind"], d["channel"], d["label"]), ("steps", "808 Kick", "Channel Rack · 808 Kick"))
        self.assertEqual(self.engine._destination(hats, chans)["kind"], "pianoroll")  # rolls can't be steps
        self.assertEqual(self.engine._destination(mel, chans)["kind"], "pianoroll")

    def test_arming_follows_fl_restarts(self):
        with mock.patch("veloura.engine.fl_started_at", return_value=1000.0), \
                mock.patch.object(bp, "SCRIPT_INSTALLED", os.path.join(self.tmp.name, "none.pyscript")), \
                mock.patch.object(bp, "BRIDGE_DIR", os.path.join(self.tmp.name, "io")):
            self.engine.bridge_ok_at = 0
            self.assertFalse(self.engine.bridge_armed())
            self.engine.bridge_ok_at = 1500.0
            self.assertTrue(self.engine.bridge_armed())
        with mock.patch("veloura.engine.fl_started_at", return_value=2000.0), \
                mock.patch.object(bp, "SCRIPT_INSTALLED", os.path.join(self.tmp.name, "none.pyscript")), \
                mock.patch.object(bp, "BRIDGE_DIR", os.path.join(self.tmp.name, "io")):  # FL restarted since
            self.assertFalse(self.engine.bridge_armed())

    def test_onboarding_setting(self):
        self.assertFalse(self.engine.state["settings"]["onboarded"])
        self.engine.update_settings({"onboarded": 1, "auto_tempo": 0})
        self.assertIs(self.engine.state["settings"]["onboarded"], True)
        self.assertIs(self.engine.state["settings"]["auto_tempo"], False)
