"""Mac-side half of the file bridge to the veloura_bridge Piano Roll script.

Flow: prepare a command -> FL runs veloura_bridge -> read the result -> verify.

FL Studio only lets Piano Roll scripts write inside its "Piano roll scripts"
folder, and it refuses folder creation, deletes and renames there. So the
exchange folder (veloura_io) lives inside that folder, this module creates
it, and this module does all the cleanup. Files are published body first,
then a ".done" marker holding the byte length, so neither side ever reads a
half-written file.

This module runs nothing in the background and never touches FL Studio itself.
"""

import glob
import hashlib
import json
import os
import shutil
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Where Veloura keeps what it writes (data/, logs/). The packaged app sets VELOURA_HOME to
# ~/Library/Application Support/Veloura so nothing is ever written inside Veloura.app; in development it is the project folder.
DATA_ROOT = os.environ.get("VELOURA_HOME") or os.environ.get("CADENCE_HOME") or ROOT   # CADENCE_*: the name before 2026-10-21
FL_SCRIPTS_DIR = os.path.expanduser("~/Documents/Image-Line/FL Studio/Settings/Piano roll scripts")
BRIDGE_DIR = os.path.join(FL_SCRIPTS_DIR, "veloura_io")
LOG_DIR = os.path.join(DATA_ROOT, "logs")
SCRIPT_SOURCE = os.path.join(ROOT, "fl_scripts", "veloura_bridge.pyscript")
SCRIPT_INSTALLED = os.path.join(FL_SCRIPTS_DIR, "veloura_bridge.pyscript")

CONTROLLER_SOURCE = os.path.join(ROOT, "fl_scripts", "device_VelouraController.py")
CONTROLLER_DIR = os.path.expanduser("~/Documents/Image-Line/FL Studio/Settings/Hardware/Veloura Controller")
# What the app installed into FL while it was called Cadence (before 2026-10-21): removed once Veloura's are in place.
OLD_FL_FILES = [os.path.join(FL_SCRIPTS_DIR, "cadence_bridge.pyscript"),
                os.path.join(os.path.dirname(CONTROLLER_DIR), "Cadence Controller", "device_CadenceController.py")]
OLD_FL_DIRS = [os.path.join(FL_SCRIPTS_DIR, "cadence_io"), os.path.join(os.path.dirname(CONTROLLER_DIR), "Cadence Controller")]


def remove_old_cadence_files():
    """Take out the Cadence-named bridge script, controller script and exchange folder (only those). Returns what went."""
    import shutil
    gone = []
    for f in OLD_FL_FILES:
        if os.path.isfile(f):
            try:
                os.remove(f)
                gone.append(f)
            except OSError:
                pass
    for d in OLD_FL_DIRS:
        if os.path.isdir(d):
            if d.endswith("cadence_io"):
                shutil.rmtree(d, ignore_errors=True)
            else:
                try:
                    os.rmdir(d)   # only if empty: never delete anything Cadence didn't put there
                except OSError:
                    continue
            gone.append(d)
    return gone
CONTROLLER_INSTALLED = os.path.join(CONTROLLER_DIR, "device_VelouraController.py")

PROTOCOL = 2
DEFAULT_TTL_SECONDS = 10 * 60
ATTEMPT_LOG_MAX_BYTES = 5_000_000   # attempts.jsonl rolls over to attempts.1.jsonl past this (one old copy kept)
ARCHIVE_KEEP = 400                  # newest retired command files kept in logs/archive


class BridgeError(RuntimeError):
    pass


def _b(name):
    return os.path.join(BRIDGE_DIR, name)


def sent_dir():
    return os.path.join(LOG_DIR, "sent")


def archive_dir():
    return os.path.join(LOG_DIR, "archive")


def attempt_log():
    return os.path.join(LOG_DIR, "attempts.jsonl")


def _write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_published(name):
    """Read <name>.json from the bridge folder only if its .done marker confirms it is complete."""
    body, done = _b(name + ".json"), _b(name + ".done")
    if not (os.path.exists(body) and os.path.exists(done)):
        return None
    with open(done, "r", encoding="utf-8") as f:
        declared = int(f.read().strip())
    with open(body, "r", encoding="utf-8") as f:
        raw = f.read()
    if len(raw.encode("utf-8")) != declared:
        return None
    return json.loads(raw)


def publish(name, obj):
    body = json.dumps(obj, indent=1)
    _write_atomic(_b(name + ".json"), body)
    _write_atomic(_b(name + ".done"), str(len(body.encode("utf-8"))))


# ---------- setup ----------

