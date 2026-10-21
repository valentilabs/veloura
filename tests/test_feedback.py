"""Send feedback: what goes in the payload, and success/failure handling (network mocked)."""
import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from veloura import edition, feedback


class FakeResp:
    def __init__(self, status):
        self.status = status
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class FeedbackTests(unittest.TestCase):
    def test_posts_json_with_only_the_allowed_fields(self):
        seen = {}
        def urlopen(req, timeout):
            seen["req"] = req
            return FakeResp(200)
        out = feedback.send("  Love it  ", "me@example.com", urlopen=urlopen)
        self.assertEqual(out, {"ok": True, "status": 200})
        req = seen["req"]
        self.assertEqual(req.full_url, "https://formspree.io/f/xgaobplj")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Accept"), "application/json")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertTrue(req.get_header("User-agent").startswith("VelouraBeta/"))
        body = json.loads(req.data)
        self.assertEqual(set(body), {"message", "_replyto", "app_version", "macos_version"})
        self.assertEqual(body["message"], "Love it")
        self.assertEqual(body["_replyto"], "me@example.com")
        self.assertIn(edition.VERSION, body["app_version"])
        self.assertNotIn(os.path.expanduser("~"), json.dumps(body))

    def test_email_is_optional(self):
        self.assertNotIn("_replyto", feedback.payload("hi", ""))

    def test_rejects_empty_message_and_bad_email(self):
        with self.assertRaises(feedback.FeedbackError):
            feedback.payload("   ")
        with self.assertRaises(feedback.FeedbackError):
            feedback.payload("hi", "not an email")

    def test_http_and_network_errors_become_short_messages(self):
        def http_err(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 422, "x", {}, io.BytesIO(b""))
        with self.assertRaisesRegex(feedback.FeedbackError, "HTTP 422"):
            feedback.send("hi", urlopen=http_err)
        def offline(req, timeout):
            raise urllib.error.URLError("no route")
        with self.assertRaisesRegex(feedback.FeedbackError, "internet"):
            feedback.send("hi", urlopen=offline)

    def test_ui_has_the_form_and_no_mailto(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "app", "ui", "app.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('api("/api/feedback"', js)
        self.assertIn("Your email, if you want a reply", js)
        self.assertNotIn("mailto:", js)


if __name__ == "__main__":
    unittest.main()
