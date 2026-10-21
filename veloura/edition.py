"""Customer build vs. the developer's developer copy.

Developer mode is OFF unless one of these is set:
  * the file ~/Library/Application Support/Veloura/dev_mode exists (the developer's Mac), or
  * the environment variable VELOURA_DEV_MODE=1.
Developer mode adds the personal "Claude (your account)" provider (Claude Code CLI; not allowed in apps given to
others) and makes Opus the default Claude model. Customers get none of that.
"""

import os

VERSION = "0.9.0"
CHANNEL = "beta"
DEV_FLAG_FILE = os.path.expanduser("~/Library/Application Support/Veloura/dev_mode")
OLD_DEV_FLAG_FILE = os.path.expanduser("~/Library/Application Support/Cadence/dev_mode")   # before the rename (2026-10-21)


def dev_mode():
    env = os.environ.get("VELOURA_DEV_MODE", os.environ.get("CADENCE_DEV_MODE"))
    if env is not None:
        return env.strip() not in ("", "0", "false", "no")
    return os.path.exists(DEV_FLAG_FILE) or os.path.exists(OLD_DEV_FLAG_FILE)