def bridge_ready():
    return os.path.isdir(BRIDGE_DIR)


def setup_bridge_dir():
    """Create veloura_io inside FL's Piano roll scripts folder (FL scripts cannot create folders)."""
    if not os.path.isdir(FL_SCRIPTS_DIR):
        raise BridgeError("FL Studio's Piano roll scripts folder was not found: %s" % FL_SCRIPTS_DIR)
    if os.path.exists(BRIDGE_DIR) and not os.path.isdir(BRIDGE_DIR):
        raise BridgeError("%s exists but is not a folder. Not touching it." % BRIDGE_DIR)
    if os.path.isdir(BRIDGE_DIR):
        return False
    os.mkdir(BRIDGE_DIR)
    return True


# ---------- commands ----------

def new_command_id():
    return "cad-%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])


def current_command():
    return read_published("command") if bridge_ready() else None


def is_handled(cmd_id):
    return os.path.exists(_b("result-%s.done" % cmd_id))


def pending_command():
    """The queued command, if FL has not handled it yet."""
    cmd = current_command()
    if cmd and not is_handled(cmd.get("id", "")):
        return cmd
    return None


def _base(cmd_type, cmd_id, show_message, ttl):
    now = time.time()
    return {"protocol": PROTOCOL, "id": cmd_id, "type": cmd_type, "created_at": now,
            "expires_at": now + ttl, "show_message": show_message}


def make_add_command(plan, cmd_id=None, allow_existing_notes=False, show_message=True, ttl=DEFAULT_TTL_SECONDS):
    cmd = _base("add_notes", cmd_id or new_command_id(), show_message, ttl)
    cmd.update({
        "allow_existing_notes": allow_existing_notes,
        "title": plan.get("title", ""),
        "max_beats": plan["bars"] * 4,
        "notes": [{"pitch": n["pitch"], "start_beats": n["start"], "length_beats": n["length"],
                   "velocity": n["velocity"]} for n in plan["notes"]],
    })
    return cmd


def make_clear_add_command(plan, cmd_id=None, show_message=True, ttl=DEFAULT_TTL_SECONDS):
    """Reapply: FL deletes every note in the open Piano Roll and writes these, in one run."""
    cmd = _base("clear_and_add", cmd_id or new_command_id(), show_message, ttl)
    cmd.update({
        "title": plan.get("title", ""),
        "max_beats": plan["bars"] * 4,
        "notes": [{"pitch": n["pitch"], "start_beats": n["start"], "length_beats": n["length"],
                   "velocity": n["velocity"]} for n in plan["notes"]],
    })
    return cmd


def make_replace_command(plan, target_id, show_message=True, ttl=DEFAULT_TTL_SECONDS):
    """Remove the notes written by target_id and write the plan's notes, in one script run (one undo step)."""
    cmd = make_add_command(plan, show_message=show_message, ttl=ttl)
    cmd["type"] = "replace_added"
    cmd["target_id"] = target_id
    del cmd["allow_existing_notes"]
    return cmd


def make_snapshot_command(show_message=True, ttl=DEFAULT_TTL_SECONDS):
    return _base("snapshot", new_command_id(), show_message, ttl)


def make_remove_command(target_id, show_message=True, ttl=DEFAULT_TTL_SECONDS):
    cmd = _base("remove_added", new_command_id(), show_message, ttl)
    cmd["target_id"] = target_id
    return cmd


def _retire_command_files():
    """Move the old command (handled or cancelled) out of the bridge folder into logs/archive."""
    os.makedirs(archive_dir(), exist_ok=True)
    stamp = int(time.time() * 1000)
    for name in ("command.json", "command.done"):
        if os.path.exists(_b(name)):
            shutil.move(_b(name), os.path.join(archive_dir(), "%d-%s" % (stamp, name)))
    _prune_archive()


def _prune_archive(keep=ARCHIVE_KEEP):
    """Keep logs/archive from growing forever: delete all but the newest retired command files."""
    try:
        names = sorted(os.listdir(archive_dir()))   # names start with a millisecond timestamp
    except OSError:
        return
    for name in names[:-keep] if len(names) > keep else []:
        try:
            os.remove(os.path.join(archive_dir(), name))
        except OSError:
            pass


def _prune_sent(keep=ARCHIVE_KEEP):
    """logs/sent keeps a copy of each command Veloura sent; only the newest are needed."""
    try:
        files = sorted(glob.glob(os.path.join(sent_dir(), "*.json")), key=os.path.getmtime)
    except OSError:
        return
    for path in files[:-keep] if len(files) > keep else []:
        try:
            os.remove(path)
        except OSError:
            pass


