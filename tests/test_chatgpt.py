"""ChatGPT sign-in and plan usage, against stand-in OpenAI responses (no network, no Keychain)."""

import base64
import io
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import ai, chatgpt  # noqa: E402


def memory_store(record=None):
    box = {"rec": dict(record) if record else None}
    s = chatgpt.Store(read=lambda: box["rec"], write=lambda r: box.update(rec=dict(r)), delete=lambda: box.update(rec=None))
    s.box = box
    return s


def id_token(**claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return "%s.%s.sig" % (enc({"alg": "RS256"}), enc(claims))


def sse(*events):
    return [("data: %s\n" % json.dumps(e)).encode() + b"\n" for e in events]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class SignInTests(unittest.TestCase):
    def setUp(self):
        chatgpt._login.update(state="idle", message="", server=None)

    def _sign_in(self, store, token_reply, callback_extra=None):
        posts = []

        def post(url, fields, **kw):
            posts.append((url, fields))
            return token_reply(fields, browser.nonce)

        def browser(url):
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
            browser.query = q
            cb = dict({"code": "the-code", "state": q["state"], "client_id": "oaiapp_123",
                       "scope": "chatgpt.tokens.use.direct email offline_access openid profile resource.invoke"},
                      **(callback_extra or {}))
            browser.nonce = q["nonce"]
            # The browser lands on Veloura's loopback page a moment later.
            def hit():
                time.sleep(0.2)
                urllib.request.urlopen(q["redirect_uri"] + "?" + urllib.parse.urlencode(cb), timeout=5).read()
            import threading
            threading.Thread(target=hit, daemon=True).start()

        chatgpt.start_login(open_browser=browser, store=store, post=post, timeout=5)
        for _ in range(100):
            if chatgpt._login["state"] != "waiting":
                break
            time.sleep(0.05)
        return browser, posts

    def test_first_sign_in_registers_and_saves_refresh_token(self):
        store = memory_store()
        browser, posts = self._sign_in(store, lambda f, nonce: {
            "access_token": "at1", "refresh_token": "rt1", "expires_in": 3600,
            "id_token": id_token(email="user@example.com", sub="u1", iss="https://auth.openai.com",
                                 nonce=nonce, exp=time.time() + 600)})
        q = browser.query
        self.assertEqual(q["client_id"], "dynamic_agent_client")
        self.assertEqual(q["agent_name_hint"], "Veloura")
        self.assertTrue(q["redirect_uri"].startswith("http://127.0.0.1:"))
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertIn("chatgpt.tokens.use.direct", q["scope"])
        self.assertEqual(q["resource"], "https://api.openai.com/v1")
        self.assertEqual(chatgpt._login["state"], "done", chatgpt._login["message"])
        url, fields = posts[0]
        self.assertEqual(fields["grant_type"], "authorization_code")
        self.assertEqual(fields["client_id"], "oaiapp_123")   # the issued id, never dynamic_agent_client
        self.assertEqual(fields["redirect_uri"], q["redirect_uri"])
        rec = store.box["rec"]
        self.assertEqual((rec["client_id"], rec["refresh_token"], rec["email"]), ("oaiapp_123", "rt1", "user@example.com"))
        self.assertNotIn("access_token", rec)   # access tokens stay in memory only
        self.assertTrue(chatgpt.status(store)["available"])

    def test_second_sign_in_reuses_issued_client_id(self):
        store = memory_store({"client_id": "oaiapp_123", "ext_agent_host_id": "urn:uuid:abc", "email": "t@x.com"})
        browser, _ = self._sign_in(store, lambda f, nonce: {"access_token": "a", "refresh_token": "r", "id_token": id_token(nonce=nonce)})
        self.assertEqual(browser.query["client_id"], "oaiapp_123")
        self.assertNotIn("agent_name_hint", browser.query)
        self.assertEqual(browser.query["ext_agent_host_id"], "urn:uuid:abc")

    def test_wrong_nonce_is_rejected(self):
        store = memory_store()
        self._sign_in(store, lambda f, nonce: {"access_token": "a", "refresh_token": "r", "id_token": id_token(nonce="nope")})
        self.assertEqual(chatgpt._login["state"], "error")
        self.assertNotIn("refresh_token", store.box["rec"] or {})

    def test_cancelled_sign_in(self):
        store = memory_store()
        self._sign_in(store, lambda f, nonce: self.fail("must not exchange a code"), callback_extra={"error": "access_denied", "code": ""})
        self.assertEqual(chatgpt._login["state"], "error")
        self.assertIn("cancelled", chatgpt._login["message"])

    def test_without_plan_scope_is_not_available(self):
        store = memory_store()
        self._sign_in(store, lambda f, nonce: {"access_token": "a", "refresh_token": "r", "scope": "openid email",
                                                     "id_token": id_token(nonce=nonce)})
        st = chatgpt.status(store)
        self.assertTrue(st["signed_in"])
        self.assertFalse(st["available"])


    def test_host_id_is_saved_before_the_browser_opens(self):
        store = memory_store()
        seen = {}
        chatgpt.start_login(open_browser=lambda u: seen.update(rec=dict(store.box["rec"] or {}), url=u), store=store,
                            post=lambda *a, **k: {}, timeout=0.3)
        self.assertTrue(seen["rec"]["ext_agent_host_id"].startswith("urn:uuid:"))
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(seen["url"]).query))
        self.assertEqual(q["ext_agent_host_id"], seen["rec"]["ext_agent_host_id"])
        time.sleep(0.5)

    def test_second_click_reuses_the_attempt_in_flight(self):
        store = memory_store()
        urls = []
        chatgpt.start_login(open_browser=urls.append, store=store, post=lambda *a, **k: {}, timeout=1)
        chatgpt.start_login(open_browser=urls.append, store=store, post=lambda *a, **k: {}, timeout=1)
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0], urls[1])   # same state, same PKCE challenge, same callback port
        time.sleep(1.3)

    def test_code_is_exchanged_once_even_if_the_callback_repeats(self):
        store = memory_store()
        posts = []
        def post(url, fields, **kw):
            posts.append(fields)
            return {"access_token": "a", "refresh_token": "r", "id_token": id_token(nonce=browser.nonce)}
        def browser(url):
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
            browser.nonce = q["nonce"]
            cb = {"code": "c", "state": q["state"], "client_id": "oaiapp_9"}
            def hit():
                for _ in range(3):
                    try:
                        urllib.request.urlopen(q["redirect_uri"] + "?" + urllib.parse.urlencode(cb), timeout=5).read()
                    except OSError:
                        pass   # the listener closes after the first good callback
            import threading
            threading.Thread(target=hit, daemon=True).start()
        chatgpt.start_login(open_browser=browser, store=store, post=post, timeout=5)
        for _ in range(100):
            if chatgpt._login["state"] != "waiting":
                break
            time.sleep(0.05)
        self.assertEqual(len(posts), 1)

    def test_invalid_grant_keeps_registration_and_explains(self):
        store = memory_store()
        def refuse(fields, nonce):
            raise chatgpt.ChatGPTError("ChatGPT sign-in failed (invalid_grant: Invalid authorization code).", code="invalid_grant")
        self._sign_in(store, refuse)
        self.assertEqual(chatgpt._login["state"], "error")
        self.assertEqual(chatgpt._login["message"], chatgpt.PLAN_MESSAGE)   # free ChatGPT accounts end up here
        self.assertEqual(chatgpt.status(store)["login_code"], "plan")
        self.assertEqual(store.box["rec"]["client_id"], "oaiapp_123")   # next try reuses it, per OpenAI
        self.assertNotIn("refresh_token", store.box["rec"])

    def test_token_errors_carry_the_description_and_a_user_agent(self):
        seen = {}
        def opener(req, timeout):
            seen["ua"] = req.get_header("User-agent")
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {},
                                         io.BytesIO(b'{"error":"invalid_grant","error_description":"Code expired"}'))
        with self.assertRaises(chatgpt.ChatGPTError) as cm:
            chatgpt._post_form(chatgpt.TOKEN_URL, {"code": "secret-code"}, opener=opener)
        self.assertEqual(cm.exception.code, "invalid_grant")
        self.assertIn("Code expired", str(cm.exception))
        self.assertNotIn("secret-code", str(cm.exception))
        self.assertTrue(seen["ua"].startswith("VelouraBeta/"))


    def test_upgrade_or_eligibility_errors_explain_the_plan_rule(self):
        for err in (chatgpt.ChatGPTError("x", code="subscription_sharing_user_not_eligible"),
                    chatgpt.ChatGPTError("ChatGPT sign-in failed (403: Upgrade your plan to continue).", code="403")):
            self.assertTrue(chatgpt._is_plan_problem(err))
        self.assertFalse(chatgpt._is_plan_problem(chatgpt.ChatGPTError("Could not reach ChatGPT: timeout")))
        self.assertIn("Google Gemini (free tier)", chatgpt.PLAN_MESSAGE)
        self.assertIn("Go, Plus or Pro", chatgpt.PLAN_MESSAGE)


