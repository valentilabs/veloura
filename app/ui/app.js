// Veloura UI. Talks only to the local Veloura service (same origin). All text goes in through textContent.
"use strict";

// ---------- basics ----------
const token = (() => {
  const m = location.hash.match(/token=([^&]+)/);
  if (m) {
    try { sessionStorage.setItem("velouraToken", m[1]); } catch (_) {}
    history.replaceState(null, "", location.pathname);
    return m[1];
  }
  try { return sessionStorage.getItem("velouraToken") || ""; } catch (_) { return ""; }
})();

const $ = (id) => document.getElementById(id);
const NOTE = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
const GENRES = ["trap", "dark trap", "plugg", "melodic plugg", "rage", "jerk", "drill", "melodic rap", "melodic trap", "detroit", "ambient", "cloud rap", "boom bap", "r&b", "pop", "other"];
const noteName = (n) => NOTE[n % 12] + (Math.floor(n / 12) - 1);

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.setAttribute("style", v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const svg = (paths) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  if (typeof paths === "string") { s.innerHTML = paths; return s; }   // trusted, hard-coded markup only
  for (const d of paths) { const p = document.createElementNS(s.namespaceURI, "path"); p.setAttribute("d", d); s.append(p); }
  return s;
};
const ICONS = {
  melody: ["M9 18V6l10-2v12", "M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3z", "M19 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z"],
  drums: ["M4 9h16v6a8 3 0 0 1-16 0z", "M4 9a8 3 0 0 0 16 0 8 3 0 0 0-16 0z", "M7 3l3 5M17 3l-3 5"],
  bass: ["M3 12c3-6 5 6 8 0s5 6 8 0", "M3 18c3-6 5 6 8 0s5 6 8 0"],
  chords: ["M5 4v16M10 4v16M15 4v16M20 4v16"],
  other: ["M12 3v18M3 12h18"],
  guide: ["M4 4h16v16H4z", "M8 9h8M8 13h8M8 17h5"],
  arrow: ["M5 12h14M13 6l6 6-6 6"],
};
const ROLE_COLOR = { melody: "var(--melody)", drums: "var(--drum)", bass: "var(--bass)", chords: "var(--melody)", other: "var(--melody)" };

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Veloura-Token": token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: "Bad response from Veloura" }));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function toast(text, kind) {
  const t = h("div", { class: "toast " + (kind || "") }, text);
  $("toasts").append(t);
  setTimeout(() => t.remove(), kind === "err" ? 7000 : 3800);
}

let session = null, status = null, setup = null, pending = 0, page = "studio", genreInfo = {}, prep = null;
const todoState = {};
const store = { get: (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} } };
const KEYS = NOTE.flatMap((n) => [n + " minor", n + " major"]);
const MI = { // menu icons
  sample: ["M9 18V6l10-2v12", "M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3z", "M19 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z"],
  song: ["M3 12h2l2-6 4 12 3-9 2 3h5"], genre: ["M4 6h16M4 12h10M4 18h7"], prep: ["M9 12l2 2 4-4", "M5 4h14v16H5z"],
  check: ["M3 12h3l3-8 4 16 3-8h5"], tempo: ["M12 3l7 18H5z", "M12 9l3 6"], roll: ["M4 5h16v14H4z", "M8 9h3M13 13h4M7 16h3"],
  setup: ["M12 3l8 4v5c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V7z"], clock: ["M12 7v5l3 2", "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z"],
  key: ["M15 7a4 4 0 1 1-4 4L4 18v2h3l7-7"], bars: ["M4 20V10M10 20V4M16 20v-6M22 20V8"], rack: ["M4 5h16v4H4zM4 11h16v4H4zM4 17h16v2H4z"],
  chev: ["M6 9l6 6 6-6"],
};

// ---------- themes (Settings ▸ Theme; saved with the other settings so it survives restarts and updates) ----------
// The colours live in styles.css under html[data-skin=…]; these are the names and the swatch for the picker.
const THEMES = [
  { id: "champagne", name: "Electric Champagne", note: "Default · matches the website", sw: ["#FFE7AE", "#FFCC6A", "#F7BD4F"], bg: "#0E0F14" },
  { id: "rose-gold", name: "Rose Gold", note: "Warm blush metal", sw: ["#FBD5C6", "#F2AE96", "#E59A80"], bg: "#0E0B0C" },
  { id: "platinum", name: "Platinum", note: "Quiet and silver", sw: ["#FAF8F4", "#E2DED6", "#CBC6BC"], bg: "#0A0A0C" },
  { id: "lilac", name: "Lilac", note: "Soft violet", sw: ["#E4D9FF", "#C9B3FF", "#B49AF7"], bg: "#0B0A10" },
  { id: "amber-noir", name: "Amber Noir", note: "Deep orange glow", sw: ["#FFCB91", "#FFA94D", "#F28F2C"], bg: "#0C0A08" },
];
function applyTheme(id) {
  const t = THEMES.find((x) => x.id === id) || THEMES[0];
  document.documentElement.dataset.skin = t.id;
}

// ---------- navigation ----------
function showPage(name) {
  page = name;
  for (const b of document.querySelectorAll(".nav")) b.classList.toggle("active", b.dataset.page === name);
  for (const s of document.querySelectorAll(".page")) s.classList.toggle("active", s.id === "page-" + name);
  if (name === "setup") { renderSetup(); refreshSetup(); }   // show the last-known state at once, then fill in
  closePops();
  forceRender();
}
for (const b of document.querySelectorAll(".nav")) b.addEventListener("click", () => showPage(b.dataset.page));
$("connBtn").addEventListener("click", () => showPage("setup"));

// ---------- data ----------
async function refreshSession() { try { session = await api("/api/session"); renderModelLabel(); render(); } catch (_) {} }
async function refreshStatus() {
  try { status = await api("/api/status"); renderStatus(); render(); }
  catch (_) { $("connText").textContent = "Offline"; $("connDot").className = "dot bad"; }
}
async function refreshSetup() { try { setup = await api("/api/setup"); status = setup.status; renderSetup(); renderStatus(); } catch (_) {} }
async function refreshPrep() { try { prep = await api("/api/prep", {}); renderPrepBanner(); } catch (_) {} }

let busyLabel = null, cancelRequested = false, addAllRunning = false;
async function withPending(fn, label) {
  if (!addAllRunning) cancelRequested = false;
  pending++; setBusy(label); render();
  const poll = setInterval(refreshSession, 800);
  try {
    const r = await fn();
    // FL actions answer with ok + status/checks: show whether the change really landed in FL
    if (r && typeof r.ok === "boolean" && ("status" in r || "checks" in r || "tempo" in r) && typeof landed === "function")
      landed(r.ok, r.ok ? "Landed in FL" : shortReason(r.message));
    return r;
  }
  catch (e) { toast(e.message, "err"); if (typeof landed === "function" && /FL/.test(e.message)) landed(false, shortReason(e.message)); }
  finally { clearInterval(poll); pending--; setBusy(null); await refreshSession(); refreshStatus(); }
}
function setBusy(label) {
  if (label !== undefined && label !== null) busyLabel = label;
  if (!pending) busyLabel = null;
  const busy = (session && session.busy) || busyLabel || (addAllRunning ? "Adding parts to FL…" : null);
  $("busy").hidden = !busy;
  if (!cancelRequested) $("busyText").textContent = busy || "";
  $("cancelBtn").hidden = !(pending > 0 || addAllRunning);
  $("cancelBtn").disabled = cancelRequested;
  $("send").disabled = pending > 0;
}
async function cancelWork() {
  cancelRequested = true; $("cancelBtn").disabled = true; $("busyText").textContent = "Cancelling…";
  try { await api("/api/cancel", {}); } catch (_) {}
}
$("cancelBtn").addEventListener("click", cancelWork);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("pop").hidden || !$("plusMenu").hidden) { closePops(); return; }
  if ($("modal").open) return;
  if (pending > 0 || addAllRunning) { e.preventDefault(); cancelWork(); }
});

// ---------- status ----------
const scriptsOk = (st) => st.bridge_script === "installed and up to date" && st.bridge_folder && st.controller_script === "installed and up to date";
const providerName = (p) => ({ chatgpt: "ChatGPT", offline: "Offline composer", gemini: "Gemini", "claude-code": "Claude", anthropic: "Claude API" }[p] || p || "");
function renderStatus() {
  if (!status) return;
  let cls = "ok", text = "Ready";
  if (!status.fl_running) { cls = "bad"; text = "FL closed"; }
  else if (!status.accessibility || !scriptsOk(status)) { cls = "warn"; text = "Setup"; }
  else if (!status.armed) { cls = "warn"; text = "Bridge"; }
  else if (!(status.controller || {}).connected) { cls = "warn"; text = "No drums"; }
  $("connDot").className = "dot " + cls; $("connText").textContent = text;
  $("setupBadge").hidden = !(!status.fl_running || !status.accessibility || !scriptsOk(status) || !(status.controller || {}).connected);
  $("armBanner").hidden = !(status.fl_running && status.accessibility && !status.armed);
  renderConnBanner();
  for (const c of document.querySelectorAll("[data-proj]")) { c.textContent = status.project || ""; c.hidden = !status.project; }
  renderModelLabel();
  const fl = flState(status);
  for (const p of document.querySelectorAll("[data-flpill]")) {
    p.className = "fl-pill " + fl.cls; p.title = fl.tip;
    p.replaceChildren(h("i", { class: "dot " + fl.cls }), "FL Studio · " + fl.text);
  }
}
// The one FL status the top bar shows on every page. Click it for Setup.
function flState(st) {
  const ctl = st.controller || {};
  if (!st.fl_running) return { cls: "bad", text: "closed", tip: "Open Veloura first, then FL Studio" };
  if (!st.accessibility || !scriptsOk(st)) return { cls: "warn", text: "finish setup", tip: "A setup step is missing. Click for Setup." };
  if (!ctl.connected) return { cls: "warn", text: "not linked", tip: "The FL controller isn't connected (Setup step 3)" };
  if (!st.armed) return { cls: "warn", text: "link the bridge", tip: "Open a Piano Roll ▸ Tools ▸ Scripts ▸ veloura_bridge" };
  return { cls: "ok", text: "connected", tip: `Pattern ${(ctl.pattern || {}).number || "?"} · ${ctl.tempo} BPM` };
}
for (const p of document.querySelectorAll("[data-flpill]")) p.addEventListener("click", () => showPage("setup"));
for (const c of document.querySelectorAll("[data-proj]")) if (c.id !== "projectChip") c.addEventListener("click", () => openProjects());
// The model button next to Send: with a Claude provider it shows the model and opens a menu to switch it (the same
// saved setting as the Settings picker); with any other provider it shows the provider and opens Settings.
const CLAUDE_PROVIDERS = ["anthropic", "claude-code"];
const claudeModels = () => ((session && session.app) || {}).claude_models || [];
function renderModelLabel() {
  const b = $("modelLabel"), prov = (session && session.settings.provider) || (status && status.provider);
  const m = claudeModels().find((x) => x.id === (session && session.settings.model));
  const claude = CLAUDE_PROVIDERS.includes(prov) && m;
  b.classList.toggle("has-menu", !!claude);
  // OpenAI's Sign in with ChatGPT guidelines: show "Using ChatGPT plan" next to the composer when beats run on the plan.
  b.replaceChildren(...(claude ? [m.label.replace(/^Claude /, ""), svg(["M6 9l6 6 6-6"])] : [prov === "chatgpt" ? "Using ChatGPT plan" : providerName(prov)]));
}
$("modelLabel").addEventListener("click", (e) => {
  if (!e.currentTarget.classList.contains("has-menu")) { showPage("settings"); return; }
  const m = $("plusMenu");
  if (!m.hidden && m.dataset.kind === "model") { closePops(); return; }
  const pick = async (id) => {
    await api("/api/settings", { model: id });
    await refreshSession();
    renderModelLabel();
  };
  m.dataset.kind = "model";
  m.replaceChildren(...claudeModels().map((x) => h("button", { type: "button", class: x.id === session.settings.model ? "on" : "",
    onclick: () => { closePops(); pick(x.id); } },
    h("span", {}, x.label, h("small", {}, x.cost)),
    x.id === session.settings.model ? svg(["M5 12l5 5 9-10"]) : null)),
    h("hr"),
    h("div", { class: "menu-note" }, session.settings.provider === "anthropic"
      ? "Rough estimates. You pay Anthropic directly for your key." : "Uses your Claude plan."));
  const r = e.currentTarget.getBoundingClientRect();
  m.hidden = false;
  m.style.left = Math.max(12, Math.min(r.right - m.offsetWidth, innerWidth - m.offsetWidth - 12)) + "px";
  m.style.top = (r.top - m.offsetHeight - 10 > 10 ? r.top - m.offsetHeight - 10 : r.bottom + 10) + "px";
});
$("armOpen").addEventListener("click", async () => {
  const r = await withPending(() => api("/api/open-piano-roll", {}), "Opening a Piano Roll…");
  if (r) toast(r.message, r.ok ? "ok" : "err");
});
$("armCheck").addEventListener("click", async () => {
  const r = await withPending(() => api("/api/test-bridge", {}), "Checking the Piano Roll link…");
  if (r) toast(r.ok ? "Piano Roll link is awake ✓" : r.message, r.ok ? "ok" : "err");
});

