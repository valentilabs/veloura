// Veloura desktop shell: starts the local Python service and shows the UI in a native window.
// The service is a child process; it exits when this app quits (its stdin closes), so nothing lingers.
const { app, BrowserWindow, dialog, ipcMain, net, shell } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const path = require("path");
const readline = require("readline");

// Development (`npm start`): the code and the data both live in the project folder and the service runs on its .venv.
// Packaged: Veloura.app is self-contained. The service, UI and FL scripts are in Contents/Resources/core, the Python
// that runs it is Contents/Resources/python, and everything Veloura writes goes to ~/Library/Application Support/Veloura.
const fs = require("fs");
const RESOURCES = process.resourcesPath;
const ROOT = app.isPackaged ? path.join(RESOURCES, "core") : path.resolve(__dirname, "..");
const HOME = app.isPackaged ? app.getPath("userData") : ROOT;
const VENV_PY = path.join(ROOT, ".venv", "bin", "python");
// The project venv has python-rtmidi (needed for the FL controller link); fall back to the system Python.
const PYTHON = process.env.VELOURA_PYTHON || (app.isPackaged ? path.join(RESOURCES, "python", "bin", "python3")
  : (fs.existsSync(VENV_PY) ? VENV_PY : "/usr/bin/python3"));

// One-time move for people upgrading from a build that kept its data in the project folder: copy data/ and the
// attempt log into Application Support the first time (the originals stay where they were). The FL command history in
// logs/archive and logs/sent is left behind: it is only for debugging and is hundreds of small files.
// Veloura was called Cadence until 2026-10-21. On the first launch after the rename, copy the old data folder
// (~/Library/Application Support/Cadence: settings, projects, library, logs, dev_mode, intro state) into Veloura's.
// It's a copy, so the old folder stays as a fallback.
function migrateFromCadence() {
  if (!app.isPackaged || fs.existsSync(path.join(HOME, "data"))) return;
  const old = path.join(app.getPath("appData"), "Cadence");
  if (!fs.existsSync(path.join(old, "data"))) return;
  for (const name of ["data", "logs", "dev_mode", "launch_state.json"]) {
    const from = path.join(old, name);
    if (!fs.existsSync(from)) continue;
    try {
      fs.cpSync(from, path.join(HOME, name), { recursive: true, filter: (src) => path.basename(src) !== "service.lock" });
    } catch (e) {
      process.stderr.write(`Veloura: could not copy ${from}: ${e.message}\n`);
    }
  }
}

function migrateUserData() {
  if (!app.isPackaged || fs.existsSync(path.join(HOME, "data"))) return;
  let legacy = null;
  try { legacy = require("./root.json").legacyRoot; } catch (_) {}
  if (!legacy) return;
  const copies = [["data", { recursive: true, filter: (src) => path.basename(src) !== "service.lock" }],
                  [path.join("logs", "attempts.jsonl"), {}]];
  for (const [name, opts] of copies) {
    const from = path.join(legacy, name);
    if (!fs.existsSync(from)) continue;
    try {
      fs.mkdirSync(path.dirname(path.join(HOME, name)), { recursive: true });
      fs.cpSync(from, path.join(HOME, name), opts);
    } catch (e) {
      process.stderr.write(`Veloura: could not copy ${from}: ${e.message}\n`);
    }
  }
}

function serviceEnv() {
  const env = { ...process.env, VELOURA_NODE: process.execPath };
  if (!app.isPackaged) return env;
  delete env.PYTHONPATH; delete env.PYTHONHOME; delete env.VIRTUAL_ENV;
  return {
    ...env,
    VELOURA_HOME: HOME,
    PYTHONNOUSERSITE: "1",
    PYTHONDONTWRITEBYTECODE: "1",                       // never write .pyc files inside Veloura.app
    NUMBA_CACHE_DIR: path.join(HOME, "numba-cache"), // librosa's numba cache, kept out of the app bundle too
  };
}
let service = null;
let win = null;
let intro = null;

