"""Style library (learning from MIDI) and best-of-two drafts."""

import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai, producer, style  # noqa: E402


def write_midi(path, events, ppq=96):
    """events: [(tick, channel, pitch, velocity, length_ticks)] -> a format-0 file."""
    msgs = []
    for t, ch, p, v, ln in events:
        msgs.append((t, bytes([0x90 | ch, p, v])))
        msgs.append((t + ln, bytes([0x80 | ch, p, 0])))
    msgs.sort(key=lambda m: m[0])
    body, last = b"", 0
    for t, m in msgs:
        d = t - last
        last = t
        v = [d & 0x7F]
        d >>= 7
        while d:
            v.insert(0, (d & 0x7F) | 0x80)
            d >>= 7
        body += bytes(v) + m
    body += b"\x00\xff\x2f\x00"
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq) + b"MTrk" + struct.pack(">I", len(body)) + body)


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = os.path.join(self.tmp.name, "my plugg beats")
        os.makedirs(d)
        q = 24   # a 16th at 96 ppq
        drums = [(s * q, 9, 36, 110, q) for s in (0, 3, 6, 10)] + [(8 * q, 9, 39, 120, q)] + [(s * q, 9, 42, 90, q) for s in range(0, 16, 2)]
        write_midi(os.path.join(d, "drums 1.mid"), drums)
        mel = []
        for bar, chord in enumerate(([65, 68, 72], [61, 65, 68])):
            for p in chord:
                mel.append((bar * 384, 0, p, 80, 384))
        write_midi(os.path.join(d, "keys.mid"), mel)
        self.lib = style.StyleLibrary(os.path.join(self.tmp.name, "style.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_learns_grooves_and_chords_from_midi(self):
        res = self.lib.import_path(os.path.join(self.tmp.name, "my plugg beats"))
        self.assertEqual(res["added"], 2)
        g = self.lib.grooves_for("plugg")
        self.assertEqual(len(g), 1)                                   # genre read from the folder name
        kick = [n["start"] for n in g[0]["lanes"]["Kick"]]
        self.assertEqual(kick, [0, 0.75, 1.5, 2.5])
        self.assertIn("Clap", g[0]["lanes"])
        ex = self.lib.examples_for_ai("plugg")
        self.assertTrue(any(e.get("drums_bar1", {}).get("Kick") == "X..X..X...X....." for e in ex))
        mel = next(e for e in ex if "melody" in e)["melody"]
        self.assertEqual(mel["chords"][:2], ["Fm", "Db"])

    def test_user_groove_drives_the_drums(self):
        self.lib.import_path(os.path.join(self.tmp.name, "my plugg beats"))
        parts = [{"name": "Kick", "role": "drums", "generate": True, "plan": {"notes": []}}]
        out, info, _ = producer.finish(parts, {"key": "F minor"}, {"profile": "plugg"}, settings={"bars": 4}, genre="plugg",
                                       style_grooves=self.lib.grooves_for("plugg"), seed=1)
        kick = next(p for p in out if p["name"] == "Kick")
        self.assertEqual([round(n["start"], 2) for n in kick["plan"]["notes"] if n["start"] < 4], [0, 0.75, 1.5, 2.5])
        self.assertEqual(info["groove"]["label"], "Your groove + Veloura fills")


class BestOfTwoTests(unittest.TestCase):
    def test_never_switches_to_another_ai_company(self):
        # The prompt must not go to a provider the user didn't choose, even if one is connected.
        both = {"claude-code": {"available": True}, "gemini": {"available": True}, "anthropic": {"available": False}}
        good = self.raw([{"pitch": 72, "start": b * 4, "length": 1, "velocity": 96} for b in range(4)])
        with mock.patch.object(ai, "_call_anthropic", side_effect=ai.ProviderError("Claude Code: You've hit your session limit")), \
                mock.patch.object(ai, "_call_gemini", return_value=good) as gemini, \
                mock.patch.object(ai, "provider_status", return_value=both):
            for quality in ("fast", "best"):
                with self.assertRaises(ai.ProviderError):
                    ai.respond("anthropic", "lead", {"provider": "anthropic", "bars": 4, "key": "F minor", "quality": quality},
                               {}, [], seed=1)
        gemini.assert_not_called()

    def raw(self, notes):
        plan = {"schema": "cadence.melody/1", "title": "Lead", "tempo_bpm": 140, "time_signature": [4, 4], "key": "F minor",
                "bars": 4, "target": "", "notes": notes}
        return {"reply": "ok", "harmony": {"key": "F minor", "chords": [{"bar": 1, "beat": 1, "symbol": "Fm"}]},
                "groove": {"profile": "", "swing": -1, "energy": 50}, "mix": [], "guidance": [],
                "parts": [{"name": "Lead", "role": "melody", "purpose": "lead", "generate": False, "register": "", "action": "new",
                           "target_hint": "", "sound": "", "plan": plan}]}

    def test_keeps_the_better_draft(self):
        hook = [{"pitch": p, "start": b * 4 + o, "length": 0.5, "velocity": 96} for b in range(4)
                for o, p in ((0, 72), (0.5, 75), (1, 77), (2, 75), (3, 72))]
        mess = [{"pitch": 61 + (i * 7) % 11, "start": i * 0.25, "length": 0.25, "velocity": 30 + (i * 37) % 97} for i in range(64)]
        calls = iter([self.raw(mess), self.raw(hook)])
        only_claude = {"claude-code": {"available": True}, "gemini": {"available": False}, "anthropic": {"available": False}}
        with mock.patch.object(ai, "_call_anthropic", side_effect=lambda msg, model: next(calls)), \
                mock.patch.object(ai, "provider_status", return_value=only_claude):
            resp, _ = ai.respond("anthropic", "plugg lead", {"provider": "anthropic", "bars": 4, "key": "F minor", "quality": "best"}, {}, [], seed=1)
        self.assertEqual(resp["info"]["picked"], "bolder")             # the hook beat the random line
        self.assertEqual(len(resp["info"]["candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
