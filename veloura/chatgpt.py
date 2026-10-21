"""ChatGPT provider: "Continue with ChatGPT", so each user's beats run on their own ChatGPT plan (Go, Plus or Pro).

Built from OpenAI's "Sign in with ChatGPT" docs for open-source, locally run apps
(developers.openai.com/siwc/token-sharing-open-source, read 2026-10-18; the program is in preview):
  * OAuth with PKCE (S256) in the user's browser, with a loopback callback on 127.0.0.1 (never "localhost").
  * First sign-in registers with client_id=dynamic_agent_client; the callback returns the issued client id
    (oaiapp_...), which is saved and reused for every later sign-in and refresh.
  * Access tokens last 1 hour and are kept in memory only. The refresh token (30 days, rotates on every refresh)
    is saved in the macOS Keychain, never in files or logs.
  * Inference: POST https://api.openai.com/v1/responses with store=false and stream=true. System messages,
    temperature and max_output_tokens are rejected, so Veloura's prompt goes in "instructions".
Uses only the standard library (Python 3.9).
"""

import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

AUTH_BASE = "https://auth.openai.com"
AUTHORIZE_URL = AUTH_BASE + "/api/accounts/authorize"
TOKEN_URL = AUTH_BASE + "/api/accounts/oauth/token"
OIDC_CONFIG_URL = AUTH_BASE + "/.well-known/openid-configuration"
API_BASE = "https://api.openai.com/v1"
RESOURCE = API_BASE
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
APP_NAME = "Veloura"
PORTS = [1455, 1456, 1457, 1458, 1459]
LOGIN_TIMEOUT = 300
REQUEST_TIMEOUT = 180
KEYCHAIN_SERVICE = "Veloura ChatGPT sign-in"
KEYCHAIN_ACCOUNT = "veloura"
USAGE_URL = "https://chatgpt.com/settings/usage"
REASONING_EFFORT = None   # None: the model's default. "low" | "medium" | "high" are accepted on the plan route (2026-10-20)
USER_AGENT = "VelouraBeta/0.9.0 (Macintosh; macOS)"   # Cloudflare in front of OpenAI can refuse Python's default agent


class ChatGPTError(RuntimeError):
    """A failure to show the user as is. `code` is OpenAI's error code when there is one."""

    def __init__(self, message, code=None):
        RuntimeError.__init__(self, message)
        self.code = code


# ---------- saved sign-in (macOS Keychain) ----------

OLD_KEYCHAIN_SERVICE, OLD_KEYCHAIN_ACCOUNT = "Cadence ChatGPT sign-in", "cadence"   # before the rename (2026-10-21)


def _keychain_read_item(service, account):
    try:
        p = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        return json.loads(base64.b64decode(p.stdout.strip()).decode("utf-8"))
    except (ValueError, TypeError):
        return None


def _keychain_read():
    rec = _keychain_read_item(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    if rec is not None:
        return rec
    old = _keychain_read_item(OLD_KEYCHAIN_SERVICE, OLD_KEYCHAIN_ACCOUNT)
    if old is not None:   # signed in before the rename: move the sign-in so it keeps working
        try:
            _keychain_write(old)
            subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", OLD_KEYCHAIN_SERVICE, "-a",
                            OLD_KEYCHAIN_ACCOUNT], capture_output=True, text=True, timeout=10)
        except (ChatGPTError, OSError, subprocess.TimeoutExpired):
            pass
    return old


def _keychain_write(record):
    # The secret goes through stdin (security's interactive mode), not the command line, so other programs on the
    # Mac can't read it from the process list. Base64 keeps it free of spaces and quotes.
    blob = base64.b64encode(json.dumps(record, separators=(",", ":")).encode("utf-8")).decode("ascii")
    cmd = 'add-generic-password -U -s "%s" -a "%s" -w %s\n' % (KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, blob)
    p = subprocess.run(["/usr/bin/security", "-i"], input=cmd, capture_output=True, text=True, timeout=10)
    if p.returncode != 0 or "error" in (p.stderr or "").lower():
        raise ChatGPTError("Could not save your ChatGPT sign-in to the Keychain: %s" % (p.stderr or "").strip()[:200])


