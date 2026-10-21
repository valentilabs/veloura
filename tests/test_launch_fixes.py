"""Launch fixes: one AI draft by default, AI usage recording, capped logs."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai, bridge_protocol as bp  # noqa: E402
from veloura.engine import DEFAULT_SETTINGS  # noqa: E402


class LaunchFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = os.path.join(self.tmp.name, "logs")
        p = mock.patch.object(bp, "LOG_DIR", self.logs)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_one_draft_by_default(self):
        self.assertEqual(DEFAULT_SETTINGS["quality"], "fast")

    def test_haiku_is_the_default_and_old_default_moves_once(self):
        """Regular installs default to Haiku; an unchosen saved model follows the default, a deliberate pick is kept."""
        from veloura.engine import Engine
        self.assertEqual(ai.PRODUCT_DEFAULT_MODEL, "claude-haiku-5-5")
        with mock.patch.object(ai, "DEV_MODE", False), mock.patch.object(ai, "DEFAULT_MODEL", "claude-haiku-5-5"):
            path = os.path.join(self.tmp.name, "s.json")
            with open(path, "w") as f:
                json.dump({"project": "P", "settings": {"model": "claude-opus-5-5"}}, f)
            e = Engine(session_file=path)
            self.assertEqual(e.state["settings"]["model"], "claude-haiku-5-5")
            e.update_settings({"model": "claude-opus-5-5"})     # a later, deliberate pick is kept
            e.save()
            self.assertEqual(Engine(session_file=path).state["settings"]["model"], "claude-opus-5-5")

    def test_usage_is_recorded(self):
        ai.record_usage("anthropic", "m", {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 3})
        ai.record_usage("gemini", "g", None)   # nothing reported: nothing written
        with open(os.path.join(self.logs, "ai_usage.jsonl")) as f:
            rows = [json.loads(x) for x in f]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["usage"]["output_tokens"], 5)

    def test_attempt_log_rolls_over(self):
        with mock.patch.object(bp, "ATTEMPT_LOG_MAX_BYTES", 200):
            for i in range(20):
                bp.log_attempt({"type": "x", "i": i})
        self.assertTrue(os.path.exists(os.path.join(self.logs, "attempts.1.jsonl")))
        self.assertLess(os.path.getsize(bp.attempt_log()), 400)

    def test_archive_is_pruned(self):
        os.makedirs(bp.archive_dir())
        for i in range(10):
            open(os.path.join(bp.archive_dir(), "%d-command.json" % (1000 + i)), "w").close()
        bp._prune_archive(keep=4)
        self.assertEqual(sorted(os.listdir(bp.archive_dir())),
                         ["%d-command.json" % (1000 + i) for i in range(6, 10)])


if __name__ == "__main__":
    unittest.main()
