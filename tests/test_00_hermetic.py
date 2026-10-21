"""Keep the test suite off the real Mac: no Keychain, AppleScript, process list, Finder, iCloud or xattr calls.

unittest imports this module first (test_00...), so the guard is in place before any other test runs. A test that
needs one of these tools mocks subprocess.run itself (mock.patch replaces this guard for that test). Anything that
slips through gets a harmless "failed" result instead of touching the user's Keychain, FL Studio or files."""
import os
import subprocess
import unittest

BLOCKED = ("/usr/bin/security", "/usr/bin/osascript", "/usr/bin/pgrep", "/bin/ps", "/usr/bin/open", "/usr/bin/brctl",
           "/usr/bin/xattr", "security", "osascript", "pgrep", "open", "brctl", "xattr")
_real_run = subprocess.run
blocked_calls = []


def _guarded_run(args, *a, **kw):
    prog = args[0] if isinstance(args, (list, tuple)) and args else args
    if isinstance(prog, str) and (prog in BLOCKED or os.path.basename(prog) in ("security", "osascript", "pgrep", "brctl", "xattr")
                                  or prog in ("/bin/ps", "/usr/bin/open")):
        blocked_calls.append(prog)
        return subprocess.CompletedProcess(args, 1, "", "blocked in tests")
    return _real_run(args, *a, **kw)


subprocess.run = _guarded_run


class HermeticTests(unittest.TestCase):
    def test_guard_is_active(self):
        r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "x"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
