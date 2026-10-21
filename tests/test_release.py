"""Customer (beta) build rules: no personal Claude login, no credits, Haiku default, keys never on a command line."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from veloura import ai, bridge_protocol as bp, edition  # noqa: E402


class EditionTests(unittest.TestCase):
    def test_dev_mode_is_off_unless_asked_for(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VELOURA_DEV_MODE", None)
            with mock.patch.object(edition, "DEV_FLAG_FILE", "/nonexistent/dev_mode"), \
                    mock.patch.object(edition, "OLD_DEV_FLAG_FILE", "/nonexistent/old_dev_mode"):
                self.assertFalse(edition.dev_mode())
        with mock.patch.dict(os.environ, {"VELOURA_DEV_MODE": "1"}):
            self.assertTrue(edition.dev_mode())
        with mock.patch.dict(os.environ, {"CADENCE_DEV_MODE": "1"}):   # the old name still works
            os.environ.pop("VELOURA_DEV_MODE", None)
            self.assertTrue(edition.dev_mode())
        with tempfile.NamedTemporaryFile() as f, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VELOURA_DEV_MODE", None)
            with mock.patch.object(edition, "DEV_FLAG_FILE", f.name):
                self.assertTrue(edition.dev_mode())

    def test_customers_get_chatgpt_first_and_no_claude_code(self):
        with mock.patch.object(ai, "DEV_MODE", False):
            self.assertEqual(ai.customer_providers()[0], "chatgpt")
            self.assertNotIn("claude-code", ai.customer_providers())
            with mock.patch.object(ai.chatgpt, "status", return_value={"available": False}):
                self.assertNotIn("claude-code", ai.provider_status())
            with self.assertRaises(ai.ProviderError):
                ai.respond("claude-code", "x", {"provider": "claude-code", "bars": 4, "key": "F minor"}, {}, [], seed=1)
        with mock.patch.object(ai, "DEV_MODE", True):
            self.assertIn("claude-code", ai.customer_providers())

    def test_no_credits_and_haiku_is_the_customer_default(self):
        self.assertEqual(ai.PRODUCT_DEFAULT_MODEL, "claude-haiku-5-5")
        self.assertFalse(hasattr(ai, "CREDIT_ALLOWANCE"))
        self.assertTrue(all("cost" in m and "credits" not in m for m in ai.CLAUDE_MODELS))

    def test_a_saved_personal_provider_is_reset_for_customers(self):
        from test_controller import FakeTrigger
        from veloura.engine import Engine
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bp, "LOG_DIR", os.path.join(d, "logs")), \
                mock.patch.object(ai, "DEV_MODE", False):
            with open(os.path.join(d, "s.json"), "w") as f:
                json.dump({"settings": {"provider": "claude-code"}}, f)
            e = Engine(session_file=os.path.join(d, "s.json"), trigger=FakeTrigger())
            self.assertEqual(e.state["settings"]["provider"], "offline")
            e.update_settings({"provider": "claude-code"})
            self.assertEqual(e.state["settings"]["provider"], "offline")
            self.assertNotIn("credits", e.snapshot_state())
            self.assertEqual(e.snapshot_state()["app"]["version"], edition.VERSION)


class KeychainTests(unittest.TestCase):
    def test_key_goes_through_stdin_not_the_command_line(self):
        with mock.patch.object(ai.subprocess, "run", return_value=mock.Mock(returncode=0, stderr="")) as run:
            ai._keychain_set("Veloura test", "sk-ant-api03-SECRET")
        argv, kwargs = run.call_args[0][0], run.call_args[1]
        self.assertEqual(argv, ["/usr/bin/security", "-i"])
        self.assertNotIn("SECRET", " ".join(argv))
        self.assertIn("SECRET", kwargs["input"])

    def test_odd_characters_are_refused(self):
        for bad in ('sk-ant-"x', "sk-ant-a b", "sk-ant-\nx", ""):
            with self.assertRaises(ValueError):
                ai._keychain_set("Veloura test", bad)


if __name__ == "__main__":
    unittest.main()


class HousekeepingTests(unittest.TestCase):
    def test_old_bridge_results_are_tidied_but_ledgers_stay(self):
        import time as _t
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bp, "BRIDGE_DIR", d):
            old = _t.time() - 8 * 24 * 3600
            for n in ("result-a.json", "result-a.done", "started-a.marker", "ledger-a.json", "removed-a.marker", "result-b.json"):
                open(os.path.join(d, n), "w").close()
            for n in ("result-a.json", "result-a.done", "started-a.marker", "ledger-a.json", "removed-a.marker"):
                os.utime(os.path.join(d, n), (old, old))
            self.assertEqual(bp.tidy_bridge_dir(), 3)
            self.assertEqual(sorted(os.listdir(d)), ["ledger-a.json", "removed-a.marker", "result-b.json"])

    def test_sent_records_are_capped(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bp, "LOG_DIR", d):
            os.makedirs(bp.sent_dir())
            for i in range(12):
                p = os.path.join(bp.sent_dir(), "cad-%02d.json" % i)
                open(p, "w").close()
                os.utime(p, (1000 + i, 1000 + i))
            bp._prune_sent(keep=5)
            self.assertEqual(len(os.listdir(bp.sent_dir())), 5)

    def test_usage_log_rolls_over(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bp, "LOG_DIR", d):
            with open(os.path.join(d, "ai_usage.jsonl"), "w") as f:
                f.write("x" * 2_000_100)
            ai.record_usage("anthropic", "m", {"input_tokens": 1})
            self.assertTrue(os.path.exists(os.path.join(d, "ai_usage.1.jsonl")))
            self.assertLess(os.path.getsize(os.path.join(d, "ai_usage.jsonl")), 1000)


class ServiceSecurityTests(unittest.TestCase):
    def test_request_log_never_contains_the_token(self):
        import io
        from veloura import service
        handler = service.make_handler(mock.Mock(), "SECRETTOKEN", [8765])
        h = handler.__new__(handler)
        err = io.StringIO()
        with mock.patch.object(service.sys, "stderr", err):
            h.log_message('"%s" %s %s', "GET /api/library/audio?id=1&t=SECRETTOKEN HTTP/1.1", "200", "-")
        self.assertNotIn("SECRETTOKEN", err.getvalue())
        self.assertTrue(h._token_ok("SECRETTOKEN"))
        self.assertFalse(h._token_ok("SECRETTOKEn"))
        self.assertFalse(h._token_ok(None))


class ServiceTokenTests(unittest.TestCase):
    """The app hands the service its token in the environment, never on the command line (ps shows arguments)."""

    def test_main_js_passes_token_in_env_not_argv(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "app", "main.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn("VELOURA_SERVICE_TOKEN: token", js)
        self.assertNotIn('"--token"', js)

    def test_service_reads_and_removes_env_token(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "veloura", "service.py"), encoding="utf-8") as f:
            py = f.read()
        self.assertIn('os.environ.pop("VELOURA_SERVICE_TOKEN", None)', py)


class BuildHygieneTests(unittest.TestCase):
    """Builds never leave a launchable copy behind: macOS could open it instead of /Applications/Veloura.app
    (a quarantined test copy shows "Apple could not verify Veloura")."""

    def _read(self, *parts):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, *parts), encoding="utf-8") as f:
            return f.read()

    def test_zip_check_unregisters_and_deletes_its_quarantined_copy(self):
        js = self._read("app", "build", "sign-adhoc.js")
        fin = js[js.index("} finally {", js.index("function checkZip")):]
        self.assertLess(fin.index("unregister("), fin.index("fs.rmSync(tmp"))

    def test_package_keeps_one_unregistered_copy(self):
        js = self._read("app", "build", "package.js")
        self.assertIn('require("./sign-adhoc").unregister(built)', js)
        self.assertNotIn('path.join(ROOT, "dist"', js)   # no second copy in the project folder
