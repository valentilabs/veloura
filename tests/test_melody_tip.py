"""The "load the sound first, then ask for chords on it" tip is in Help, the composer and the AI's instructions."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai  # noqa: E402


class MelodyTipTests(unittest.TestCase):
    def test_tip_everywhere(self):
        with open(os.path.join(ROOT, "app", "ui", "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn("Best way to get a melody:", html)
        self.assertIn("add slow string chords in ZENOLOGY 2", html)
        self.assertIn("When a melody's instrument isn't loaded, add ONE line", ai.SYSTEM_PROMPT)
        self.assertIn("add slow string chords in ZENOLOGY 2", ai.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
