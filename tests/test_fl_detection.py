"""FL detection and Accessibility must not depend on System Events (it can hang and make FL look closed)."""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from veloura import fl_trigger  # noqa: E402


class FLDetectionTests(unittest.TestCase):
    def test_fl_running_uses_process_list_not_apple_events(self):
        with mock.patch.object(fl_trigger, "_osascript", side_effect=AssertionError("System Events used")), \
                mock.patch.object(fl_trigger.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "4242\n", "")) as run:
            self.assertTrue(fl_trigger.fl_running())
        self.assertEqual(run.call_args[0][0], ["/usr/bin/pgrep", "-x", "OsxFL"])
        with mock.patch.object(fl_trigger.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
            self.assertFalse(fl_trigger.fl_running())

    def test_accessibility_prefers_in_process_check(self):
        with mock.patch.object(fl_trigger, "_ax_trusted", return_value=True), \
                mock.patch.object(fl_trigger, "_osascript", side_effect=AssertionError("System Events used")):
            self.assertTrue(fl_trigger.accessibility_enabled())
        with mock.patch.object(fl_trigger, "_ax_trusted", return_value=None), \
                mock.patch.object(fl_trigger, "_osascript", return_value="true"):
            self.assertTrue(fl_trigger.accessibility_enabled())

    def test_ax_trusted_answers_on_this_mac(self):
        self.assertIn(fl_trigger._ax_trusted(), (True, False))

    def test_hung_system_events_does_not_block(self):
        """The background trigger doesn't need System Events, so a hung System Events no longer blocks writes."""
        with mock.patch.object(fl_trigger, "fl_running", return_value=True), \
                mock.patch.object(fl_trigger, "accessibility_enabled", return_value=True), \
                mock.patch.object(fl_trigger, "_osascript", side_effect=subprocess.TimeoutExpired("osascript", 4)):
            self.assertEqual(fl_trigger.preflight(), [])

    def test_background_trigger_never_switches_apps(self):
        results = iter([None, None, {"status": "applied"}])
        with mock.patch.object(fl_trigger, "_post_shortcut_to_fl", return_value=True), \
                mock.patch.object(fl_trigger, "_osascript", side_effect=AssertionError("switched apps")):
            res, secs, n = fl_trigger.trigger_and_wait(lambda: next(results), timeout=2)
        self.assertEqual(res, {"status": "applied"})
        self.assertEqual(n, 1)
        self.assertEqual(fl_trigger.last_trigger["mode"], "background")

    def test_falls_back_to_the_foreground_shortcut(self):
        calls = []
        state = {"n": 0}
        def get():
            return {"status": "snapshot"} if calls else None
        with mock.patch.object(fl_trigger, "BACKGROUND_WAIT", 0.1), \
                mock.patch.object(fl_trigger, "_post_shortcut_to_fl", return_value=True), \
                mock.patch.object(fl_trigger, "frontmost_app", return_value="Veloura"), \
                mock.patch.object(fl_trigger, "_activate_fl", side_effect=lambda: calls.append("activate")), \
                mock.patch.object(fl_trigger, "_send_rerun_shortcut", side_effect=lambda: calls.append("keys")), \
                mock.patch.object(fl_trigger, "_restore", side_effect=lambda app: calls.append("restore " + str(app))):
            res, secs, n = fl_trigger.trigger_and_wait(get, timeout=2)
        self.assertEqual(res, {"status": "snapshot"})
        self.assertEqual(calls, ["activate", "keys", "restore Veloura"])
        self.assertEqual(fl_trigger.last_trigger["mode"], "foreground")

    def test_first_system_events_contact_waits_for_the_permission_prompt(self):
        calls = []
        with mock.patch.dict(fl_trigger._system_events_ok, {"seen": False}), \
                mock.patch.object(fl_trigger, "_osascript", side_effect=lambda lines, timeout=5: calls.append(timeout)):
            self.assertTrue(fl_trigger.system_events_responding())
            self.assertTrue(fl_trigger.system_events_responding())
        self.assertEqual(calls, [120, 4])


if __name__ == "__main__":
    unittest.main()