class ModelCatalogTests(unittest.TestCase):
    def _opener(self, payload):
        def opener(req, timeout):
            self.assertEqual(req.full_url, "https://api.openai.com/v1/models")
            return FakeResponse(json.dumps(payload).encode())
        return opener

    def test_reads_the_plan_catalog_models_array_in_server_order(self):
        cat = {"models": [{"slug": "gpt-6.1-sol", "display_name": "GPT-6.1", "visibility": "list"},
                          {"slug": "hidden-one", "visibility": "hide"},
                          {"slug": "gpt-6.1-mini", "display_name": "GPT-6.1 mini", "visibility": "list"}]}
        self.assertEqual(chatgpt.pick_model("t", None, self._opener(cat)), "gpt-6.1-sol")
        self.assertEqual(chatgpt.pick_model("t", "gpt-6.1-mini", self._opener(cat)), "gpt-6.1-mini")
        self.assertEqual(chatgpt.pick_model("t", "not-listed", self._opener(cat)), "gpt-6.1-sol")

    def test_regular_api_shape_still_works(self):
        self.assertEqual(chatgpt.pick_model("t", None, self._opener({"data": [{"id": "m1"}]})), "m1")

    def test_really_empty_catalog_is_an_error(self):
        with self.assertRaises(chatgpt.ChatGPTError):
            chatgpt.pick_model("t", None, self._opener({"models": []}))


