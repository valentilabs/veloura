"""Mac side of the Veloura Controller link (Milestone C).

Talks SysEx to fl_scripts/device_VelouraController.py over two MIDI ports that
Veloura creates itself while it runs: "Veloura to FL" (FL's MIDI input) and
"FL to Veloura" (FL's MIDI output). No macOS MIDI setup is needed; the ports
disappear when Veloura quits. (IAC Driver buses also work if named in the hints.)
Needs python-rtmidi (installed in the project's .venv). If it or the ports are
missing, every call raises ControllerUnavailable and Veloura falls back to the
Piano Roll bridge and guided steps.
"""

import fcntl
import json
import os
import signal
import subprocess
import threading
import time

from .help_text import RECONNECT_TEXT

MANUFACTURER = 0x7D
TAG = 0x43
CHUNK = 200
PROTOCOL = 1


class ControllerUnavailable(RuntimeError):
    pass


class ControllerError(RuntimeError):
    pass


def pack7(data):
    out = bytearray()
    for i in range(0, len(data), 7):
        group = data[i:i + 7]
        high = 0
        for j, b in enumerate(group):
            high |= ((b >> 7) & 1) << j
        out.append(high)
        out.extend(b & 0x7F for b in group)
    return bytes(out)


def unpack7(data):
    out = bytearray()
    i = 0
    while i < len(data):
        high = data[i]
        i += 1
        n = min(7, len(data) - i)
        for j in range(n):
            out.append(data[i + j] | (((high >> j) & 1) << 7))
        i += n
    return bytes(out)


