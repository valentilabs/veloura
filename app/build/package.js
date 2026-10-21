// Builds dist/Veloura-darwin-arm64/Veloura.app as a self-contained app (run with `npm run package`).
//
// Inside Contents/Resources it puts:
//   python/  a relocatable Python (python-build-standalone, pinned below) with the packages in requirements.txt,
//            at the exact versions in build/python-lock.txt
//   core/    the Python service (veloura/), the UI (app/ui), the Anthropic helper (app/ai + its npm packages) and the
//            FL scripts (fl_scripts/), laid out like the project folder so every path inside the service works unchanged.
// The app writes nothing inside itself: user data lives in ~/Library/Application Support/Veloura (see main.js).
//
// Signing and notarization are prepared but OFF. To turn them on later (needs a "Developer ID Application" certificate
// in the login keychain and a notarytool keychain profile):  VELOURA_SIGN=1 VELOURA_NOTARY_PROFILE=<profile> npm run package
const { execFileSync } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const APP = path.resolve(__dirname, "..");          // app/
const ROOT = path.resolve(APP, "..");               // the project folder
// Downloads, the built Python and the staged core. Kept outside the project folder: the Desktop is synced to iCloud
// on this Mac, which makes reading hundreds of MB back from it very slow.
const CACHE = path.join(require("os").homedir(), "Library", "Caches", "Cadence Build");

// Pinned Python: the same minor version as the project .venv (3.9). 3.9.24 is the last 3.9 release.
const PY = {
  version: "3.9.24",
  file: "cpython-3.9.24+20251014-aarch64-apple-darwin-install_only.tar.gz",
  url: "https://github.com/astral-sh/python-build-standalone/releases/download/20251014/cpython-3.9.24%2B20251014-aarch64-apple-darwin-install_only.tar.gz",
  sha256: "6b65213e639e91eb8072db80ed9c140d769af1d5e0386efd8f153449c3694714",
};
const REQUIREMENTS = path.join(ROOT, "requirements.txt");
const LOCK = path.join(__dirname, "python-lock.txt");
const BUNDLE_ID = "com.valentilabs.veloura";

const run = (cmd, args, opts = {}) => execFileSync(cmd, args, { stdio: "inherit", ...opts });
const sha256 = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");

// 1. The bundled Python, rebuilt only when the pinned version or the requirements change.
function buildPython() {
  const key = crypto.createHash("sha256").update(fs.readFileSync(REQUIREMENTS)).update(fs.readFileSync(LOCK))
    .digest("hex").slice(0, 12);
  const dir = path.join(CACHE, `python-${PY.version}-${key}`);
  const py = path.join(dir, "bin", "python3");
  if (fs.existsSync(path.join(dir, ".complete"))) return dir;
  fs.mkdirSync(CACHE, { recursive: true });
  const tarball = path.join(CACHE, PY.file);
  if (!fs.existsSync(tarball) || sha256(tarball) !== PY.sha256) {
    console.log("Downloading", PY.file);
    run("/usr/bin/curl", ["-fL", "--retry", "3", "-o", tarball, PY.url]);
  }
  if (sha256(tarball) !== PY.sha256) throw new Error("Python download does not match its pinned SHA-256; not using it.");
  fs.rmSync(dir, { recursive: true, force: true });
  const unpack = path.join(CACHE, "unpack");
  fs.rmSync(unpack, { recursive: true, force: true });
  fs.mkdirSync(unpack);
  run("/usr/bin/tar", ["-xzf", tarball, "-C", unpack]);          // the tarball holds one folder: python/
  fs.renameSync(path.join(unpack, "python"), dir);
  fs.rmSync(unpack, { recursive: true, force: true });
  const env = { PATH: "/usr/bin:/bin", PIP_DISABLE_PIP_VERSION_CHECK: "1", PYTHONNOUSERSITE: "1" };
  run(py, ["-I", "-m", "pip", "install", "--no-cache-dir", "--only-binary=:all:", "-r", REQUIREMENTS, "-c", LOCK], { env });
  // Trim what the app never uses (tests, IDLE/Tk, pip's own cache of wheels).
  for (const sub of ["lib/python3.9/test", "lib/python3.9/idlelib", "lib/python3.9/tkinter", "lib/python3.9/turtledemo"]) {
    fs.rmSync(path.join(dir, sub), { recursive: true, force: true });
  }
  run(py, ["-I", "-m", "compileall", "-q", "-j", "0", path.join(dir, "lib")], { env, stdio: ["ignore", "ignore", "inherit"] });
  fs.writeFileSync(path.join(dir, ".complete"), new Date().toISOString());
  return dir;
}

