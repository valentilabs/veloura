"""Only one Veloura service may create FL's ports ("Veloura to FL" / "FL to Veloura"): no "#2" pair in FL."""
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from veloura import fl_controller as fc  # noqa: E402

HOLD = """
import fcntl, sys, time
fh = open(sys.argv[1], "a+"); fcntl.flock(fh, fcntl.LOCK_EX); fh.seek(0); fh.truncate(); fh.write(sys.argv[2]); fh.flush()
print("held", flush=True); time.sleep(30)
"""


class PortLockTests(unittest.TestCase):
    def setUp(self):
        fc._port_lock["fh"] = None
        self.path = os.path.join(tempfile.mkdtemp(), "ports.lock")
        self.addCleanup(lambda: fc._port_lock.update(fh=None))

    def _holder(self, pid_text):
        p = subprocess.Popen([sys.executable, "-c", HOLD, self.path, pid_text], stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.kill)
        self.assertEqual(p.stdout.readline().strip(), "held")
        return p

    @mock.patch.object(fc, "other_services", lambda: [])
    def test_free_lock_is_claimed_and_records_our_pid(self):
        self.assertTrue(fc.claim_ports(self.path, wait=1))
        with open(self.path) as f:
            self.assertEqual(f.read(), str(os.getpid()))

    @mock.patch.object(fc, "other_services", lambda: [])
    def test_an_older_veloura_service_is_asked_to_quit(self):
        holder = self._holder("0")
        with open(self.path, "w") as f:   # what the holder recorded: its own pid
            f.write(str(holder.pid))
        killed = []
        def kill(pid, sig):
            killed.append((pid, sig))
            holder.kill(); holder.wait()
        self.assertTrue(fc.claim_ports(self.path, wait=3, is_service=lambda pid: True, kill=kill))
        self.assertEqual(killed, [(holder.pid, signal.SIGTERM)])

    @mock.patch.object(fc, "other_services", lambda: [])
    def test_something_else_holding_the_lock_is_left_alone_and_refused(self):
        holder = self._holder("12345")
        with self.assertRaises(fc.ControllerUnavailable):
            fc.claim_ports(self.path, wait=0.5, is_service=lambda pid: False, kill=lambda *a: self.fail("must not kill"))
        self.assertIsNone(holder.poll())

    def test_services_from_before_the_lock_are_stopped(self):
        killed = []
        with mock.patch.object(fc, "other_services", lambda: [4242]):
            fc.claim_ports(self.path, wait=1, kill=lambda pid, sig: killed.append((pid, sig)))
        self.assertIn((4242, signal.SIGTERM), killed)

    def test_virtual_ports_are_only_made_after_the_lock(self):
        src = open(os.path.join(ROOT, "veloura", "fl_controller.py"), encoding="utf-8").read()
        body = src[src.index("class RtMidiTransport"):]
        self.assertLess(body.index("claim_ports()"), body.index("open_virtual_port"))


if __name__ == "__main__":
    unittest.main()