// ---------- bridge picture (FL's Piano Roll ▸ Tools ▸ Scripts menu) ----------
function bridgeMock(small) {
  const wrench = h("span", { class: "fm-tool" }, svg('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>'));
  return h("div", { class: "flmock" + (small ? " small" : "") },
    h("div", { class: "fm-bar" }, h("span", { class: "fm-step" }, "1"), h("span", { class: "fm-title" }, "Piano roll"), wrench, h("span", { class: "fm-hint" }, "← Tools")),
    h("div", { class: "fm-menu" },
      h("div", { class: "fm-col" }, ["Quick legato", "Quick chop", "Quantize", "Arpeggiate"].map((t) => h("div", { class: "fm-i dim" }, t)),
        h("div", { class: "fm-i sel" }, h("span", { class: "fm-step" }, "2"), "Scripts ▸")),
      h("div", { class: "fm-col" }, h("div", { class: "fm-i dim" }, "Run last script again", h("kbd", {}, "⌘⌥Y")),
        h("div", { class: "fm-i dim" }, "Arpeggiator"), h("div", { class: "fm-i hl" }, h("span", { class: "fm-step" }, "3"), "veloura_bridge"),
        h("div", { class: "fm-i dim" }, "Chord progression"))));
}
$("armMock").replaceChildren(bridgeMock(true));

// ---------- Veloura Channel Rack: a small mirror of FL's current pattern, click a step to change it in FL ----------
// Hidden until the first prompt in a project; after that it shows unless the user hides it (rackOpen).
let rack = null, rackPats = null, rackBars = {}, rackOpen = true, rackHold = 0, paint = null;
let rackQueue = Promise.resolve();
const rackWanted = () => rackOpen && !!(session && session.messages.length);
function setRackOpen(v) {
  rackOpen = v;
  if (session && session.settings.rack_open !== v) api("/api/settings", { rack_open: v }).catch(() => {});
  if (session) session.settings.rack_open = v;
  applyRackVisibility();
  if (v) refreshRack();
}
function applyRackVisibility() {
  const on = rackWanted();
  $("page-studio").classList.toggle("norack", !on);
  $("rackToggle").classList.toggle("on", on);
}
$("rackToggle").addEventListener("click", () => setRackOpen(!rackWanted()));
$("rackClose").addEventListener("click", () => setRackOpen(false));
async function refreshRack() {
  // pending: Veloura is in the middle of an FL action; reading every pattern now would queue behind it on the
  // same MIDI link and slow it down
  if (page !== "studio" || !rackWanted() || rackHold || paint || pending || document.hidden || !$("pop").hidden) return;
  try {
    const r = await api("/api/rack", { all: true });
    if (rackHold || paint) return;
    rack = r;
    if (r.patterns) rackPats = r.patterns;          // FL playing: keep the last full read, refresh the current pattern only
    else if (rackPats && r.pattern) rackPats = rackPats.map((p) => p.number === r.pattern.number ? { ...p, steps: r.channels.map((c) => c.steps) } : p);
    if (changed("rack", [rack, rackPats, rackBars])) renderRack();
  } catch (_) {}
}
const flColor = (c) => "#" + ((c || 0x5f6a73) & 0xffffff).toString(16).padStart(6, "0");
function rackClick(ch, pat, step, on, el) {
  el.classList.toggle("on", on);
  const list = pat.steps[ch.index] || (pat.steps[ch.index] = []);
  const set = new Set(list); on ? set.add(step) : set.delete(step); pat.steps[ch.index] = [...set].sort((x, y) => x - y);
  rackHold++;
  rackQueue = rackQueue.then(() => api("/api/rack/toggle", { index: ch.index, name: ch.name, step, on, pattern: pat.number }))
    .catch((e) => { toast("FL didn't take that step: " + e.message, "err"); el.classList.toggle("on", !on); })
    .finally(() => { rackHold--; });
}
window.addEventListener("pointerup", () => { if (paint) { paint = null; } });
const isPluginCh = (ch) => ch.type === "plugin" || ch.type === "hybrid";
async function rackMute(ch) {
  rackHold++;
  try { const r = await api("/api/rack/mute", { index: ch.index, name: ch.name, muted: !ch.muted }); ch.muted = r.muted; renderRack(); }
  catch (e) { toast(e.message, "err"); } finally { rackHold--; }
}
// A colour for an instrument row: the part Veloura wrote on it, else FL's channel colour.
function chanTint(ch) {
  const e = Object.values((session && session.parts) || {}).find((p) => p.channel_name === ch.name);
  return e ? (ROLE_COLOR[e.role] || ROLE_COLOR.other) : flColor(ch.color);
}
function renderRack() {
  const body = $("rackBody");
  applyRackVisibility();
  if (!rack || !rack.connected) {
    $("rackPat").textContent = ""; $("rackPat").hidden = true; $("rackBars").textContent = "";
    body.replaceChildren(h("div", { class: "rp-empty" }, unpluggedScene(96), h("b", {}, "Not connected"),
      h("span", {}, "Connect the FL controller to see your Channel Rack here."),
      h("button", { class: "link-quiet", type: "button", onclick: () => showPage("setup") }, "Open Setup")));
    $("rackFoot").replaceChildren(); return;
  }
  const cur = rack.pattern ? rack.pattern.number : 1;
  const pats = (rackPats && rackPats.length) ? rackPats : [{ ...rack.pattern, length: rack.length, steps: rack.channels.map((c) => c.steps) }];
  const pat = pats.find((p) => p.number === cur) || pats[0];
  const bars = Math.max(1, Math.ceil((pat.length || 16) / 16));
  const bar = Math.min(rackBars[pat.number] || 0, bars - 1);
  $("rackPat").hidden = false;
  $("rackPat").textContent = pat.name || "Pattern " + pat.number;
  $("rackBars").replaceChildren(...(bars > 1 ? Array.from({ length: bars }, (_, b) => h("button", { class: "rp-bar" + (b === bar ? " sel" : ""), type: "button",
    title: `Bar ${b + 1}`, onclick: () => { rackBars[pat.number] = b; renderRack(); } }, String(b + 1))) : [`${pat.length || 16} steps`]));
  const steps = rack.channels.filter((ch) => !isPluginCh(ch)), inst = rack.channels.filter(isPluginCh);
  const rows = steps.map((ch) => {
    const set = new Set(pat.steps[ch.index] || []);
    const cells = Array.from({ length: 16 }, (_, i) => {
      const st = bar * 16 + i;
      const el = h("button", { class: "st" + (Math.floor(i / 4) % 2 ? " alt" : "") + (set.has(st) ? " on" : ""), type: "button", "aria-label": `${ch.name} step ${st + 1}` });
      el.addEventListener("pointerdown", (e) => { e.preventDefault(); paint = { key: pat.number + ":" + ch.index, on: !el.classList.contains("on") }; rackClick(ch, pat, st, paint.on, el); });
      el.addEventListener("pointerenter", () => { if (paint && paint.key === pat.number + ":" + ch.index && el.classList.contains("on") !== paint.on) rackClick(ch, pat, st, paint.on, el); });
      return el;
    });
    return h("div", { class: "rp-row" + (ch.muted ? " muted" : "") },
      h("button", { class: "rp-name", type: "button", title: ch.muted ? `${ch.name} (muted) · click to unmute` : `${ch.name} · click to mute`, onclick: () => rackMute(ch) }, ch.name),
      h("div", { class: "rp-steps" }, cells));
  });
  body.replaceChildren(h("div", { class: "rp-grid" }, rows.length ? rows : h("span", { class: "rp-none" }, "No drum channels yet")),
    inst.length ? h("div", { class: "rp-sep" }) : null,
    inst.length ? h("div", { class: "rp-inst" }, inst.map((ch) => h("button", { class: "rp-irow" + (ch.muted ? " muted" : ""), type: "button", title: "Choose a sound for " + ch.name,
      onclick: (e) => openSounds(e.currentTarget, ch) },
      h("i", { style: `background:${chanTint(ch)}` }), h("span", {}, ch.name), h("small", {}, ch.muted ? "Muted" : "Ready")))) : null);
  $("rackFoot").replaceChildren();
}
$("rackPat").addEventListener("click", (e) => {
  const pats = rackPats || [];
  if (pats.length < 2) return;
  const cur = rack && rack.pattern ? rack.pattern.number : 1;
  openPop(e.currentTarget, [h("h3", {}, "Patterns"), h("div", { class: "opt-list" }, pats.map((p) => h("button", { class: "opt" + (p.number === cur ? " sel" : ""), type: "button",
    onclick: async () => { closePops(); if (p.number === cur) return; try { await api("/api/rack/pattern", { number: p.number }); rackHold = 0; refreshRack(); } catch (err) { toast(err.message, "err"); } } },
    p.name || "Pattern " + p.number, p.steps.some((x) => x && x.length) ? h("span", { class: "k" }, "has steps") : null)))], 240);
});
async function openSounds(anchor, ch) {
  openPop(anchor, [h("h3", {}, ch.name), h("p", { class: "pop-sub" }, "Loading sounds…")], 320);
  let info;
  try { info = await api("/api/sounds", { index: ch.index, name: ch.name }); } catch (e) { openPop(anchor, [h("h3", {}, ch.name), h("p", { class: "pop-sub" }, e.message)], 320); return; }
  if (!info.names || info.count <= 1) {
    openPop(anchor, [h("h3", {}, ch.name), h("p", { class: "pop-sub" }, `${info.plugin || "This plugin"} doesn't list its sounds to FL, so pick them inside the plugin.`)], 320); return;
  }
  const list = h("div", { class: "sound-list" });
  const fill = (q) => list.replaceChildren(...info.names.filter((n) => n && n.toLowerCase().includes(q)).slice(0, 400).map((n) =>
    h("button", { class: "sound" + (n === info.current ? " sel" : ""), onclick: async () => {
      closePops();
      const r = await withPending(() => api("/api/sounds/switch", { index: ch.index, name: ch.name, sound: n }), `Loading ${n}…`);
      if (r) toast(r.ok ? `${ch.name}: ${n}` : r.message, r.ok ? "ok" : "err");
    } }, n)));
  const search = h("input", { placeholder: `Search ${info.count} sounds`, oninput: (e) => fill(e.target.value.toLowerCase()) });
  openPop(anchor, [h("h3", {}, info.plugin || ch.name), h("p", { class: "pop-sub" }, "Now: " + (info.current || "?")), search, list], 320);
  fill(""); search.focus();
}

// ---------- popovers & + menu ----------
function closePops() { $("pop").hidden = true; $("plusMenu").hidden = true; $("plusBtn").classList.remove("open"); }
function openPop(anchor, children, width) {
  const pop = $("pop");
  pop.replaceChildren(...children);
  pop.style.width = (width || 340) + "px";
  pop.hidden = false;
  const r = anchor.getBoundingClientRect(), ph = pop.offsetHeight;
  pop.style.left = Math.max(12, Math.min(r.left, innerWidth - (width || 340) - 12)) + "px";
  pop.style.top = (r.top - ph - 10 > 10 ? r.top - ph - 10 : r.bottom + 10) + "px";
}
document.addEventListener("mousedown", (e) => {
  if (!$("pop").hidden && !$("pop").contains(e.target) && !e.target.closest(".pillbtn")) $("pop").hidden = true;
  if (!$("plusMenu").hidden && !$("plusMenu").contains(e.target) && !e.target.closest("#plusBtn, #modelLabel")) { $("plusMenu").hidden = true; $("plusBtn").classList.remove("open"); }
});

const item = (icon, label, sub, fn, badge) => h("button", { type: "button", onclick: () => { closePops(); fn(); } },
  svg(MI[icon]), h("span", {}, label, sub ? h("small", {}, sub) : null), badge ? h("span", { class: "badge-n" }, badge) : null);
