"""Sounds evicted to iCloud are downloaded (and their kit pinned) before Veloura stages or loads them."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from veloura import bridge_protocol as bp, icloud  # noqa: E402


class ICloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kit = os.path.join(self.tmp.name, "My Kit", "snares")
        os.makedirs(self.kit)
        self.files = [os.path.join(self.kit, n) for n in ("a.wav", "b.wav")]
        for f in self.files:
            with open(f, "wb") as fh:
                fh.write(b"x" * 100)
        self.evicted = set(self.files)

    def fake_evicted(self, p):
        return p in self.evicted

    def test_downloads_evicted_files_and_waits(self):
        def download(paths):
            for p in paths:
                self.evicted.discard(p)
        with mock.patch.object(icloud, "is_evicted", side_effect=self.fake_evicted), \
                mock.patch.object(icloud, "request_download", side_effect=download) as req, \
                mock.patch.object(icloud, "free_bytes", return_value=50 * 1024 ** 3):
            left = icloud.ensure_local(self.files, sleep=lambda s: None)
        self.assertEqual(left, [])
        self.assertEqual(sorted(req.call_args[0][0]), sorted(self.files))

    def test_never_fills_the_disk(self):
        with mock.patch.object(icloud, "is_evicted", side_effect=self.fake_evicted), \
                mock.patch.object(icloud, "request_download") as req, \
                mock.patch.object(icloud, "free_bytes", return_value=4 * 1024 ** 3):
            left = icloud.ensure_local(self.files, sleep=lambda s: None)
        self.assertEqual(sorted(left), sorted(self.files))
        req.assert_not_called()

    def test_local_files_need_nothing(self):
        with mock.patch.object(icloud, "request_download") as req:
            self.assertEqual(icloud.ensure_local(self.files), [])   # real files in a temp dir aren't evicted
        req.assert_not_called()

    def test_kit_folder_is_the_library_folder(self):
        lib = os.path.join(self.tmp.name, "My Kit")
        self.assertEqual(icloud.kit_folder(self.files[0], [lib]), os.path.realpath(lib))
        self.assertEqual(icloud.kit_folder(self.files[0], []), os.path.realpath(self.kit))

    def test_pin_sets_finders_keep_downloaded_flag(self):
        with mock.patch.object(icloud.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(icloud.pin(self.kit))
        self.assertEqual(run.call_args[0][0], ["/usr/bin/xattr", "-w", "com.apple.fileprovider.pinned#PX", "1", self.kit])

    def test_staging_downloads_and_pins_first_and_skips_what_is_still_in_icloud(self):
        from test_controller import FakeTrigger
        from veloura.engine import Engine
        with mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs")):
            e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=FakeTrigger(), controller=mock.Mock(request=mock.Mock(return_value={"channels": []})))
            e.library.data["folders"] = [os.path.join(self.tmp.name, "My Kit")]
            roles = {"snare": {"path": self.files[0], "name": "a", "id": "1"}, "clap": {"path": self.files[1], "name": "b", "id": "2"}}
            with mock.patch.object(icloud, "pin", return_value=True) as pin, \
                    mock.patch.object(icloud, "is_pinned", return_value=False), \
                    mock.patch.object(icloud, "ensure_local", return_value=[self.files[1]]), \
                    mock.patch.object(e.library, "stage", return_value={"folder": self.tmp.name, "files": {}}) as stage, \
                    mock.patch("subprocess.run"):
                e.stage_kit(roles)
        pin.assert_called_once_with(os.path.realpath(os.path.join(self.tmp.name, "My Kit")))
        self.assertEqual(list(stage.call_args[0][0]), ["snare"])     # the clap is still in iCloud: not linked yet

    def test_startup_repins_and_brings_back_evicted_sounds(self):
        kitroot = os.path.join(self.tmp.name, "My Kit")
        with mock.patch.object(icloud, "is_pinned", return_value=False), \
                mock.patch.object(icloud, "pin", return_value=True) as pin, \
                mock.patch.object(icloud, "is_evicted", side_effect=self.fake_evicted), \
                mock.patch.object(icloud, "request_download") as req, \
                mock.patch.object(icloud, "free_bytes", return_value=50 * 1024 ** 3):
            res = icloud.keep([kitroot, os.path.join(self.tmp.name, "missing")])
        pin.assert_called_once_with(kitroot)
        self.assertEqual(res[kitroot], {"pinned": True, "evicted": 2, "requested": True})
        self.assertEqual(sorted(req.call_args[0][0]), sorted(self.files))

    def test_startup_never_fills_the_disk(self):
        kitroot = os.path.join(self.tmp.name, "My Kit")
        with mock.patch.object(icloud, "is_pinned", return_value=True), \
                mock.patch.object(icloud, "is_evicted", side_effect=self.fake_evicted), \
                mock.patch.object(icloud, "request_download") as req, \
                mock.patch.object(icloud, "free_bytes", return_value=3 * 1024 ** 3):
            res = icloud.keep([kitroot])
        self.assertFalse(res[kitroot]["requested"])
        req.assert_not_called()

    def test_startup_also_keeps_folders_listed_in_data(self):
        import json
        from test_controller import FakeTrigger
        from veloura.engine import Engine
        with mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs")):
            e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=FakeTrigger(), controller=mock.Mock())
            with open(os.path.join(self.tmp.name, "keep_folders.json"), "w") as f:
                json.dump({"folders": ["/kits/Plug", "/kits/Trap kit"]}, f)
            with mock.patch.object(icloud, "keep", return_value={}) as keep:
                e.keep_kits_local()
        self.assertEqual(keep.call_args[0][0][-2:], ["/kits/Plug", "/kits/Trap kit"])


if __name__ == "__main__":
    unittest.main()