RESULT_MAX_AGE = 7 * 24 * 3600


def tidy_bridge_dir(max_age=RESULT_MAX_AGE, now=None):
    """FL's script can only create files, so old result files pile up in the exchange folder. Remove results older
    than a week. Ledgers and removed-markers stay: Remove and Reapply need them to recognise Veloura's notes."""
    now = now or time.time()
    removed = 0
    for pattern in ("result-*.json", "result-*.done", "started-*.marker", "result-invalid-*"):
        for path in glob.glob(_b(pattern)):
            try:
                if now - os.path.getmtime(path) > max_age:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    return removed


def send_command(cmd, keep_record=True):
    """Queue a command for FL. Refuses if another command is still waiting."""
    if not bridge_ready():
        raise BridgeError("The bridge folder does not exist yet. In Veloura, open Setup and click Install Veloura's FL helpers.")
    waiting = pending_command()
    if waiting is not None:
        raise BridgeError("Command %s is still waiting to be run in FL Studio. Run the script, or cancel it first."
                          % waiting.get("id"))
    _retire_command_files()
    os.makedirs(sent_dir(), exist_ok=True)
    if keep_record:
        record = os.path.join(sent_dir(), cmd["id"] + ".json")
        if not os.path.exists(record):  # a retry keeps the original record
            _write_atomic(record, json.dumps(cmd, indent=1))
            _prune_sent()
    publish("command", cmd)
    return cmd


def cancel_pending():
    cmd = pending_command()
    if cmd is None:
        return None
    _retire_command_files()
    return cmd


def sent_command(cmd_id):
    path = os.path.join(sent_dir(), cmd_id + ".json")
    return _read_json(path) if os.path.exists(path) else None


def last_sent_id():
    files = glob.glob(os.path.join(sent_dir(), "*.json"))
    if not files:
        return None
    return os.path.basename(max(files, key=os.path.getmtime))[:-5]


def command_started(cmd_id):
    """True once FL's bridge script has picked this command up (it writes started-<id>.marker before editing)."""
    return os.path.exists(_b("started-%s.marker" % cmd_id))


def find_result(cmd_id):
    """Newest complete result for this id (including '-dup-' results from retries)."""
    names = []
    for done in glob.glob(_b("result-%s.done" % cmd_id)) + glob.glob(_b("result-%s-dup-*.done" % cmd_id)):
        names.append((os.path.getmtime(done), os.path.basename(done)[:-5]))
    for _, name in sorted(names, reverse=True):
        r = read_published(name)
        if r is not None:
            return r
    return None


def latest_result(cmd_type):
    best = None
    for done in glob.glob(_b("result-*.done")):
        r = read_published(os.path.basename(done)[:-5])
        if r and r.get("type") == cmd_type and (best is None or r.get("handled_at", 0) > best.get("handled_at", 0)):
            best = r
    return best


# ---------- verification ----------

def _key(d):
    return (d["number"], d["time"], d["length"], d["vel127"])


def _counter(keys):
    out = {}
    for k in keys:
        out[k] = out.get(k, 0) + 1
    return out


def expected_ticks(cmd, ppq):
    out = []
    for n in cmd["notes"]:
        out.append({"number": n["pitch"], "time": int(round(n["start_beats"] * ppq)),
                    "length": int(round(n["length_beats"] * ppq)), "vel127": n["velocity"]})
    return out


