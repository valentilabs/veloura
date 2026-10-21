"""AI countdown estimates and the ad hoc signing rule that keeps the bundled Python's own signature."""
import os
import sys
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura.engine import Engine  # noqa: E402


class Fake:
    AI_DEFAULT_SECONDS = Engine.AI_DEFAULT_SECONDS
    _ai_seconds = Engine._ai_seconds
    _record_ai_seconds = Engine._record_ai_seconds

    def __init__(self):
        self.state, self.state_lock = {}, threading.Lock()


class AiTimingTests(unittest.TestCase):
    def test_default_for_chatgpt_is_short(self):
        self.assertLessEqual(Fake()._ai_seconds("chatgpt", "gpt-6.1-sol"), 30)

    def test_median_of_recent_times_per_model(self):
        e = Fake()
        for s in (12, 14, 13, 90, 15):   # one very slow reply shouldn't drag the estimate up
            e._record_ai_seconds("chatgpt", s, "gpt-6.1-sol")
        self.assertEqual(e._ai_seconds("chatgpt", "gpt-6.1-sol"), 14)
        e._record_ai_seconds("chatgpt", 40, "gpt-6-luna")
        self.assertEqual(e._ai_seconds("chatgpt", "gpt-6-luna"), 40)
        self.assertEqual(e._ai_seconds("chatgpt", "unseen-model"), 14.5)   # falls back to the provider's history

    def test_keeps_the_last_ten(self):
        e = Fake()
        for s in range(30):
            e._record_ai_seconds("anthropic", s)
        self.assertEqual(len(e.state["ai_timing"]["anthropic"]), 10)


class SigningRuleTests(unittest.TestCase):
    def test_valid_binaries_keep_their_signature(self):
        with open(os.path.join(ROOT, "app", "build", "sign-adhoc.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("if (!valid(f)) sign(f);", js)


if __name__ == "__main__":
    unittest.main()
