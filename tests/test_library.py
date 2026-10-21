"""Drum Library tests: scanning, classification (names + audio), duplicates, corrections, kit choice, staging."""

import math
import os
import random
import shutil
import struct
import sys
import tempfile
import unittest
import unittest.mock
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import library  # noqa: E402
from veloura.library import Library, classify_name  # noqa: E402
from veloura.taste import Taste  # noqa: E402


def tone(path, f, dur, noise=0.0, decay=0.15):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    r = random.Random(1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"".join(struct.pack("<h", int(25000 * math.exp(-i / 44100 / decay) *
                                                     ((1 - noise) * math.sin(2 * math.pi * f * i / 44100) + noise * (r.random() * 2 - 1))))
                               for i in range(int(44100 * dur))))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        b = self.base = os.path.join(self.tmp.name, "Kits")
        tone(b + "/Trap Kit/Kicks/Punchy Kick 01.wav", 55, 0.4)
        tone(b + "/Trap Kit/Kicks/Hard Kick.wav", 50, 0.5)
        tone(b + "/Trap Kit/Snares/Crisp Snare.wav", 200, 0.3, 0.7, 0.08)
        tone(b + "/Trap Kit/Claps/Clap.wav", 900, 0.3, 0.9, 0.06)
        tone(b + "/Trap Kit/Hats/HH 01.wav", 8000, 0.1, 0.95, 0.02)
        tone(b + "/Trap Kit/808s/Dark 808.wav", 44, 1.6, 0, 0.9)
        tone(b + "/Plugg Kit/Soft Kick.wav", 60, 0.35)
        tone(b + "/Plugg Kit/one shots/sample_014.wav", 48, 0.35)
        tone(b + "/Plugg Kit/one shots/sample_015.wav", 9000, 0.08, 0.95, 0.015)
        tone(b + "/Plugg Kit/one shots/mystery.wav", 700, 0.5, 0.3, 0.3)
        shutil.copy(b + "/Trap Kit/Kicks/Hard Kick.wav", b + "/Plugg Kit/copy of hard kick.wav")
        self.lib = Library(os.path.join(self.tmp.name, "library.json"))
        self.lib.add_folder(b)
        self.lib.scan()

    def tearDown(self):
        self.tmp.cleanup()

    def test_names_win_and_808_kick_is_a_kick(self):
        self.assertEqual(classify_name("/x/808 Kick 3.wav")[0], "kick")
        self.assertEqual(classify_name("/x/Dark 808 (F#).wav")[0], "808")
        self.assertEqual(classify_name("/x/Open Hat 2.wav")[0], "open hat")
        self.assertEqual(classify_name("/x/HiHat_closed.wav")[0], "hat")
        self.assertEqual(classify_name("/k/Snares/Rimshot.wav", "/k")[0], "snare")
        self.assertEqual(classify_name("/k/Percs/thing 4.wav", "/k")[0], "perc")
        self.assertEqual(classify_name("/k/stuff/sample_001.wav", "/k")[0], "uncertain")

    def test_scan_metadata_audio_guess_duplicates_and_uncertain(self):
        s = self.lib.summary()
        self.assertEqual(s["total"], 11)
        self.assertEqual(s["duplicates"], 1)
        by_name = {x["name"]: x for x in self.lib.list()}
        self.assertNotIn("copy of hard kick", by_name)                    # duplicates hidden from lists
        self.assertEqual(by_name["sample_014"]["category"], "kick")
        self.assertEqual(by_name["sample_014"]["source"], "audio analysis")
        self.assertEqual(by_name["sample_015"]["category"], "hat")
        self.assertEqual(by_name["mystery"]["category"], "uncertain")     # not forced into a guess
        meta = self.lib.get(by_name["Punchy Kick 01"]["id"])
        self.assertAlmostEqual(meta["duration"], 0.4, places=2)
        self.assertEqual((meta["sample_rate"], meta["channels"]), (44100, 1))

    def test_correction_and_rescan_keeps_it(self):
        sid = next(x["id"] for x in self.lib.list() if x["name"] == "mystery")
        self.lib.set_category(sid, "perc")
        tone(self.base + "/Trap Kit/Percs/Shaker.wav", 6000, 0.2, 0.9, 0.05)
        self.lib.scan()
        by_name = {x["name"]: x for x in self.lib.list()}
        self.assertEqual(by_name["mystery"]["category"], "perc")
        self.assertIn("Shaker", by_name)

    def test_kit_choice_is_real_files_and_genre_aware(self):
        trap = self.lib.choose_kit("trap", seed=1)
        plugg = self.lib.choose_kit("plugg", seed=1)
        for kit in (trap, plugg):
            self.assertTrue(all(os.path.isfile(s["path"]) for s in kit.values()))
            self.assertTrue({"kick", "snare", "hat", "808"} <= set(kit))
        self.assertEqual(plugg["kick"]["name"], "Soft Kick")
        self.assertIn(trap["kick"]["name"], ("Hard Kick", "Punchy Kick 01"))
        taste = Taste(os.path.join(self.tmp.name, "taste.json"))
        punchy = next(x["id"] for x in self.lib.list() if x["name"] == "Punchy Kick 01")
        for _ in range(5):
            taste.note("sample", punchy, "kept")
        picks = [self.lib.choose_kit("trap", seed=s, taste=taste)["kick"]["name"] for s in range(30)]
        self.assertGreater(picks.count("Punchy Kick 01"), 10)              # what the user keeps comes up more often
        self.assertEqual(self.lib.choose_kit("plugg", seed=1, taste=taste)["kick"]["name"], "Soft Kick")   # but fit comes first
        kept = self.lib.choose_kit("trap", seed=5, keep={"kick": punchy})
        self.assertEqual(kept["kick"]["id"], punchy)

    def test_favorites_hidden_variety_and_tone(self):
        hats = [x for x in self.lib.list("hat")]
        self.assertTrue(hats)
        # hidden sounds are never picked, and don't show in the list (but can be restored)
        for x in self.lib.list("kick"):
            if x["name"] != "Soft Kick":
                self.lib.hide(x["id"])
        for seed in range(10):
            self.assertEqual(self.lib.choose_kit("trap", seed=seed)["kick"]["name"], "Soft Kick")
        self.assertEqual([x["name"] for x in self.lib.list("kick")], ["Soft Kick"])
        self.assertTrue(self.lib.list("kick", hidden=True))
        for x in self.lib.list("kick", hidden=True):
            self.lib.hide(x["id"], False)
        # favourites come up more often, but not always (others stay possible)
        fav = next(x for x in self.lib.list("kick") if x["name"] == "Hard Kick")
        self.lib.favorite(fav["id"])
        picks = [self.lib.choose_kit("trap", seed=s)["kick"]["name"] for s in range(40)]
        self.assertGreater(picks.count("Hard Kick"), 8)
        self.assertGreater(len(set(picks)), 1)
        self.assertTrue(next(x for x in self.lib.list("kick") if x["name"] == "Hard Kick")["favorite"])
        # variety: what was just used is less likely next time
        self.lib.analyze_drums()
        first = self.lib.choose_kit("trap", seed=3)
        self.lib.note_used(first)
        again = [self.lib.choose_kit("trap", seed=s)["kick"]["id"] for s in range(20)]
        self.assertLess(again.count(first["kick"]["id"]), 20)
        # tone: a bright hat beats a dull, low one
        bright = {"audio": {"centroid": 10000, "low_share": 0.01, "decay": 0.05}}
        dull = {"audio": {"centroid": 3000, "low_share": 0.05, "decay": 0.05}}
        self.assertGreater(self.lib.tone_score(bright, "hat"), self.lib.tone_score(dull, "hat"))
        deep = {"audio": {"centroid": 600, "low_share": 0.5, "decay": 0.3}}
        snappy = {"audio": {"centroid": 3000, "low_share": 0.05, "decay": 0.2}}
        self.assertGreater(self.lib.tone_score(snappy, "snare"), self.lib.tone_score(deep, "snare"))

    def test_staging_copies_and_never_touches_originals(self):
        kit = self.lib.choose_kit("trap", seed=1)
        before = {s["path"]: os.path.getmtime(s["path"]) for s in kit.values()}
        with unittest.mock.patch.object(library, "STAGE_ROOT", os.path.join(self.tmp.name, "Veloura Kit")):
            staged = self.lib.stage(kit, "Trap test")
        self.assertTrue(staged["folder"].startswith(os.path.join(self.tmp.name, "Veloura Kit")))
        self.assertTrue(all(os.path.isfile(f["file"]) for f in staged["files"].values()))
        self.assertTrue(staged["files"]["kick"]["name"].startswith("Kick - "))
        src = kit["kick"]["path"]
        self.assertTrue(os.path.samefile(src, staged["files"]["kick"]["file"]))     # a hard link: no duplicate space
        with unittest.mock.patch.object(library, "STAGE_ROOT", os.path.join(self.tmp.name, "Veloura Kit")):
            again = self.lib.stage(kit, "Trap test")
            self.assertTrue(again.get("reused"))                                       # same kit: same folder
            dup = os.path.join(self.tmp.name, "Veloura Kit", "old", "Kick - copy.wav")
            os.makedirs(os.path.dirname(dup))
            shutil.copy(src, dup)
            self.assertGreater(self.lib.dedupe_staged(), 0)
            self.assertTrue(os.path.samefile(src, dup))
        self.assertEqual(before, {p: os.path.getmtime(p) for p in before})
        self.assertTrue(all(os.path.isfile(p) for p in before))


if __name__ == "__main__":
    unittest.main()