def _keychain_delete():
    try:
        subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
                       capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


class Store:
    """The saved sign-in plus the in-memory access token. Swappable in tests."""

    def __init__(self, read=_keychain_read, write=_keychain_write, delete=_keychain_delete):
        self._read, self._write, self._delete = read, write, delete
        self.lock = threading.Lock()
        self.access_token = None
        self.expires_at = 0

    def load(self):
        return self._read() or {}

    def save(self, record):
        self._write(record)

    def clear(self, keep_registration=True):
        """Forget the tokens. The issued client id and host id are kept, since OpenAI asks apps to reuse them."""
        old = self.load()
        self.access_token, self.expires_at = None, 0
        if keep_registration and old.get("client_id"):
            self._write({k: old[k] for k in ("client_id", "ext_agent_host_id", "email") if old.get(k)})
        else:
            self._delete()


STORE = Store()


def _host_id(record):
    # Opaque and distinct per install (OpenAI: not an email or user id).
    return record.get("ext_agent_host_id") or "urn:uuid:%s" % uuid.uuid4()


# ---------- sign-in ----------

def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt_claims(token):
    """Read an ID token's claims. The token comes straight from auth.openai.com over TLS in our own code exchange,
    which OpenID Connect allows in place of checking the signature (OIDC Core 3.1.3.7)."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8"))
    except (IndexError, ValueError, AttributeError):
        return {}


def _post_form(url, fields, timeout=30, opener=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode("ascii"), method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
                                          "User-Agent": USER_AGENT})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(detail)
        except ValueError:
            err = {}
        code = err.get("error") if isinstance(err.get("error"), str) else (err.get("error") or {}).get("code")
        e_obj = err.get("error") if isinstance(err, dict) else None
        desc = (err.get("error_description") if isinstance(err, dict) else "") or \
            (e_obj.get("message") if isinstance(e_obj, dict) else "")
        desc = " ".join(str(desc or "").split())[:160]
        # Log the status, the error code and OpenAI's description only: never the request (codes, tokens, verifier).
        print("chatgpt: %s -> HTTP %s %s%s" % (urllib.parse.urlparse(url).path, e.code, code or "", (": " + desc) if desc else ""),
              file=sys.stderr, flush=True)
        raise ChatGPTError("ChatGPT sign-in failed (%s%s)." % (code or e.code, (": " + desc) if desc else ""),
                           code=code or str(e.code))
    except (urllib.error.URLError, socket.timeout) as e:
        raise ChatGPTError("Could not reach ChatGPT: %s" % getattr(e, "reason", e))


_login = {"state": "idle", "message": "", "server": None, "url": None, "code": None}   # idle | waiting | done | error

# OpenAI refuses free ChatGPT accounts for plan use. Seen as invalid_grant at the code exchange (the browser still says
# it worked) or an eligibility / upgrade error. Veloura then explains the plan rule and offers the free alternatives.
PLAN_MESSAGE = ("Veloura needs ChatGPT Go, Plus or Pro. On the free plan, use Google Gemini (free tier) or Offline instead.")
PLAN_CODES = {"invalid_grant", "subscription_sharing_user_not_eligible", "unsupported_plan", "plan_not_eligible"}


def _is_plan_problem(err):
    text = str(err).lower()
    return (getattr(err, "code", None) in PLAN_CODES or "upgrade" in text or "eligib" in text
            or ("plan" in text and "chatgpt sign-in failed" in text))
_login_lock = threading.Lock()


def login_status():
    return {"state": _login["state"], "message": _login["message"]}


def _bind_callback_server(handler):
    for port in PORTS:
        try:
            return HTTPServer(("127.0.0.1", port), handler)
        except OSError:
            continue
    return HTTPServer(("127.0.0.1", 0), handler)


def start_login(open_browser=None, store=None, post=_post_form, timeout=LOGIN_TIMEOUT):
    """Open "Continue with ChatGPT" in the browser and finish in the background. Returns the URL that was opened.
    The UI polls login_status() / provider status to see the result."""
    store = store or STORE
    with _login_lock:
        # One attempt at a time: a second click re-opens the same page instead of starting a new attempt, so the
        # browser can never come back with a code minted for a verifier Veloura has already thrown away.
        if _login["state"] == "waiting" and _login.get("server") and _login.get("url"):
            url = _login["url"]
            (open_browser or (lambda u: subprocess.run(["/usr/bin/open", u], timeout=15)))(url)
            return url
    record = store.load()
    host_id = _host_id(record)
    if not record.get("ext_agent_host_id"):
        # OpenAI: choose and persist the host id before the first sign-in.
        record = dict(record, ext_agent_host_id=host_id)
        try:
            store.save(record)
        except ChatGPTError:
            pass
    client_id = record.get("client_id")
    verifier = _b64url(secrets.token_bytes(48))
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    result = {}
    done = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *a):   # keep codes and tokens out of logs
            pass

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            if done.is_set():
                ok, text = True, "Already done. You can close this tab and go back to Veloura."
            elif q.get("state") != state:
                ok, text = False, "This sign-in link doesn't match. Go back to Veloura and try again."
            elif q.get("error"):
                result["error"] = q.get("error")
                ok, text = False, "Sign-in was cancelled. You can close this tab."
            else:
                result.update(q)
                ok, text = True, "You're signed in to Veloura with ChatGPT. You can close this tab and go back to Veloura."
            page = ("<!doctype html><meta charset=utf-8><title>Veloura</title><body style='font:16px -apple-system,sans-serif;"
                    "padding:40px;background:#0b1020;color:#e8ecf5'><h2>%s</h2><p>%s</p>" % ("Done" if ok else "Not signed in", text))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            if (ok or result.get("error")) and not done.is_set():
                done.set()

    server = _bind_callback_server(Callback)
    redirect_uri = "http://127.0.0.1:%d/auth/callback" % server.server_address[1]
    params = {"response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPES, "resource": RESOURCE,
              "state": state, "nonce": nonce, "code_challenge_method": "S256",
              "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
              "ext_agent_host_id": host_id}
    if client_id:
        params["client_id"] = client_id
        if record.get("email"):
            params["login_hint"] = record["email"]
    else:
        params.update(client_id="dynamic_agent_client", agent_name_hint=APP_NAME)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)

    with _login_lock:
        if _login.get("server"):
            try:
                _login["server"].shutdown()
            except OSError:
                pass
        attempt = object()   # this attempt's identity: a late finish of an older attempt must not overwrite it
        _login.update(state="waiting", message="Finish signing in in your browser.", server=server, url=url, code=None,
                      attempt=attempt)

    def finish(**kw):
        with _login_lock:
            if _login.get("attempt") is attempt:
                _login.update(server=None, url=None, **kw)

    def serve():
        threading.Thread(target=server.serve_forever, daemon=True).start()
        finished = done.wait(timeout)
        server.shutdown()
        server.server_close()
        try:
            if not finished:
                raise ChatGPTError("Sign-in timed out. Click Continue with ChatGPT to try again.")
            if result.get("error"):
                raise ChatGPTError("Sign-in was cancelled." if result["error"] == "access_denied"
                                   else "ChatGPT sign-in failed (%s)." % result["error"], code=result["error"])
            issued = result.get("client_id") or client_id
            if not issued or issued == "dynamic_agent_client":
                raise ChatGPTError("ChatGPT didn't return an app id. Try again.")
            if client_id and result.get("client_id") and result["client_id"] != client_id:
                raise ChatGPTError("ChatGPT answered for a different Veloura connection. Try again.")
            if not client_id:
                # Keep the new registration right away (OpenAI: retain the issued id, even if the exchange fails).
                try:
                    store.save({k: v for k, v in dict(record, client_id=issued).items()
                                if k in ("client_id", "ext_agent_host_id", "email")})
                except ChatGPTError:
                    pass
            tok = post(TOKEN_URL, {"grant_type": "authorization_code", "client_id": issued, "code": result.get("code", ""),
                                   "code_verifier": verifier, "redirect_uri": redirect_uri, "resource": RESOURCE})
            claims = _jwt_claims(tok.get("id_token", ""))
            if claims and (claims.get("nonce") not in (None, nonce) or claims.get("iss") not in (None, AUTH_BASE, AUTH_BASE + "/")
                           or (claims.get("exp") and claims["exp"] < time.time() - 60)):
                raise ChatGPTError("ChatGPT's sign-in reply didn't check out. Try again.")
            if not tok.get("access_token"):
                raise ChatGPTError("ChatGPT didn't return a sign-in token. Try again.")
            scopes = (tok.get("scope") or result.get("scope") or "").replace("+", " ").split()
            rec = {"client_id": issued, "ext_agent_host_id": host_id, "refresh_token": tok.get("refresh_token"),
                   "email": claims.get("email") or record.get("email"), "subject": claims.get("sub"),
                   "scopes": scopes, "saved_at": int(time.time())}
            store.save(rec)
            with store.lock:
                store.access_token = tok["access_token"]
                store.expires_at = time.time() + int(tok.get("expires_in") or 3600)
            msg = "Signed in as %s." % (rec["email"] or "your ChatGPT account")
            if PLAN_SCOPE not in scopes:
                msg += " Plan use wasn't turned on, so Veloura can't use your ChatGPT plan yet."
            finish(state="done", message=msg, code=None)
        except ChatGPTError as e:
            if _is_plan_problem(e):
                finish(state="error", message=PLAN_MESSAGE, code="plan")
            else:
                finish(state="error", message=str(e), code=e.code)

    threading.Thread(target=serve, daemon=True).start()
    (open_browser or (lambda u: subprocess.run(["/usr/bin/open", u], timeout=15)))(url)
    return url


def _revocation_endpoint(opener=None):
    try:
        with (opener or urllib.request.urlopen)(OIDC_CONFIG_URL, timeout=15) as r:
            return json.loads(r.read().decode("utf-8")).get("revocation_endpoint")
    except (urllib.error.URLError, socket.timeout, ValueError):
        return None


def sign_out(store=None, post=_post_form):
    store = store or STORE
    rec = store.load()
    if rec.get("refresh_token") and rec.get("client_id"):
        endpoint = _revocation_endpoint()
        if endpoint:
            try:
                post(endpoint, {"token": rec["refresh_token"], "token_type_hint": "refresh_token", "client_id": rec["client_id"]})
            except ChatGPTError:
                pass   # signing out locally still works
    store.clear(keep_registration=True)
    _login.update(state="idle", message="", url=None)


TERMINAL_REFRESH = {"invalid_grant", "invalid_refresh_token", "token_expired", "refresh_token_expired",
                    "refresh_token_invalidated", "refresh_token_reused"}


def access_token(store=None, post=_post_form):
    """A valid access token, refreshing it when it's within 2 minutes of expiring. Refreshes run one at a time."""
    store = store or STORE
    with store.lock:
        if store.access_token and time.time() < store.expires_at - 120:
            return store.access_token
        rec = store.load()
        if not rec.get("refresh_token") or not rec.get("client_id"):
            raise ChatGPTError("Not signed in to ChatGPT. Click Continue with ChatGPT in Settings.", code="signed_out")
        try:
            tok = post(TOKEN_URL, {"grant_type": "refresh_token", "client_id": rec["client_id"],
                                   "refresh_token": rec["refresh_token"], "resource": RESOURCE})
        except ChatGPTError as e:
            if e.code in TERMINAL_REFRESH:
                store.access_token, store.expires_at = None, 0
                store._write({k: rec[k] for k in ("client_id", "ext_agent_host_id", "email") if rec.get(k)})
                raise ChatGPTError("Your ChatGPT sign-in expired. Click Continue with ChatGPT in Settings.", code="signed_out")
            raise
        if tok.get("refresh_token") and tok["refresh_token"] != rec["refresh_token"]:
            rec["refresh_token"] = tok["refresh_token"]   # rotating: always keep the newest one
            rec["saved_at"] = int(time.time())
            store.save(rec)
        store.access_token = tok.get("access_token")
        store.expires_at = time.time() + int(tok.get("expires_in") or 3600)
        if not store.access_token:
            raise ChatGPTError("ChatGPT didn't return a token. Try again.")
        return store.access_token


