"""0.9.1 redesign: the theme and Channel Rack choices are saved, and recent beats carry a small summary."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_controller import FakeTrigger  # noqa: E402
from veloura import bridge_protocol as bp, engine as engmod  # noqa: E402
from veloura.engine import Engine  # noqa: E402


class RedesignSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs"))
        p.start()
        self.addCleanup(p.stop)
        self.path = os.path.join(self.tmp.name, "s.json")
        self.e = Engine(session_file=self.path, trigger=FakeTrigger())

    def test_defaults(self):
        self.assertEqual(self.e.state["settings"]["theme"], "champagne")
        self.assertIs(self.e.state["settings"]["rack_open"], True)

    def test_theme_is_validated_and_persists(self):
        self.e.update_settings({"theme": "lilac"})
        self.e.update_settings({"theme": "neon-green"})   # unknown themes are ignored
        self.assertEqual(self.e.state["settings"]["theme"], "lilac")
        for t in engmod.THEMES:
            self.e.update_settings({"theme": t})
            self.assertEqual(self.e.state["settings"]["theme"], t)
        self.e.update_settings({"theme": "rose-gold", "rack_open": 0})
        again = Engine(session_file=self.path, trigger=FakeTrigger())
        self.assertEqual(again.state["settings"]["theme"], "rose-gold")
        self.assertIs(again.state["settings"]["rack_open"], False)

    def test_project_summary(self):
        data = {"proposals": {"a": {"genre": "plugg", "info": {"tempo": 150, "key": "C minor"},
                                    "parts": [{"role": "drums", "plan": {"notes": [{"start": 0, "length": .25, "pitch": 36}]}},
                                              {"role": "lead", "plan": {"notes": [{"start": i, "length": 1, "pitch": 60 + i} for i in range(60)]}}]}}}
        s = Engine._project_summary(data)
        self.assertEqual((s["genre"], s["tempo"], s["key"], s["preview_role"]), ("plugg", 150, "C minor", "lead"))
        self.assertEqual(len(s["preview"]), 48)
        self.assertEqual(s["preview"][1], [1, 1, 61])
        self.assertEqual(Engine._project_summary({})["preview"], [])


if __name__ == "__main__":
    unittest.main()
