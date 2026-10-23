"""FL's Master is never left muted by Veloura (2026-10-22). With protection on (default) Veloura never touches
it; with it off, a Browser walk's mute is always undone, even after an interruption; the user's Unmute always works."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from veloura import bridge_protocol as bp, engine as engmod  # noqa: E402
from veloura.engine import Engine  # noqa: E402


class FakeMixer:
    """A stand-in for FL's mixer over the controller: tracks the Master mute and every set_mix sent."""
    def __init__(self, muted=False):
        self.muted, self.sent, self.ignore_unmute = muted, [], False

    def request(self, op, params=None, timeout=None, **kw):
        if op == "mix_state":
            return {"tracks": [{"track": 0, "muted": self.muted}], "channels": []}
        if op == "set_mix":
            self.sent.append(list(params["changes"]))
            res = []
            for c in params["changes"]:
                if c.get("kind") == "mixer_mute" and int(c.get("track", -1)) == 0:
                    if c["value"] or not self.ignore_unmute:
                        self.muted = bool(c["value"])
                res.append({"ok": True})
            return {"results": res}
        return {}


class MasterProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, name, value in ((bp, "LOG_DIR", os.path.join(self.tmp.name, "logs")),
                                    (engmod, "DATA_DIR", self.tmp.name)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.fl = FakeMixer()
        self.e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), controller=self.fl)
        p = mock.patch.object(engmod.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_protected_by_default_and_the_browser_walk_never_mutes(self):
        self.assertTrue(self.e.state["settings"]["protect_master"])
        with self.e._quiet():
            self.assertFalse(self.fl.muted)
        self.assertEqual(self.fl.sent, [])

    def test_master_mute_changes_are_dropped_while_protected(self):
        out = self.e.controller.request("set_mix", {"changes": [
            {"kind": "mixer_mute", "track": 0, "value": True}, {"kind": "channel_mute", "channel": 2, "value": True}]})
        self.assertFalse(self.fl.muted)
        self.assertEqual(self.fl.sent, [[{"kind": "channel_mute", "channel": 2, "value": True}]])   # only the channel
        self.assertEqual([r.get("ok") for r in out["results"]], [False, True])                       # results still line up

    def test_unprotected_walk_mutes_then_unmutes_and_cleans_up(self):
        self.e.state["settings"]["protect_master"] = False
        with self.e._quiet():
            self.assertTrue(self.fl.muted)
            self.assertTrue(os.path.exists(self.e._master_marker()))   # written before muting
        self.assertFalse(self.fl.muted)
        self.assertFalse(os.path.exists(self.e._master_marker()))

    def test_an_interrupted_walk_is_undone_later_not_mistaken_for_the_users_mute(self):
        self.e.state["settings"]["protect_master"] = False
        self.fl.ignore_unmute = True            # FL busy: the unmute at the end doesn't take
        with self.e._quiet():
            pass
        self.assertTrue(self.fl.muted)
        with self.e._quiet():                   # the next sound: still knows the mute is Veloura's own
            pass
        self.fl.ignore_unmute = False
        self.e.restore_master_if_ours()         # what every status check does
        self.assertFalse(self.fl.muted)
        self.assertFalse(os.path.exists(self.e._master_marker()))

    def test_the_users_own_mute_is_left_alone(self):
        self.e.state["settings"]["protect_master"] = False
        self.fl.muted = True                    # the user muted it in FL
        with self.e._quiet():
            pass
        self.e.restore_master_if_ours()
        self.assertTrue(self.fl.muted)

    def test_unmute_button_always_works_even_when_protected(self):
        self.fl.muted = True
        self.assertEqual(self.e.unmute_master(), {"ok": True, "muted": False})
        self.assertFalse(self.fl.muted)


if __name__ == "__main__":
    unittest.main()
