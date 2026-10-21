// Beta update notice: once per launch, read the small manifest attached to the latest GitHub Release and, if it names
// a newer version, offer to open the download page. Never downloads or installs anything itself, never blocks startup,
// and asks only once per version. (A one-click updater comes after the beta.)
const fs = require("fs");

const MANIFEST_URL = "https://github.com/valentilabs/veloura/releases/latest/download/veloura-update-mac.json";

// "0.9.10" > "0.9.2"; anything after "-" (e.g. "-beta") is ignored.
function newer(a, b) {
  const p = (v) => String(v || "").split("-")[0].split(".").map((n) => parseInt(n, 10) || 0);
  const x = p(a), y = p(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
}

function readSeen(file) { try { return JSON.parse(fs.readFileSync(file, "utf8")).seen || null; } catch (_) { return null; } }
function writeSeen(file, version) { try { fs.writeFileSync(file, JSON.stringify({ seen: version })); } catch (_) {} }

// fetchJson(url) -> manifest; ask(manifest) -> Promise<bool> (true = open the download page).
async function check({ current, stateFile, fetchJson, ask, open }) {
  let m;
  try { m = await fetchJson(MANIFEST_URL); } catch (_) { return "offline"; }       // no internet: say nothing
  if (!m || !m.version || !newer(m.version, current)) return "current";
  if (readSeen(stateFile) === m.version) return "seen";
  writeSeen(stateFile, m.version);
  const url = typeof m.download_url === "string" && m.download_url.startsWith("https://") ? m.download_url : null;
  if ((await ask(m)) && url) open(url);
  return "offered";
}

module.exports = { check, newer, MANIFEST_URL };