class TokenTests(unittest.TestCase):
    def test_refresh_rotates_and_saves_newest(self):
        store = memory_store({"client_id": "oaiapp_1", "refresh_token": "rt_old"})
        seen = []
        post = lambda url, f, **kw: seen.append(f) or {"access_token": "new", "refresh_token": "rt_new", "expires_in": 3600}
        self.assertEqual(chatgpt.access_token(store, post), "new")
        self.assertEqual(seen[0]["grant_type"], "refresh_token")
        self.assertEqual(seen[0]["client_id"], "oaiapp_1")
        self.assertNotIn("scope", seen[0])
        self.assertEqual(store.box["rec"]["refresh_token"], "rt_new")
        self.assertEqual(chatgpt.access_token(store, lambda *a, **k: self.fail("cached token should be used")), "new")

    def test_expired_refresh_signs_out_but_keeps_client_id(self):
        store = memory_store({"client_id": "oaiapp_1", "refresh_token": "rt", "email": "e@x.com"})

        def post(url, f, **kw):
            raise chatgpt.ChatGPTError("x", code="refresh_token_expired")
        with self.assertRaises(chatgpt.ChatGPTError) as c:
            chatgpt.access_token(store, post)
        self.assertEqual(c.exception.code, "signed_out")
        self.assertEqual(store.box["rec"], {"client_id": "oaiapp_1", "email": "e@x.com"})


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.store = memory_store({"client_id": "oaiapp_1", "refresh_token": "rt"})
        self.store.access_token, self.store.expires_at = "tok", time.time() + 3600
        self.bodies = []

    def opener(self, responses):
        def op(req, timeout=None):
            if isinstance(req, str) or req.full_url.endswith("/models"):
                return FakeResponse(json.dumps({"data": [{"slug": "gpt-hidden", "visibility": "hide"},
                                                         {"slug": "gpt-6.1-sol", "visibility": "list"}]}).encode())
            self.bodies.append(json.loads(req.data))
            self.assertEqual(req.headers["Authorization"], "Bearer tok")
            r = responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return FakeResponse(b"".join(r))
        return op

    def test_streams_text_and_follows_the_rules(self):
        lines = sse({"type": "response.output_text.delta", "delta": '{"reply": "hi",'},
                    {"type": "response.output_text.delta", "delta": ' "parts": []}'},
                    {"type": "response.completed", "response": {"model": "gpt-6.1-sol", "usage": {"input_tokens": 5}}})
        text, usage, model = chatgpt.generate("SYS", "make a beat", {"type": "object"}, store=self.store, opener=self.opener([lines]))
        self.assertEqual(json.loads(text), {"reply": "hi", "parts": []})
        self.assertEqual(model, "gpt-6.1-sol")
        b = self.bodies[0]
        self.assertEqual((b["store"], b["stream"], b["model"], b["instructions"]), (False, True, "gpt-6.1-sol", "SYS"))
        self.assertTrue(all(m["role"] != "system" for m in b["input"]))
        for banned in ("temperature", "max_output_tokens", "top_p", "previous_response_id"):
            self.assertNotIn(banned, b)

    def test_drops_structured_output_if_unsupported(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(json.dumps(
            {"error": {"code": "subscription_sharing_unsupported_capability", "param": "text.format"}}).encode()))
        ok = sse({"type": "response.output_text.delta", "delta": "{}"}, {"type": "response.completed", "response": {}})
        chatgpt.generate("S", "m", {}, store=self.store, opener=self.opener([err, ok]))
        self.assertIn("text", self.bodies[0])
        self.assertNotIn("text", self.bodies[1])

    def test_usage_limit_is_friendly(self):
        lines = sse({"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}})
        with self.assertRaises(chatgpt.ChatGPTError) as c:
            chatgpt.generate("S", "m", {}, store=self.store, opener=self.opener([lines]))
        self.assertIn("Manage usage", str(c.exception))

    def test_overloaded_is_retried_then_succeeds(self):
        busy = sse({"type": "response.failed", "response": {"error": {"code": "server_error",
                                                                      "message": "Our servers are currently overloaded. Please try again later."}}})
        ok = sse({"type": "response.output_text.delta", "delta": "{}"}, {"type": "response.completed", "response": {"usage": {}}})
        waits = []
        text, _, _ = chatgpt.generate("S", "m", {}, store=self.store, opener=self.opener([busy, busy, ok]), sleep=waits.append)
        self.assertEqual(text, "{}")
        self.assertEqual(waits, [2, 5])

    def test_usage_limit_is_never_retried(self):
        lines = sse({"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}})
        waits = []
        with self.assertRaises(chatgpt.ChatGPTError):
            chatgpt.generate("S", "m", {}, store=self.store, opener=self.opener([lines, lines]), sleep=waits.append)
        self.assertEqual(waits, [])

    def test_dropped_connection_is_retried_once_then_explained(self):
        ok = sse({"type": "response.output_text.delta", "delta": "{}"}, {"type": "response.completed", "response": {}})
        waits = []
        text, _, _ = chatgpt.generate("S", "m", {}, store=self.store, opener=self.opener([ConnectionResetError(54, "reset"), ok]),
                                      sleep=waits.append)
        self.assertEqual((text, waits), ("{}", [2]))
        with self.assertRaises(chatgpt.ChatGPTError) as c:   # never a bare "internal error"
            chatgpt.generate("S", "m", {}, store=self.store, sleep=waits.append,
                             opener=self.opener([ConnectionResetError(54, "reset"), ConnectionResetError(54, "reset")]))
        self.assertIn("connection to ChatGPT dropped", str(c.exception))

    def test_read_timeout_is_explained(self):
        import socket
        with self.assertRaises(chatgpt.ChatGPTError) as c:
            chatgpt.generate("S", "m", {}, store=self.store, opener=self.opener([socket.timeout("timed out")]))
        self.assertIn("took too long", str(c.exception))

    def test_stream_without_completed_is_an_error(self):
        lines = sse({"type": "response.output_text.delta", "delta": "{"})
        with self.assertRaises(chatgpt.ChatGPTError):
            chatgpt.generate("S", "m", {}, store=self.store, opener=self.opener([lines]))

    def test_veloura_provider_uses_chatgpt(self):
        with mock.patch.object(chatgpt, "generate", return_value=('{"reply": "ok", "parts": []}', {"input_tokens": 1}, "gpt-x")), \
                mock.patch.object(ai, "record_usage") as rec:
            self.assertEqual(ai._call_chatgpt("hello", None), {"reply": "ok", "parts": []})
        rec.assert_called_once_with("chatgpt", "gpt-x", {"input_tokens": 1})
        self.assertIn("chatgpt", ai.provider_status())


if __name__ == "__main__":
    unittest.main()
