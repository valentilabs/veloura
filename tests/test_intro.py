"""The opening animation plays only after a Mac restart, a Veloura update or 4+ hours away (app/intro-policy.js)."""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class IntroPolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is needed to run the JavaScript test")
    def test_policy(self):
        p = subprocess.run([shutil.which("node"), os.path.join(ROOT, "app", "intro-policy.test.js")],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_intro_respects_reduce_motion_and_plays_the_startup_sound(self):
        with open(os.path.join(ROOT, "app", "ui", "intro.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn('new Audio("startup.mp3")', js)
        self.assertNotIn("AudioContext", js)          # the old synthesized sound is gone
        self.assertIn("DURATION = 3000", js)
        mp3 = os.path.join(ROOT, "app", "ui", "startup.mp3")
        with open(mp3, "rb") as f:
            head = f.read(3)
        self.assertTrue(head == b"ID3" or head[0] == 0xFF, "startup.mp3 is not an MP3")
        self.assertLess(os.path.getsize(mp3), 500_000)

if __name__ == "__main__":
    unittest.main()
