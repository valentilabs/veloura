"""Taste memory: what the user keeps, rejects or replaces, so later suggestions lean their way.

Stored locally in data/taste.json. Kinds: "sound" (plugin presets), "sample" (drum library files),
"groove" (drum profiles), "layer" (purposes like counter/pad). Each item counts kept / rejected.
"""

import json
import os
import threading
import time

_lock = threading.Lock()


class Taste:
    def __init__(self, path):
        self.path = path
        self.data = {"items": {}}
        try:
            with open(path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            pass
        self.data.setdefault("items", {})

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)

    def note(self, kind, item, verdict, context=None):
        """verdict: 'kept' or 'rejected'."""
        if verdict not in ("kept", "rejected") or not item:
            return
        with _lock:
            key = "%s:%s" % (kind, item)
            e = self.data["items"].setdefault(key, {"kind": kind, "item": item, "kept": 0, "rejected": 0, "context": {}})
            e[verdict] += 1
            e["last"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if context:
                c = e["context"].setdefault(str(context), {"kept": 0, "rejected": 0})
                c[verdict] += 1
            self._save()

    def score(self, kind, item):
        e = self.data["items"].get("%s:%s" % (kind, item))
        if not e:
            return 0.0
        return (e["kept"] - 1.5 * e["rejected"]) / (1 + e["kept"] + e["rejected"])

    def summary(self, limit=8):
        """Short lists for the AI: liked and disliked items per kind."""
        out = {}
        for e in self.data["items"].values():
            s = (e["kept"] - 1.5 * e["rejected"])
            bucket = out.setdefault(e["kind"], {"likes": [], "dislikes": []})
            if s > 0:
                bucket["likes"].append((s, e["item"]))
            elif s < 0:
                bucket["dislikes"].append((s, e["item"]))
        return {k: {"likes": [i for _, i in sorted(v["likes"], reverse=True)[:limit]],
                    "dislikes": [i for _, i in sorted(v["dislikes"])[:limit]]} for k, v in out.items()}
