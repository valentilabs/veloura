"""Run the veloura_bridge Piano Roll script without clicking menus.

FL Studio has no documented way to start a Piano Roll script from outside FL (Image-Line only describes the Scripts
menu and "Run last script again", Cmd+Opt+Y). Veloura sends that shortcut straight to FL's process, so FL runs the
script while it stays in the background and the screen doesn't switch apps. If that ever gets no answer, it falls back
to bringing FL to the front, typing the shortcut through System Events and returning focus afterwards.

KNOWN RISKS (documented, not solved):
  * Cmd+Opt+Y re-runs WHATEVER Piano Roll script ran last. If you used another
    script (Humanize, Arpeggiator...) since veloura_bridge, that script runs
    instead. Veloura detects that no result arrived, but cannot undo what the
    other script did. Run veloura_bridge from the menu once after using any
    other script.
  * The keystroke goes to whichever FL window has focus. The Piano Roll must
    be the focused FL window.
  * Requires macOS Accessibility permission for the app running Veloura.
Use only on test projects until Stage 2 adds proper targeting.
"""

import re
import subprocess
import time

FL_BUNDLE_ID = "com.image-line.flstudio"
FL_PROCESS = "OsxFL"  # FL Studio's process name as seen by System Events (2024 and 2026)


class TriggerError(RuntimeError):
    pass


def _osascript(lines, timeout=5):
    args = ["/usr/bin/osascript"]
    for line in lines:
        args += ["-e", line]
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise TriggerError(p.stderr.strip() or "osascript failed")
    return p.stdout.strip()


def _ax_trusted():
    """macOS's own answer to "may this app send keystrokes?" (AXIsProcessTrusted). It is asked in-process, so it
    works even when System Events is busy or hung. For the service it reflects the app that launched it (Veloura.app,
    or Terminal / Claude Code in development). None if the framework can't be loaded."""
    try:
        import ctypes
        lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except (OSError, AttributeError):
        return None


def accessibility_enabled():
    trusted = _ax_trusted()
    if trusted is not None:
        return trusted
    try:
        return _osascript(['tell application "System Events" to get UI elements enabled']) == "true"
    except (TriggerError, subprocess.TimeoutExpired):
        return False