$("plusBtn").addEventListener("click", (e) => {
  const m = $("plusMenu");
  if (!m.hidden && m.dataset.kind !== "model") { closePops(); return; }
  m.dataset.kind = "plus";
  const ctl = (status && status.controller) || {};
  m.replaceChildren(
    item("sample", "Add a sample", "Build a beat around a loop", () => pickFile("sample")),
    item("song", "Add an inspiration song", "Make something that feels like it", () => pickFile("inspiration")),
    item("genre", "Make a genre beat", "Trap, plugg, rage, jerk, drill…", () => openGenre($("plusBtn"), true)),
    h("hr"),
    item("clock", "Tempo", `${session.settings.tempo_bpm} BPM`, () => openTempo($("plusBtn"))),
    item("key", "Key", session.settings.key_auto ? "Auto" : session.settings.key, () => openKey($("plusBtn"))),
    item("roll", "Loop length", session.settings.bars_auto ? "Auto" : session.settings.bars + " bars", () => openBars($("plusBtn"))),
    item("bars", "Feel", "Simple or complex, sparse or full…", () => openFeel($("plusBtn"))),
    h("hr"),
    item("prep", "Sound prep checklist", "Loop points off · Cut itself on 808s", () => openPrep($("plusBtn")), prep && prep.pending ? String(prep.pending) : null),
    item("check", "Check for sound after stop", "Finds channels that keep ringing", soundCheck),
    item("tempo", `Set FL to ${session.settings.tempo_bpm} BPM`, ctl.connected ? null : "Needs the FL controller", setFLTempo),
    item("roll", "Check the Piano Roll link", null, async () => { const r = await withPending(() => api("/api/test-bridge", {}), "Checking…"); if (r) toast(r.ok ? r.message : r.message, r.ok ? "ok" : "err"); }),
    item("setup", "Setup", null, () => showPage("setup")));
  const r = e.currentTarget.getBoundingClientRect();
  m.hidden = false;
  m.style.left = Math.max(12, r.left - 6) + "px";
  m.style.top = (r.top - m.offsetHeight - 10 > 10 ? r.top - m.offsetHeight - 10 : r.bottom + 10) + "px";
  $("plusBtn").classList.add("open");
});

async function setFLTempo() {
  const r = await withPending(() => api("/api/fl-tempo", { bpm: session.settings.tempo_bpm }), "Setting FL tempo…");
  if (r) toast(r.ok ? `FL is now at ${r.tempo} BPM ✓` : `FL reports ${r.tempo} BPM`, r.ok ? "ok" : "err");
}
async function soundCheck() {
  const go = await askSimple("Check for sound after stop", "Press play in FL for a few seconds, then press stop, then click Check right away. Veloura listens to every mixer track for 4 seconds.", "Check");
  if (!go) return;
  const r = await withPending(() => api("/api/sound-check", {}), "Listening to FL's mixer…");
  if (!r) return;
  if (!r.ok) { toast(r.message, "err"); return; }
  const hint = r.tracks && r.tracks.length ? " Usually a sample with loop points on, or an 808 without Cut itself. See Sound prep in the + menu." : "";
  await askSimple(r.tracks && r.tracks.length ? "Found sound after stop" : "All quiet ✓", r.message + hint, "OK", true);
}
function askSimple(title, text, okLabel, okOnly) {
  return new Promise((resolve) => {
    const dlg = $("modal"), done = (v) => { dlg.onclose = null; dlg.close(); resolve(v); };
    $("modalBody").replaceChildren(h("h3", {}, title), h("p", {}, text), h("div", { class: "row-btns end" },
      okOnly ? null : h("button", { class: "btn", onclick: () => done(false) }, "Cancel"),
      h("button", { class: "btn primary", onclick: () => done(true) }, okLabel)));
    dlg.onclose = () => resolve(false);
    dlg.showModal();
  });
}