// The npm packages the Anthropic helper needs: @anthropic-ai/sdk and everything it depends on (not Electron).
function helperPackages() {
  const found = new Set();
  const visit = (name) => {
    if (found.has(name)) return;
    const pj = path.join(APP, "node_modules", name, "package.json");
    if (!fs.existsSync(pj)) return;                // optional dependency that is not installed
    found.add(name);
    const p = JSON.parse(fs.readFileSync(pj, "utf8"));
    for (const dep of Object.keys({ ...p.dependencies, ...p.optionalDependencies })) visit(dep);
  };
  visit("@anthropic-ai/sdk");
  return [...found];
}

// 2. The service, UI and FL scripts, staged in the project layout.
function stageCore(pythonDir) {
  const core = path.join(CACHE, "core");
  fs.rmSync(core, { recursive: true, force: true });
  // Leave out caches and, for npm packages, source maps, type declarations and TypeScript sources (not used at run time).
  const skip = (src) => !/(__pycache__|\.pyc$|\.DS_Store$|node_modules\/.*(\.map$|\.d\.[mc]?ts$|\/src$))/.test(src);
  const copy = (from, to) => fs.cpSync(path.join(ROOT, from), path.join(core, to || from), { recursive: true, filter: skip });
  copy("veloura");
  copy("fl_scripts");
  copy("app/ui");
  copy("app/ai");
  for (const name of helperPackages()) copy(path.join("app/node_modules", name));
  // Precompile with the bundled Python so the app never needs to write .pyc files inside itself.
  run(path.join(pythonDir, "bin", "python3"), ["-I", "-m", "compileall", "-q", path.join(core, "veloura")]);
  return core;
}