def status(store=None):
    rec = (store or STORE).load()
    signed_in = bool(rec.get("refresh_token"))
    plan = PLAN_SCOPE in (rec.get("scopes") or [])
    if _login["state"] == "waiting":
        detail = _login["message"]
    elif not signed_in:
        detail = _login["message"] if _login["state"] == "error" else "Not signed in. Needs ChatGPT Go, Plus or Pro."
    elif not plan:
        detail = "Signed in as %s, but plan use is off, so Veloura can't use your plan." % (rec.get("email") or "you")
    else:
        detail = "Using your ChatGPT plan (%s)." % (rec.get("email") or "signed in")
    return {"available": signed_in and plan, "signed_in": signed_in, "email": rec.get("email"), "login_code": _login.get("code"),
            "login": _login["state"], "detail": detail}


# ---------- inference ----------

FRIENDLY = {
    "subscription_sharing_usage_limit_exceeded":
        "You've used up your ChatGPT plan's usage for now. Check when it resets under Manage usage (%s)." % USAGE_URL,
    "subscription_sharing_usage_unavailable": "ChatGPT plan usage is busy right now. Try again in a minute.",
    "subscription_sharing_user_unavailable": "ChatGPT is busy right now. Try again in a minute.",
    "subscription_sharing_user_not_eligible":
        "Your ChatGPT plan can't be used in other apps. " + PLAN_MESSAGE,
    "subscription_sharing_invalid_user": "ChatGPT says this sign-in is no longer connected. Sign in again in Settings.",
}


