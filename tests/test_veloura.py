"""Offline tests. Run from the project folder:  python3 -m unittest discover -s tests -v

The bridge tests run veloura_bridge.pyscript against a FAKE flpianoroll
module, so they are simulations of FL Studio, not verification in FL Studio.
They also imitate FL's file sandbox (observed in FL 2024 on 2026-10-13: os.mkdir
failed with SystemError): while the FL script runs, creating folders, renaming,
deleting, and writing outside veloura_io all raise.
"""

import glob
import json
import os
import runpy
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_flpianoroll  # noqa: E402
from veloura import bridge_protocol as bp  # noqa: E402
from veloura.melody_plan import PlanError, load_plan, validate_plan  # noqa: E402
from veloura.midi_file import read_midi, verify_midi, write_midi  # noqa: E402

TEST_PLAN = os.path.join(ROOT, "melodies", "fminor_4bar_test.json")
SCRIPT = os.path.join(ROOT, "fl_scripts", "veloura_bridge.pyscript")


class MelodyPlanTests(unittest.TestCase):
    def test_test_melody_is_valid(self):
        plan = load_plan(TEST_PLAN)
        self.assertEqual(len(plan["notes"]), 16)
        self.assertEqual(max(n["start"] + n["length"] for n in plan["notes"]), 16)

    def test_all_invalid_examples_are_rejected(self):
        files = glob.glob(os.path.join(ROOT, "melodies", "invalid", "*.json"))
        self.assertGreaterEqual(len(files), 5)
        for f in files:
            with self.subTest(f=os.path.basename(f)):
                with self.assertRaises(PlanError):
                    load_plan(f)

    def test_booleans_are_not_numbers(self):
        with self.assertRaises(PlanError):
            validate_plan({"schema": "cadence.melody/1", "tempo_bpm": 140, "time_signature": [4, 4], "bars": 1,
                           "notes": [{"pitch": True, "start": 0, "length": 1, "velocity": 100}]})


class MidiFileTests(unittest.TestCase):
    def test_export_round_trip(self):
        plan = load_plan(TEST_PLAN)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.mid")
            write_midi(plan, path)
            self.assertEqual(verify_midi(plan, path), [])
            info = read_midi(path)
            self.assertEqual(len(info["notes"]), 16)
            self.assertEqual(info["key"], (-4, 1))  # F minor = 4 flats, minor

    def test_export_never_overwrites(self):
        plan = load_plan(TEST_PLAN)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.mid")
            open(path, "w").close()
            with self.assertRaises(FileExistsError):
                write_midi(plan, path)