def verify_add(cmd, result):
    """Independent check of an add_notes result against what Veloura asked for."""
    checks = []

    def check(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    check("FL handled the command", result.get("status") in ("applied", "applied_unverified"),
          "status=%s: %s" % (result.get("status"), result.get("message")))
    if result.get("status") not in ("applied", "applied_unverified"):
        return checks
    ppq = result.get("ppq")
    check("PPQ read from FL", isinstance(ppq, int) and ppq > 0, "PPQ=%s" % ppq)
    want = expected_ticks(cmd, ppq)
    before, after = result.get("before", []), result.get("after", [])
    after_c = _counter(_key(d) for d in after)
    before_c = _counter(_key(d) for d in before)
    want_c = _counter(_key(w) for w in want)
    missing = sum(max(0, c - (after_c.get(k, 0) - before_c.get(k, 0))) for k, c in want_c.items())
    check("Every requested note found in readback (pitch, start, length, velocity)", missing == 0,
          "%d/%d matched" % (len(want) - missing, len(want)))
    lost = [k for k, c in before_c.items() if after_c.get(k, 0) < c]
    check("All pre-existing notes still present", not lost, "%d pre-existing, %d missing" % (len(before), len(lost)))
    check("Note count = before + requested", len(after) == len(before) + len(want),
          "before=%d requested=%d after=%d" % (len(before), len(want), len(after)))
    return checks


def verify_clear_add(cmd, result):
    """Independent check of a clear_and_add result: the Piano Roll now holds exactly the requested notes."""
    checks = []

    def check(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    check("FL handled the command", result.get("status") in ("applied", "applied_unverified"),
          "status=%s: %s" % (result.get("status"), result.get("message")))
    if result.get("status") not in ("applied", "applied_unverified"):
        return checks
    ppq = result.get("ppq")
    check("PPQ read from FL", isinstance(ppq, int) and ppq > 0, "PPQ=%s" % ppq)
    want = expected_ticks(cmd, ppq)
    after = result.get("after", [])
    check("Old notes cleared, only the new notes are there (pitch, start, length, velocity)",
          _counter(_key(d) for d in after) == _counter(_key(w) for w in want),
          "cleared %d, wrote %d, now %d" % (len(result.get("before", [])), len(want), len(after)))
    return checks


def verify_replace(cmd, result):
    """Independent check of a replace_added result: new notes present, nothing else lost."""
    checks = []
    status = result.get("status")
    checks.append({"check": "FL handled the command", "passed": status in ("applied", "applied_unverified"),
                   "detail": "status=%s: %s" % (status, result.get("message"))})
    if status not in ("applied", "applied_unverified"):
        return checks
    v = result.get("in_run_verification") or {}
    want = _counter(_key(w) for w in expected_ticks(cmd, result.get("ppq")))
    after = _counter(_key(d) for d in result.get("after", []))
    missing = sum(max(0, c - after.get(k, 0)) for k, c in want.items())
    checks.append({"check": "Every new note found in readback", "passed": missing == 0,
                   "detail": "%d/%d matched" % (sum(want.values()) - missing, sum(want.values()))})
    expected_count = v.get("notes_before", 0) - v.get("notes_removed", 0) + v.get("notes_added", 0)
    checks.append({"check": "Note count = before - replaced + new", "passed": len(result.get("after", [])) == expected_count,
                   "detail": "before=%s replaced=%s new=%s after=%d" % (v.get("notes_before"), v.get("notes_removed"),
                                                                         v.get("notes_added"), len(result.get("after", [])))})
    checks.append({"check": "FL-side check: all other notes untouched", "passed": bool(v.get("passed")), "detail": ""})
    return checks


def verify_snapshot_after_add(cmd, add_result, snapshot):
    """Post-run check: are the added notes really in FL after the script finished?"""
    ppq = snapshot.get("ppq")
    want = _counter(_key(w) for w in expected_ticks(cmd, ppq))
    before = _counter(_key(d) for d in add_result.get("before", []))
    now = _counter(_key(d) for d in snapshot.get("notes", []))
    expected = dict(before)
    for k, c in want.items():
        expected[k] = expected.get(k, 0) + c
    return [{"check": "Snapshot taken after the script finished matches before + added notes",
             "passed": now == expected,
             "detail": "expected %d notes, found %d" % (sum(expected.values()), sum(now.values()))}]


def compare_to_before(add_result, snapshot):
    """Undo test: does the Piano Roll now match the state before the add?"""
    before = _counter(_key(d) for d in add_result.get("before", []))
    now = _counter(_key(d) for d in snapshot.get("notes", []))
    return before == now, sum(before.values()), sum(now.values())


# ---------- log ----------

def log_attempt(entry):
    os.makedirs(LOG_DIR, exist_ok=True)
    entry = dict(entry)
    entry.setdefault("logged_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    path = attempt_log()
    try:
        if os.path.getsize(path) > ATTEMPT_LOG_MAX_BYTES:
            os.replace(path, path[:-len(".jsonl")] + ".1.jsonl")
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def file_sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def installed_script_state():
    if not os.path.exists(SCRIPT_INSTALLED):
        return "not installed"
    if file_sha256(SCRIPT_INSTALLED) != file_sha256(SCRIPT_SOURCE):
        return "installed, but DIFFERENT from fl_scripts/veloura_bridge.pyscript (out of date)"
    return "installed and up to date"


def controller_script_state():
    if not os.path.exists(CONTROLLER_INSTALLED):
        return "not installed"
    if file_sha256(CONTROLLER_INSTALLED) != file_sha256(CONTROLLER_SOURCE):
        return "installed, but out of date"
    return "installed and up to date"