def _request(token, body, opener=None):
    req = urllib.request.Request(API_BASE + "/responses", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                          "Accept": "text/event-stream", "User-Agent": USER_AGENT})
    return (opener or urllib.request.urlopen)(req, timeout=REQUEST_TIMEOUT)


def _http_error(e):
    detail = e.read().decode("utf-8", "replace")
    code = None
    try:
        j = json.loads(detail)
        err = j.get("error") if isinstance(j.get("error"), dict) else {}
        code = err.get("code") or (j.get("error") if isinstance(j.get("error"), str) else None)
        param = err.get("param")
        msg = err.get("message") or j.get("detail")
    except ValueError:
        param, msg = None, detail[:200]
    return code, param, msg


def read_stream(lines):
    """Collect a Responses API event stream. Returns (text, usage, model); raises ChatGPTError on response.failed."""
    text, data_lines, usage, model, completed = [], [], None, None, False
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        if line or not data_lines:
            continue
        payload, data_lines = "\n".join(data_lines), []
        if payload == "[DONE]":
            break
        try:
            ev = json.loads(payload)
        except ValueError:
            continue
        kind = ev.get("type")
        if kind == "response.output_text.delta":
            text.append(ev.get("delta") or "")
        elif kind == "response.completed":
            r = ev.get("response") or {}
            usage, model, completed = r.get("usage"), r.get("model"), True
        elif kind in ("response.failed", "error"):
            err = (ev.get("response") or {}).get("error") or ev.get("error") or {}
            code = err.get("code")
            raise ChatGPTError(FRIENDLY.get(code) or "ChatGPT error: %s" % (err.get("message") or code or "unknown"), code=code)
        elif kind == "response.incomplete":
            raise ChatGPTError("ChatGPT's answer was cut off. Ask for fewer parts or bars.", code="incomplete")
    if not completed:
        raise ChatGPTError("ChatGPT stopped before finishing. Try again.", code="interrupted")
    return "".join(text), usage, model