class SimulatedBridgeTests(unittest.TestCase):
    """End-to-end protocol tests against the fake Piano Roll."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.patches = [
            mock.patch.object(bp, "BRIDGE_DIR", os.path.join(d, "veloura_io")),
            mock.patch.object(bp, "LOG_DIR", os.path.join(d, "logs")),
        ]
        for p in self.patches:
            p.start()
        os.makedirs(bp.BRIDGE_DIR)
        os.environ["VELOURA_BRIDGE_DIR"] = bp.BRIDGE_DIR
        sys.modules["flpianoroll"] = fake_flpianoroll
        fake_flpianoroll.score.reset()
        fake_flpianoroll.Utils.messages.clear()
        fake_flpianoroll.Utils.logs.clear()
        self.plan = load_plan(TEST_PLAN)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        os.environ.pop("VELOURA_BRIDGE_DIR", None)
        self.tmp.cleanup()

    def run_fl_script(self):
        """Run the FL script under a simulated FL sandbox (see module docstring)."""
        def refused(*a, **k):
            raise SystemError("<built-in function> returned NULL without setting an exception")

        real_open = open
        allowed = os.path.realpath(bp.BRIDGE_DIR)

        def sandboxed_open(path, mode="r", *a, **k):
            if any(c in mode for c in "wax+") and not os.path.realpath(path).startswith(allowed + os.sep):
                raise SystemError("write outside the script folder refused")
            return real_open(path, mode, *a, **k)

        with mock.patch("os.mkdir", refused), mock.patch("os.makedirs", refused), \
                mock.patch("os.replace", refused), mock.patch("os.rename", refused), \
                mock.patch("os.remove", refused), mock.patch("os.unlink", refused), \
                mock.patch("builtins.open", sandboxed_open):
            runpy.run_path(SCRIPT, run_name="__main__")

    def add(self, **kw):
        cmd = bp.make_add_command(self.plan, **kw)
        bp.send_command(cmd)
        self.run_fl_script()
        return cmd, bp.find_result(cmd["id"])

    def test_add_verifies_and_is_readable(self):
        cmd, res = self.add()
        self.assertEqual(res["status"], "applied")
        self.assertTrue(all(c["passed"] for c in bp.verify_add(cmd, res)))
        self.assertEqual(fake_flpianoroll.score.noteCount, 16)
        self.assertIsNone(bp.pending_command())
        self.assertIn("channel_error", res["context"])  # no MIDI modules offline

    def test_missing_bridge_folder_changes_nothing(self):
        os.rmdir(bp.BRIDGE_DIR)
        self.run_fl_script()
        self.assertEqual(fake_flpianoroll.score.noteCount, 0)
        self.assertIn("bridge folder not found", fake_flpianoroll.Utils.messages[-1])

    def test_running_script_twice_after_add_is_harmless(self):
        cmd, _ = self.add()
        self.run_fl_script()  # command file is still there (FL cannot delete it)
        self.assertEqual(fake_flpianoroll.score.noteCount, 16)
        self.assertEqual(bp.find_result(cmd["id"])["status"], "duplicate_ignored")

    def test_half_written_command_is_ignored(self):
        with open(os.path.join(bp.BRIDGE_DIR, "command.json"), "w") as f:
            f.write('{"protocol": 2, "id": "x"')
        self.run_fl_script()
        self.assertEqual(fake_flpianoroll.score.noteCount, 0)
        self.assertEqual(fake_flpianoroll.Utils.messages, [])

    def test_ticks_follow_fl_ppq(self):
        fake_flpianoroll.score.reset(ppq=960)
        cmd, res = self.add()
        self.assertEqual(res["status"], "applied")
        self.assertEqual(fake_flpianoroll.score.getNote(1).time, 960)  # beat 1

    def test_retry_same_id_does_not_duplicate(self):
        cmd, _ = self.add()
        again = dict(cmd)
        again["expires_at"] = time.time() + 600
        bp.send_command(again)
        self.run_fl_script()
        self.assertEqual(bp.find_result(cmd["id"])["status"], "duplicate_ignored")
        self.assertEqual(fake_flpianoroll.score.noteCount, 16)

    def test_no_command_changes_nothing(self):
        self.run_fl_script()
        self.assertEqual(fake_flpianoroll.score.noteCount, 0)
        self.assertEqual(fake_flpianoroll.Utils.messages, [])  # silent: must not block automation
        self.assertIn("no pending command", fake_flpianoroll.Utils.logs[-1])

    def test_expired_command_refused(self):
        cmd = bp.make_add_command(self.plan, ttl=-1)
        bp.send_command(cmd)
        self.run_fl_script()
        self.assertEqual(bp.find_result(cmd["id"])["status"], "expired")
        self.assertEqual(fake_flpianoroll.score.noteCount, 0)

    def test_non_empty_piano_roll_refused_by_default(self):
        n = fake_flpianoroll.Note()
        fake_flpianoroll.score.addNote(n)
        cmd, res = self.add()
        self.assertEqual(res["status"], "refused")
        self.assertEqual(fake_flpianoroll.score.noteCount, 1)

    def test_existing_notes_kept_when_allowed(self):
        n = fake_flpianoroll.Note()
        n.number, n.time = 40, 0
        fake_flpianoroll.score.addNote(n)
        cmd, res = self.add(allow_existing_notes=True)
        self.assertEqual(res["status"], "applied")
        self.assertTrue(all(c["passed"] for c in bp.verify_add(cmd, res)))
        self.assertEqual(fake_flpianoroll.score.noteCount, 17)

    def test_selection_refused(self):
        n = fake_flpianoroll.Note()
        n.selected = True
        fake_flpianoroll.score.addNote(n)
        cmd, res = self.add(allow_existing_notes=True)
        self.assertEqual(res["status"], "refused")
        self.assertEqual(fake_flpianoroll.score.noteCount, 1)

    def test_tampered_command_rejected_without_changes(self):
        cmd = bp.make_add_command(self.plan)
        cmd["notes"][0]["pitch"] = 500
        bp.send_command(cmd)  # bypasses plan validation on purpose: the FL side must still refuse
        self.run_fl_script()
        self.assertEqual(bp.find_result(cmd["id"])["status"], "rejected")
        self.assertEqual(fake_flpianoroll.score.noteCount, 0)

    def test_crash_mid_add_blocks_retry(self):
        fake_flpianoroll.score.fail_on_add_after = 5
        cmd, res = self.add()
        self.assertEqual(res["status"], "error")
        self.assertIn("partly applied", res["message"])
        fake_flpianoroll.score.fail_on_add_after = None
        again = dict(cmd)
        again["expires_at"] = time.time() + 600
        bp.send_command(again)
        self.run_fl_script()
        self.assertEqual(bp.find_result(cmd["id"])["status"], "duplicate_ignored")
        self.assertEqual(fake_flpianoroll.score.noteCount, 5)

    def test_snapshot_then_confirm(self):
        cmd, res = self.add()
        snap = bp.make_snapshot_command()
        bp.send_command(snap)
        self.run_fl_script()
        s = bp.find_result(snap["id"])
        self.assertTrue(all(c["passed"] for c in bp.verify_snapshot_after_add(cmd, res, s)))

    def test_remove_added_keeps_other_notes(self):
        keep = fake_flpianoroll.Note()
        keep.number = 40
        fake_flpianoroll.score.addNote(keep)
        cmd, res = self.add(allow_existing_notes=True)
        rm = bp.make_remove_command(cmd["id"])
        bp.send_command(rm)
        self.run_fl_script()
        self.assertEqual(bp.find_result(rm["id"])["status"], "applied")
        self.assertEqual(fake_flpianoroll.score.noteCount, 1)
        self.assertEqual(fake_flpianoroll.score.getNote(0).number, 40)

    def test_remove_refused_if_user_edited_notes(self):
        cmd, res = self.add()
        fake_flpianoroll.score.getNote(0).time += 12  # user moved a note
        rm = bp.make_remove_command(cmd["id"])
        bp.send_command(rm)
        self.run_fl_script()
        self.assertEqual(bp.find_result(rm["id"])["status"], "refused")
        self.assertEqual(fake_flpianoroll.score.noteCount, 16)

    def test_replace_swaps_only_veloura_notes_in_one_run(self):
        keep = fake_flpianoroll.Note()
        keep.number = 40
        fake_flpianoroll.score.addNote(keep)
        cmd, res = self.add(allow_existing_notes=True)
        new_plan = dict(self.plan)
        new_plan["notes"] = [{"pitch": 70, "start": 0.0, "length": 2.0, "velocity": 90},
                             {"pitch": 72, "start": 2.0, "length": 2.0, "velocity": 100}]
        rep = bp.make_replace_command(new_plan, cmd["id"])
        bp.send_command(rep)
        self.run_fl_script()
        r = bp.find_result(rep["id"])
        self.assertEqual(r["status"], "applied")
        self.assertTrue(all(c["passed"] for c in bp.verify_replace(rep, r)))
        self.assertEqual(sorted(n.number for n in fake_flpianoroll.score.notes), [40, 70, 72])
        # the replacement can itself be replaced or removed later
        rm = bp.make_remove_command(rep["id"])
        bp.send_command(rm)
        self.run_fl_script()
        self.assertEqual(bp.find_result(rm["id"])["status"], "applied")
        self.assertEqual([n.number for n in fake_flpianoroll.score.notes], [40])

    def test_clear_and_add_replaces_everything_in_one_run(self):
        """Reapply: every old note in this Piano Roll goes (Veloura's and the user's), only the new notes remain."""
        user = fake_flpianoroll.Note()
        user.number = 40
        fake_flpianoroll.score.addNote(user)
        self.add(allow_existing_notes=True)                       # an earlier Veloura write on top
        new_plan = dict(self.plan)
        new_plan["notes"] = [{"pitch": 70, "start": 0.0, "length": 2.0, "velocity": 90},
                             {"pitch": 72, "start": 2.0, "length": 2.0, "velocity": 100}]
        cmd = bp.make_clear_add_command(new_plan)
        bp.send_command(cmd)
        self.run_fl_script()
        r = bp.find_result(cmd["id"])
        self.assertEqual(r["status"], "applied")
        self.assertTrue(all(c["passed"] for c in bp.verify_clear_add(cmd, r)))
        self.assertEqual(sorted(n.number for n in fake_flpianoroll.score.notes), [70, 72])
        self.assertGreater(r["in_run_verification"]["notes_removed"], 1)
        rm = bp.make_remove_command(cmd["id"])                    # the new version can still be removed later
        bp.send_command(rm)
        self.run_fl_script()
        self.assertEqual(bp.find_result(rm["id"])["status"], "applied")
        self.assertEqual(fake_flpianoroll.score.notes, [])

    def test_replace_refused_after_user_edit(self):
        cmd, _ = self.add()
        fake_flpianoroll.score.getNote(3).number += 1
        rep = bp.make_replace_command(self.plan, cmd["id"])
        bp.send_command(rep)
        self.run_fl_script()
        self.assertEqual(bp.find_result(rep["id"])["status"], "refused")
        self.assertEqual(fake_flpianoroll.score.noteCount, 16)

    def test_replace_twice_on_same_target_refused(self):
        cmd, _ = self.add()
        rep = bp.make_replace_command(self.plan, cmd["id"])
        bp.send_command(rep)
        self.run_fl_script()
        rep2 = bp.make_replace_command(self.plan, cmd["id"])
        bp.send_command(rep2)
        self.run_fl_script()
        self.assertEqual(bp.find_result(rep2["id"])["status"], "refused")
        self.assertEqual(fake_flpianoroll.score.noteCount, 16)

    def test_stale_unstarted_command_is_withdrawn_not_blocking(self):
        old = bp.send_command(bp.make_snapshot_command())
        new = bp.send_command(bp.make_snapshot_command())
        self.assertEqual(bp.pending_command()["id"], new["id"])
        self.assertNotEqual(old["id"], new["id"])

    def test_command_fl_is_running_still_blocks(self):
        cmd = bp.send_command(bp.make_snapshot_command())
        open(bp._b("started-%s.marker" % cmd["id"]), "w").close()
        with self.assertRaises(bp.BridgeError):
            bp.send_command(bp.make_snapshot_command())


if __name__ == "__main__":
    unittest.main()
