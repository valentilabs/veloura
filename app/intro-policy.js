// When to play Veloura's opening animation: only on the first launch after the Mac starts up, after Veloura is
// updated, or after 4+ hours without Veloura running. A normal quit and reopen never plays it.
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const AWAY_MS = 4 * 60 * 60 * 1000;   // 2026-10-20: was 8 hours

function bootTime() {
  // "{ sec = 1760900000, usec = 123 } Sun Oct 19 ..." -> 1760900000
  try {
    const out = execFileSync("/usr/sbin/sysctl", ["-n", "kern.boottime"], { encoding: "utf8", timeout: 3000 });
    const m = /sec\s*=\s*(\d+)/.exec(out);
    return m ? Number(m[1]) : null;
  } catch (_) { return null; }
}

function read(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch (_) { return {}; }
}

function write(file, state) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file + ".tmp", JSON.stringify(state));
    fs.renameSync(file + ".tmp", file);
  } catch (_) {}
}

// Pure decision, so it can be tested: prev = saved state, now = {boot, version, time}.
function shouldPlay(prev, now) {
  if (!prev || !prev.version) return true;                      // first launch ever
  if (now.boot && prev.boot !== now.boot) return true;          // first launch since the Mac started
  if (prev.version !== now.version) return true;                // Veloura was updated
  if (!prev.lastSeen || now.time - prev.lastSeen >= AWAY_MS) return true;   // 4+ hours without Veloura running
  return false;
}

// Decide for this launch, record it, and keep "lastSeen" fresh while Veloura runs (so time away is measured from
// when Veloura last ran, not from when it was opened). Returns { play, stop } where stop() records the quit.
function start(file, version) {
  const now = { boot: bootTime(), version, time: Date.now() };
  const play = shouldPlay(read(file), now);
  const save = () => write(file, { boot: now.boot, version, lastSeen: Date.now() });
  save();
  const timer = setInterval(save, 5 * 60 * 1000);
  return { play, stop: () => { clearInterval(timer); save(); } };
}

module.exports = { shouldPlay, start, AWAY_MS };
