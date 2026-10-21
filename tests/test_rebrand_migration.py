"""Cadence -> Veloura: what carries over for people who used the app under its old name (2026-10-21)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai, bridge_protocol as bp, chatgpt  # noqa: E402


class KeychainMigrationTests(unittest.TestCase):
    def test_old_api_key_is_found_and_moved(self):
        items = {("Cadence Anthropic API key", "cadence"): "sk-old"}
        saved, deleted = {}, []
        def find(service, account):
            return items.get((service, account))
        with mock.patch.object(ai, "_keychain_find", find), \
                mock.patch.object(ai, "_keychain_set", lambda s, k: saved.update({s: k})), \
                mock.patch("subprocess.run", lambda args, **kw: deleted.append(args)):
            self.assertEqual(ai._keychain_get(ai.KEYCHAIN_SERVICE), "sk-old")
        self.assertEqual(saved, {"Veloura Anthropic API key": "sk-old"})
        self.assertIn("Cadence Anthropic API key", deleted[0])

    def test_new_key_wins_and_nothing_moves(self):
        with mock.patch.object(ai, "_keychain_find", lambda s, a: "sk-new" if s.startswith("Veloura") else "sk-old"), \
                mock.patch.object(ai, "_keychain_set", lambda *a: self.fail("must not rewrite")):
            self.assertEqual(ai._keychain_get(ai.KEYCHAIN_SERVICE), "sk-new")

    def test_old_chatgpt_sign_in_is_moved(self):
        old = {"client_id": "oaiapp_1", "refresh_token": "rt"}
        written = []
        with mock.patch.object(chatgpt, "_keychain_read_item", lambda s, a: old if s.startswith("Cadence") else None), \
                mock.patch.object(chatgpt, "_keychain_write", written.append), \
                mock.patch("subprocess.run", lambda *a, **k: None):
            self.assertEqual(chatgpt._keychain_read(), old)
        self.assertEqual(written, [old])


class FlScriptMigrationTests(unittest.TestCase):
    def test_old_cadence_fl_files_are_removed_and_nothing_else(self):
        d = tempfile.mkdtemp()
        scripts, hw = os.path.join(d, "Piano roll scripts"), os.path.join(d, "Hardware")
        os.makedirs(os.path.join(scripts, "cadence_io"))
        os.makedirs(os.path.join(hw, "Cadence Controller"))
        for f in (os.path.join(scripts, "cadence_bridge.pyscript"), os.path.join(scripts, "cadence_io", "result-1.json"),
                  os.path.join(hw, "Cadence Controller", "device_CadenceController.py"), os.path.join(scripts, "my_script.pyscript")):
            open(f, "w").close()
        files = [os.path.join(scripts, "cadence_bridge.pyscript"),
                 os.path.join(hw, "Cadence Controller", "device_CadenceController.py")]
        dirs = [os.path.join(scripts, "cadence_io"), os.path.join(hw, "Cadence Controller")]
        with mock.patch.object(bp, "OLD_FL_FILES", files), mock.patch.object(bp, "OLD_FL_DIRS", dirs):
            gone = bp.remove_old_cadence_files()
        self.assertEqual(len(gone), 4)
        self.assertEqual(os.listdir(scripts), ["my_script.pyscript"])   # the user's own script stays
        self.assertEqual(os.listdir(hw), [])

    def test_new_fl_names(self):
        from veloura import fl_controller
        self.assertEqual((fl_controller.VIRTUAL_TO_FL, fl_controller.VIRTUAL_FROM_FL), ("Veloura to FL", "FL to Veloura"))
        self.assertTrue(bp.SCRIPT_INSTALLED.endswith("veloura_bridge.pyscript"))
        self.assertTrue(bp.CONTROLLER_DIR.endswith("Veloura Controller"))


class AppMigrationTests(unittest.TestCase):
    def test_main_js_copies_the_old_data_folder_once(self):
        with open(os.path.join(ROOT, "app", "main.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('path.join(app.getPath("appData"), "Cadence")', js)
        self.assertLess(js.index("migrateFromCadence();"), js.index("svc = await startService()"))


if __name__ == "__main__":
    unittest.main()