def frames_for(req_id, payload, kind=0):
    packed = pack7(json.dumps(payload).encode("utf-8"))
    total = max(1, (len(packed) + CHUNK - 1) // CHUNK)
    out = []
    for seq in range(total):
        f = bytearray([0xF0, MANUFACTURER, TAG, kind, (req_id >> 7) & 0x7F, req_id & 0x7F, seq, total])
        f.extend(packed[seq * CHUNK:(seq + 1) * CHUNK])
        f.append(0xF7)
        out.append(bytes(f))
    return out


VIRTUAL_TO_FL = "Veloura to FL"
VIRTUAL_FROM_FL = "FL to Veloura"


# FL's ports ("Veloura to FL" / "FL to Veloura") exist once per Mac, so only one Veloura service may create them.
# The lock is per user and machine-wide (not in the data folder): a second service with another data folder (an old
# install, a development run) used to create "Veloura to FL #2", and FL kept talking to the other one.
PORT_LOCK = "/tmp/veloura-midi-ports-%d.lock" % os.getuid()
_port_lock = {"fh": None}


def _is_veloura_service(pid):
    try:
        out = subprocess.run(["/bin/ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "veloura.service" in out or "cadence.service" in out   # also the app's old name


def other_services():
    """Other running Veloura services of this user (any install or a development run), not this one."""
    try:
        out = subprocess.run(["/usr/bin/pgrep", "-U", str(os.getuid()), "-f", "[ ]-m (veloura|cadence)[.]service"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(x) for x in out.split() if x.isdigit() and int(x) not in (os.getpid(), os.getppid())]


def claim_ports(path=PORT_LOCK, wait=4.0, is_service=_is_veloura_service, kill=os.kill):
    """Hold the machine-wide lock for FL's ports. An older Veloura service holding it is asked to quit (it can only
    be a leftover: the app runs one service). Anything else holding it: refuse, so FL never sees a second pair."""
    if _port_lock["fh"] is not None:
        return True
    for pid in other_services():   # older Veloura services from before this lock existed hold no lock: stop them too
        try:
            kill(pid, signal.SIGTERM)
        except OSError:
            pass
    fh = open(path, "a+")
    deadline, asked = time.time() + wait, False
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            fh.seek(0)
            try:
                pid = int(fh.read().strip() or 0)
            except ValueError:
                pid = 0
            if not asked and pid and pid != os.getpid() and is_service(pid):
                try:
                    kill(pid, signal.SIGTERM)
                except OSError:
                    pass
                asked = True
            if time.time() > deadline:
                fh.close()
                raise ControllerUnavailable("Another Veloura is already connected to FL. Quit it (or restart your Mac) "
                                            "and reopen Veloura.")
            time.sleep(0.2)
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    _port_lock["fh"] = fh
    return True


class RtMidiTransport:
    """Real MIDI I/O via python-rtmidi: uses existing ports matching the hints, else creates virtual ports."""

    def __init__(self, out_hint=None, in_hint=None):
        try:
            import rtmidi  # noqa: F401
        except ImportError:
            raise ControllerUnavailable("python-rtmidi is not installed (it lives in the project's .venv).")
        import rtmidi
        self.out = rtmidi.MidiOut()
        self.inp = rtmidi.MidiIn()
        outs, ins = self.out.get_ports(), self.inp.get_ports()
        oi = next((i for i, n in enumerate(outs) if out_hint and out_hint.lower() in n.lower()), None)
        ii = next((i for i, n in enumerate(ins) if in_hint and in_hint.lower() in n.lower()), None)
        if oi is not None and ii is not None:
            self.out.open_port(oi)
            self.inp.open_port(ii)
            self.virtual = False
        else:
            claim_ports()
            self.out.open_virtual_port(VIRTUAL_TO_FL)
            self.inp.open_virtual_port(VIRTUAL_FROM_FL)
            self.virtual = True
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        self.on_frame = None
        self.inp.set_callback(self._cb)

    def _cb(self, event, _data=None):
        msg = event[0]
        if msg and msg[0] == 0xF0 and self.on_frame:
            self.on_frame(bytes(msg))

    def send(self, frame):
        self.out.send_message(list(frame))

    def close(self):
        for p in (self.inp, self.out):
            try:
                p.close_port()
            except Exception:
                pass


class ControllerLink:
    def __init__(self, out_hint=None, in_hint=None, transport_factory=None):
        self.out_hint, self.in_hint = out_hint, in_hint
        self.transport_factory = transport_factory or (lambda: RtMidiTransport(self.out_hint, self.in_hint))
        self.transport = None
        self.lock = threading.Lock()
        self.next_id = int(time.time()) % 16000
        self.pending = {}
        self.cond = threading.Condition()

    def _ensure(self):
        if self.transport is None:
            t = self.transport_factory()
            t.on_frame = self._on_frame
            self.transport = t

    def _on_frame(self, raw):
        if len(raw) < 9 or raw[1] != MANUFACTURER or raw[2] != TAG or raw[3] != 1:
            return
        req_id, seq, total = (raw[4] << 7) | raw[5], raw[6], raw[7]
        with self.cond:
            entry = self.pending.get(req_id)
            if entry is None:
                return
            entry["chunks"][seq] = raw[8:-1]
            entry["total"] = total
            if len(entry["chunks"]) == total:
                try:
                    entry["result"] = json.loads(unpack7(b"".join(entry["chunks"][i] for i in range(total))).decode("utf-8"))
                except ValueError as e:
                    entry["result"] = {"ok": False, "error": "unreadable response: %s" % e}
                self.cond.notify_all()

    def request(self, op, params=None, timeout=2.0):
        with self.lock:
            self._ensure()
            self.next_id = (self.next_id + 1) % 16384
            req_id = self.next_id
            with self.cond:
                self.pending[req_id] = {"chunks": {}, "total": None, "result": None}
            try:
                for f in frames_for(req_id, {"protocol": PROTOCOL, "op": op, "params": params or {}}):
                    self.transport.send(f)
                deadline = time.time() + timeout
                with self.cond:
                    while self.pending[req_id]["result"] is None:
                        left = deadline - time.time()
                        if left <= 0:
                            raise ControllerUnavailable(
                                "FL Studio is not answering. " + RECONNECT_TEXT + " If it still won't connect: in FL's "
                                "Options > MIDI settings, set Input 'Veloura to FL' to controller type 'Veloura Controller' "
                                "(enabled, port 10) and Output 'FL to Veloura' to port 10.")
                        self.cond.wait(left)
                    res = self.pending[req_id]["result"]
            finally:
                with self.cond:
                    self.pending.pop(req_id, None)
        if not res.get("ok"):
            raise ControllerError(res.get("error", "controller error"))
        return res["result"]

    def close(self):
        if self.transport:
            self.transport.close()
            self.transport = None