def fl_running():
    """Whether FL Studio is open, from the process list (no Apple Events, so a busy System Events can't make FL
    look closed)."""
    try:
        p = subprocess.run(["/usr/bin/pgrep", "-x", FL_PROCESS], capture_output=True, text=True, timeout=5)
        return p.returncode == 0 and bool(p.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


_system_events_ok = {"seen": False}


def system_events_responding(timeout=4):
    """False when macOS's System Events helper doesn't answer (it can hang; restarting it fixes that).

    The first time an app (a new Veloura build counts as a new app) talks to System Events, macOS asks the user
    "Veloura wants access to control System Events" and holds the request until they answer. A short timeout would
    cancel that prompt before anyone can click OK, so the first check waits up to two minutes."""
    try:
        _osascript(['tell application "System Events" to get name of first process'],
                   timeout=timeout if _system_events_ok["seen"] else 120)
        _system_events_ok["seen"] = True
        return True
    except subprocess.TimeoutExpired:
        return False
    except TriggerError:
        return True   # it answered, with an error (e.g. Automation was declined): not hung


def fl_project_name():
    """The project open in FL, from its window title ('Claude test.flp - FL Studio 2024' -> 'Claude test').
    None if FL isn't running or the title can't be read."""
    if not fl_running():   # asking System Events about a process that isn't there waits out the whole timeout
        return None
    try:
        out = _osascript(['tell application "System Events" to tell process "%s" to get name of every window' % FL_PROCESS],
                         timeout=2)
    except (TriggerError, subprocess.TimeoutExpired):
        return None
    for title in out.split(", "):
        if " - FL Studio" in title:
            name = title.split(" - FL Studio")[0].strip()
            name = name[:-4] if name.lower().endswith(".flp") else name
            return name.lstrip("*").strip() or "Untitled"
        if re.match(r"^FL Studio( \d{4})?$", title.strip()):
            return "Untitled"
    return None


def frontmost_app():
    try:
        return _osascript(['tell application "System Events" to get name of first process whose frontmost is true'])
    except (TriggerError, subprocess.TimeoutExpired):
        return None


def _activate_fl():
    _osascript(['tell application id "%s" to activate' % FL_BUNDLE_ID, "delay 0.25"])


def _send_rerun_shortcut():
    _osascript(['tell application "System Events" to tell process "%s"' % FL_PROCESS,
                'keystroke "y" using {command down, option down}',
                "end tell"])


def _restore(app):
    if app and app != FL_PROCESS:
        try:
            _osascript(['tell application "System Events" to set frontmost of process "%s" to true' % app])
        except (TriggerError, subprocess.TimeoutExpired):
            pass


def preflight():
    """Problems that make automatic triggering impossible right now (empty list = OK)."""
    problems = []
    if not fl_running():
        problems.append("FL Studio is not running.")
    if not accessibility_enabled():
        problems.append("macOS Accessibility permission is off for the app running Veloura "
                        "(System Settings > Privacy & Security > Accessibility).")
    # System Events isn't checked here: the background trigger doesn't use it (only the rare fallback does).
    return problems


_previous_app = {"name": None}


def restore_previous():
    """Give focus back to the app that was in front before Veloura first activated FL."""
    _restore(_previous_app["name"])
    _previous_app["name"] = None


# Cmd+Opt+Y delivered straight to FL's process with Quartz (CGEventPostToPid). FL runs the Piano Roll script while it
# stays in the background, so the user's screen doesn't flip to FL and back. Verified on FL 2026 / macOS 26:
# 20/20 runs, median 0.04 s, Veloura stayed in front. If it ever doesn't answer, Veloura falls back to the old way
# (bring FL to the front and type the shortcut through System Events).
KEY_Y = 16
FLAG_CMD, FLAG_OPT = 0x100000, 0x80000
BACKGROUND_WAIT = 1.2        # seconds to wait for the background trigger before falling back
last_trigger = {"mode": None}  # "background" or "foreground": how the last run reached FL


def _fl_pid():
    try:
        out = subprocess.run(["/usr/bin/pgrep", "-x", FL_PROCESS], capture_output=True, text=True, timeout=5).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _post_shortcut_to_fl():
    """Send Cmd+Opt+Y to FL without activating it. False if that isn't possible here."""
    pid = _fl_pid()
    if not pid:
        return False
    try:
        import ctypes
        cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        cg.CGEventPostToPid.argtypes = [ctypes.c_int, ctypes.c_void_p]
        cg.CFRelease.argtypes = [ctypes.c_void_p]
        for down in (True, False):
            ev = cg.CGEventCreateKeyboardEvent(None, KEY_Y, down)
            if not ev:
                return False
            cg.CGEventSetFlags(ev, FLAG_CMD | FLAG_OPT)
            cg.CGEventPostToPid(pid, ev)
            cg.CFRelease(ev)
            time.sleep(0.02)
        return True
    except (OSError, AttributeError):
        return False


def _poll(get_result, until):
    while time.time() < until:
        result = get_result()
        if result is not None:
            return result
        time.sleep(0.03)
    return None


def trigger_and_wait(get_result, timeout=4.0, retry_trigger=False, restore_focus=True, background=True, get_started=None):
    """Run the Piano Roll script and poll get_result() until it returns something or time runs out.

    First tries the background trigger (no app switch). If FL doesn't answer within BACKGROUND_WAIT it brings FL to the
    front and types the shortcut. Re-sending is safe even for edits: the bridge applies each command ID at most once.
    Read-only commands may re-send the shortcut to cover FL focus races. Returns (result_or_None, seconds, triggers).
    """
    start = time.time()
    triggers = 0
    if background and _post_shortcut_to_fl():
        triggers = 1
        result = _poll(get_result, min(start + BACKGROUND_WAIT, start + timeout))
        if result is None and get_started and get_started():
            # FL already picked the command up in the background and is just busy: wait for it, don't bring FL
            # forward and send the shortcut a second time.
            result = _poll(get_result, start + timeout)
        if result is not None:
            last_trigger["mode"] = "background"
            return result, time.time() - start, triggers
    if time.time() - start >= timeout:
        return None, time.time() - start, triggers
    front = frontmost_app()
    if front and front != FL_PROCESS:
        _previous_app["name"] = front
    try:
        _activate_fl()
        _send_rerun_shortcut()
        triggers += 1
        last_trigger["mode"] = "foreground"
        next_retry = time.time() + 1.0
        while time.time() - start < timeout:
            result = get_result()
            if result is not None:
                return result, time.time() - start, triggers
            if retry_trigger and time.time() >= next_retry:
                _send_rerun_shortcut()
                triggers += 1
                next_retry = time.time() + 1.0
            time.sleep(0.05)
        return None, time.time() - start, triggers
    finally:
        if restore_focus:
            restore_previous()