// ---------- attachments (sample / inspiration) ----------
let attached = store.get("attached", null);   // reference id attached to the next message
let genreChip = false;                        // "make a genre beat" mode for the next message
let pendingKind = "sample";
function pickFile(kind) { pendingKind = kind; $("fileInput").click(); }
$("fileInput").addEventListener("change", (e) => { if (e.target.files[0]) uploadRef(e.target.files[0], pendingKind); e.target.value = ""; });
const comp = $("composer");
comp.addEventListener("dragover", (e) => { e.preventDefault(); comp.classList.add("over"); });
comp.addEventListener("dragleave", () => comp.classList.remove("over"));
comp.addEventListener("drop", async (e) => {
  e.preventDefault(); comp.classList.remove("over");
  const f = e.dataTransfer.files[0];
  if (!f) return;
  const kind = await new Promise((resolve) => {
    const dlg = $("modal"), done = (v) => { dlg.onclose = null; dlg.close(); resolve(v); };
    $("modalBody").replaceChildren(h("h3", {}, "How should Veloura use this?"), h("p", {}, f.name),
      h("div", { class: "row-btns end" }, h("button", { class: "btn", onclick: () => done(null) }, "Cancel"),
        h("button", { class: "btn", onclick: () => done("inspiration") }, "Inspiration (sound like it)"),
        h("button", { class: "btn primary", onclick: () => done("sample") }, "Sample (build around it)")));
    dlg.onclose = () => resolve(null);
    dlg.showModal();
  });
  if (kind) uploadRef(f, kind);
});
async function uploadRef(file, kind) {
  const r = await withPending(async () => {
    const res = await fetch(`/api/reference?mode=${kind}&name=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { "X-Veloura-Token": token, "Content-Type": "application/octet-stream" }, body: file });
    const data = await res.json().catch(() => ({ error: "Upload failed" }));
    if (!res.ok) throw new Error(data.error || "Upload failed");
    return data;
  }, `Listening to ${file.name}…`);
  if (r && r.id) { attached = r.id; store.set("attached", attached); genreChip = false; await refreshSession(); forceRender(); $("input").focus(); }
}
function currentRef() { return attached && session.references && session.references[attached] ? session.references[attached] : null; }
function renderAttachment() {
  const ref = currentRef(), el = $("attach");
  el.hidden = !ref;
  if (!ref) { el.replaceChildren(); return; }
  const a = ref.analysis, ext = (ref.name.split(".").pop() || "").toUpperCase();
  el.replaceChildren(h("div", { class: "attach-tile", title: ref.summary },
    h("div", { class: "kind" }, `${ext} · ${ref.mode === "sample" ? "Sample" : "Inspiration"}`),
    h("b", {}, ref.name.replace(/\.[^.]+$/, "")),
    h("div", { class: "facts-line" }, `${a.tempo_bpm} BPM · ${a.key}` + (a.chords_per_bar.length ? ` · ${a.chords_per_bar.slice(0, 2).join(" ")}` : "")),
    ref.mode === "sample" ? h("div", { class: "facts-line" }, h("a", { href: "#", style: "color:var(--accent)", onclick: (e) => { e.preventDefault(); api("/api/reference/reveal", { id: ref.id }); } }, "Show in Finder")) : null,
    h("button", { class: "x", type: "button", title: "Remove", onclick: () => { attached = null; store.set("attached", null); forceRender(); } }, "×")));
}
function renderModeChip() {
  const ref = currentRef(), el = $("modeChip");
  if (ref) { el.replaceChildren(h("span", { class: "mode-chip" }, svg(MI[ref.mode === "sample" ? "sample" : "song"]), ref.mode === "sample" ? "Build around sample" : "Inspired by song")); return; }
  if (genreChip) {
    const g = genreInfo[session.settings.genre] || {};
    el.replaceChildren(h("span", { class: "mode-chip" }, svg(MI.genre), `${g.label || session.settings.genre} beat`,
      h("button", { type: "button", title: "Remove", onclick: () => { genreChip = false; forceRender(); } }, "×")));
    return;
  }
  el.replaceChildren();
}

// ---------- pills under the composer ----------
// Tempo, key, bars, genre and sounds live inside the prompt box as small tokens (the + menu has them too).
function pill(label, value, onclick, title) {
  return h("button", { class: "token", type: "button", title, onclick }, h("span", {}, label), h("b", {}, value));
}
function renderPills() {
  const s = session.settings, g = genreInfo[s.genre] || {}, ctl = (status && status.controller) || {};
  $("pills").replaceChildren(
    pill("BPM", String(s.tempo_bpm), (e) => openTempo(e.currentTarget), "Tempo"),
    pill("Key", s.key_auto ? "Auto" : s.key, (e) => openKey(e.currentTarget), s.key_auto && g.key ? `Auto: ${g.key} suits ${g.label}` : "Key"),
    pill("Bars", s.bars_auto ? (g.bars ? String(g.bars) : "Auto") : String(s.bars), (e) => openBars(e.currentTarget), s.bars_auto ? "Auto length" : "Loop length"),
    pill("Genre", g.label || s.genre, (e) => openGenre(e.currentTarget, false), "Genre"),
    pill("Sounds", ctl.connected ? "My rack" : "–", (e) => openRack(e.currentTarget), ctl.connected ? `${(ctl.channels || []).length} channels in your Channel Rack` : "Connect FL to use your sounds"));
}
// Feel sliders (simple ↔ complex, sparse ↔ full…), saved for every beat.
function openFeel(anchor) {
  const feel = Object.assign({}, FEEL_DEFAULT, session.settings.feel || {});
  openPop(anchor, [h("h3", {}, "Feel"), h("p", { class: "pop-sub" }, "Nudges every beat Veloura writes. Middle is balanced."),
    h("div", { class: "feel-grid" }, FEEL.map(([k, lo, hi]) => h("label", { class: "feel-row" }, h("span", {}, lo),
      h("input", { type: "range", min: 0, max: 100, value: feel[k], oninput: (e) => { feel[k] = +e.target.value; saveFeel(feel); } }), h("span", {}, hi)))),
    h("div", { class: "row-btns end" }, h("button", { class: "btn small", type: "button", onclick: () => { Object.assign(feel, FEEL_DEFAULT); saveFeel(feel); closePops(); } }, "Reset"),
      h("button", { class: "btn small primary", type: "button", onclick: closePops }, "Done"))], 360);
}
let tempoTimer = null;
function setTempo(v) {
  v = Math.max(40, Math.min(300, Math.round(Number(v) || 140)));
  session.settings.tempo_bpm = v;
  for (const id of ["tpBox", "tpRange"]) { const el = document.getElementById(id); if (el && el !== document.activeElement) el.value = v; }
  clearTimeout(tempoTimer);
  tempoTimer = setTimeout(async () => { await api("/api/settings", { tempo_bpm: v, tempo_auto: false }); renderPills(); }, 200);
}
function openTempo(anchor) {
  const box = h("input", { type: "number", id: "tpBox", min: "40", max: "300", value: session.settings.tempo_bpm,
    onchange: (e) => setTempo(e.target.value),
    onkeydown: (e) => { if (e.key === "ArrowUp") { e.preventDefault(); setTempo(session.settings.tempo_bpm + 1); } if (e.key === "ArrowDown") { e.preventDefault(); setTempo(session.settings.tempo_bpm - 1); } } });
  const range = h("input", { type: "range", id: "tpRange", min: "60", max: "200", step: "1", value: session.settings.tempo_bpm, oninput: (e) => setTempo(e.target.value) });
  const g = genreInfo[session.settings.genre];
  openPop(anchor, [h("div", { class: "pop-tempo" },
    h("div", { class: "tempo-big" },
      h("button", { class: "step-btn", type: "button", onclick: () => setTempo(session.settings.tempo_bpm - 1) }, "−"), box,
      h("button", { class: "step-btn", type: "button", onclick: () => setTempo(session.settings.tempo_bpm + 1) }, "+")),
    h("div", { class: "tempo-row" }, h("span", { class: "k" }, "60"), range, h("span", { class: "k" }, "200")),
    g ? h("p", { style: "margin:0;color:var(--muted);font-size:12px;text-align:center" }, `${g.label} usually sits at ${g.tempo_range[0]}–${g.tempo_range[1]} BPM`) : null,
    h("div", { class: "row-btns end" }, h("button", { class: "btn small", type: "button", disabled: !(status && status.controller && status.controller.connected), onclick: setFLTempo }, "Set in FL"),
      h("button", { class: "btn small primary", type: "button", onclick: closePops }, "Done")))], 320);
}
function optionList(entries, current, onPick) {
  return h("div", { class: "opt-list" }, entries.map((e) => e.head ? h("div", { class: "opt-head" }, e.head)
    : h("button", { class: "opt" + (e.value === current ? " sel" : ""), type: "button", onclick: async () => { await onPick(e.value); closePops(); } }, e.label, e.note ? h("span", { class: "k" }, e.note) : null)));
}
function openKey(anchor) {
  const s = session.settings, g = genreInfo[s.genre] || {};
  const entries = [{ value: "auto", label: "Auto", note: g.key ? `best for ${g.label}: ${g.key}` : "" }];
  if (g.keys) { entries.push({ head: "Suits " + g.label }); g.keys.forEach((k) => entries.push({ value: k, label: k })); }
  entries.push({ head: "All keys" }); KEYS.forEach((k) => entries.push({ value: k, label: k }));
  openPop(anchor, [h("h3", {}, "Key"), optionList(entries, s.key_auto ? "auto" : s.key, async (v) => {
    await api("/api/settings", v === "auto" ? { key_auto: true } : { key: v, key_auto: false }); await refreshSession(); forceRender(); })], 300);
}
function openBars(anchor) {
  const s = session.settings, g = genreInfo[s.genre] || {};
  const entries = [{ value: "auto", label: "Auto", note: g.bars ? `${g.bars} bars suits ${g.label}` : "" },
    ...[2, 4, 8, 16].map((b) => ({ value: String(b), label: `${b} bars` }))];
  openPop(anchor, [h("h3", {}, "Loop length"), optionList(entries, s.bars_auto ? "auto" : String(s.bars), async (v) => {
    await api("/api/settings", v === "auto" ? { bars_auto: true } : { bars: Number(v), bars_auto: false }); await refreshSession(); forceRender(); })], 280);
}
function openGenre(anchor, asMode) {
  const s = session.settings;
  openPop(anchor, [h("h3", {}, asMode ? "Make a genre beat" : "Genre"),
    h("div", { class: "genre-grid" }, Object.entries(genreInfo).map(([k, g]) => h("button", { class: "genre" + (s.genre === k ? " sel" : ""), type: "button",
      onclick: async () => {
        await api("/api/settings", { genre: k, ...(s.tempo_auto ? {} : { tempo_bpm: g.tempo_bpm }) });
        if (asMode) { genreChip = true; attached = null; store.set("attached", null); }
        await refreshSession(); closePops(); forceRender(); $("input").focus();
      } }, h("b", {}, g.label), h("span", {}, `${g.tempo_range[0]}–${g.tempo_range[1]} BPM`)))),
    asMode ? h("p", { style: "margin:10px 0 0;color:var(--muted);font-size:12px" }, "Then add anything you want in the box (optional) and press Send.") : null], 460);
}
const ROLE_GUESS = [["kick", "Kick"], ["snare", "Snare"], ["clap", "Clap"], ["hat", "Hi-hat"], ["hh", "Hi-hat"], ["perc", "Perc"],
  ["808", "808 / bass"], ["bass", "808 / bass"], ["sample", "Sample"]];
const guessRole = (n) => (ROLE_GUESS.find(([k]) => n.toLowerCase().includes(k)) || [0, "Melodic"])[1];
function openRack(anchor) {
  const ctl = (status && status.controller) || {}, chans = ctl.channels || [];
  openPop(anchor, [h("h3", {}, "Your Channel Rack"),
    ctl.connected ? h("p", { style: "color:var(--muted);margin:0 0 8px;font-size:13px" }, "Veloura writes parts for these sounds. Name channels clearly (Kick, Snare, Hat, 808…).")
      : h("p", { style: "color:var(--muted)" }, "Connect the FL controller (Setup step 3) so Veloura can see your sounds."),
    chans.length ? h("div", { class: "rack" }, chans.map((c) => h("div", { class: "rack-row" }, h("span", { class: "rack-name" }, c.name),
      h("span", { style: "font-size:12px;color:var(--muted)" }, guessRole(c.name) + (c.type && c.type !== "sampler" ? " · plugin" : ""))))) : null,
    h("div", { class: "row-btns end" }, h("button", { class: "btn small", type: "button", onclick: () => openPrep(anchor) }, "Sound prep"),
      h("button", { class: "btn small primary", type: "button", onclick: closePops }, "Done"))], 380);
}

// ---------- sound prep ----------
function openPrep(anchor) {
  if (!prep || !prep.connected) { toast("Connect the FL controller first (Setup step 3).", "err"); return; }
  const list = h("div", { class: "prep-list" }, prep.items.map((it) => h("div", { class: "prep-item" }, h("b", {}, it.channel),
    it.tasks.map((t) => h("label", {}, h("input", { type: "checkbox", checked: t.done, onchange: async (e) => { prep = await api("/api/prep", { channel: it.channel, task: t.id, done: e.target.checked }); renderPrepBanner(); } }), h("span", {}, t.label))))));
  openPop(anchor, [h("h3", {}, "Sound prep"),
    h("p", { style: "color:var(--muted);margin:0;font-size:13px" }, "FL doesn't let Veloura change these, so tick them off as you go. In FL, click the channel's name to open its settings. Veloura reminds you about new sounds."),
    prep.items.length ? list : h("p", {}, "Nothing to prep."),
    h("div", { class: "row-btns end" }, h("button", { class: "btn small primary", type: "button", onclick: closePops }, "Done"))], 400);
}
function renderPrepBanner() {
  const b = $("prepBanner"), s = session && session.settings;
  if (!prep || !prep.connected || !prep.pending || !s) { b.hidden = true; return; }
  const loop = prep.items.some((i) => i.tasks.some((t) => t.id === "loop" && !t.done));
  const cut = prep.items.some((i) => i.tasks.some((t) => t.id === "cut" && !t.done));
  b.hidden = false;
  b.replaceChildren(...[h("div", {}, h("b", {}, `${prep.pending} sound setting${prep.pending === 1 ? "" : "s"} to check`),
    h("span", {}, [loop ? "turn off “Use loop points” on samples" : null, cut ? "turn on “Cut itself” on 808s" : null].filter(Boolean).join(" and ") + " so nothing rings after you stop.")),
    h("button", { class: "btn small", type: "button", onclick: (e) => openPrep(e.currentTarget) }, "Show list"),
    loop ? h("button", { class: "btn small ghost", type: "button", title: "Stop reminding me about loop points", onclick: async () => { await api("/api/settings", { remind_loop: false }); await refreshSession(); refreshPrep(); toast("Loop point reminders off (turn back on in Settings)"); } }, "Don't remind: loop points") : null,
    cut ? h("button", { class: "btn small ghost", type: "button", title: "Stop reminding me about Cut itself", onclick: async () => { await api("/api/settings", { remind_cut: false }); await refreshSession(); refreshPrep(); toast("Cut itself reminders off (turn back on in Settings)"); } }, "Don't remind: Cut itself") : null].filter(Boolean));
}

// ---------- chat ----------
const MODE_NAME = { describe: "", genre: "Genre", sample: "Sample", inspiration: "Inspiration" };
function renderChat() {
  const chat = $("chat"), sc = $("chatScroll");
  const stick = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 80;
  const fresh = !session.messages.length;
  $("page-studio").classList.toggle("fresh", fresh);
  if (!fresh) $("input").placeholder = "Ask for a change…";
  else if ($("input").placeholder === "Ask for a change…") $("input").placeholder = "What are we making tonight?";
  if (fresh) { chat.replaceChildren(); return; }
  chat.replaceChildren(...session.messages.map((m) => {
    if (m.role === "user") return h("div", { class: "msg-user" },
      m.attachment ? h("div", { class: "msg-attach" }, svg(ICONS.melody), m.attachment.name, h("span", {}, m.attachment.mode === "sample" ? " · Sample" : " · Inspiration")) : null, m.text);
    const prop = m.proposal_id ? session.proposals[m.proposal_id] : null;
    const drumIdx = prop ? prop.parts.map((p, i) => i).filter((i) => isDrumPart(prop.parts[i])) : [];
    const otherIdx = prop ? prop.parts.map((p, i) => i).filter((i) => !isDrumPart(prop.parts[i])) : [];
    const open = prop ? prop.parts.filter((p) => p.status !== "applied") : [];
    const ref = prop && prop.reference_id && session.references ? session.references[prop.reference_id] : null;
    const special = prop && ["improve", "variations"].includes(prop.kind);
    return h("div", { class: "msg-ai" }, h("span", { class: "avatar" }, h("i"), h("i"), h("i"), h("i")),
      h("div", { class: "ai-body" },
        h("div", { class: "ai-text" + (m.error ? " error" : "") + (m.cancelled ? " cancelled" : "") }, m.text || "Here's a draft."),
        h("div", { class: "meta" }, providerName(m.provider) + (prop && MODE_NAME[prop.mode] ? " · " + MODE_NAME[prop.mode] + (ref ? " (" + ref.name + ")" : "") : "") + (m.time ? " · " + m.time.slice(11, 16) : "")),
        prop && prop.problems && prop.problems.length ? h("div", { class: "problems" }, prop.problems.map((p) => h("div", {}, "⚠ " + p))) : null,
        special ? proposalHeader(prop) : null,
        prop && prop.kind === "improve" ? improveCards(prop) : null,
        prop && prop.kind === "variations" ? variationCards(prop) : null,
        prop && !special && prop.parts.length ? resultCard(prop, m) : null,
        prop && !special && !prop.parts.length ? orderedProposal(prop, m) : null,
        special && prop.mix ? mixCard(prop) : null));
  }));
  if (stick) sc.scrollTop = sc.scrollHeight;
}
function mixCard(prop) {
  const m = prop.mix, applied = m.status === "applied" || m.status === "partial";
  const rows = (m.preview || []).map((r) => h("tr", {}, h("td", {}, r.target), h("td", {}, r.what),
    h("td", { class: "k" }, r.before), h("td", {}, "→ ", h("b", {}, r.after)), h("td", { class: "k" }, r.why)));
  return h("div", { class: "part mix-card", style: "--role:var(--info)" },
    h("div", { class: "part-head" }, h("span", { class: "role-icon", style: "--role:var(--info)" }, svg(MI.bars)), h("span", { class: "part-title" }, "Mix moves"),
      h("span", { class: "tag" }, `${(m.preview || []).length} change${(m.preview || []).length === 1 ? "" : "s"}`),
      m.status === "undone" ? h("span", { class: "tag" }, "undone") : null),
    rows.length ? h("table", { class: "mix-table" }, h("tr", {}, h("th", {}, "Where"), h("th", {}, "Control"), h("th", {}, "Now"), h("th", {}, "New"), h("th", {}, "Why")), rows) : null,
    (m.problems || []).length ? h("div", { class: "problems" }, m.problems.map((p) => h("div", {}, "⚠ " + p))) : null,
    m.result && m.result.failed && m.result.failed.length ? h("div", { class: "note-box bad" }, h("b", {}, "Some changes failed."), " ", m.result.failed.join(" · ")) : null,
    h("div", { class: "part-actions" }, h("span", { class: "part-hint" }, applied ? "Applied in FL with one undo point. Cmd+Z in FL works too." : "Veloura changes these in FL for you, then reads them back."),
      !applied ? h("button", { class: "btn primary small", disabled: pending > 0 || !rows.length, onclick: async () => {
        const r = await withPending(() => api("/api/mix/apply", { proposal_id: prop.id }), "Mixing in FL…");
        if (r) toast(r.ok ? `Mix applied: ${r.applied} change${r.applied === 1 ? "" : "s"} ✓` : `Applied ${r.applied}, ${r.failed.length} failed`, r.ok ? "ok" : "err"); } }, m.status === "undone" ? "Apply again" : "Apply mix")
        : h("button", { class: "btn small", disabled: pending > 0, onclick: async () => {
          const r = await withPending(() => api("/api/mix/undo", { proposal_id: prop.id }), "Undoing mix…");
          if (r) toast(r.ok ? "Mix undone ✓" : "Undo only partly worked", r.ok ? "ok" : "err"); } }, "Undo mix")));
}

// Fresh Studio: 3 short ideas (rotating per session, leaning to the genres this person makes). After a reply:
// 4 follow-ups that fit what was just written. Each chip shows a short label and sends a fuller request.
function renderChips() {
  const fresh = !session.messages.length;
  $("chips").replaceChildren(...(fresh ? startIdeas() : []).map(([label, text]) => h("button", { class: "chip", type: "button", onclick: () => send(text) }, label)));
  $("followChips").replaceChildren(...(fresh ? [] : followUps()).map(([label, text]) => h("button", { class: "chip", type: "button", disabled: pending > 0, onclick: () => send(text) }, label)));
}
function defaultPrompt() {
  const ref = currentRef(), g = (genreInfo[session.settings.genre] || {}).label || session.settings.genre;
  if (ref) return ref.mode === "sample" ? "Build a complete beat around my sample." : "Make an original beat inspired by this song.";
  if (genreChip) return `Make a complete, professional ${g} beat.`;
  return "";
}
async function send(text) {
  text = (text || "").trim() || defaultPrompt();
  if (!text) { $("input").focus(); return; }
  if (pending) return;
  const ref = currentRef();
  const body = { text, mode: ref ? ref.mode : (genreChip ? "genre" : "describe"), genre: session.settings.genre };
  if (ref) body.reference_id = ref.id;
  // the attachment and genre chip travel with this one message, then clear
  attached = null; store.set("attached", null); genreChip = false;
  $("input").value = ""; autosize();
  session.messages.push({ role: "user", text, time: "", attachment: ref ? { name: ref.name, mode: ref.mode } : null });
  forceRender();
  $("chatScroll").scrollTop = $("chatScroll").scrollHeight;
  await withPending(() => api("/api/chat", body), ref ? "Studying your reference and producing…" : "Producing…");
}
$("composer").addEventListener("submit", (e) => { e.preventDefault(); send($("input").value); });
const autosize = () => { const t = $("input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 180) + "px"; };
$("input").addEventListener("input", autosize);
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); } });

// ---------- FL-style previews ----------
function rackSteps(plan) {
  const steps = (plan.bars || 4) * 16, on = new Array(steps).fill(0), roll = new Array(steps).fill(false);
  for (const n of plan.notes) {
    const pos = n.start * 4, st = Math.floor(pos + 1e-6);
    if (st >= steps) continue;
    on[st] = Math.max(on[st], n.velocity);
    if (Math.abs(pos - Math.round(pos)) > 1e-6 || n.length < .25 - 1e-6) roll[st] = true;
  }
  const groups = [];
  for (let g = 0; g < steps / 4; g++) {
    groups.push(h("span", { class: "rack-group" }, [0, 1, 2, 3].map((i) => {
      const st = g * 4 + i, vel = on[st];
      return h("span", { class: "stepcell" + (vel ? " on" : "") + (roll[st] ? " roll" : ""),
        style: vel ? `opacity:${(.55 + .45 * vel / 127).toFixed(2)}` : null, title: vel ? `Step ${st + 1} · velocity ${vel}` : null });
    })));
  }
  return h("span", { class: "rack-steps" }, groups);
}

function pianoRoll(plan, color) {
  const NS = "http://www.w3.org/2000/svg", notes = plan.notes || [], beats = (plan.bars || 4) * 4;
  const lo0 = Math.min(...notes.map((n) => n.pitch)), hi0 = Math.max(...notes.map((n) => n.pitch));
  let lo = lo0 - 2, hi = hi0 + 2;
  while (hi - lo + 1 < 13) { lo--; hi++; }
  const rows = hi - lo + 1;
  const keys = h("div", { class: "proll-keys" });
  for (let p = hi; p >= lo; p--) {
    const black = [1, 3, 6, 8, 10].includes(p % 12);
    keys.append(h("div", { class: "proll-key" + (black ? " black" : "") }, p % 12 === 0 ? noteName(p) : ""));
  }
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("class", "proll-grid"); s.setAttribute("viewBox", `0 0 ${beats * 40} ${rows * 10}`); s.setAttribute("preserveAspectRatio", "none");
  const rect = (x, y, w, hgt, fill, op) => { const r = document.createElementNS(NS, "rect"); r.setAttribute("x", x); r.setAttribute("y", y); r.setAttribute("width", w); r.setAttribute("height", hgt); r.style.fill = fill; if (op !== undefined) r.style.fillOpacity = op; return r; };
  for (let p = hi; p >= lo; p--) {
    const y = (hi - p) * 10;
    s.append(rect(0, y, beats * 40, 10, [1, 3, 6, 8, 10].includes(p % 12) ? "var(--note-lane)" : "var(--note-lane-alt)"));
  }
  for (let b = 0; b <= beats * 4; b++) {
    const l = document.createElementNS(NS, "line");
    l.setAttribute("x1", b * 10); l.setAttribute("x2", b * 10); l.setAttribute("y1", 0); l.setAttribute("y2", rows * 10);
    l.style.stroke = "#000"; l.style.strokeOpacity = b % 16 === 0 ? ".55" : b % 4 === 0 ? ".3" : ".12"; l.style.strokeWidth = b % 16 === 0 ? "1.4" : ".7";
    s.append(l);
  }
  for (const n of notes) {
    const r = rect(n.start * 40 + .5, (hi - n.pitch) * 10 + .8, Math.max(n.length * 40 - 1, 2), 8.4, color, (.55 + .45 * n.velocity / 127).toFixed(2));
    r.setAttribute("rx", 1.5); r.style.stroke = "rgb(0 0 0 / .45)"; r.style.strokeWidth = ".6";
    const t = document.createElementNS(NS, "title");
    t.textContent = `${noteName(n.pitch)} · bar ${Math.floor(n.start / 4) + 1} beat ${+((n.start % 4) + 1).toFixed(2)} · ${n.length} beats · vel ${n.velocity}`;
    r.append(t); s.append(r);
  }
  return h("div", { class: "proll" }, keys, s);
}
// Tracks still uses this compact view.
const roll = (plan, color) => plan.notes.every((n) => n.pitch === plan.notes[0].pitch)
  ? h("div", { class: "rack" }, h("div", { class: "rack-row" }, rackSteps(plan))) : pianoRoll(plan, color);

// ---------- part cards ----------
function destLabel(part) {
  const d = part.destination || { kind: "pianoroll", label: "Piano Roll" };
  return h("span", { class: "dest" + (d.missing ? " missing" : d.warning ? " warn" : ""), title: d.missing ? (d.problem + " " + (d.fix || "")) : (d.warning || d.why || "") },
    svg(ICONS.arrow), d.label);
}
const isStepsPart = (part) => (part.destination || {}).kind === "steps";
const isDrumPart = (part) => part.role === "drums";

function channelPicker(prop, part, idx, label) {
  const chans = (status && status.controller && status.controller.channels) || [];
  const d = part.destination || {};
  const sel = h("select", { class: "chan-pick" + (d.missing ? " missing" : "") + (d.warning ? " warn" : ""), title: d.warning || (d.how === "remembered" ? "You picked this channel before" : d.how === "kit" ? "From the kit Veloura picked for this beat" : "Which channel this part goes to"),
    onchange: async (e) => {
      const v = e.target.value; if (v === "") return;
      const applied = part.status === "applied";
      if (applied) { await withPending(() => api("/api/reapply", { proposal_id: prop.id, index: idx, channel: +v }), `Moving ${part.name}…`); }
      else { try { await api("/api/route", { proposal_id: prop.id, index: idx, channel: +v }); } catch (err) { toast(err.message, "err"); } }
      await refreshSession(); forceRender();
    } },
    h("option", { value: "", selected: !d.channel }, label || (d.missing ? "Choose a channel…" : "Move to…")),
    chans.map((c) => h("option", { value: c.index, selected: c.name === d.channel }, `${c.index + 1}. ${c.name}`)));
  return sel;
}
function partActions(prop, part, idx, compact) {
  const inFL = session.parts[part.name], applied = part.status === "applied", out = [];
  const d = part.destination || {};
  out.push(channelPicker(prop, part, idx));
  if (!applied) out.push(h("button", { class: "btn primary small", disabled: pending > 0 || d.missing, title: d.missing ? d.fix || "" : "", onclick: () => applyPart(prop, idx) }, inFL ? "Swap in" : "Add"));
  else {
    out.push(h("button", { class: "btn small ok-state", disabled: true }, "In FL ✓"));
    out.push(h("button", { class: "btn small", disabled: pending > 0, title: "Write it again (e.g. if it didn't sound right)", onclick: async () => {
      const r = await withPending(() => api("/api/reapply", { proposal_id: prop.id, index: idx }), `Re-applying ${part.name}…`); if (r && r.ok) toast(`${part.name} re-applied ✓`, "ok"); } }, "Re-apply"));
    if (inFL) out.push(h("button", { class: "btn small", disabled: pending > 0, onclick: () => undoPart(part.name) }, "Undo"));
  }
  if (!compact) out.push(h("button", { class: "btn small ghost", onclick: () => exportPart({ proposal_id: prop.id, index: idx }) }, "Save MIDI"));
  return out;
}

function drumRack(prop, idxs) {
  const rows = idxs.map((i) => {
    const part = prop.parts[i];
    return h("div", {},
      h("div", { class: "rack-row" },
        h("span", { class: "rack-name" + ((part.destination || {}).missing ? " missing" : ""), title: (part.destination || {}).missing ? (part.destination.problem + " " + (part.destination.fix || "")) : ((part.destination || {}).label || "") },
          (part.destination || {}).channel || part.name),
        rackSteps(part.plan),
        h("span", { class: "rack-status row-btns" }, partActions(prop, part, i, true))),
      part.result && !part.result.ok ? resultBox(prop, part, i, part.result) : null,
      (part.destination || {}).missing && part.status !== "applied" && !(part.result && !part.result.ok) ? h("div", { class: "note-box warn" }, h("b", {}, part.name + ": "), part.destination.problem + " " + (part.destination.fix || "")) : null);
  });
  const open = idxs.filter((i) => prop.parts[i].status !== "applied");
  const allSteps = open.every((i) => isStepsPart(prop.parts[i]));
  return h("div", { class: "part", style: "--role:var(--drum)" },
    h("div", { class: "part-head" }, h("span", { class: "role-icon" }, svg(ICONS.drums)), h("span", { class: "part-title" }, "Drums"),
      h("span", { class: "tag" }, `${idxs.length} channels · ${prop.parts[idxs[0]].plan.bars} bars`),
      h("span", { class: "dest" }, svg(ICONS.arrow), "Channel Rack")),
    h("div", { class: "rack" }, rows),
    open.length > 1 ? h("div", { class: "part-actions" }, h("span", { class: "part-hint" }, allSteps ? "These go straight into your Channel Rack. No Piano Rolls needed." : "Rows marked Piano Roll need that channel's Piano Roll open."),
      h("button", { class: "btn primary small", disabled: pending > 0, onclick: () => addAll(prop, open) }, "Add all drums")) : null);
}

function partCard(prop, part, idx) {
  const color = ROLE_COLOR[part.role] || ROLE_COLOR.other, applied = part.status === "applied", inFL = session.parts[part.name];
  const d = part.destination || {};
  const auto = d.open && (status && status.controller && status.controller.connected);
  const hint = applied ? null : h("span", { class: "part-hint" + (d.missing ? " fixme" : "") }, d.missing ? `${d.problem} ${d.fix || ""}`
    : auto ? `Goes to “${d.channel}”. Veloura opens its Piano Roll for you.` : d.channel ? `Goes to “${d.channel}”.` : "");
  return h("div", { class: "part" + (applied ? " applied" : ""), style: `--role:${color}` },
    h("div", { class: "part-head" },
      h("span", { class: "role-icon" }, svg(ICONS[part.role] || ICONS.other)),
      h("span", { class: "part-title" }, part.name),
      h("span", { class: "tag" }, `${part.plan.notes.length} notes · ${part.plan.bars} bars · ${part.plan.key}`),
      inFL && !applied ? h("span", { class: "tag rev" }, "new version") : null,
      destLabel(part)),
    pianoRoll(part.plan, color),
    h("div", { class: "part-actions" }, hint, partActions(prop, part, idx)),
    resultBox(prop, part, idx, part.result));
}

function resultBox(prop, part, idx, res) {
  if (!res || res.ok) {
    return res && res.checks ? h("details", { class: "checks" }, h("summary", {}, "How Veloura checked this"),
      h("ul", {}, res.checks.map((c) => h("li", { class: c.passed ? "pass" : "fail" }, (c.passed ? "✓ " : "✗ ") + c.check)),
        res.confirm_detail ? h("li", { class: res.confirmed ? "pass" : "fail" }, (res.confirmed ? "✓ " : "✗ ") + res.confirm_detail) : null)) : null;
  }
  const box = (cls, title, text, ...btns) => h("div", { class: "note-box " + cls }, h("b", {}, title), " ", text,
    btns.length ? h("div", { class: "row-btns" }, btns) : null);
  if (res.code === "not_empty") {
    return box("warn", "Nothing changed.", isStepsPart(part) ? "That channel already has steps, and Veloura protects them."
      : "That Piano Roll already has notes, and Veloura protects them.",
      h("button", { class: "btn small primary", onclick: () => applyPart(prop, idx, { allow_existing: true }) },
        isStepsPart(part) ? "Replace them (undoable)" : "Add alongside them"));
  }
  if (res.code === "replace_failed") {
    return box("warn", "Nothing changed.", res.message,
      h("button", { class: "btn small primary", onclick: () => applyPart(prop, idx, { as_new: true, allow_existing: true }) }, "Add as a new copy"));
  }
  if (res.code === "no_target") {
    return box("warn", "Not added yet.", `${res.message} ${res.fix || ""}`, channelPicker(prop, part, idx, "Choose its channel…"));
  }
  if (res.code === "target_failed") {
    return box("warn", "Nothing changed.", res.message,
      h("button", { class: "btn small primary", onclick: () => applyPart(prop, idx, { manual_target: true }) }, "I opened it myself, add now"));
  }
  if (res.code === "no_result" || res.status === "no_result") {
    return h("div", { class: "note-box bad" }, h("b", {}, "Connect the bridge, then try again."), " FL forgets it when it restarts.", bridgeMock(true),
      h("div", { class: "row-btns" }, h("button", { class: "btn small primary glow", onclick: () => applyPart(prop, idx) }, "Try again")));
  }
  return box("bad", "Didn't work.", res.message, h("button", { class: "btn small primary", onclick: () => applyPart(prop, idx) }, "Apply again"),
    channelPicker(prop, part, idx, "Apply to another channel…"));
}

function guideCard(g, key) {
  todoState[key] = todoState[key] || {};
  return h("div", { class: "guide" },
    h("div", { class: "guide-head" }, h("span", { class: "role-icon" }, svg(ICONS.guide)), h("b", {}, g.title), h("span", { class: "guide-tag" }, "in FL")),
    g.problem ? h("p", {}, g.problem) : null,
    g.steps && g.steps.length ? h("ol", { class: "todo" }, g.steps.slice(0, 5).map((st, i) => h("li", {}, h("label", {},
      h("input", { type: "checkbox", checked: todoState[key][i] || false, onchange: (e) => { todoState[key][i] = e.target.checked; } }),
      h("span", {}, st))))) : null,
    g.settings && g.settings.length ? h("div", { class: "guide-set" }, g.settings.map((x) => h("span", { title: x.range || "" }, x.control, h("b", {}, x.value)))) : null);
}

// ---------- applying parts ----------
async function matchTempo(plan) {
  const ctl = status && status.controller;
  if (!session.settings.auto_tempo || !ctl || !ctl.connected || !plan.tempo_bpm) return;
  if (Math.abs((ctl.tempo || 0) - plan.tempo_bpm) < 0.01) return;
  try {
    const r = await api("/api/fl-tempo", { bpm: plan.tempo_bpm });
    if (r.ok) { toast(`FL tempo set to ${r.tempo} BPM`, "ok"); ctl.tempo = r.tempo; }
  } catch (_) {}
}

async function applyPart(prop, idx, opts) {
  const part = prop.parts[idx];
  const res = await withPending(async () => {
    await matchTempo(part.plan);
    return api("/api/apply", { proposal_id: prop.id, index: idx, ...(opts || {}) });
  }, `Adding ${part.name} to FL…`);
  if (res && res.ok) toast(`${part.name} is in FL ✓`, "ok");
  return res;
}

function ask(title, text, okLabel) {
  return new Promise((resolve) => {
    const dlg = $("modal");
    const done = (v) => { dlg.close(); resolve(v); };
    $("modalBody").replaceChildren(h("h3", {}, title), h("p", {}, text),
      h("div", { class: "row-btns end" },
        h("button", { class: "btn", onclick: () => done("cancel") }, "Stop"),
        h("button", { class: "btn", onclick: () => done("skip") }, "Skip this part"),
        h("button", { class: "btn primary", onclick: () => done("ok") }, okLabel)));
    dlg.onclose = () => resolve("cancel");
    dlg.showModal();
  });
}

async function addAll(prop, only) {
  addAllRunning = true; cancelRequested = false;
  try { await addAllInner(prop, only); } finally { addAllRunning = false; cancelRequested = false; setBusy(null); }
}
async function addAllInner(prop, only) {
  // Every part goes to its routed channel: drums into the Channel Rack, the rest into their own Piano Rolls.
  const order = (only || prop.parts.map((p, i) => i)).filter((i) => prop.parts[i].status !== "applied")
    .sort((a, b) => (isStepsPart(prop.parts[b]) ? 1 : 0) - (isStepsPart(prop.parts[a]) ? 1 : 0));
  const skipped = [], failed = [];
  for (const i of order) {
    if (cancelRequested) { toast("Stopped. Parts already added stay in FL.", ""); return; }
    await refreshSession();
    const fresh = session.proposals[prop.id], part = fresh.parts[i];
    if ((part.destination || {}).missing) { skipped.push(part.name); continue; }
    const r = await applyPart(fresh, i);
    if (cancelRequested) { toast("Stopped. Parts already added stay in FL.", ""); return; }
    if (!r || !r.ok) failed.push(part.name);
  }
  if (session.settings.auto_mixer !== false) { try { const m = await api("/api/mixer-setup", {}); if (m.routed && m.routed.length) toast(`Gave ${m.routed.length} channel(s) their own mixer track`, "ok"); } catch (_) {} }
  await refreshSession();
  if (!skipped.length && !failed.length) toast("Everything's in FL. Press play! ▶", "ok");
  else toast([skipped.length ? `Needs a channel: ${skipped.join(", ")}` : "", failed.length ? `Didn't go in: ${failed.join(", ")} (press Apply again on its card)` : ""].filter(Boolean).join(" · "), "err");
}

async function undoPart(name) {
  const entry = session.parts[name];
  const path = entry && entry.history && entry.history.length ? "/api/revert" : "/api/remove";
  const r = await withPending(() => api(path, { name }), `Undoing ${name}…`);
  if (r) toast(r.ok ? `${name} undone ✓` : r.message, r.ok ? "ok" : "err");
}

async function exportPart(body) {
  let directory;
  if (window.velouraNative && window.velouraNative.chooseFolder) {
    directory = await window.velouraNative.chooseFolder();
    if (directory === null) return;
  }
  const r = await withPending(() => api("/api/export", { ...body, directory }), "Saving MIDI…");
  if (r && r.path) {
    toast("Saved " + r.path.split("/").pop() + ". Drag it onto a channel in FL.", "ok");
    api("/api/reveal", { path: r.path });
  }
}

// ---------- tracks ----------
function renderTracks() {
  const names = Object.keys(session.parts);
  if (!names.length) {
    $("trackGrid").replaceChildren(h("div", { class: "empty" }, illustration("sketch", 64), h("b", {}, "Nothing in FL yet"),
      "Parts you add from Studio show up here, so you can undo them, go back a version or save them as MIDI.",
      h("div", { style: "margin-top:14px" }, h("button", { class: "btn primary small", onclick: () => showPage("studio") }, "Go to Studio"))));
    return;
  }
  $("trackGrid").replaceChildren(...names.map((n) => {
    const p = session.parts[n], color = ROLE_COLOR[p.role] || ROLE_COLOR.other;
    const where = p.mode === "steps" ? `Channel Rack · ${p.channel_name} · pattern ${p.pattern}` : "Piano Roll";
    return h("div", { class: "part applied", style: `--role:${color}` },
      h("div", { class: "part-head" }, h("span", { class: "role-icon" }, svg(ICONS[p.role] || ICONS.other)),
        h("span", { class: "part-title" }, n), h("span", { class: "tag" }, `${p.plan.notes.length} notes`),
        p.history.length ? h("span", { class: "tag" }, `${p.history.length + 1} versions`) : null,
        h("span", { class: "dest" }, svg(ICONS.arrow), where)),
      roll(p.plan, color),
      h("div", { class: "part-actions" }, h("span", { class: "part-hint" }, "Updated " + p.updated.slice(11, 16)),
        h("button", { class: "btn small", disabled: !p.history.length || pending > 0, onclick: () => trackOp("/api/revert", n, "Going back…") }, "Previous version"),
        h("button", { class: "btn small danger", disabled: pending > 0, onclick: () => trackOp("/api/remove", n, "Removing…") }, "Remove from FL"),
        h("button", { class: "btn small ghost", onclick: () => exportPart({ name: n }) }, "Save MIDI")));
  }));
}
async function trackOp(path, name, label) {
  if (path === "/api/remove" && !confirm(`Remove Veloura's "${name}" from FL Studio? Your own notes and steps stay.`)) return;
  const r = await withPending(() => api(path, { name }), label);
  if (r) toast(r.ok ? "Done ✓" : r.message, r.ok ? "ok" : "err");
}
async function exportAll() {
  let directory;
  if (window.velouraNative && window.velouraNative.chooseFolder) { directory = await window.velouraNative.chooseFolder(); if (directory === null) return; }
  let last;
  for (const n of Object.keys(session.parts)) last = await api("/api/export", { name: n, directory }).catch((e) => toast(e.message, "err"));
  if (last && last.path) { toast("All parts saved as MIDI ✓", "ok"); api("/api/reveal", { path: last.path }); }
}

// ---------- setup ----------
// The reconnect order that reliably brings Veloura and FL back together. One copy for the whole UI; the service's
// messages use the same words (veloura/help_text.py, kept identical by tests/test_setup_speed.py).
const RECONNECT_STEPS = [
  "Quit FL Studio and quit Veloura.",
  "Open Veloura first.",
  "Then open FL Studio.",
  "Open your project.",
  "Go straight to the Piano Roll.",
  "Link the bridge (Tools > Scripts > veloura_bridge).",
];
const reconnectList = () => h("ol", { class: "reconnect" }, ...RECONNECT_STEPS.map((t) => h("li", {}, t)));
$("helpReconnect").replaceChildren(reconnectList());
const SETUP_ORDER = ["ai", "keys", "midi", "pianoroll", "kits"];
// Steps from the last status Veloura already has (null = still checking), so Setup shows at once and fills in.
function stepsFromStatus(st) {
  if (!st) return SETUP_ORDER.map((id) => ({ id, ok: null }));
  const prov = (st.providers || {})[st.provider] || {};
  const ok = { ai: !!prov.available && st.provider !== "offline", keys: st.accessibility, midi: !!(st.controller || {}).connected,
    pianoroll: st.armed, kits: (st.kit_folders || 0) > 0 };
  return SETUP_ORDER.map((id) => ({ id, ok: !!ok[id], provider: id === "ai" ? st.provider : undefined }));
}
const STEP_INFO = {
  ai: { title: "Connect your AI", done: "Connected",
    // ChatGPT first: most people sign in with their ChatGPT plan. Their own key (Claude, Gemini) or Offline sits
    // behind "Use my own AI instead", already open for someone who picked one of those before.
    body: () => {
      const cur = session.settings.provider, own = setupOwnAI === null ? !["chatgpt", "offline"].includes(cur) : setupOwnAI;
      return [chatgptSheet(),
        h("button", { class: "link-btn", onclick: () => { setupOwnAI = !own; renderSetup(); } }, own ? "Hide other options" : "Use my own AI instead"),
        own ? h("div", { class: "ai-choice" }, ...offeredProviders().filter(([id]) => id !== "chatgpt").map(([id, name, sub]) => providerButton(id, name, sub))) : null];
    } },
  keys: { title: "Allow Accessibility", done: "Allowed",
    body: () => [h("p", {}, "Veloura presses FL's “run script” shortcut for you, and macOS needs your OK for that."),
      h("ol", {}, h("li", {}, "Open Accessibility settings."), h("li", {}, "Turn on ", h("b", {}, "Veloura"), " (or click + and add it)."),
        h("li", {}, "Quit and reopen Veloura.")),
      h("button", { class: "btn primary small", onclick: () => api("/api/open-accessibility", {}) }, "Open Accessibility settings")] },
  midi: { title: "Connect FL (one time)", done: "FL is connected",
    body: () => {
      const st = status || {}, scriptsOk = scriptsOk2(st);
      return [
        st.fl_running ? null : h("div", { class: "note-box warn" }, h("b", {}, "Open Veloura first, then FL Studio."), " ",
          h("button", { class: "btn small", onclick: () => api("/api/open-fl", {}) }, "Open FL Studio")),
        scriptsOk ? null : h("p", {}, h("button", { class: "btn small", onclick: async () => { await withPending(() => api("/api/repair-bridge", {}), "Installing…"); refreshSetup(); } }, "Install Veloura's FL helpers")),
        h("ol", {}, h("li", {}, "In FL: ", h("kbd", {}, "Options ▸ MIDI settings"), "."),
          h("li", {}, "Input ", h("b", {}, "Veloura to FL"), ": Controller type ", h("b", {}, "Veloura Controller"), ", ", h("b", {}, "Enable"), ", Port ", h("b", {}, "10"), "."),
          h("li", {}, "Output ", h("b", {}, "FL to Veloura"), ": Port ", h("b", {}, "10"), ".")),
        h("div", { class: "mock" }, h("div", { class: "h" }, h("span", {}, ""), h("span", {}, "Device"), h("span", {}, "Controller type"), h("span", {}, "Port")),
          h("div", {}, h("span", { class: "h" }, "Input"), h("span", { class: "hl" }, "Veloura to FL"), h("span", { class: "hl" }, "Veloura Controller"), h("span", { class: "hl" }, "10")),
          h("div", {}, h("span", { class: "h" }, "Output"), h("span", { class: "hl" }, "FL to Veloura"), h("span", {}, ""), h("span", { class: "hl" }, "10"))),
        h("p", { class: "muted" }, "This step turns green as soon as FL answers. FL remembers it.")];
    } },
  pianoroll: { title: "Link the bridge", done: "Linked",
    body: () => [h("p", {}, "Each time FL starts: open a Piano Roll, then choose ", h("kbd", {}, "Tools ▸ Scripts ▸ veloura_bridge"), "."),
      bridgeMock(),
      h("details", { class: "reconnect-details inline" },
        h("summary", {}, h("button", { class: "btn primary small", type: "button", onclick: async (e) => { e.preventDefault(); const r = await withPending(() => api("/api/test-bridge", {}), "Checking…"); if (r) toast(r.ok ? "Linked ✓" : r.message, r.ok ? "ok" : "err"); refreshSetup(); } }, "Check"),
          h("span", { class: "link-quiet" }, "If it won't connect")), reconnectList())] },
  kits: { title: "Pick your drum kit folder", done: "Kits added",
    body: () => [h("p", {}, "Choose the folder with your drum kits. Veloura sorts them into kicks, snares, hats and 808s."),
      h("button", { class: "btn primary small", onclick: async () => { const r = await withPending(() => api("/api/library/add-folder", {}), "Adding your kits…"); if (r && r.ok !== false) { toast("Kits added. Sorting them now.", "ok"); refreshSetup(); } } }, "Choose folder…")] },
};
const scriptsOk2 = (st) => st.bridge_script === "installed and up to date" && st.bridge_folder && st.controller_script === "installed and up to date";
let setupOwnAI = null;   // null: decide from the saved provider
function providerButton(id, name, sub) {
  const sel = session && session.settings.provider === id;
  return h("button", { class: "provider brand-" + id + (sel ? " sel" : ""), onclick: async () => { await api("/api/settings", { provider: id }); await refreshSession(); await refreshSetup(); if (id !== "offline") showPage("settings"); } },
    providerHead(id, name), h("small", {}, sub));
}
const providerHead = (id, name) => h("span", { class: "prov-head" }, brandLogo(id, 18), h("b", {}, name));
const velouraMark = () => h("span", { class: "logo", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i"));

// ---------- ChatGPT sign-in sheet (OpenAI's "Sign in with ChatGPT" look), in Setup and Settings ----------
const CHATGPT_USAGE = "https://chatgpt.com/settings/usage";
let cgPoll = null;
async function useProvider(id) {
  await api("/api/settings", { provider: id }); await refreshSession(); await refreshStatus();
  if (id !== "offline") showPage("settings"); else if (page === "setup") refreshSetup();
  forceRender();
}
async function chatgptSignIn() {
  try {
    if (session.settings.provider !== "chatgpt") { await api("/api/settings", { provider: "chatgpt" }); await refreshSession(); }
    await api("/api/chatgpt-login", {});   // a second click re-opens the same sign-in page
    toast("Finish signing in in your browser.");
  } catch (e) { toast(e.message, "err"); return; }
  await refreshStatus(); forceRender();
  clearInterval(cgPoll);
  let n = 0;
  cgPoll = setInterval(async () => {
    await refreshStatus();
    if (page === "setup") await refreshSetup();
    forceRender();
    const c = (status.providers || {}).chatgpt || {};
    if (c.login !== "waiting" || ++n > 150) {
      clearInterval(cgPoll);
      if (c.available) chatgptWelcome(); else if (c.login === "error" && c.login_code !== "plan") toast(c.detail, "err");
    }
  }, 2000);
}
// OpenAI asks for a one-time "You're using your ChatGPT plan" confirmation after the first sign-in.
function chatgptWelcome() {
  if (store.get("chatgptWelcomed", false)) { toast("Connected to ChatGPT ✓", "ok"); return; }
  store.set("chatgptWelcomed", true);
  const body = $("modalBody"), dlg = $("modal");
  body.replaceChildren(h("div", { class: "sheet-chatgpt welcome" }, h("span", { class: "tile" }, brandLogo("chatgpt", 28)),
    h("h2", {}, "You're using your ChatGPT plan"),
    h("p", {}, "Beats you make in Veloura use your ChatGPT plan. Manage usage in your ChatGPT settings."),
    h("div", { class: "sheet-row" }, h("a", { class: "cg-btn ghost", href: CHATGPT_USAGE, target: "_blank" }, "Manage usage"),
      h("button", { class: "cg-btn", onclick: () => dlg.close() }, "Got it"))));
  if (!dlg.open) dlg.showModal();
}
function chatgptSheet() {
  const cg = ((status && status.providers) || {}).chatgpt || {}, waiting = cg.login === "waiting";
  return h("div", { class: "brand-sheet sheet-chatgpt" },
    h("div", { class: "sheet-logos" }, h("span", { class: "tile" }, brandLogo("chatgpt", 30)), h("span", { class: "dots" }, "•••"),
      h("span", { class: "tile veloura" }, velouraMark())),
    h("h3", {}, cg.signed_in ? "ChatGPT is connected" : "Connect ChatGPT and Veloura"),
    h("div", { class: "sheet-option" }, h("span", { class: "opt-icon" }, brandLogo("chatgpt", 16)),
      h("div", {}, h("b", {}, "Use your ChatGPT plan"),
        h("small", {}, cg.signed_in ? cg.detail : "Veloura uses usage from your ChatGPT plan's limits. Needs a paid plan (Go, Plus or Pro). We recommend Plus."))),
    cg.signed_in
      ? h("div", { class: "sheet-row" },
          h("a", { class: "cg-btn ghost", href: CHATGPT_USAGE, target: "_blank" }, "Manage usage"),
          h("button", { class: "cg-btn ghost", onclick: async () => { await api("/api/chatgpt-signout", {}); toast("Signed out of ChatGPT"); await refreshStatus(); forceRender(); } }, "Sign out"))
      : h("button", { class: "cg-btn wide", onclick: chatgptSignIn }, brandLogo("chatgpt", 18),
          waiting ? "Waiting for your browser… (click to reopen)" : "Continue with ChatGPT"),
    !cg.signed_in && cg.login === "error" ? h("p", { class: "sheet-err" }, cg.detail) : null,
    // Free ChatGPT accounts can't share their plan with apps (OpenAI's rule): offer the free choices right here.
    !cg.signed_in && cg.login_code === "plan" ? h("div", { class: "sheet-row plan-alt" },
      h("button", { class: "cg-btn ghost", onclick: () => useProvider("gemini") }, brandLogo("gemini", 16), "Use Google Gemini (free tier)"),
      h("button", { class: "cg-btn ghost", onclick: () => useProvider("offline") }, "Use Offline")) : null,
    h("p", { class: "sheet-foot" }, "Veloura never sees your ChatGPT password or chats. You can manage this connection anytime in ChatGPT settings."));
}
// Waiting labels for the step being worked on (the right side of its row).
const STEP_WAIT = { ai: "Not connected", keys: "Waiting for macOS", midi: "Waiting for FL", pianoroll: "Waiting for FL", kits: "Choose a folder" };
const setupOpen = new Set();   // steps the user opened by hand
function renderSetup() {
  if (!session) return;
  const steps = setup ? setup.steps : stepsFromStatus(status), checking = steps.some((s) => s.ok === null);
  const okCount = steps.filter((s) => s.ok).length, firstOpen = checking ? -1 : steps.findIndex((s) => !s.ok);
  $("setupProgress").style.width = (okCount / steps.length * 100) + "%";
  $("setupCount").textContent = checking ? "" : `${okCount} of ${steps.length}`;
  const onboarding = !session.settings.onboarded;
  $("setupEyebrow").textContent = onboarding ? "Welcome to Veloura Beta" : "One-time setup";
  $("setupTitle").textContent = "Connect to FL Studio";
  $("setupSub").textContent = checking ? "Checking your setup…" : okCount === steps.length ? "Everything is connected. Let's make something."
    : "Five quick steps. Each one turns green by itself when it is done.";
  // the reconnect order helps people who were set up and lost the connection, not someone setting up for the first time
  const flTrouble = !checking && !!session.settings.onboarded && steps.some((s) => !s.ok && s.id === "midi");   // the bridge step has its own "If it won't connect"
  $("setupReconnect").hidden = !flTrouble;
  $("setupReconnect").replaceChildren(h("b", {}, "Can't connect? Do these in order:"), reconnectList());
  $("steps").replaceChildren(...steps.map((s, i) => {
    const info = STEP_INFO[s.id], current = i === firstOpen, open = !s.ok && (current || setupOpen.has(s.id));
    const state = s.ok ? (s.id === "ai" ? `${providerName(s.provider)} · connected` : info.done)
      : s.ok === null ? "Checking…" : current ? STEP_WAIT[s.id] : "Next";
    const toggle = () => { if (s.ok || current) return; setupOpen.has(s.id) ? setupOpen.delete(s.id) : setupOpen.add(s.id); renderSetup(); };
    return h("li", { class: "step" + (s.ok ? " ok" : "") + (s.ok === null ? " checking" : "") + (current ? " current" : "") + (open ? " open" : "") + (!s.ok && !current ? " later" : "") },
      h("button", { class: "step-head", type: "button", onclick: toggle, "aria-expanded": open ? "true" : "false" },
        h("span", { class: "step-num" }, s.ok ? svg(["M5 12.5l4.5 4.5L19 7.5"]) : String(i + 1)),
        h("h3", {}, info.title), h("span", { class: "state" }, state)),
      open ? h("div", { class: "step-detail" }, info.body()) : null);
  }));
  const coreOk = steps.filter((s) => s.id !== "kits").every((s) => s.ok);
  $("startMaking").textContent = "Start making music →";
  $("startMaking").className = "btn big " + (coreOk ? "primary" : "quiet");
  $("skipSetup").hidden = !onboarding || coreOk;
}
const finishSetup = async () => { await api("/api/settings", { onboarded: true }); await refreshSession(); showPage("studio"); };
$("startMaking").addEventListener("click", finishSetup);
$("skipSetup").addEventListener("click", finishSetup);

// ---------- settings ----------
// The AI options, recommended first. "claude-code" (a personal Claude login) only exists in the developer's developer copy;
// the service lists which ones this build offers (session.app.providers).
const PROVIDER_INFO = {
  chatgpt: ["ChatGPT", "Recommended · a paid plan, Plus is the best pick"],
  anthropic: ["Claude API", "Your API key · pay Anthropic per use"],
  gemini: ["Google Gemini", "Your API key · free tier available"],
  offline: ["Offline composer", "Simple patterns · not AI"],
  "claude-code": ["Claude (developer)", "Your Claude login · developer copy only"],
};
const offeredProviders = () => (((session && session.app) || {}).providers || ["chatgpt", "anthropic", "gemini", "offline"])
  .filter((id) => PROVIDER_INFO[id]).map((id) => [id, ...PROVIDER_INFO[id]]);
function renderThemes() {
  const cur = (session.settings.theme && THEMES.some((t) => t.id === session.settings.theme)) ? session.settings.theme : "champagne";
  $("themeGrid").replaceChildren(...THEMES.map((t) => h("button", { class: "theme-card" + (t.id === cur ? " sel" : ""), type: "button", "aria-pressed": t.id === cur ? "true" : "false",
    onclick: async () => {
      applyTheme(t.id); session.settings.theme = t.id; renderThemes();
      try { await api("/api/settings", { theme: t.id }); } catch (e) { toast(e.message, "err"); }
    } },
    h("span", { class: "tc-swatch", style: `--s1:${t.sw[0]};--s2:${t.sw[1]};--s3:${t.sw[2]};--sbg:${t.bg}` }, h("i"), h("i"), h("i"), h("i")),
    h("span", { class: "tc-name" }, t.name), h("small", {}, t.note),
    t.id === cur ? h("span", { class: "tc-check" }, svg(["M5 12.5l4.5 4.5L19 7.5"])) : null)));
}
function renderSettings() {
  const s = session.settings, pv = (status && status.providers) || {};
  renderThemes();
  $("providerGrid").replaceChildren(...offeredProviders().map(([id, name, sub]) => h("button", { class: "provider brand-" + id + (s.provider === id ? " sel" : ""),
    onclick: async () => { await api("/api/settings", { provider: id }); await refreshSession(); await refreshStatus(); forceRender(); } },
    h("span", { class: "dot " + ((pv[id] || {}).available ? "ok" : "") }), providerHead(id, name), h("small", {}, sub))));
  const d = $("providerDetail");
  if (d.contains(document.activeElement)) return;  // don't wipe a key someone is typing
  const p = s.provider;
  d.className = p === "offline" ? "card" : "brand-host";
  const sheetHead = (id, title, tag) => h("div", { class: "sheet-head" }, h("span", { class: "tile" }, brandLogo(id, 24)), h("h3", {}, title), tag ? h("span", { class: "dev-tag" }, tag) : null);
  const model = (key, def) => h("label", {}, "Model", h("input", { value: s[key] || def, onchange: (e) => api("/api/settings", { [key]: e.target.value.trim() || def }) }));
  // Claude models: Haiku / Sonnet / Opus with a rough cost per beat (the user pays Anthropic directly).
  const claudeModel = () => h("div", {},
    h("label", {}, "Model", h("select", { onchange: async (e) => { await api("/api/settings", { model: e.target.value }); await refreshSession(); forceRender(); } },
      ...claudeModels().map((m) => h("option", { value: m.id, selected: s.model === m.id }, `${m.label} · ${m.cost}`)))),
    h("p", { style: "color:var(--muted);font-size:12px;margin:6px 0 0" }, "Rough estimates at Anthropic's prices. Haiku is plenty for most beats."));
  const keyRow = (prov, placeholder) => {
    const inp = h("input", { type: "password", placeholder, autocomplete: "off" });
    return h("div", { class: "row-btns", style: "margin:8px 0" }, h("div", { style: "flex:1" }, inp),
      h("button", { class: "btn small primary", onclick: async () => { try { await api("/api/apikey", { key: inp.value, provider: prov }); inp.value = ""; toast("Key saved to your Keychain ✓", "ok"); refreshStatus(); } catch (e) { toast(e.message, "err"); } } }, "Save key"),
      h("button", { class: "btn small ghost", onclick: async () => { await api("/api/apikey", { delete: true, provider: prov }); toast("Key removed"); refreshStatus(); } }, "Remove"));
  };
  const stat = (id) => h("p", { style: "margin:0 0 8px;color:var(--muted)" },
    h("span", { class: "dot " + ((pv[id] || {}).available ? "ok" : "warn"), style: "display:inline-block;margin-right:7px" }), (pv[id] || {}).detail || "");
  if (p === "gemini") d.replaceChildren(h("div", { class: "brand-sheet sheet-gemini" }, h("div", { class: "sheet-head" }, brandWordmark("gemini", 30)), stat("gemini"),
    h("p", {}, "1. Go to ", h("a", { href: "https://aistudio.google.com/apikey", target: "_blank" }, "aistudio.google.com/apikey"), " and click ", h("b", {}, "Create API key"), ". 2. Paste it below. It's stored in your Mac's Keychain."),
    keyRow("gemini", "Paste your Gemini key"), model("gemini_model", "gemini-3.8-flash"),
    h("p", { class: "sheet-foot" }, "Free tier: Google may use your requests to improve its products, and it isn't offered in the EEA, UK or Switzerland (use a paid key there). Gemini requires you to be 18 or older.")));
  else if (p === "chatgpt") d.replaceChildren(chatgptSheet(),
    h("details", { class: "sheet-advanced" }, h("summary", {}, "Advanced"), model("chatgpt_model", ""),
      h("p", { class: "muted", style: "font-size:12px" }, "Leave Model empty to use your plan's default.")));
  else if (p === "claude-code") d.replaceChildren(h("div", { class: "brand-sheet sheet-claude" }, sheetHead("claude-code", "Claude", "Developer copy"), stat("claude-code"),
    h("p", {}, "Uses your Claude plan through Claude Code. There's no extra cost; it counts toward your usual limits."),
    h("button", { class: "btn primary small", onclick: async () => { try { await api("/api/claude-login", {}); toast("Finish signing in in your browser."); } catch (e) { toast(e.message, "err"); } } }, "Connect Claude account"),
    h("div", { style: "margin-top:10px" }, claudeModel())));
  else if (p === "anthropic") d.replaceChildren(h("div", { class: "brand-sheet sheet-claude" }, h("div", { class: "sheet-head" }, brandWordmark("anthropic", 30)), stat("anthropic"),
    h("p", {}, "Create a key at ", h("a", { href: "https://console.anthropic.com/settings/keys", target: "_blank" }, "console.anthropic.com"), ". You pay Anthropic directly for what you use."),
    keyRow("anthropic", "sk-ant-…"), claudeModel()));
  else d.replaceChildren(h("h3", {}, "Offline composer"), h("p", { style: "color:var(--muted);margin:0" }, "Built-in rule-based patterns (scales and rhythm templates). Free and always available, but not AI, so it won't understand detailed requests."));

  if (!document.activeElement || !document.activeElement.closest || !document.activeElement.closest("#page-settings .grid2")) {
    $("setAutoTempo").checked = !!s.auto_tempo;
    $("setRemindLoop").checked = s.remind_loop !== false;
    $("setRemindCut").checked = s.remind_cut !== false;
    $("setCareful").checked = !!s.careful;
    $("setKitAuto").checked = !!s.kit_auto_load;
    $("setGuideArrow").checked = s.guide_arrow !== false;
    $("setListenAfter").checked = s.listen_after !== false;
    $("setQuality").checked = s.quality !== "fast";
    $("setAutoMixer").checked = s.auto_mixer !== false;
  }
  $("events").replaceChildren(...session.events.slice(-120).reverse().map((e) => h("li", { class: e.level }, h("time", {}, e.time), e.text)));
}
$("setListenAfter").addEventListener("change", async () => { await api("/api/settings", { listen_after: $("setListenAfter").checked }); await refreshSession(); });
$("setGuideArrow").addEventListener("change", async () => { await api("/api/settings", { guide_arrow: $("setGuideArrow").checked }); await refreshSession(); if (!$("setGuideArrow").checked) hideReadGuide(); });
$("setKitAuto").addEventListener("change", async () => { await api("/api/settings", { kit_auto_load: $("setKitAuto").checked }); await refreshSession(); });
$("setCareful").addEventListener("change", async () => { await api("/api/settings", { careful: $("setCareful").checked }); await refreshSession(); });
$("setQuality").addEventListener("change", async () => { await api("/api/settings", { quality: $("setQuality").checked ? "best" : "fast" }); await refreshSession(); });
$("setAutoMixer").addEventListener("change", async () => { await api("/api/settings", { auto_mixer: $("setAutoMixer").checked }); await refreshSession(); });
for (const id of ["setRemindLoop", "setRemindCut"]) {
  $(id).addEventListener("change", async () => {
    await api("/api/settings", { remind_loop: $("setRemindLoop").checked, remind_cut: $("setRemindCut").checked });
    await refreshSession(); refreshPrep();
  });
}
// Tempo, key, bars and genre are set from the Studio pills; Settings only keeps the options.
$("setAutoTempo").addEventListener("change", async () => { await api("/api/settings", { auto_tempo: $("setAutoTempo").checked }); refreshSession(); });
$("repairBridge").addEventListener("click", async () => { const r = await withPending(() => api("/api/repair-bridge", {}), "Reinstalling…"); if (r) toast("FL helpers are up to date ✓", "ok"); });
$("openExports").addEventListener("click", () => api("/api/open-folder", { which: "exports" }));
$("openLogs").addEventListener("click", () => api("/api/open-folder", { which: "logs" }));
$("rerunSetup").addEventListener("click", async () => { await api("/api/settings", { onboarded: false }); await refreshSession(); showPage("setup"); });
$("clearChat").addEventListener("click", async () => {
  if (!confirm("Clear the conversation? Parts already in FL stay in Tracks.")) return;
  await api("/api/clear-chat", {}); refreshSession();
});

// ---------- render loop ----------
const lastSig = {};
function changed(name, data) { const sig = JSON.stringify(data); if (lastSig[name] === sig) return false; lastSig[name] = sig; return true; }
function render() {
  if (!session) return;
  setBusy();
  const live = [pending > 0, status && status.fl_running, status && (status.controller || {}).connected, status && scriptsOk(status),
    status && ((status.controller || {}).channels || []).map((c) => c.name).join("|")];
  if (page === "studio") {
    if (changed("chat", [session.messages, session.proposals, session.parts, live])) renderChat();
    if (changed("chips", [session.messages.length, Object.keys(session.parts), session.settings.genre, pending > 0])) renderChips();
    if (changed("composer", [attached, genreChip, session.references && Object.keys(session.references), session.settings.genre, Object.keys(genreInfo).length])) { renderAttachment(); renderModeChip(); }
    if (changed("pills", [session.settings, status && status.controller, Object.keys(genreInfo).length])) renderPills();
    if (changed("prep", [prep, session.settings.remind_loop, session.settings.remind_cut])) renderPrepBanner();
    if (changed("rackbase", [rackOpen, session.messages.length > 0])) { renderRack(); if (rackWanted()) refreshRack(); }
  }
  if (page === "tracks" && changed("tracks", [session.parts, pending > 0, session.arrangement, session.settings.locked_parts, beatRackSig()])) { renderTracks(); renderBeat(); }
  if (page === "sounds" && changed("sounds", [libState, kitState, status && (status.controller || {}).channels])) renderSounds();
  if (page === "studio" && changed("hero", [session.messages.length > 0, session.settings.genre, genreChip, Object.keys(genreInfo).length, session.parts, session.project])) renderHero();
  if (page === "setup") renderSetup();
  if (page === "help" && changed("about", [session.app])) renderAbout();
  if (page === "settings" && changed("settings", [session.settings, session.events.length, status && status.providers])) renderSettings();
  if (changed("theme", [session.settings.theme])) applyTheme(session.settings.theme);
}
function forceRender() { for (const k of Object.keys(lastSig)) delete lastSig[k]; render(); }
function fillKeySelects() {
}

(async function start() {
  fillKeySelects();
  try { genreInfo = await api("/api/genres", {}); } catch (_) {}
  await Promise.all([refreshSession(), refreshStatus()]);
  refreshPrep();
  if (session) { rackOpen = session.settings.rack_open !== false; applyTheme(session.settings.theme); }
  if (session && !session.settings.onboarded) showPage("setup"); else forceRender();
  setInterval(refreshStatus, 5000);
  setInterval(() => { if (!pending && page !== "settings") refreshSession(); }, 3000);
  setInterval(() => { if (page === "setup") refreshSetup(); }, 3000);
  setInterval(refreshPrep, 15000);
  applyRackVisibility();
  setInterval(refreshRack, 2000);
})();

// ---------- about (beta) ----------
// Fill in the feedback address before release. Until then the link opens a mail with the subject only.
const LICENSE_TEXT = [
  "Veloura Beta is beta software, provided as is. It may have bugs. Back up your projects.",
  "You must be 18 or older to use Veloura.",
  "Veloura is free during the beta. It uses the AI you connect (ChatGPT, Claude or Gemini) and you pay that provider directly under their terms. Veloura never charges you.",
  "FL Studio is a trademark of Image-Line. Veloura is not made by or affiliated with Image-Line, OpenAI, Anthropic or Google.",
];
const PRIVACY_TEXT = [
  "Veloura runs on your Mac. Valenti Labs has no Veloura servers and collects no analytics.",
  "Your projects, chats, settings and sound library are stored on this Mac, in ~/Library/Application Support/Veloura.",
  "API keys and your ChatGPT sign-in are kept in your Mac's Keychain. Veloura never sees your ChatGPT password.",
  "When you ask for music, Veloura sends your request and what it needs about your project (tempo, key, channel names, notes) to the AI you chose. That provider's privacy policy applies.",
  "Veloura reads FL Studio's window and controls FL only to write the parts you ask for.",
  "Feedback you send from Veloura (your message, an optional reply email, and the app and macOS versions) is delivered through Formspree.",
  "Veloura checks GitHub once per launch for a newer version. Nothing about you or your projects is sent.",
];
function openTextPanel(title, lines) {
  const body = $("modalBody"), dlg = $("modal");
  body.replaceChildren(h("h2", {}, title), ...lines.map((t) => h("p", {}, t)),
    h("div", { class: "row-btns end" }, h("button", { class: "btn small primary", onclick: () => dlg.close() }, "Close")));
  dlg.showModal();
}
// Feedback goes to Valenti Labs through the service (veloura/feedback.py): only the message, an optional reply email,
// and the app and macOS versions. On failure the typed text stays so nothing is lost.
const feedbackDraft = { message: "", email: "" };
function openFeedback() {
  const body = $("modalBody"), dlg = $("modal");
  const msg = h("textarea", { rows: 6, placeholder: "What worked, what didn't, what you'd like next" });
  const mail = h("input", { type: "email", placeholder: "you@example.com" });
  msg.value = feedbackDraft.message; mail.value = feedbackDraft.email;
  const note = h("p", { class: "muted" }, "Sends your message and the Veloura and macOS versions. Nothing else.");
  const send = h("button", { class: "btn small primary" }, "Send");
  msg.addEventListener("input", () => { feedbackDraft.message = msg.value; });
  mail.addEventListener("input", () => { feedbackDraft.email = mail.value; });
  send.addEventListener("click", async () => {
    if (!msg.value.trim()) { note.textContent = "Write a message first."; note.className = "err"; return; }
    send.disabled = true; send.textContent = "Sending...";
    try {
      await api("/api/feedback", { message: msg.value, email: mail.value });
      feedbackDraft.message = ""; feedbackDraft.email = "";
      dlg.close(); toast("Thanks! Your feedback was sent.");
    } catch (e) {
      note.textContent = e.message; note.className = "err";
      send.disabled = false; send.textContent = "Send";
    }
  });
  body.replaceChildren(h("h2", {}, "Send feedback"),
    h("label", { class: "field" }, "Message", msg),
    h("label", { class: "field" }, "Your email, if you want a reply", mail),
    note,
    h("div", { class: "row-btns end" }, h("button", { class: "btn small", onclick: () => dlg.close() }, "Cancel"), send));
  if (!dlg.open) dlg.showModal();
  msg.focus();
}

function renderAbout() {
  const app = (session && session.app) || {};
  $("aboutCard").replaceChildren(
    h("div", { class: "about-head" }, h("span", { class: "logo", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")),
      h("div", {}, h("h3", {}, "Veloura ", h("span", { class: "beta-tag" }, "Beta")),
        h("small", {}, `Version ${app.version || "0.9.1"}${app.dev_mode ? " · developer mode" : ""} · Valenti Labs`))),
    h("p", { class: "muted" }, "Beta software, provided as is. It may have bugs. Back up your projects. 18+. You pay your AI provider directly."),
    h("div", { class: "row-btns" },
      h("button", { class: "btn small primary", onclick: openFeedback }, "Send feedback"),
      h("button", { class: "btn small", onclick: () => openTextPanel("License", LICENSE_TEXT) }, "License"),
      h("button", { class: "btn small", onclick: () => openTextPanel("Privacy", PRIVACY_TEXT) }, "Privacy")));
}
$("brandBtn").addEventListener("click", () => { showPage("help"); renderAbout(); });


// ---------- composer placeholder: short lines that rotate (with a gentle fade) while the box is empty ----------
(function rotatePlaceholder() {
  const LINES = ["What are we making tonight?", "Hum it in words.", "Start with a vibe.", "One idea. One beat.", "Make it hit.",
    "Dark, bouncy, or dreamy?", "Load a sound and tell it what to play."];
  const box = $("input");
  if (!box) return;
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let i = 0;
  setInterval(() => {
    if (box.value || document.hidden || !$("page-studio").classList.contains("fresh")) return;
    i = (i + 1) % LINES.length;
    if (calm) { box.placeholder = LINES[i]; return; }
    box.classList.add("ph-fade");
    setTimeout(() => { box.placeholder = LINES[i]; box.classList.remove("ph-fade"); }, 350);
  }, 8000);
})();
