"""A new, never-saved FL project starts with an empty chat; saved projects keep their own history."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_controller import FakeTrigger  # noqa: E402
from veloura import bridge_protocol as bp, engine as engmod  # noqa: E402
from veloura.engine import Engine  # noqa: E402


class FreshChatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs"))
        p.start()
        self.addCleanup(p.stop)
        self.fl_start = {"t": 1000.0}
        p2 = mock.patch.object(engmod, "fl_started_at", side_effect=lambda: self.fl_start["t"])
        p2.start()
        self.addCleanup(p2.stop)
        self.current = {"name": "Song A"}
        trig = FakeTrigger()
        trig.fl_project_name = lambda: self.current["name"]
        self.e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=trig)

    def say(self, text):
        self.e.state["messages"].append({"id": text, "role": "user", "text": text})
        self.e.save()

    def go(self, name):
        """FL shows `name` for two checks in a row (a real project change, not a title flicker)."""
        self.current["name"] = name
        self.e.check_project(force=True)
        self.e.check_project(force=True)

    def test_a_brief_untitled_flicker_keeps_the_chat(self):
        self.go("Song A")
        self.say("song A idea")
        self.current["name"] = "Untitled"            # FL's title for a moment while it opens or saves
        self.e.check_project(force=True)
        self.current["name"] = "Song A"
        self.e.check_project(force=True)
        self.assertEqual(self.e.project, "Song A")
        self.assertEqual([m["text"] for m in self.e.state["messages"]], ["song A idea"])

    def test_untitled_after_a_saved_project_is_a_fresh_chat(self):
        self.go("Untitled")
        self.say("old untitled idea")
        self.go("Song A")
        self.say("song A idea")
        self.go("Untitled")                       # File > New in FL
        self.assertEqual(self.e.state["messages"], [])
        self.go("Song A")                          # saved projects keep their history
        self.assertEqual([m["text"] for m in self.e.state["messages"]], ["song A idea"])

    def test_untitled_after_fl_restart_is_a_fresh_chat(self):
        self.go("Untitled")
        self.say("idea")
        self.e.check_project(force=True)           # same FL session: chat stays
        self.assertEqual(len(self.e.state["messages"]), 1)
        self.fl_start["t"] = 2000.0               # FL was quit and reopened on a new Untitled project
        self.e.check_project(force=True)
        self.assertEqual(self.e.state["messages"], [])
        archived = [f for f in os.listdir(os.path.join(self.tmp.name, "projects")) if f.endswith(".bak")]
        self.assertTrue(archived, "the old unsaved chat is archived, not deleted")

    def test_saving_a_fresh_untitled_project_keeps_its_chat(self):
        self.go("Untitled")
        self.say("keep me")
        self.go("My New Song")
        self.assertEqual(self.e.project, "My New Song")
        self.assertEqual([m["text"] for m in self.e.state["messages"]], ["keep me"])

    def test_veloura_restart_in_the_same_fl_session_keeps_the_untitled_chat(self):
        self.go("Untitled")
        self.say("still here")
        trig = FakeTrigger()
        trig.fl_project_name = lambda: "Untitled"
        e2 = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=trig)
        e2.check_project(force=True)
        self.assertEqual([m["text"] for m in e2.state["messages"]], ["still here"])

    def test_unsaved_names(self):
        self.assertTrue(engmod._is_unsaved_project("Untitled"))
        self.assertTrue(engmod._is_unsaved_project("untitled 3"))
        self.assertFalse(engmod._is_unsaved_project("Untitled beat"))
        self.assertFalse(engmod._is_unsaved_project("Song A"))


if __name__ == "__main__":
    unittest.main()
