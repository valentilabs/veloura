"""Reapply (and a failed "replace") clears the target channel's Piano Roll first instead of stacking new notes on old."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_controller import FakeTrigger  # noqa: E402
from veloura import bridge_protocol as bp  # noqa: E402
from veloura.engine import Engine  # noqa: E402

PLAN = {"schema": "cadence.melody/1", "title": "Strings", "tempo_bpm": 140, "time_signature": [4, 4], "key": "F minor",
        "bars": 1, "target": "", "notes": [{"pitch": 60, "start": 0, "length": 1, "velocity": 90}]}


class ReapplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs"))
        p.start()
        self.addCleanup(p.stop)
        self.e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=FakeTrigger(),
                        controller=mock.Mock(request=mock.Mock(return_value={"channels": []})))
        self.e.state["proposals"]["p1"] = {"id": "p1", "parts": [{"name": "Strings", "role": "chords", "plan": PLAN, "status": "applied"}]}
        self.e.state["parts"]["Strings"] = {"role": "chords", "command_id": "cad-20261018-000000-aaaaaa", "plan": PLAN, "history": []}

    def test_reapply_clears_the_channel_first(self):
        with mock.patch.object(self.e, "apply", return_value={"ok": True}) as apply:
            self.e.reapply("p1", 0)
        self.assertTrue(apply.call_args.kwargs.get("replace"))

    def test_reapply_writes_a_clear_and_add_command(self):
        sent = []
        with mock.patch.object(self.e, "_run_mutation", side_effect=lambda cmd, verify, target=None: sent.append(cmd) or
                               {"ok": True, "status": "applied", "message": "ok", "command_id": cmd["id"]}), \
                mock.patch.object(self.e, "_target_channel", return_value={"index": 1, "name": "ZENOLOGY #2"}):
            try:
                self.e.reapply("p1", 0)
            except Exception:
                pass
        self.assertTrue(sent, "a bridge command was sent")
        self.assertEqual(sent[-1]["type"], "clear_and_add")

    def test_failed_replace_falls_back_to_clearing_not_stacking(self):
        calls = []
        real = Engine.apply

        def spy(eng, pid, index, **kw):
            calls.append(kw)
            if kw.get("replace"):
                return {"ok": True}
            return real(eng, pid, index, **kw)
        refused = {"ok": False, "status": "refused", "message": "3 of Veloura's earlier notes were changed, moved or duplicated"}
        with mock.patch.object(Engine, "apply", autospec=True, side_effect=spy), \
                mock.patch.object(self.e, "_target_channel", return_value={"index": 1, "name": "ZENOLOGY #2"}), \
                mock.patch.object(self.e, "_run_mutation", return_value=refused):
            self.e.apply("p1", 0)
        self.assertTrue(any(kw.get("replace") for kw in calls), calls)
        self.assertFalse(any(kw.get("as_new") and not kw.get("replace") for kw in calls), "never written on top")


if __name__ == "__main__":
    unittest.main()
