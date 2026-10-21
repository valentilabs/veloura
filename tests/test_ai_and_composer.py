"""Regression tests: the offline composer always yields valid plans, and malformed AI output never reaches FL."""

import os
import sys
import unittest
import unittest.mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai, composer  # noqa: E402
from veloura.melody_plan import validate_plan  # noqa: E402

SETTINGS = {"tempo_bpm": 140, "key": "F minor", "bars": 4, "genre": "trap", "mood": "dark", "swing": 0}
REQUESTS = ["dark bouncy melody in F minor, 145 bpm", "808 pattern", "trap drums with hi-hat rolls",
            "make me a beat from scratch in C# minor 8 bars", "busy rage melody in E phrygian", "spacious plugg melody in Bb major",
            "simple kick and snare", "melody and 808 in G harmonic minor 16 bars"]


class ComposerTests(unittest.TestCase):
    def test_every_request_and_seed_gives_valid_plans(self):
        for text in REQUESTS:
            for seed in range(40):
                resp, problems = ai.respond("offline", text, SETTINGS, {}, [], seed=seed)
                self.assertEqual(problems, [], (text, seed, problems))
                self.assertTrue(resp["parts"], text)
                for p in resp["parts"]:
                    validate_plan(p["plan"])

    def test_revision_targets_existing_parts(self):
        resp, _ = ai.respond("offline", "melody in F minor", SETTINGS, {}, [], seed=1)
        parts = {p["name"]: {"role": p["role"], "plan": p["plan"]} for p in resp["parts"]}
        self.assertIn("Melody", parts)
        rev, _ = ai.respond("offline", "make it less repetitive", SETTINGS, parts, [], seed=2)
        self.assertEqual(sorted(p["name"] for p in rev["parts"]), sorted(parts))
        self.assertTrue(all(p["action"] == "revise" for p in rev["parts"]))

    def test_guidance_for_mix_requests(self):
        resp, _ = ai.respond("offline", "my mix sounds muddy", SETTINGS, {}, [], seed=1)
        self.assertEqual(resp["parts"], [])
        self.assertTrue(resp["guidance"])
        self.assertTrue(all(g["steps"] and g["undo"] for g in resp["guidance"]))

    def test_key_parsing(self):
        self.assertEqual(composer.parse_key("in C# minor please"), (1, "minor"))
        self.assertEqual(composer.parse_key("Bbm"), (10, "minor"))
        self.assertEqual(composer.parse_key("E phrygian"), (4, "phrygian"))
        self.assertIsNone(composer.parse_key("no key here"))


class NormalizeTests(unittest.TestCase):
    def good_plan(self):
        return {"schema": "cadence.melody/1", "title": "x", "tempo_bpm": 140, "time_signature": [4, 4], "key": "F minor",
                "bars": 1, "target": "", "notes": [{"pitch": 65, "start": 0, "length": 1, "velocity": 100},
                                                   {"pitch": 67, "start": 0.166667, "length": 0.166667, "velocity": 90}]}

    def test_invalid_parts_dropped_valid_kept(self):
        bad = self.good_plan()
        bad["notes"][0]["pitch"] = 300
        raw = {"reply": "ok", "parts": [
            {"name": "Good", "role": "melody", "action": "new", "target_hint": "", "plan": self.good_plan()},
            {"name": "Bad", "role": "melody", "action": "new", "target_hint": "", "plan": bad},
            {"name": "Junk", "plan": "rm -rf /"}], "guidance": [{"title": "t", "steps": ["a"]}, "nonsense"]}
        resp, problems = ai.normalize(raw, "anthropic")
        self.assertEqual([p["name"] for p in resp["parts"]], ["Good"])
        self.assertEqual(len(problems), 2)
        self.assertEqual(len(resp["guidance"]), 1)
        # a lone 16th-triplet sliver isn't part of a pattern: Veloura keeps notes on real grid lines
        self.assertTrue(all(abs(n["start"] * 4 - round(n["start"] * 4)) < 1e-6 for n in resp["parts"][0]["plan"]["notes"]))

    def test_imprecise_ai_timing_is_repaired_not_rejected(self):
        plan = self.good_plan()
        plan["bars"] = 2
        plan["notes"] = [{"pitch": 66, "start": 0.0, "length": 0.45, "velocity": 100},      # staccato, off-grid length
                         {"pitch": 66, "start": 0.3, "length": 0.4, "velocity": 90},       # overlaps the first
                         {"pitch": 66, "start": 0.3, "length": 0.2, "velocity": 90},       # exact duplicate start
                         {"pitch": 70, "start": 7.8, "length": 0.3, "velocity": 80}]       # a hair past the loop end
        resp, problems = ai.normalize({"reply": "", "parts": [{"name": "Lead", "role": "melody", "action": "new",
                                                               "target_hint": "", "plan": plan}], "guidance": []}, "x")
        self.assertEqual(problems, [])
        notes = resp["parts"][0]["plan"]["notes"]
        self.assertEqual(len(notes), 3)
        for n in notes:
            self.assertAlmostEqual(n["start"] * 96, round(n["start"] * 96))
        self.assertLessEqual(notes[0]["start"] + notes[0]["length"], notes[1]["start"] + 1e-9)
        self.assertLessEqual(notes[-1]["start"] + notes[-1]["length"], 8 + 1e-9)
        self.assertTrue(resp["parts"][0]["repairs"])

    def test_non_object_response(self):
        resp, problems = ai.normalize(["not", "an", "object"], "anthropic")
        self.assertEqual(resp["parts"], [])
        self.assertTrue(problems)

    def test_schema_is_strict(self):
        def walk(node):
            if node.get("type") == "object":
                self.assertFalse(node.get("additionalProperties", True))
                self.assertEqual(set(node["required"]), set(node["properties"]))
                for v in node["properties"].values():
                    walk(v)
            if node.get("type") == "array":
                walk(node["items"])
        walk(ai.RESPONSE_SCHEMA)


