"""Melody placement (not too many pushed 16ths on short-note lines) and per-request variety in the trap styles."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import blueprints, theory  # noqa: E402

N = lambda p, s, l: {"pitch": p, "start": s, "length": l, "velocity": 100}
# the developer's ZENOLOGY #3 line, first two bars (2026-10-20): pushes at 1.25, 1.75 and 6.25
LINE = [N(76, 0.5, 0.5), N(73, 1.25, 0.25), N(71, 1.75, 0.75), N(73, 3.0, 1.5), N(76, 5.5, 0.5), N(73, 6.25, 0.75), N(69, 7.0, 0.75)]
push = lambda ns: [n["start"] for n in ns if abs((n["start"] * 4) % 2 - 1) < 1e-3]


class PlacementTests(unittest.TestCase):
    def test_keeps_one_push_per_bar_and_moves_the_rest_to_the_8th(self):
        out = theory.calm_pushes(LINE)
        self.assertEqual(push(out), [1.25, 6.25])            # the first push of each bar stays (some human feel)
        moved = next(n for n in out if n["pitch"] == 71)
        self.assertEqual((moved["start"], moved["start"] + moved["length"]), (2.0, 2.5))   # same end
        self.assertEqual(sorted(n["pitch"] for n in out), sorted(n["pitch"] for n in LINE))   # pitches untouched

    def test_short_lone_notes_get_an_8th_when_there_is_room(self):
        out = theory.calm_pushes([N(60, 0.0, 0.25), N(62, 1.0, 0.25)])
        self.assertEqual([n["length"] for n in out], [0.5, 0.5])

    def test_16th_runs_and_arpeggios_are_left_alone(self):
        run = [N(60 + i, i * 0.25, 1.0 - i * 0.25) for i in range(4)]
        self.assertEqual(theory.calm_pushes(run), run)

    def test_never_moves_onto_another_note(self):
        line = [N(60, 1.25, 0.25), N(62, 1.5, 0.5), N(64, 2.75, 0.25), N(65, 3.0, 0.5)]
        out = theory.calm_pushes(line)
        self.assertEqual(len({n["start"] for n in out}), len(out))


class VarietyTests(unittest.TestCase):
    def test_requests_get_different_families_and_yo_is_one_of_them(self):
        picks = {blueprints.pick(blueprints.KEYS_FAMILIES, seed, 1) for seed in range(60)}
        self.assertIn("yo", picks)
        self.assertGreaterEqual(len(picks), 5)

    def test_switch_off_means_always_yo(self):
        old = blueprints.VARIETY
        blueprints.VARIETY = False
        try:
            self.assertEqual({blueprints.pick(blueprints.KEYS_FAMILIES, s, 1) for s in range(20)}, {"yo"})
        finally:
            blueprints.VARIETY = old

    def test_every_keys_family_stays_in_the_chords(self):
        h = blueprints.yo_harmony((5, "minor"), 8, 0)
        for fam in blueprints.KEYS_FAMILIES:
            notes = blueprints.keys(h, 8, family=fam)
            self.assertTrue(notes, fam)
            for n in notes:
                self.assertIn(n["pitch"] % 12, theory.chord_at(h, n["start"])["pcs"], fam)


if __name__ == "__main__":
    unittest.main()


class NoLearningFromPastProjectsTests(unittest.TestCase):
    """2026-10-20: Veloura shouldn't loop on a user's past projects; taste grows."""

    def _src(self, *p):
        with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
            return f.read()

    def test_use_my_style_is_off_by_default_and_for_existing_users(self):
        from veloura.engine import DEFAULT_SETTINGS
        self.assertFalse(DEFAULT_SETTINGS["use_my_style"])
        self.assertIn('st["settings"]["use_my_style"] = False', self._src("veloura", "engine.py"))

    def test_nothing_learned_is_sent_while_it_is_off(self):
        src = self._src("veloura", "engine.py")
        self.assertIn('style_examples=self.style.examples_for_ai(g_now) if settings.get("use_my_style") else []', src)
        self.assertIn('style_grooves=self.style.grooves_for(g_now) if settings.get("use_my_style") else None', src)

    def test_yo_is_described_as_one_example_not_a_template(self):
        from veloura import ai
        self.assertIn("It is not a template", ai.SYSTEM_PROMPT)