function startService() {
  return new Promise((resolve, reject) => {
    const token = crypto.randomBytes(24).toString("base64url");
    // The token goes in the environment, not the arguments: other programs on the Mac can read a process's
    // arguments (ps), but only the same user can read its environment.
    service = spawn(PYTHON, ["-m", "veloura.service", "--port", "0"], {
      cwd: ROOT,
      env: { ...serviceEnv(), VELOURA_SERVICE_TOKEN: token },
      stdio: ["pipe", "pipe", "pipe"],
    });
    const timer = setTimeout(() => reject(new Error("The Veloura service did not start within 15 s.")), 15000);
    readline.createInterface({ input: service.stdout }).once("line", (line) => {
      clearTimeout(timer);
      try {
        const msg = JSON.parse(line);
        if (msg.error) reject(new Error(msg.error)); else resolve({ port: msg.port, token });
      } catch (e) { reject(e); }
    });
    service.stderr.on("data", (d) => process.stderr.write(d));
    service.on("exit", (code) => {
      clearTimeout(timer);
      if (win && !app.isQuitting) {
        dialog.showErrorBox("Veloura", `The Veloura service stopped (code ${code}). FL Studio is unaffected. Restart Veloura.`);
      }
      reject(new Error("service exited with code " + code));
    });
  });
}

function stopService() {
  if (!service) return;
  try { service.stdin.end(); } catch (_) {}
  const s = service;
  setTimeout(() => { try { s.kill(); } catch (_) {} }, 1500);
  service = null;
}

async function createWindow() {
  let svc;
  try {
    migrateFromCadence();
    migrateUserData();
    svc = await startService();
  } catch (e) {
    dialog.showErrorBox("Veloura could not start", String(e.message || e));
    app.quit();
    return;
  }
  const origin = `http://127.0.0.1:${svc.port}`;
  win = new BrowserWindow({
    width: 1320, height: 860, minWidth: 900, minHeight: 600,
    title: "Veloura Beta", backgroundColor: "#15161a",
    titleBarStyle: "hiddenInset", trafficLightPosition: { x: 14, y: 14 },
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true, nodeIntegration: false,
                      autoplayPolicy: "no-user-gesture-required" },   // the opening sound plays without a click
  });
  win.webContents.on("will-navigate", (e, url) => { if (!url.startsWith(origin)) e.preventDefault(); });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) shell.openExternal(url);
    return { action: "deny" };
  });
  // Opening animation only after a Mac restart, a Veloura update, or 8+ hours away (see intro-policy.js).
  intro = require("./intro-policy").start(path.join(app.getPath("userData"), "launch_state.json"), app.getVersion());
  await win.loadURL(`${origin}/#token=${svc.token}${intro.play ? "&intro=1" : ""}`);
  // Beta update notice (update-check.js): a few seconds after opening, so it never slows startup.
  if (app.isPackaged) setTimeout(() => require("./update-check").check({
    current: app.getVersion(),
    stateFile: path.join(app.getPath("userData"), "update_state.json"),
    fetchJson: async (url) => { const r = await net.fetch(url, { cache: "no-store" }); if (!r.ok) throw new Error(String(r.status)); return r.json(); },
    ask: async (m) => win && (await dialog.showMessageBox(win, {
      type: "info", buttons: ["Download", "Later"], defaultId: 0, cancelId: 1,
      message: `${app.getName()} ${m.version} is ready`,
      detail: (m.headline ? m.headline + "\n\n" : "") + "Download it and drag it into Applications. Your chats, settings and sign-in are kept.",
    })).response === 0,
    open: (url) => shell.openExternal(url),
  }).catch(() => {}), 8000);
}

ipcMain.handle("choose-folder", async () => {
  const r = await dialog.showOpenDialog(win, {
    title: "Export MIDI to…", properties: ["openDirectory", "createDirectory"],
    defaultPath: path.join(app.getPath("music"), "Veloura Exports"),
  });
  return r.canceled ? null : r.filePaths[0];
});

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(createWindow);
  app.on("before-quit", () => { app.isQuitting = true; if (intro) intro.stop(); stopService(); });
  app.on("window-all-closed", () => app.quit());
}
