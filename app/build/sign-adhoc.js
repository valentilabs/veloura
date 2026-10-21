// Ad hoc signing for builds without a Developer ID certificate, done inside-out so every nested piece has a valid
// signature: each Mach-O binary (the bundled Python's libraries, Electron's dylibs and helpers), then each framework
// and helper app, then Veloura.app itself. Signing only the outer app left Electron's helper apps with signatures
// that no longer matched their renamed Info.plist; macOS ignores that for a local build but Gatekeeper checks it on
// a downloaded (quarantined) copy and reports the app as "damaged".
//   node build/sign-adhoc.js <Veloura.app> <bundle id>      sign
//   node build/sign-adhoc.js --check-zip <Veloura.app>        zip it like a release, unzip like Safari, verify
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const MACHO = new Set(["feedfacf", "cffaedfe", "cafebabe", "bebafeca", "feedface", "cefaedfe"]);
const isMachO = (file) => {
  const fd = fs.openSync(file, "r");
  try { const b = Buffer.alloc(4); return fs.readSync(fd, b, 0, 4, 0) === 4 && MACHO.has(b.toString("hex")); }
  finally { fs.closeSync(fd); }
};
const depth = (p) => p.split(path.sep).length;
const LSREGISTER = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister";
// Forget a build copy in LaunchServices, so opening "Veloura" can only ever start the installed /Applications copy.
// (A stray copy with the same app id, especially a quarantined test copy, is what macOS may launch instead.)
const unregister = (app) => { try { execFileSync(LSREGISTER, ["-u", app], { stdio: "ignore" }); } catch (_) {} };
const sign = (target, extra = []) =>
  execFileSync("/usr/bin/codesign", ["--force", "--sign", "-", ...extra, target], { stdio: ["ignore", "ignore", "inherit"] });

function walk(dir, files, bundles) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isSymbolicLink()) continue;
    if (e.isDirectory()) {
      if (/\.(app|framework)$/.test(e.name)) bundles.push(p);
      walk(p, files, bundles);
    } else if (e.isFile() && isMachO(p)) files.push(p);
  }
}

function signApp(app, bundleId) {
  execFileSync("/usr/bin/xattr", ["-cr", app]);   // codesign refuses Finder/provenance attributes
  const files = [], bundles = [];
  walk(path.join(app, "Contents"), files, bundles);
  // 1. binaries whose own signature is missing or broken, deepest first. Binaries that already verify keep their
  // signature: re-signing the bundled Python gave it a new code identity, and macOS then kept turning Veloura's
  // Accessibility permission off after each quit (the Python service is what checks it and sends FL's shortcut).
  const valid = (f) => { try { execFileSync("/usr/bin/codesign", ["--verify", "--strict", f], { stdio: "ignore" }); return true; } catch (_) { return false; } };
  for (const f of files.sort((x, y) => depth(y) - depth(x))) if (!valid(f)) sign(f);
  // 2. frameworks and helper apps, deepest first
  for (const b of bundles.sort((a, b) => depth(b) - depth(a))) sign(b);
  // 3. the app itself, under Veloura's identifier
  sign(app, ["--identifier", bundleId]);
  execFileSync("/usr/bin/codesign", ["--verify", "--deep", "--strict", app], { stdio: "inherit" });
}

// Zip like the release (ditto, keeping symlinks), unzip like Safari / Archive Utility, mark it downloaded, verify.
function checkZip(app, { notarized = false } = {}) {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "veloura-zipcheck-"));
  try {
    const zip = path.join(tmp, "Veloura.zip"), out = path.join(tmp, "out");
    execFileSync("/usr/bin/ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", app, zip]);
    execFileSync("/usr/bin/ditto", ["-x", "-k", zip, out]);
    const copy = path.join(out, path.basename(app));
    const q = "0083;" + Math.floor(Date.now() / 1000).toString(16) + ";Safari;";
    execFileSync("/usr/bin/xattr", ["-r", "-w", "com.apple.quarantine", q, copy]);
    execFileSync("/usr/bin/codesign", ["--verify", "--deep", "--strict", copy], { stdio: "inherit" });
    // An ad hoc app is "rejected" by Gatekeeper (the user clicks Open Anyway); what must never appear is a broken
    // signature, which is what makes macOS call the app damaged.
    const r = require("child_process").spawnSync("/usr/sbin/spctl", ["-a", "-vv", "-t", "exec", copy], { encoding: "utf8" });
    const msg = String(r.stdout || "") + String(r.stderr || "");   // spctl reports on stderr, also on success
    if (/invalid|damaged|no resources|not signed at all|modified/i.test(msg)) throw new Error("Gatekeeper sees a broken signature: " + msg.trim());
    if (notarized && !/accepted[\s\S]*Notarized Developer ID/i.test(msg)) throw new Error("Gatekeeper didn't accept the notarized build: " + msg.trim());
    console.log("Zip check OK (downloaded copy verifies; Gatekeeper: " + (msg.trim().split("\n")[0] || "accepted") + ")");
  } finally {
    unregister(path.join(tmp, "out", path.basename(app)));   // the quarantined test copy must never stay launchable
    fs.rmSync(tmp, { recursive: true, force: true });
  }
}

module.exports = { signApp, checkZip, unregister, isMachO };
if (require.main === module) {
  const [a, b] = process.argv.slice(2);
  if (a === "--check-zip") checkZip(path.resolve(b));
  else signApp(path.resolve(a), b || "com.valentilabs.veloura");
}
