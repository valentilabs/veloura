"""Fixes from the first outside test (Charlie, 0.9.0): a hung trigger must not leave a command queued or crash."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from veloura import bridge_protocol as bp  # noqa: E402
from veloura.engine import Engine, EngineError  # noqa: E402


class HangingTrigger:
    def trigger_and_wait(self, *a, **k):
        raise subprocess.TimeoutExpired("osascript", 5)


class SendCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, sub in (("LOG_DIR", "logs"), ("BRIDGE_DIR", "bridge")):
            p = mock.patch.object(bp, name, os.path.join(self.tmp.name, sub))
            p.start()
            self.addCleanup(p.stop)
        os.makedirs(bp.BRIDGE_DIR)
        self.e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=HangingTrigger(),
                        controller=mock.Mock(request=mock.Mock(return_value={})))

    def test_trigger_timeout_withdraws_the_command_and_explains(self):
        with mock.patch.object(bp, "bridge_ready", return_value=True):
            with self.assertRaises(EngineError) as c:
                self.e._send(bp.make_snapshot_command(), mutating=True)
            self.assertIsNone(bp.pending_command())   # the next Add isn't blocked by "Command … is still waiting"
            self.assertIn("nothing was changed", str(c.exception))


if __name__ == "__main__":
    unittest.main()
