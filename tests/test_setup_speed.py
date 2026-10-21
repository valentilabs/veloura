"""Setup and status stay quick, and the reconnect steps read the same everywhere."""
import os
import re
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai, bridge_protocol as bp, fl_trigger, help_text  # noqa: E402
from veloura.engine import Engine  # noqa: E402
from veloura.fl_controller import ControllerUnavailable  # noqa: E402


class SlowTrigger:
    """FL open, but the project-name lookup is slow (as when System Events is busy)."""
    def fl_running(self): return True
    def accessibility_enabled(self): return True
    def preflight(self): return []
    def restore_previous(self): pass
    def fl_project_name(self):
        time.sleep(1.0)
        return None


class SlowController:
    def request(self, op, params=None, timeout=1.2):
        time.sleep(1.0)
        raise ControllerUnavailable("FL Studio is not answering.")
    def _ensure(self): pass


class SetupSpeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(bp, "LOG_DIR", os.path.join(self.tmp.name, "logs"))
        p.start()
        self.addCleanup(p.stop)

    def test_slow_checks_run_side_by_side(self):
        e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=SlowTrigger(), controller=SlowController())
        with mock.patch.object(ai, "provider_status", side_effect=lambda: time.sleep(1.0) or {}):
            t = time.time()
            st = e.status()
            took = time.time() - t
        self.assertLess(took, 1.8, "three 1-second checks should overlap, not add up")
        self.assertFalse(st["controller"]["connected"])
        self.assertEqual(st["reconnect_steps"], help_text.RECONNECT_STEPS)

    def test_fl_opened_before_veloura_is_explained_not_crashed(self):
        from veloura import engine as engmod
        e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=SlowTrigger(), controller=SlowController())
        with mock.patch.object(engmod, "fl_started_at", return_value=e.started_at - 60), \
                mock.patch.object(ai, "provider_status", return_value={}):
            st = e.status()
        self.assertEqual(st["connection_hint"]["code"], "fl_first")

    def test_project_name_is_instant_when_fl_is_closed(self):
        with mock.patch.object(fl_trigger, "fl_running", return_value=False), \
                mock.patch.object(fl_trigger, "_osascript", side_effect=AssertionError("asked System Events")):
            self.assertIsNone(fl_trigger.fl_project_name())

    def test_ui_and_service_show_the_same_reconnect_steps(self):
        with open(os.path.join(ROOT, "app", "ui", "app.js"), encoding="utf-8") as f:
            js = f.read()
        block = re.search(r"const RECONNECT_STEPS = \[(.*?)\];", js, re.S).group(1)
        self.assertEqual(re.findall(r'"([^"]+)"', block), help_text.RECONNECT_STEPS)
        self.assertEqual(help_text.RECONNECT_STEPS[1], "Open Veloura first.")

    def test_fl_actions_count_down_from_real_timings(self):
        e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=SlowTrigger(), controller=SlowController())
        self.assertEqual(e.fl_action_seconds("write"), Engine.FL_ACTION_DEFAULTS["write"])
        with e.timed_action("write"):
            p = e.get_progress()
            self.assertEqual(p["fl_action"], "write")
            self.assertGreater(p["remaining"], 0)
            time.sleep(0.2)
        self.assertFalse(e.get_progress()["active"])
        with e.timed_action("write"):
            time.sleep(0.1)
        self.assertLess(e.fl_action_seconds("write"), 0.5)          # learned: writes take ~0.15 s here
        e.set_progress(50, "Composing")                                 # an AI request's progress is never replaced
        with e.timed_action("write"):
            self.assertNotIn("fl_action", e.get_progress())
        self.assertEqual(e.get_progress()["stage"], "Composing")

    def test_status_does_not_wait_behind_a_busy_controller(self):
        e = Engine(session_file=os.path.join(self.tmp.name, "s.json"), trigger=SlowTrigger(), controller=SlowController())
        e.controller.lock = __import__("threading").Lock()
        e._ctl_cache = (time.time() - 10, {"connected": True, "detail": "Connected (API 45)", "channels": []})
        with e.controller.lock:                       # Veloura is in the middle of loading a kit
            t = time.time()
            st = e.controller_status()
            self.assertLess(time.time() - t, 0.1)
        self.assertTrue(st["connected"])
        self.assertTrue(st["busy"])

    def test_background_trigger_waits_for_a_started_command_instead_of_falling_back(self):
        results = iter([None] * 50 + [{"status": "applied"}])
        with mock.patch.object(fl_trigger, "BACKGROUND_WAIT", 0.05), \
                mock.patch.object(fl_trigger, "_post_shortcut_to_fl", return_value=True), \
                mock.patch.object(fl_trigger, "_activate_fl", side_effect=AssertionError("brought FL forward")):
            res, secs, n = fl_trigger.trigger_and_wait(lambda: next(results), timeout=5, get_started=lambda: True)
        self.assertEqual(res, {"status": "applied"})
        self.assertEqual(n, 1)

    def test_kits_are_staged_by_default(self):
        from veloura.engine import DEFAULT_SETTINGS
        self.assertFalse(DEFAULT_SETTINGS["kit_auto_load"])
        with open(os.path.join(ROOT, "app", "ui", "workspace.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("session.settings.kit_auto_load ? await withPending(() => api(\"/api/kit/load\"", js)


if __name__ == "__main__":
    unittest.main()
