"""Veloura local service: serves the UI and a small JSON API on 127.0.0.1.

Started by the Electron app (or by hand for development):
    python3 -m veloura.service --port 0 --token <secret>
It prints one JSON line {"port": N} on stdout once listening.

Security: binds to 127.0.0.1 only, every /api request must carry the per-launch
token (X-Veloura-Token header), and the Host header must be the loopback
address, which blocks DNS-rebinding attacks from web pages. It exits when stdin
closes (the parent app quit), so it never lingers in the background.
"""

import argparse
import fcntl
import hmac
import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import shutil

from . import ai
from . import bridge_protocol as bp
from .engine import Engine, EngineError

# Requests that change or read FL, by the kind used for their time estimates.
TIMED_ACTIONS = {"/api/apply": "write", "/api/reapply": "write", "/api/remove": "remove", "/api/revert": "revert",
                 "/api/mix/apply": "mix", "/api/mix/undo": "mix", "/api/kit/load": "kit", "/api/fl-tempo": "tempo",
                 "/api/test-bridge": "check", "/api/read": "check", "/api/load-sample": "kit",
                 "/api/kit/stage": "kit"}

UI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "ui")


def make_handler(engine, token, port_ref):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Veloura/1"

        def log_message(self, fmt, *args):  # keep stdout clean (the parent reads the port line)
            # never write query strings: the audio URL carries the session token
            sys.stderr.write("veloura-service: " + re.sub(r"\?\S*", "", fmt % args) + "\n")

        def _token_ok(self, given):
            return isinstance(given, str) and hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8"))

        def _host_ok(self):
            host = self.headers.get("Host", "")
            return host in ("127.0.0.1:%d" % port_ref[0], "localhost:%d" % port_ref[0])

        def _json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, path):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(UI_DIR, rel))
            if not full.startswith(os.path.realpath(UI_DIR) + os.sep) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
                             "img-src 'self' data:; media-src 'self'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self._host_ok():
                return self.send_error(403)
            path = urlparse(self.path).path
            if not path.startswith("/api/"):
                return self._static(path)
            q = parse_qs(urlparse(self.path).query)
            if not self._token_ok(self.headers.get("X-Veloura-Token")) and not (path == "/api/library/audio" and self._token_ok(q.get("t", [""])[0])):
                return self._json(401, {"error": "bad token"})
            if path == "/api/status":
                return self._json(200, engine.status())
            if path == "/api/library/audio":
                return self._audio(engine.library.get(parse_qs(urlparse(self.path).query).get("id", [""])[0]))
            if path == "/api/progress":
                return self._json(200, engine.get_progress())
            if path == "/api/session":
                return self._json(200, engine.snapshot_state())
            if path == "/api/setup":
                steps, st = engine.setup_steps()
                return self._json(200, {"steps": steps, "status": st})
            return self._json(404, {"error": "unknown endpoint"})

        def do_POST(self):
            if not self._host_ok():
                return self.send_error(403)
            path = urlparse(self.path).path
            if not self._token_ok(self.headers.get("X-Veloura-Token")):
                return self._json(401, {"error": "bad token"})
            if path == "/api/reference":
                return self._upload()
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 1_000_000:
                    return self._json(413, {"error": "request too large"})
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json(400, {"error": "invalid JSON"})
            try:
                kind = TIMED_ACTIONS.get(path)
                if kind:   # FL actions: a countdown from how long this kind of action really took lately
                    with engine.timed_action(kind):
                        return self._json(200, self.route(path, body))
                return self._json(200, self.route(path, body))
            except EngineError as e:
                return self._json(400, {"error": str(e)})
            except (ValueError, RuntimeError) as e:
                return self._json(400, {"error": str(e)})
            except subprocess.TimeoutExpired:
                traceback.print_exc()
                return self._json(400, {"error": "macOS took too long to answer (System Events can get stuck). Nothing was "
                                                 "changed. Try again; if it keeps happening, restart FL Studio and Veloura."})
            except OSError as e:
                traceback.print_exc()
                return self._json(400, {"error": "Veloura couldn't reach a file or app it needs (%s). Try again." % (e.strerror or e)})
            except Exception as e:
                traceback.print_exc()
                try:
                    engine.event("error", "Unexpected error on %s: %r" % (path, e))
                except Exception:
                    pass
                return self._json(500, {"error": "Something went wrong, and nothing was changed. Try again; if it keeps "
                                                 "happening, send feedback from Help (the details are in the Activity log)."})

        def _audio(self, sample):
            """Stream one library sound for preview (only files that are in the user's indexed library)."""
            if not sample or not os.path.isfile(sample["path"]):
                return self.send_error(404)
            ctype = mimetypes.guess_type(sample["path"])[0] or "audio/wav"
            size = os.path.getsize(sample["path"])
            if size > 50_000_000:
                return self.send_error(413)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(sample["path"], "rb") as f:
                shutil.copyfileobj(f, self.wfile)

        def _upload(self):
            """Raw audio upload (streamed to a temp file), then analysis."""
            import tempfile
            from urllib.parse import parse_qs, unquote
            q = parse_qs(urlparse(self.path).query)
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= 300_000_000:
                return self._json(413, {"error": "Audio files up to 300 MB please."})
            fd, tmp = tempfile.mkstemp(prefix="veloura-upload-")
            try:
                with os.fdopen(fd, "wb") as f:
                    left = length
                    while left:
                        chunk = self.rfile.read(min(left, 1 << 20))
                        if not chunk:
                            break
                        f.write(chunk)
                        left -= len(chunk)
                ref = engine.add_reference(unquote(q.get("name", ["audio"])[0]), tmp, q.get("mode", ["inspiration"])[0])
                return self._json(200, ref)
            except EngineError as e:
                return self._json(400, {"error": str(e)})
            except Exception as e:
                traceback.print_exc()
                return self._json(500, {"error": "Analysis failed: %r" % (e,)})
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

        def route(self, path, b):
            if path == "/api/feedback":
                from . import feedback
                try:
                    return feedback.send(b.get("message"), b.get("email"))
                except feedback.FeedbackError as e:
                    raise EngineError(str(e))
            if path == "/api/rack":
                return engine.rack_state(bool(b.get("all")))
            if path == "/api/rack/pattern":
                return engine.rack_select_pattern(b.get("number"))
            if path == "/api/rack/toggle":
                return engine.rack_toggle(b.get("index"), b.get("name"), b.get("step"), b.get("on"), pattern=b.get("pattern"))
            if path == "/api/rack/mute":
                return engine.rack_mute(b.get("index"), b.get("name"), b.get("muted"))
            if path == "/api/focus-fl":
                return engine.focus_fl()
            if path == "/api/open-fl":
                return engine.open_fl()
            if path == "/api/restart-fl":
                return engine.restart_fl()
            if path == "/api/style":
                return engine.style.summary()
            if path == "/api/style/import":
                return engine.style_import(b.get("path"), b.get("genre"))
            if path == "/api/style/remove":
                engine.style.remove(b.get("id"))
                return engine.style.summary()
            if path == "/api/projects":
                return engine.list_projects()
            if path == "/api/new-project":
                return engine.new_fl_project(b.get("name"))
            if path == "/api/save-starter":
                return engine.save_starter()
            if path == "/api/delete-project":
                return engine.delete_project(b.get("name"))
            if path == "/api/start-fresh":
                return engine.start_fresh()
            if path == "/api/improve":
                return engine.improve()
            if path == "/api/variations":
                return engine.variations(b.get("name"), int(b.get("count") or 3))
            if path == "/api/groove":
                return engine.groove_action(b.get("action"))
            if path == "/api/restore-version":
                return engine.restore_version(b.get("name"), b.get("id"))
            if path == "/api/arrangement":
                return engine.arrangement(b.get("genre"))
            if path == "/api/feel":
                return engine.update_settings({"feel": b.get("feel") or {}})
            if path == "/api/lock":
                names = set(engine.state["settings"].get("locked_parts") or [])
                (names.add if b.get("locked") else names.discard)(b.get("name"))
                return engine.update_settings({"locked_parts": sorted(names)})
            if path == "/api/library":
                return engine.library.summary()
            if path == "/api/library/add-folder":
                return engine.library_add_folder(b.get("path"))
            if path == "/api/library/remove-folder":
                engine.library.remove_folder(b.get("path"))
                return engine.library.summary()
            if path == "/api/library/scan":
                return engine.library_scan()
            if path == "/api/library/list":
                return {"samples": engine.library.list(b.get("category"), b.get("q"), int(b.get("limit") or 200), bool(b.get("hidden")))}
            if path == "/api/library/favorite":
                engine.library.favorite(b.get("id"), b.get("on", True))
                engine.taste.note("sample", b.get("id"), "kept" if b.get("on", True) else "rejected")
                return {"ok": True}
            if path == "/api/library/hide":
                engine.library.hide(b.get("id"), b.get("on", True))
                return {"ok": True}
            if path == "/api/library/set-category":
                engine.library.set_category(b.get("id"), b.get("category"))
                return {"ok": True}
            if path == "/api/kit/choose":
                return engine.choose_kit(b.get("genre"), b.get("seed"), b.get("keep"), b.get("exclude"))
            if path == "/api/kit/load":
                return engine.load_kit(b.get("roles"), b.get("proposal_id"))
            if path == "/api/load-sample":
                return engine.load_sample(b.get("channel"), b.get("path"), b.get("name"))
            if path == "/api/kit/stage":
                return engine.stage_kit(b.get("roles"), b.get("label"))
            if path == "/api/kit/check":
                return engine.check_kit()
            if path == "/api/kit/feedback":
                return engine.kit_feedback(b.get("id"), b.get("verdict"), b.get("role"))
            if path == "/api/sounds":
                return engine.sound_list(b.get("index"), b.get("name"))
            if path == "/api/sounds/switch":
                return engine.switch_sound(b.get("index"), b.get("name"), b.get("sound"))
            if path == "/api/mixer-setup":
                return engine.mixer_setup()
            if path == "/api/mix/apply":
                return engine.apply_mix(b.get("proposal_id"))
            if path == "/api/mix/undo":
                return engine.undo_mix(b.get("proposal_id"))
            if path == "/api/prep":
                if "channel" in b:
                    return engine.set_prep(b["channel"], b.get("task"), b.get("done", True))
                return engine.sound_prep()
            if path == "/api/listen":
                return engine.listen_check(float(b.get("seconds") or 8))
            if path == "/api/listen/fix":
                return engine.listen_fix(b.get("kind"), b.get("target"), b.get("value"))
            if path == "/api/sound-check":
                return engine.sound_after_stop()
            if path == "/api/cancel":
                return engine.cancel()
            if path == "/api/chat":
                return engine.chat(b.get("text", ""), mode=b.get("mode", "describe"), genre=b.get("genre"),
                                   reference_id=b.get("reference_id"))
            if path == "/api/reference/delete":
                return engine.delete_reference(b.get("id"))
            if path == "/api/reference/reveal":
                return engine.reveal_reference(b.get("id"))
            if path == "/api/genres":
                from . import genres
                return {k: dict(genres.defaults(k), label=v["label"]) for k, v in genres.GENRES.items()}
            if path == "/api/apply":
                return engine.apply(b["proposal_id"], int(b["index"]), allow_existing=bool(b.get("allow_existing")),
                                    as_new=bool(b.get("as_new")), manual_target=bool(b.get("manual_target")))
            if path == "/api/undo-all":
                return engine.undo_all() if b.get("confirm") else {"plan": engine.undo_all_plan()}
            if path == "/api/auto-instrument":
                return engine.auto_instrument(b["proposal_id"], int(b["index"]))
            if path == "/api/route":
                return engine.set_route(b["proposal_id"], int(b["index"]), b["channel"], b.get("remember", True))
            if path == "/api/reapply":
                return engine.reapply(b["proposal_id"], int(b["index"]), b.get("channel"))
            if path == "/api/remove":
                return engine.remove(b["name"])
            if path == "/api/revert":
                return engine.revert(b["name"])
            if path == "/api/read":
                return engine.read_piano_roll()
            if path == "/api/export":
                return engine.export(pid=b.get("proposal_id"), index=b.get("index"), name=b.get("name"),
                                     directory=b.get("directory"))
            if path == "/api/reveal":
                p = b.get("path", "")
                if os.path.exists(p) and os.path.realpath(p).startswith(os.path.expanduser("~")):
                    subprocess.run(["/usr/bin/open", "-R", p], timeout=10)
                return {"ok": True}
            if path == "/api/open-accessibility":
                return engine.open_accessibility_settings()
            if path == "/api/controller-read":
                op = b.get("op")
                if op not in ("hello", "focus_piano_roll", "project", "mix_state", "presets", "rack_state", "read_steps", "introspect",
                              "browser", "browser_goto", "eq_probe"):
                    raise EngineError("read-only diagnostic ops only")
                if op == "browser_goto" and "channel" in (b.get("params") or {}):
                    raise EngineError("diagnostics never load sounds")
                return engine.controller.request(op, b.get("params") or {}, timeout=15)
            if path == "/api/controller-hello":
                try:
                    return engine.controller.request("hello")
                except Exception as e:
                    return {"error": str(e)}
            if path == "/api/open-piano-roll":
                return engine.open_any_piano_roll(b.get("name"))
            if path == "/api/test-bridge":
                return engine.test_bridge()
            if path == "/api/open-folder":
                target = {"exports": os.path.expanduser("~/Music/Veloura Exports"),
                          "logs": bp.LOG_DIR}.get(b.get("which"))
                if target:
                    os.makedirs(target, exist_ok=True)
                    subprocess.run(["/usr/bin/open", os.path.realpath(target)], timeout=10)
                return {"ok": True}
            if path == "/api/fl-tempo":
                return engine.set_fl_tempo(b.get("bpm"))
            if path == "/api/settings":
                return engine.update_settings(b)
            if path == "/api/apikey":
                prov = "gemini" if b.get("provider") == "gemini" else "anthropic"
                if b.get("delete"):
                    ai.delete_api_key(prov)
                else:
                    ai.set_api_key(b.get("key", ""), prov)
                return {"ok": True, "providers": ai.provider_status()}
            if path == "/api/chatgpt-login":
                ai.chatgpt.start_login()
                return {"ok": True}
            if path == "/api/chatgpt-signout":
                ai.chatgpt.sign_out()
                return {"ok": True, "providers": ai.provider_status()}
            if path == "/api/claude-login":
                ai.open_claude_login()
                return {"ok": True}
            if path == "/api/repair-bridge":
                return {"ok": True, "bridge_script": engine.ensure_bridge()}
            if path == "/api/clear-chat":
                return engine.start_fresh()
            raise EngineError("unknown endpoint")

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--token", default=None)
    ap.add_argument("--no-stdin-watch", action="store_true", help="keep running when stdin closes (development)")
    args = ap.parse_args()
    # The app passes the token in VELOURA_SERVICE_TOKEN (never on the command line, where `ps` shows it to everyone);
    # --token is kept for development. It is removed from the environment so child processes don't inherit it.
    env_token = os.environ.pop("VELOURA_SERVICE_TOKEN", None)
    token = env_token or args.token or secrets.token_urlsafe(24)
    # One Veloura service at a time: two would overwrite each other's session file.
    from .engine import DATA_DIR
    os.makedirs(DATA_DIR, exist_ok=True)
    lock = open(os.path.join(DATA_DIR, "service.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(json.dumps({"error": "Veloura is already running (another Veloura window or service holds the lock)."}), flush=True)
        sys.exit(2)
    engine = Engine()
    engine.open_controller_ports()
    threading.Thread(target=engine.tidy_staged_kits, daemon=True).start()
    threading.Thread(target=engine.keep_kits_local, daemon=True).start()
    def fl_helpers():
        # A new Veloura may ship a newer FL bridge script: put it in FL's scripts folder (Veloura's own files only).
        # Only when FL Studio has run on this Mac (its Settings folder exists): never create FL's folders on a Mac
        # without FL. Then clear out old result files FL left in the exchange folder.
        try:
            if os.path.isdir(os.path.dirname(bp.FL_SCRIPTS_DIR)):
                engine.ensure_bridge()
                bp.tidy_bridge_dir()
        except Exception:
            pass
    threading.Thread(target=fl_helpers, daemon=True).start()
    threading.Thread(target=engine.listen_to_library, daemon=True).start()
    port_ref = [0]
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(engine, token, port_ref))
    server.daemon_threads = True
    port_ref[0] = server.server_address[1]
    print(json.dumps({"port": port_ref[0], "token": token if not (args.token or env_token) else None}), flush=True)

    if not args.no_stdin_watch:
        def watch():
            sys.stdin.read()  # returns when the parent closes our stdin (app quit or crash)
            os._exit(0)
        threading.Thread(target=watch, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