async function main() {
  const { packager } = await import("@electron/packager");
  const pythonDir = buildPython();
  const core = stageCore(pythonDir);
  // Customer builds carry no paths from the build Mac. Only a build made with VELOURA_LEGACY_ROOT set (the developer's own
  // migration from the old FLprod-folder data) records where to copy old data from on first launch.
  fs.writeFileSync(path.join(APP, "root.json"), JSON.stringify(process.env.VELOURA_LEGACY_ROOT ? { legacyRoot: process.env.VELOURA_LEGACY_ROOT } : {}));

  const sign = process.env.VELOURA_SIGN === "1";
  const opts = {
    dir: APP,
    name: "Veloura",
    platform: "darwin",
    arch: "arm64",
    out: path.join(CACHE, "dist"),     // built and sealed outside iCloud, then copied to ../dist below
    overwrite: true,
    appBundleId: BUNDLE_ID,
    appCategoryType: "public.app-category.music",
    icon: path.join(__dirname, "icon.icns"),   // flat icon: make-icon-flat.py writes veloura-icon.svg, make-icon.js renders it (not run here)
    // The Anthropic helper and its npm packages ship in core/, so app.asar needs only main.js, preload.js and root.json.
    ignore: [/^\/build/, /^\/ui/, /^\/ai/, /^\/node_modules/, /\.test\.js$/],
    prune: false,
    appCopyright: "© 2026 Valenti Labs. Beta software, provided as is.",
    extendInfo: {
      NSAppleEventsUsageDescription:
        "Veloura sends keystrokes to FL Studio (through System Events) to run its Piano Roll script and open windows.",
    },
    // Copy the bundled Python and the core with ditto, which keeps the Python folder's symlinks relative.
    afterCopy: [async ({ buildPath }) => {
      const resources = path.resolve(buildPath, "..");
      run("/usr/bin/ditto", [pythonDir, path.join(resources, "python")]);
      fs.rmSync(path.join(resources, "python", ".complete"), { force: true });
      // pip's console scripts (normalizer, numba, f2py...) hard-code this Mac's build path in their #! line and
      // the app never runs them: leave them out so the bundle holds no path from the build machine.
      const bin = path.join(resources, "python", "bin");
      for (const f of fs.readdirSync(bin)) {
        const file = path.join(bin, f);
        if (fs.lstatSync(file).isFile() && fs.readFileSync(file).includes(CACHE)) fs.rmSync(file);
      }
      run("/usr/bin/ditto", [core, path.join(resources, "core")]);
    }],
  };
  if (sign) {
    // Developer ID: hardened runtime, the app entitlements for Electron, and the Python ones
    // for the bundled interpreter and its native libraries (numba/llvmlite JIT needs unsigned executable memory).
    opts.osxSign = {
      identity: process.env.VELOURA_SIGN_IDENTITY || "Developer ID Application",
      // Sign code only: bundles and Mach-O binaries. Data files that merely look binary (e.g. scipy's .sav test data)
      // must not get a code signature.
      ignore: (file) => {
        if (/\.(app|framework)$/.test(file)) return false;
        try { return fs.statSync(file).isFile() && !require("./sign-adhoc").isMachO(file); } catch (_) { return false; }
      },
      optionsForFile: (file) => ({
        hardenedRuntime: true,
        entitlements: path.join(__dirname, file.includes("/Contents/Resources/python/")
          ? "entitlements.python.plist" : "entitlements.mac.plist"),
      }),
    };
    if (process.env.VELOURA_NOTARY_PROFILE) opts.osxNotarize = { keychainProfile: process.env.VELOURA_NOTARY_PROFILE };
  }
  try {
    // Apple's timestamp server occasionally doesn't answer for one file ("A timestamp was expected but was not
    // found"); that's transient, so a signed build tries again up to twice before giving up.
    let out;
    for (let attempt = 1; ; attempt++) {
      try { [out] = await packager(opts); break; }
      catch (e) {
        if (!sign || attempt >= 3 || !/timestamp/i.test(String(e && (e.stack || e.message || e)))) throw e;
        console.log("Signing hit a timestamp hiccup; trying again (" + (attempt + 1) + "/3)");
      }
    }
    const built = path.join(out, "Veloura.app");
    if (!sign) {
      // Without a certificate, sign everything ad hoc, inside-out, under Veloura's own identifier (sign-adhoc.js), then
      // check that a zipped, downloaded copy still verifies (otherwise macOS calls it "damaged"). macOS still ties
      // Accessibility to this exact build, so each new build has to be granted again.
      const { signApp, checkZip } = require("./sign-adhoc");
      signApp(built, BUNDLE_ID);
      checkZip(built);
    }
    if (sign) {
      // A signed release must pass as a real download: deep strict signature, Apple's notarization ticket stapled,
      // Gatekeeper "accepted ... Notarized Developer ID", also for a zipped, quarantined copy.
      run("/usr/bin/codesign", ["--verify", "--deep", "--strict", built]);
      if (process.env.VELOURA_NOTARY_PROFILE) run("/usr/bin/xcrun", ["stapler", "validate", built]);
      require("./sign-adhoc").checkZip(built, { notarized: !!process.env.VELOURA_NOTARY_PROFILE });
    }
    // One build copy only (no second copy in the project's dist/), and not registered with LaunchServices: the app
    // people open must always be /Applications/Veloura.app.
    require("./sign-adhoc").unregister(built);
    console.log("Built", built, sign ? "(signed)" : "(ad hoc signature)", "- install it with ditto to /Applications");
  } finally {
    fs.rmSync(path.join(APP, "root.json"), { force: true });
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