def pick_model(token, preferred=None, opener=None):
    """The model to use: the user's choice if their account lists it, else the first listed model."""
    req = urllib.request.Request(API_BASE + "/models", headers={"Authorization": "Bearer " + token, "User-Agent": USER_AGENT})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=30) as r:
            body = json.loads(r.read().decode("utf-8"))
        # OpenAI's plan catalog is {"models": [{"slug", "display_name", "visibility"}, ...]} in the server's order
        # (developers.openai.com/siwc/.../models-and-inference); "data" is the regular API's shape, kept as a fallback.
        data = (body.get("models") or body.get("data") or []) if isinstance(body, dict) else []
    except (urllib.error.URLError, socket.timeout, ValueError):
        if preferred:
            return preferred
        raise ChatGPTError("Couldn't get the list of ChatGPT models. Try again.")
    slugs = [m.get("slug") or m.get("id") for m in data if m.get("visibility", "list") == "list"]
    slugs = [s for s in slugs if s]
    if preferred and preferred in slugs:
        return preferred
    if not slugs:
        raise ChatGPTError("Your ChatGPT account has no models available for other apps.")
    return slugs[0]


TRANSIENT_HTTP = {429, 500, 502, 503, 504}
TRANSIENT_CODES = {"server_error", "server_overloaded", "overloaded", "service_unavailable", "rate_limit_exceeded"}
RETRY_WAITS = (2, 5, 10)   # seconds before the 2nd, 3rd and 4th try


