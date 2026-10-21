"""Drum rows go to the kit Veloura staged, not FL's stock channels (the developer's report, 2026-10-20). Known bug: the
fix landed in the final signed build (2026-10-21)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import drums  # noqa: E402

RACK = [{"name": n} for n in ("808 Kick", "808 Clap", "808 HiHat", "808 Snare",
                               "Kick - SAINT6 Drill Kick 2", "Hat - SAINT6 Drill Hi Hat 7", "Snare - SAINT6 Dior Snare")]
STAGED = ["Kick - SAINT6 Drill Kick 2", "Hat - SAINT6 Drill Hi Hat 7", "Snare - SAINT6 Dior Snare"]


class DrumRoutingTests(unittest.TestCase):
    def test_part_named_after_a_stock_channel_still_goes_to_the_staged_kit(self):
        chan, _ = drums.match_channel("808 Kick", RACK, prefer=STAGED)   # the staged kit wins over the stock channel
        self.assertEqual(chan["name"], "Kick - SAINT6 Drill Kick 2")

    def test_plain_lane_name_already_prefers_the_staged_kit(self):
        chan, _ = drums.match_channel("Kick", RACK, prefer=STAGED)
        self.assertEqual(chan["name"], "Kick - SAINT6 Drill Kick 2")


if __name__ == "__main__":
    unittest.main()


class WriteTimeRoutingTests(unittest.TestCase):
    """Engine._resolve_route with the developer's rack: stock 808 channels plus the dragged-in kit."""

    def _engine(self, staged_names, routing=None):
        from veloura.engine import Engine
        class E:
            _resolve_route = Engine._resolve_route
            _route_key = staticmethod(Engine._route_key)
            def __init__(self):
                self.state = {"kit": {"staged": {"files": {i: {"name": n} for i, n in enumerate(staged_names)}}},
                              "routing": routing or {}}
            def kit_prefer(self):
                return Engine.kit_prefer(self)
        return E()

    def _rack(self):
        names = ["808 Kick", "808 Clap", "808 HiHat", "808 Snare", "Kick - SAINT6 Drill Kick 2", "Hat - SAINT6 Drill Hi Hat 7",
                 "Snare - SAINT6 Dior Snare"]
        return [{"name": n, "index": i, "type": "sampler"} for i, n in enumerate(names)]

    def test_every_drum_goes_to_the_new_kit(self):
        e = self._engine(["Kick - SAINT6 Drill Kick 2", "Hat - SAINT6 Drill Hi Hat 7", "Snare - SAINT6 Dior Snare"])
        for part, want in (("808 Kick", "Kick - SAINT6 Drill Kick 2"), ("808 HiHat", "Hat - SAINT6 Drill Hi Hat 7"),
                           ("808 Snare", "Snare - SAINT6 Dior Snare")):
            r = e._resolve_route({"name": part, "role": "drums"}, self._rack())
            self.assertEqual((r["name"], r["how"]), (want, "kit"), part)

    def test_kit_without_that_drum_falls_back_and_says_so(self):
        e = self._engine(["Kick - SAINT6 Drill Kick 2", "Hat - SAINT6 Drill Hi Hat 7", "Snare - SAINT6 Dior Snare"])
        r = e._resolve_route({"name": "808 Clap", "role": "drums"}, self._rack())
        self.assertEqual(r["name"], "808 Clap")
        self.assertIn("Your kit has no clap", r.get("warning") or "")

    def test_the_new_kit_beats_an_older_remembered_choice_but_not_a_pick_on_the_part(self):
        e = self._engine(["Kick - SAINT6 Drill Kick 2"], routing={"drum:kick": "808 Kick"})
        self.assertEqual(e._resolve_route({"name": "808 Kick", "role": "drums"}, self._rack())["name"], "Kick - SAINT6 Drill Kick 2")
        chosen = {"name": "808 Kick", "role": "drums", "route": {"how": "chosen", "name": "808 Kick"}}
        self.assertEqual(e._resolve_route(chosen, self._rack())["name"], "808 Kick")

    def test_without_a_staged_kit_nothing_changes(self):
        e = self._engine([])
        r = e._resolve_route({"name": "808 Kick", "role": "drums"}, self._rack())
        self.assertEqual((r["name"], r["how"]), ("808 Kick", "exact"))
