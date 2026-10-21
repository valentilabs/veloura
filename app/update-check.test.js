const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs"), os = require("os"), path = require("path");
const { check, newer } = require("./update-check");

test("version compare", () => {
  assert.ok(newer("0.9.10", "0.9.2"));
  assert.ok(newer("1.0.0", "0.9.9"));
  assert.ok(!newer("0.9.0", "0.9.0"));
  assert.ok(!newer("0.8.9", "0.9.0"));
});

test("offers a newer version once, ignores offline and same version", async () => {
  const stateFile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cu-")), "update_state.json");
  const opened = [];
  const base = { current: "0.9.0", stateFile, ask: async () => true, open: (u) => opened.push(u) };
  assert.equal(await check({ ...base, fetchJson: async () => { throw new Error("offline"); } }), "offline");
  assert.equal(await check({ ...base, fetchJson: async () => ({ version: "0.9.0" }) }), "current");
  const m = { version: "0.9.1", download_url: "https://example.com/veloura" };
  assert.equal(await check({ ...base, fetchJson: async () => m }), "offered");
  assert.deepEqual(opened, ["https://example.com/veloura"]);
  assert.equal(await check({ ...base, fetchJson: async () => m }), "seen");
  assert.equal(await check({ ...base, fetchJson: async () => ({ version: "0.9.2", download_url: "http://bad" }) }), "offered");
  assert.equal(opened.length, 1);   // a non-https link is never opened
});
