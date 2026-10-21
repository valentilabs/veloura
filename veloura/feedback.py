"""Send feedback from the About section to Valenti Labs' Formspree form.

Only what the user typed (message, optional reply email) plus the app and macOS versions. Never logs, chat history,
keys or file paths."""

import json
import platform
import re
import urllib.error
import urllib.request

from . import edition

ENDPOINT = "https://formspree.io/f/xgaobplj"
MAX_MESSAGE = 5000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FeedbackError(Exception):
    pass


def payload(message, email=None):
    message = (message or "").strip()
    if not message:
        raise FeedbackError("Write a message first.")
    if len(message) > MAX_MESSAGE:
        raise FeedbackError("Please keep it under %d characters." % MAX_MESSAGE)
    email = (email or "").strip()
    if email and not EMAIL_RE.match(email):
        raise FeedbackError("That email address doesn't look right.")
    out = {"message": message, "app_version": "%s %s" % (edition.VERSION, edition.CHANNEL),
           "macos_version": platform.mac_ver()[0] or "unknown"}
    if email:
        out["_replyto"] = email
    return out


def send(message, email=None, urlopen=urllib.request.urlopen, timeout=20):
    """POST the feedback as JSON. Returns {"ok": True, "status": code}; raises FeedbackError with a short reason."""
    data = json.dumps(payload(message, email)).encode()
    req = urllib.request.Request(ENDPOINT, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          # Formspree's Cloudflare blocks Python's default "Python-urllib" agent
                                          "User-Agent": "VelouraBeta/%s (Macintosh; macOS)" % edition.VERSION})
    try:
        with urlopen(req, timeout=timeout) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        raise FeedbackError("Feedback couldn't be sent (HTTP %d). Try again later." % e.code)
    except (urllib.error.URLError, OSError):
        raise FeedbackError("Feedback couldn't be sent. Check your internet connection and try again.")
    if not 200 <= code < 300:
        raise FeedbackError("Feedback couldn't be sent (HTTP %d). Try again later." % code)
    return {"ok": True, "status": code}
