"""Loading a sound by walking FL's Browser: a wrong neighbouring file is reported and recorded so it can be undone."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_controller import FakeTrigger  # noqa: E402
from veloura import bridge_protocol as bp  # noqa: E402
from veloura.engine import Engine  # noqa: E402


class BrowserFL:
    """Just enough of the FL controller for load_sample; `lands_on` is the file FL really loads."""
    def __init__(self, lands_on):
        self.name, self.lands_on, self.muted = "old snare", lands_on, False

    def request(self, op, params=None, timeout=2.0):
        if op == "project":
            return {"channels": [{"index": 0, "name": self.name, "selected": True}]}
        if op == "mix_state":
            return {"tracks": [{"track": 0, "muted": self.muted}]}
        if op == "set_mix":
            self.muted = params["changes"][0]["value"]
            return {"ok": True}
        if op == "browser_goto":
            self.target = params["path"][-1]
            return {"ok": True}
        if op == "browser":
            if params["action"] == "caption":
                return {"in_menu": True, "focused": self.target}
            if params["action"] == "enter":
                self.name = self.lands_on
            return {"ok": True}
        return {}

    def _ensure(self): pass


class KitLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs"))
        p.start()
        self.addCleanup(p.stop)
        self.kit = os.path.join(self.tmp.name, "kit")
        os.makedirs(self.kit)
        for n in ("fav snare.wav", "flex snare.wav"):
            open(os.path.join(self.kit, n), "wb").close()

    def engine(self, lands_on):
        e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=FakeTrigger(), controller=BrowserFL(lands_on))
        e.library.data["folders"] = [self.kit]
        return e

    def test_right_file_loads(self):
        e = self.engine("fav snare")
        with mock.patch("time.sleep"):
            r = e.load_sample(0, os.path.join(self.kit, "fav snare.wav"), "old snare")
        self.assertTrue(r["ok"])
        self.assertFalse(e.controller.muted, "Master is unmuted again")

    def test_wrong_neighbour_is_reported_and_undoable(self):
        e = self.engine("flex snare")
        with mock.patch("time.sleep"):
            r = e.load_sample(0, os.path.join(self.kit, "fav snare.wav"), "old snare")
        self.assertFalse(r["ok"])
        self.assertIn("instead of fav snare", r["message"])
        change = e.state["changes"][-1]
        self.assertEqual((change["type"], change["name"], change["before_name"]), ("sample", "flex snare", "old snare"))
        self.assertFalse(e.controller.muted)


if __name__ == "__main__":
    unittest.main()
