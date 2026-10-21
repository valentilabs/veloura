"""Instrument sounds: let the AI choose a plugin preset by name, and switch the plugin to it.

FL's scripting API exposes, for plugins that publish their presets to FL, the preset NAMES
(plugins.getName(..., FPN_Preset, i)) and next/previous navigation. There is no "load preset N", so Veloura
steps one preset at a time and checks the current name after each step (batched steps get dropped by FL).
Loading a preset makes FL rename the channel to the preset, so Veloura renames it back afterwards.
"""

import re
import time

STEP_PAUSE = 0.2             # FL loads presets asynchronously; give it a moment before reading the name
MAX_STEPS = 600              # beyond this, switching would take too long; Veloura guides the user instead
SOUND_WORDS = ("bell", "pluck", "pad", "lead", "key", "piano", "rhodes", "ep", "organ", "synth", "arp", "choir", "vox",
               "voice", "flute", "string", "violin", "cello", "brass", "horn", "guitar", "harp", "marimba", "mallet",
               "glock", "music box", "bass", "808", "sub", "saw", "square", "dark", "bright", "dream", "ambient",
               "atmos", "texture", "fx", "sweep", "chord", "stab", "trap", "drill", "rage")


def shortlist(names, request_text, limit=150):
    """Pick the presets worth showing the AI: keyword matches for this request first, then a spread of the rest."""
    names = [n for n in names if n and n.strip()]
    if len(names) <= limit:
        return names
    words = set(re.findall(r"[a-z0-9]+", (request_text or "").lower()))
    wanted = [w for w in SOUND_WORDS if w in words] or []
    picked = [n for n in names if any(w in n.lower() for w in wanted)][:limit // 2]
    rest = [n for n in names if n not in picked]
    stride = max(1, len(rest) // (limit - len(picked)))
    return picked + rest[::stride][:limit - len(picked)]


def plan_steps(names, current, target, count):
    """Signed number of single steps from current to target (shortest way round), or None if unknown."""
    if target not in names:
        return None
    t = names.index(target)
    if current not in names:
        return None
    c = names.index(current)
    fwd = (t - c) % count
    back = fwd - count
    return fwd if fwd <= -back else back


def switch(controller, chan, target, progress=None):
    """Step the instrument on `chan` to the preset called `target`. Returns (ok, message, previous_preset)."""
    info = controller.request("presets", {"channel": chan["index"], "expect_name": chan["name"]}, timeout=20)
    names, current, count = info["names"], info.get("current"), info["count"]
    if current == target:
        return True, "already on %r" % target, current
    steps = plan_steps(names, current, target, count)
    if steps is None:
        return False, "%s doesn't list a sound called %r" % (info.get("plugin") or "This plugin", target), current
    if abs(steps) > MAX_STEPS:
        return False, "%r is %d presets away; pick it in the plugin yourself" % (target, abs(steps)), current
    one = 1 if steps > 0 else -1
    controller.request("step_preset", {"channel": chan["index"], "expect_name": chan["name"], "steps": 0, "undo": True})
    name_now = chan["name"]
    for k in range(abs(steps) + 3):
        cur = controller.request("presets", {"channel": chan["index"], "names": False}, timeout=20).get("current")
        if cur == target:
            break
        controller.request("step_preset", {"channel": chan["index"], "steps": one, "undo": False})
        if progress:
            progress(k + 1, abs(steps))
        time.sleep(STEP_PAUSE)
    else:
        cur = None
    # FL renames the channel to the loaded preset: put the user's name back so Veloura's matching keeps working.
    controller.request("rename_channel", {"channel": chan["index"], "name": name_now})
    if cur != target:
        return False, "couldn't reach %r (stopped at %r)" % (target, cur), current
    return True, "switched to %r" % target, current
