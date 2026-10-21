"""Keep the sounds Veloura uses really on this Mac when they live in iCloud Drive (Desktop & Documents sync).

With "Optimize Mac Storage", macOS evicts files to iCloud: they stay listed but hold no data ("dataless"). Opening one
makes macOS download it first, which can take seconds per file, and a hard link to one points at an empty placeholder.
So before Veloura stages or loads a kit it downloads the files, and pins their kit folder ("Keep Downloaded", the same
flag Finder sets) so macOS doesn't evict them again. Verified on macOS 26: the pin xattr sets FileProvider's
isKeepDownloaded = 1.
"""

import os
import shutil
import subprocess
import time

SF_DATALESS = 0x40000000                         # st_flags bit for an evicted (iCloud-only) file
PIN_XATTR = "com.apple.fileprovider.pinned#PX"   # what Finder's "Keep Downloaded" sets
MIN_FREE_BYTES = 5 * 1024 ** 3                   # never fill the disk below ~5 GB to download sounds


def is_evicted(path):
    try:
        return bool(os.stat(path).st_flags & SF_DATALESS)
    except (OSError, AttributeError):
        return False


def free_bytes(path=None):
    try:
        return shutil.disk_usage(path or os.path.expanduser("~")).free
    except OSError:
        return 0


def pin(folder):
    """Mark a folder "Keep Downloaded" so iCloud keeps its files on this Mac. True if the flag was set."""
    try:
        p = subprocess.run(["/usr/bin/xattr", "-w", PIN_XATTR, "1", folder], capture_output=True, timeout=10)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def is_pinned(folder):
    try:
        p = subprocess.run(["/usr/bin/xattr", "-p", PIN_XATTR, folder], capture_output=True, timeout=10)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def request_download(paths):
    for i in range(0, len(paths), 50):
        try:
            subprocess.run(["/usr/bin/brctl", "download"] + list(paths[i:i + 50]), capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pass


def ensure_local(paths, timeout=60.0, on_progress=None, sleep=time.sleep):
    """Download any evicted files among `paths` and wait for them. Returns the paths still not on this Mac.

    Refuses (returns them all) when the downloads would leave less than MIN_FREE_BYTES free."""
    todo = [p for p in paths if is_evicted(p)]
    if not todo:
        return []
    need = sum(os.stat(p).st_size for p in todo)
    if free_bytes() - need < MIN_FREE_BYTES:
        return todo
    request_download(todo)
    end = time.time() + timeout
    while todo and time.time() < end:
        if on_progress:
            on_progress(len(paths) - len(todo), len(paths))
        sleep(0.3)
        todo = [p for p in todo if is_evicted(p)]
    return todo


def kit_folder(path, roots):
    """The kit folder a sound belongs to: the library folder it was added from (or its own folder)."""
    real = os.path.realpath(path)
    best = None
    for r in roots or []:
        r = os.path.realpath(r)
        if real.startswith(r + os.sep) and (best is None or len(r) > len(best)):
            best = r
    return best or os.path.dirname(real)


def keep(folders):
    """Pin each folder ("Keep Downloaded") and ask iCloud to bring back anything already evicted, unless that would
    leave less than MIN_FREE_BYTES free. Doesn't wait. Returns {folder: {"pinned", "evicted", "requested"}}."""
    out = {}
    for d in folders:
        if not d or not os.path.isdir(d):
            continue
        pinned = is_pinned(d) or pin(d)
        gone = []
        for dp, dn, fn in os.walk(d):
            gone += [os.path.join(dp, f) for f in fn if is_evicted(os.path.join(dp, f))]
        need = sum(os.stat(p).st_size for p in gone)
        ok = bool(gone) and free_bytes() - need >= MIN_FREE_BYTES
        if ok:
            request_download(gone)
        out[d] = {"pinned": pinned, "evicted": len(gone), "requested": ok}
    return out