if __name__ == "__main__":
    unittest.main()


class GeminiRetryTests(unittest.TestCase):
    """Simulated Google responses (no network)."""

    def setUp(self):
        import io
        import socket
        import urllib.error
        self.io, self.socket, self.urllib_error = io, socket, urllib.error
        self.calls = []
        self.key_patch = unittest.mock.patch.object(ai, "get_gemini_key", return_value="AIzaTESTKEY000000000000000")
        self.key_patch.start()

    def tearDown(self):
        self.key_patch.stop()

    def http(self, code, body="{}"):
        return self.urllib_error.HTTPError("u", code, "x", {}, self.io.BytesIO(body.encode()))

    def run_with(self, script):
        def fake(key, model, msg, schema=True):
            self.calls.append(model)
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return {"candidates": [{"content": {"parts": [{"text": '{"reply": "ok", "parts": [], "guidance": []}'}]}}]}
        with unittest.mock.patch.object(ai, "_gemini_once", side_effect=fake):
            return ai._call_gemini("hi", "gemini-3.8-flash", sleep=lambda s: None)

    def test_503_then_success(self):
        self.assertEqual(self.run_with([self.http(503), "ok"])["reply"], "ok")
        self.assertEqual(self.calls, ["gemini-3.8-flash", "gemini-3.8-flash"])

    def test_timeout_skips_to_fallback_model(self):
        self.assertEqual(self.run_with([self.socket.timeout("slow"), "ok"])["reply"], "ok")
        self.assertEqual(self.calls, ["gemini-3.8-flash", "gemini-3.7-flash"])

    def test_everything_busy_gives_clear_error(self):
        with self.assertRaises(ai.ProviderError) as cm:
            self.run_with([self.http(503)] * 6)
        self.assertIn("busy", str(cm.exception))

    def test_busy_model_falls_through_chain(self):
        self.assertEqual(self.run_with([self.http(503), self.http(503), self.http(503), "ok"])["reply"], "ok")
        self.assertEqual(self.calls, ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"])

    def test_bad_key_stops_immediately(self):
        with self.assertRaises(ai.ProviderError) as cm:
            self.run_with([self.http(400, '{"error": {"message": "API key not valid", "status": "API_KEY_INVALID"}}')])
        self.assertIn("rejected", str(cm.exception))
        self.assertEqual(len(self.calls), 1)


class ChatNeverLosesTurnTests(unittest.TestCase):
    def test_unexpected_error_becomes_message(self):
        import tempfile
        from veloura.engine import Engine
        from veloura import bridge_protocol as bp
        with tempfile.TemporaryDirectory() as d, \
                unittest.mock.patch.object(bp, "LOG_DIR", os.path.join(d, "logs")), \
                unittest.mock.patch.object(ai, "respond", side_effect=TimeoutError("boom")):
            e = Engine(session_file=os.path.join(d, "s.json"))
            e.update_settings({"provider": "gemini"})
            e.controller_status = lambda *a, **k: {"connected": False}
            m = e.chat("hello")
            self.assertTrue(m["error"])
            self.assertEqual(e.state["messages"][-1]["role"], "assistant")


class CancelTests(unittest.TestCase):
    def test_cancel_stops_a_slow_ai_reply(self):
        import tempfile
        import threading
        import time as _t
        from veloura.engine import Engine
        from veloura import bridge_protocol as bp

        def slow(*a, **k):
            _t.sleep(5)
            return {"reply": "late", "parts": [], "guidance": [], "provider": "gemini"}, []
        with tempfile.TemporaryDirectory() as d, \
                unittest.mock.patch.object(bp, "LOG_DIR", os.path.join(d, "logs")), \
                unittest.mock.patch.object(ai, "respond", side_effect=slow):
            e = Engine(session_file=os.path.join(d, "s.json"))
            e.controller_status = lambda *a, **k: {"connected": False}
            threading.Timer(0.4, e.cancel).start()
            t0 = _t.time()
            m = e.chat("hello")
            self.assertLess(_t.time() - t0, 2)
            self.assertTrue(m["cancelled"])
            self.assertEqual(e.state["messages"][-1]["text"], "Cancelled. Nothing was changed.")

    def test_cancel_kills_ai_subprocess(self):
        import threading
        import time as _t
        threading.Timer(0.4, ai.cancel_running).start()
        t0 = _t.time()
        p = ai._run(["/bin/sleep", "10"], timeout=20)
        self.assertLess(_t.time() - t0, 3)
        self.assertNotEqual(p.returncode, 0)