def _transient(code, msg, status=None):
    """A temporary OpenAI problem worth retrying ("servers are overloaded"). Never the user's plan limit."""
    if code and code.startswith("subscription_sharing_usage_limit"):
        return False
    text = (msg or "").lower()
    return status in TRANSIENT_HTTP or code in TRANSIENT_CODES or "overloaded" in text or "try again later" in text


def generate(instructions, user_message, schema, model=None, store=None, post=_post_form, opener=None, sleep=time.sleep):
    """One Veloura request on the user's ChatGPT plan. Returns (text, usage, model)."""
    token = access_token(store, post)
    model = pick_model(token, model, opener)
    body = {"model": model, "instructions": instructions, "store": False, "stream": True,
            **({"reasoning": {"effort": REASONING_EFFORT}} if REASONING_EFFORT else {}),
            "input": [{"role": "user", "content": user_message}],
            "text": {"format": {"type": "json_schema", "name": "veloura_response", "schema": schema, "strict": False}}}
    for attempt in range(4):
        try:
            with _request(token, body, opener) as r:
                return read_stream(r)
        except urllib.error.HTTPError as e:
            code, param, msg = _http_error(e)
            if "text" in body and (code == "subscription_sharing_unsupported_capability" or (e.code == 400 and param and "text" in str(param))):
                body.pop("text")   # structured output not offered here: ask by instruction only (Veloura validates anyway)
                continue
            if e.code == 401 and attempt == 0:
                with (store or STORE).lock:
                    (store or STORE).access_token = None
                token = access_token(store, post)
                continue
            if (code in ("subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable")
                    or _transient(code, msg, e.code)) and attempt < len(RETRY_WAITS):
                sleep(RETRY_WAITS[attempt])
                continue
            raise ChatGPTError(FRIENDLY.get(code) or "ChatGPT error %d: %s" % (e.code, msg or code), code=code)
        except ChatGPTError as e:
            if e.code == "subscription_sharing_unsupported_capability" and "text" in body:
                body.pop("text")
                continue
            if (e.code == "subscription_sharing_usage_unavailable" or _transient(e.code, str(e))) and attempt < len(RETRY_WAITS):
                sleep(RETRY_WAITS[attempt])   # e.g. response.failed "Our servers are currently overloaded"
                continue
            raise
        except (urllib.error.URLError, socket.timeout) as e:
            raise ChatGPTError("Could not reach ChatGPT: %s" % getattr(e, "reason", e))
    raise ChatGPTError("ChatGPT couldn't answer right now. Try again in a minute.")
