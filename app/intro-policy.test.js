// node app/intro-policy.test.js  (run by tests/test_intro.py)
const assert = require("assert");
const { shouldPlay, AWAY_MS } = require("./intro-policy");
const t = 1_800_000_000_000;
const prev = { boot: 100, version: "0.9.0", lastSeen: t - 60_000 };
assert.strictEqual(shouldPlay({}, { boot: 100, version: "0.9.0", time: t }), true, "first launch ever");
assert.strictEqual(shouldPlay(prev, { boot: 100, version: "0.9.0", time: t }), false, "normal quit and reopen");
assert.strictEqual(shouldPlay(prev, { boot: 200, version: "0.9.0", time: t }), true, "after the Mac restarted");
assert.strictEqual(shouldPlay(prev, { boot: 100, version: "0.9.1", time: t }), true, "after an update");
assert.strictEqual(shouldPlay(prev, { boot: 100, version: "0.9.0", time: prev.lastSeen + AWAY_MS }), true, "4 hours away");
assert.strictEqual(shouldPlay(prev, { boot: 100, version: "0.9.0", time: prev.lastSeen + AWAY_MS - 1 }), false, "just under 4 hours");
assert.strictEqual(shouldPlay(prev, { boot: null, version: "0.9.0", time: t }), false, "boot time unknown: no false replays");
console.log("intro policy ok");
assert.strictEqual(AWAY_MS, 4 * 60 * 60 * 1000, "the away rule is 4 hours");
assert.strictEqual(shouldPlay(prev, { boot: 100, version: "0.9.0", time: prev.lastSeen + 30 * 60 * 1000 }), false, "a quick reopen stays silent");
