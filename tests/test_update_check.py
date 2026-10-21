"""Beta update notice (app/update-check.js): version compare, offer once, never open non-https links."""
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class UpdateCheckTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is needed to run the JavaScript test")
    def test_update_check(self):
        p = subprocess.run([shutil.which("node"), "--test", os.path.join(ROOT, "app", "update-check.test.js")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_manifest_uses_the_veloura_name(self):
        with open(os.path.join(ROOT, "app", "update-check.js"), encoding="utf-8") as f:
            self.assertIn("veloura-update-mac.json", f.read())


if __name__ == "__main__":
    unittest.main()
