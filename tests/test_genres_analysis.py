"""Genre playbooks, auto defaults, and (when librosa is available in .venv) reference analysis on a synthetic beat."""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai, genres  # noqa: E402

try:
    import numpy as np  # noqa: F401
    import librosa  # noqa: F401
    HAVE_AUDIO = True
except ImportError:
    HAVE_AUDIO = False


class GenreTests(unittest.TestCase):
    def test_every_genre_has_sane_defaults(self):
        for k, g in genres.GENRES.items():
            d = genres.defaults(k)
            self.assertTrue(g["tempo"][0] <= d["tempo_bpm"] <= g["tempo"][1], k)
            self.assertIn(d["bars"], (2, 4, 8, 16))
            self.assertTrue(d["key"] in g["keys"])

    def test_match_and_playbook(self):
        self.assertEqual(genres.match("make me a pluggnb beat"), "melodic plugg")
        self.assertEqual(genres.match("UK drill please"), "drill")
        self.assertIn("GENRE PLAYBOOK: Rage", genres.playbook("rage"))
        self.assertIn("Senior producer standards", genres.playbook(None))

    def test_prompt_carries_mode_channels_and_reference(self):
        msg = ai.build_user_message("go", {"genre": "trap", "key_auto": True, "bars_auto": True, "tempo_bpm": 140},
                                    {}, [], {"channels": [{"name": "808 Kick"}, {"name": "Pluck"}]},
                                    {"mode": "sample", "reference": {"name": "loop.wav", "analysis": {"tempo_bpm": 90}}})
        self.assertIn('"request_mode": "sample"', msg)
        self.assertIn('"key": "auto"', msg)
        self.assertIn("808 Kick", msg)
        self.assertIn('"sample_channel": "Sample"', msg)


@unittest.skipUnless(HAVE_AUDIO, "librosa not installed (run with .venv/bin/python)")
class AnalysisTests(unittest.TestCase):
    def test_synthetic_trap_loop(self):
        import numpy as np
        import soundfile as sf
        from veloura import analysis
        sr, bpm, bars = 22050, 140, 16
        step = 60 / bpm / 4
        n = int(bars * 16 * step * sr) + sr
        y, t = np.zeros(n), np.arange(n) / sr
        rng = np.random.default_rng(0)

        def add(start, sig):
            i = int(start * sr)
            y[i:i + len(sig)] += sig[:max(0, n - i)]
        kt = np.arange(int(.25 * sr)) / sr
        kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-kt * 30)) * kt) * np.exp(-kt * 12)
        snare = rng.normal(0, 1, int(.15 * sr)) * np.exp(-np.arange(int(.15 * sr)) / sr * 30) * .5
        raw = rng.normal(0, 1, int(.04 * sr))
        hat = np.diff(raw, prepend=0) * np.exp(-np.arange(len(raw)) / sr * 120) * .25
        for b in range(bars):
            for s in range(16):
                st = (b * 16 + s) * step
                if s in (0, 7, 10):
                    add(st, kick)
                if s == 8:
                    add(st, snare)
                if s % 2 == 0:
                    add(st, hat)
        y += sum(np.sin(2 * np.pi * f * t) for f in (220.0, 261.63, 329.63, 110.0)) * .08
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "loop.wav")
            sf.write(p, (y / np.abs(y).max()).astype(np.float32), sr)
            a = analysis.analyze(p)
        self.assertAlmostEqual(a["tempo_bpm"], 140, delta=1.5)
        self.assertEqual(a["key"], "A minor")
        self.assertEqual(a["drums"]["kick"]["pattern"], "x......x..x.....")
        self.assertEqual(a["drums"]["hats"]["pattern"], "x.x.x.x.x.x.x.x.")
        self.assertEqual(a["drums"]["snare"]["pattern"][8], "x")


if __name__ == "__main__":
    unittest.main()
