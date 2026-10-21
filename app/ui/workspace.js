// Veloura UI, part 2: Studio hero, working animation, proposal extras, Beat Workspace, Sounds.
// Uses the helpers and state from app.js (h, svg, api, toast, session, status, withPending, ...).
"use strict";

const put = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
const GROUP_OF = { melody: "melody", chords: "melody", other: "other", bass: "bass", drums: "drums" };
const GROUP_META = {
  melody: { title: "Melody", color: "var(--melody)", icon: "melody" },
  drums: { title: "Drums", color: "var(--drum)", icon: "drums" },
  bass: { title: "Bass", color: "var(--bass)", icon: "bass" },
  other: { title: "Other layers", color: "var(--other)", icon: "other" },
};
// Fresh Start tiles: 8 genres in two rows of 4 (every other genre still works by typing it). Flat, blurred colour
// washes, one mood per genre: [base, glow 1, glow 2].
const TILE_GENRES = ["trap", "drill", "boom bap", "r&b", "rage", "plugg", "melodic trap", "cloud rap"];
const TILE_LOOK = {   // retinted for Veloura's palette: warm, earthy, still one mood per genre
  trap: ["#1A1418", "#8E3B3B", "#4A2E46"],            // ember red / plum haze
  drill: ["#13161E", "#4F6684", "#8C93A6"],           // cold mineral blue / slate
  "boom bap": ["#1C150E", "#8A5F3A", "#C9A45C"],      // bronze / antique gold vinyl
  "r&b": ["#1C1418", "#C98A86", "#8E7BB3"],           // warm rose / lavender
  rage: ["#17121A", "#A24D6E", "#8E9461"],            // berry / olive
  plugg: ["#1A1720", "#E4A8B8", "#98A6E6"],           // blush / periwinkle
  "melodic trap": ["#12191A", "#5F9A8E", "#A898D0"],  // eucalyptus / lavender
  "cloud rap": ["#161A22", "#E8E1D6", "#8FB3D6"],     // ivory mist / mineral blue
};
const FEEL = [["complexity", "Simple", "Complex"], ["variation", "Repetitive", "Varied"], ["fullness", "Sparse", "Full"],
  ["angular", "Smooth", "Angular"], ["atmosphere", "Melodic", "Atmospheric"], ["experimental", "Familiar", "Experimental"]];
const FEEL_DEFAULT = { complexity: 50, variation: 50, fullness: 50, angular: 35, atmosphere: 40, experimental: 20 };

// ---------------------------------------------------------------- projects + connection
function renderConnBanner() {
  const b = $("connBanner"), hint = status && status.connection_hint;
  if (!hint) { b.hidden = true; return; }
  b.hidden = false;
  b.className = "banner conn-banner " + (hint.code === "fl_closed" ? "soft" : "");
  const btn = hint.action === "restart_fl" ? h("button", { class: "btn small primary glow", onclick: async () => {
      if (!confirm("Veloura will save your project (Cmd+S), close FL Studio and reopen the same project. Continue?")) return;
      const r = await withPending(() => api("/api/restart-fl", {}), "Restarting FL Studio…"); if (r && r.ok) toast("FL is reopening. It will connect by itself.", "ok"); } }, "Restart FL for me")
    : hint.action === "open_fl" ? h("button", { class: "btn small primary", onclick: () => api("/api/open-fl", {}) }, "Open FL Studio")
    : hint.action === "focus_fl" ? h("button", { class: "btn small primary", onclick: () => api("/api/focus-fl", {}) }, "Show FL")
    : h("button", { class: "btn small", onclick: () => showPage("setup") }, "Open Setup");
  put(b, h("div", {}, h("b", {}, hint.code === "fl_first" ? "Open Veloura before FL Studio" : hint.code === "fl_closed" ? "FL Studio is closed"
      : hint.code === "fl_busy" ? "FL is blocked by an open window" : "FL isn't connected"),
    h("span", {}, hint.text),
    hint.code === "fl_closed" ? null : h("details", { class: "reconnect-details" }, h("summary", {}, "How to reconnect"), reconnectList())), btn);
}
$("projectChip").addEventListener("click", openProjects);
async function openProjects() {
  let list = { projects: [] };
  try { list = await api("/api/projects", {}); } catch (_) {}
  const body = $("modalBody"), dlg = $("modal");
  const nameIn = h("input", { placeholder: "New project name", maxlength: 60 });
  const create = async () => {
    const name = nameIn.value.trim(); if (!name) { nameIn.focus(); return; }
    dlg.close();
    const r = await withPending(() => api("/api/new-project", { name }), "Creating your project in FL…");
    if (r && r.ok) toast(`“${name}” is opening in FL (from ${r.from}). Veloura switches to it by itself.`, "ok");
  };
  nameIn.addEventListener("keydown", (e) => { if (e.key === "Enter") create(); });
  put(body, h("h2", {}, "Projects"),
    h("p", { class: "muted" }, "Veloura follows whatever project is open in FL. Each project keeps its own chat, parts and history."),
    h("div", { class: "proj-new" }, nameIn, h("button", { class: "btn primary small", onclick: create }, "New project in FL")),
    h("small", { class: "muted" }, list.has_starter ? "New projects start from your starter project." : "New projects start from FL's Empty template. Tip: set up your channels once and use “Make this my starter”."),
    h("div", { class: "proj-list big" }, list.projects.map((p) => h("div", { class: "proj" + (p.name === list.current ? " cur" : "") },
      h("div", {}, h("b", {}, p.name), h("small", {}, `${p.messages} messages · ${p.parts} parts · ${p.updated}`)),
      p.name === list.current ? h("span", { class: "rp-badge" }, "open in FL")
        : h("button", { class: "icon-btn", title: "Delete this project's chat and history from Veloura (the FL file isn't touched)", onclick: async () => {
            if (!confirm(`Delete Veloura's chat and history for “${p.name}”? Your FL project file stays.`)) return;
            try { await api("/api/delete-project", { name: p.name }); openProjects(); } catch (err) { toast(err.message, "err"); } } },
          svg(["M5 7h14", "M9 7V4h6v3", "M7 7l1 13h8l1-13"]))))),
    h("div", { class: "row-btns" },
      h("button", { class: "btn small", onclick: async () => { dlg.close(); if (!confirm(`Start a fresh conversation for “${list.current}”? The old chat is archived; nothing in FL changes.`)) return; await api("/api/start-fresh", {}); seenMsgs = null; await refreshSession(); forceRender(); toast("Fresh start ✓", "ok"); } }, "Start fresh"),
      h("button", { class: "btn small", onclick: async () => { const r = await api("/api/save-starter", {}).catch((e) => toast(e.message, "err")); if (r && r.ok) toast("New projects will start from this one ✓", "ok"); } }, "Make this my starter"),
      h("button", { class: "btn small danger", onclick: () => { dlg.close(); undoEverything(); } }, "Undo everything Veloura did"),
      h("span", { class: "spacer" }), h("button", { class: "btn small", onclick: () => dlg.close() }, "Close")));
  dlg.showModal();
  nameIn.focus();
}
async function undoEverything() {
  let plan;
  try { plan = (await api("/api/undo-all", {})).plan; } catch (e) { toast(e.message, "err"); return; }
  if (!plan.length) { toast("Veloura hasn't changed anything in this project."); return; }
  const body = $("modalBody"), dlg = $("modal");
  put(body, h("h2", {}, "Put the project back"), h("p", { class: "muted" }, "Veloura takes out only what it added. Your own notes, steps and sounds stay."),
    h("ul", { class: "undo-list" }, plan.map((i) => h("li", {}, i.label))),
    h("div", { class: "row-btns end" }, h("button", { class: "btn small", onclick: () => dlg.close() }, "Cancel"),
      h("button", { class: "btn small danger", onclick: async () => {
        dlg.close();
        const r = await withPending(() => api("/api/undo-all", { confirm: true }), "Undoing Veloura's changes…");
        if (r) toast(r.ok ? "Back to how it was ✓" : `${r.results.filter((x) => !x.ok).length} item(s) couldn't be undone. See Settings ▸ Activity.`, r.ok ? "ok" : "err");
      } }, `Undo ${plan.length} change${plan.length === 1 ? "" : "s"}`)));
  dlg.showModal();
}

// ---------------------------------------------------------------- Studio hero
// The greeting: "Make something." most of the time, now and then another short line. Picked once per launch and
// again when a project starts fresh, so it changes between sessions but never while you're looking at it.
const GREETINGS = [["Make something.", 10], ["What's the vibe?", 2], ["Let's cook.", 2], ["Start with a feeling.", 1],
  ["Make it hit.", 1], ["Say it in sound.", 1], ["One idea. One beat.", 1]];
const LATE_GREETINGS = [["Night shift.", 1], ["Late-night ideas.", 1]];
function pickGreeting() {
  const hr = new Date().getHours(), pool = GREETINGS.concat(hr < 5 || hr >= 23 ? LATE_GREETINGS : []);
  let r = Math.random() * pool.reduce((t, [, w]) => t + w, 0);
  for (const [g, w] of pool) { if ((r -= w) <= 0) return g; }
  return pool[0][0];
}
let greeting = pickGreeting(), greetedProject = null;
// The small line above the headline: time of day, the day, whether this person has made beats before.
function heroEyebrow(projects) {
  const d = new Date(), hr = d.getHours(), day = d.toLocaleDateString("en-US", { weekday: "long" }).toLowerCase();
  const made = (projects || []).filter((p) => p.parts > 0);
  const lines = [];
  if (!made.length) lines.push("your first beat starts here", "let's create...");
  else {
    lines.push("let's create...", "welcome back");
    const last = made.slice().sort((a, b) => (b.updated || "").localeCompare(a.updated || ""))[0];
    if (last && last.name !== session.project) lines.push(`last time: ${last.name}`);
  }
  lines.push(hr < 5 ? "late-night session" : hr < 12 ? "morning session" : hr < 17 ? "afternoon session" : hr < 21 ? "evening session" : "night session");
  if (["friday", "saturday"].includes(day) && hr >= 18) lines.push(`${day} night session`);
  else if (hr >= 9 && hr < 18 && ["saturday", "sunday"].includes(day)) lines.push(`${day} session`);
  return "VELOURA · " + lines[heroEyebrow.seed % lines.length];
}
heroEyebrow.seed = Math.floor(Math.random() * 1000);
let projectsCache = null, projectsAt = 0;
async function loadProjects(force) {
  if (!force && projectsCache && Date.now() - projectsAt < 15000) return projectsCache;
  try { projectsCache = await api("/api/projects", {}); projectsAt = Date.now(); } catch (_) {}
  return projectsCache || { projects: [] };
}
// Hero starter cards, genre chips and recent beats, shown only before the first message in a project.
const HERO_GENRES = ["trap", "plugg", "rage", "jerk", "drill", "melodic trap", "cloud rap", "boom bap", "r&b", "detroit", "pop"];
function renderHero() {
  const fresh = !session.messages.length;
  $("heroExtra").hidden = !fresh;
  if (fresh && greetedProject !== null && greetedProject !== session.project) { greeting = pickGreeting(); heroEyebrow.seed++; }
  greetedProject = session.project;
  $("heroGreeting").textContent = greeting;
  const names = Object.keys(session.parts), hasParts = names.length > 0;
  const card = (title, sub, fn) => h("button", { class: "qcard", type: "button", onclick: fn }, h("b", {}, title), h("small", {}, sub));
  put($("quickCards"),
    card("Make a beat", "From an idea", () => { genreChip = false; renderModeChip(); $("input").focus(); }),
    card("Build on a sample", "Drop in a loop", () => pickFile("sample")),
    card("Use a reference", "A song you love", () => pickFile("inspiration")),
    card("Keep going", hasParts ? `${session.project || "This beat"} · ${names.length} part${names.length === 1 ? "" : "s"}` : "Nothing yet",
      () => hasParts ? send("Continue this beat: add the layer it needs most, and keep everything else.") : toast("Make a beat first.")));
  const cur = session.settings.genre;
  put($("genreTiles"), ...HERO_GENRES.filter((g) => genreInfo[g] || !Object.keys(genreInfo).length).map((g) => {
    const info = genreInfo[g] || {};
    return h("button", { class: "gchip" + (g === cur && genreChip ? " sel" : ""), type: "button", title: info.tempo_range ? `${info.tempo_range[0]}–${info.tempo_range[1]} BPM` : "",
      onclick: async () => { await api("/api/settings", { genre: g, ...(session.settings.tempo_auto && info.tempo_bpm ? { tempo_bpm: info.tempo_bpm } : {}) }); genreChip = true; await refreshSession(); renderModeChip(); renderPills(); renderHero(); renderChips(); $("input").focus(); } },
      info.label || g);
  }));
  if (fresh) loadProjects().then((list) => { $("heroEyebrow").textContent = heroEyebrow(list.projects); renderRecent(list); });
}
function whenLabel(stamp) {
  const t = new Date((stamp || "").replace(" ", "T"));
  if (isNaN(t)) return "";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.floor((today - new Date(t.getFullYear(), t.getMonth(), t.getDate())) / 864e5);
  if (days <= 0) return t.getHours() >= 18 ? "Tonight" : "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return t.toLocaleDateString("en-US", { weekday: "long" });
  return t.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
function renderRecent(list) {
  const items = (list.projects || []).filter((p) => p.parts > 0 || p.messages > 0)
    .sort((a, b) => (b.updated || "").localeCompare(a.updated || "")).slice(0, 3);
  $("recentBeats").previousElementSibling.hidden = !items.length;
  put($("recentBeats"), items.map((p) => {
    const facts = [p.genre, p.tempo ? Math.round(p.tempo) : null, p.key, p.parts ? `${p.parts} part${p.parts === 1 ? "" : "s"}` : "no parts yet"].filter(Boolean).join(" · ");
    return h("button", { class: "rcard" + (p.name === list.current ? " cur" : ""), type: "button", title: p.name === list.current ? "Open in FL now" : `Open “${p.name}” in FL to keep going`,
      onclick: () => {
        if (p.name === list.current) { $("input").focus(); return; }
        toast(`Open “${p.name}” in FL Studio. Veloura follows the project that's open.`);
      } },
      notesStrip(p.preview, ROLE_COLOR[p.preview_role] || "var(--accent)"),
      h("span", { class: "rc-top" }, h("b", {}, p.name), h("small", {}, whenLabel(p.updated))),
      h("small", { class: "rc-facts" }, facts));
  }));
}
$("allProjects").addEventListener("click", () => openProjects());
// A tiny piano-roll strip from [start, length, pitch] notes (beats), or drum-style rows from a step list.
function notesStrip(notes, color, cls) {
  const box = h("span", { class: "nstrip" + (cls ? " " + cls : "") });
  if (!notes || !notes.length) return box;
  const end = Math.max(4, ...notes.map(([st, len]) => st + len)), lo = Math.min(...notes.map((n) => n[2])), hi = Math.max(...notes.map((n) => n[2]));
  const rows = Math.max(4, hi - lo + 1);
  for (const [st, len, p] of notes) box.append(h("i", { style: `left:${(st / end * 100).toFixed(2)}%;width:${Math.max(.8, len / end * 100).toFixed(2)}%;top:${((hi - p) / rows * 100).toFixed(2)}%;height:${(100 / rows).toFixed(2)}%;--c:${color}` }));
  return box;
}
const planNotes = (plan) => ((plan && plan.notes) || []).map((n) => [n.start, n.length, n.pitch]);
// Rows for a drum part: each lane on its own row, like the mock-up's step strips.
function drumStrip(plans, color) {
  const lanes = plans.filter((p) => p && p.notes && p.notes.length);
  const notes = [];
  lanes.forEach((pl, i) => { for (const n of pl.notes) notes.push([n.start, Math.max(.2, Math.min(n.length, .25)), lanes.length - 1 - i]); });
  return notesStrip(notes, color, "drums");
}

// ---------------------------------------------------------------- suggestions
// Short ideas for an empty Studio. They rotate between sessions and lean towards the genres this person picks.
const IDEAS = {
  trap: [["Hard trap, sliding 808", "Hard trap beat with a sliding 808 and crisp hats."], ["Dark trap bells", "Dark trap beat with eerie bells and heavy 808."]],
  plugg: [["Dark plugg, bouncy drums", "Dark plugg beat with bouncy drums and a glassy lead."], ["Dreamy plugg chords", "Dreamy plugg beat with soft chords and a sliding 808."]],
  rage: [["Rage with my whole kit", "Rage beat using my whole kit, loud synth lead."], ["Rage synth, fast hats", "Rage beat with a big synth lead and fast hats."]],
  jerk: [["Bouncy jerk drums", "Jerk beat with bouncy drums and a playful lead."]],
  drill: [["Sliding drill 808", "Drill beat with sliding 808s and dark piano."], ["Cold drill strings", "UK drill beat with cold strings and gliding 808."]],
  "melodic trap": [["Sad piano and 808", "Sad melodic trap with piano and 808."], ["Guitar melodic trap", "Melodic trap beat with an emotional guitar loop feel."]],
  "cloud rap": [["Hazy cloud pads", "Cloud rap beat with hazy pads and soft drums."]],
  "boom bap": [["Dusty boom bap", "Dusty boom bap beat with jazzy keys."]],
  "r&b": [["Soft R&B chords", "Slow R&B beat with warm chords and a smooth bassline."]],
  detroit: [["Detroit bounce", "Detroit beat with a bouncy, off-beat bassline."]],
  pop: [["Bright pop drums", "Bright pop beat with clean drums and catchy chords."]],
};
const IDEAS_ANY = [["Sad piano and 808", "Sad melodic trap with piano and 808."], ["Dark plugg, bouncy drums", "Dark plugg beat with bouncy drums and a glassy lead."],
  ["Rage with my whole kit", "Rage beat using my whole kit, loud synth lead."], ["Something dark at 140", "Something dark at 140 BPM. Surprise me."],
  ["Soft R&B chords", "Slow R&B beat with warm chords and a smooth bassline."], ["Hard drill drums", "Drill beat with hard drums and sliding 808s."]];
const ideaSeed = Math.floor(Math.random() * 1000);
function startIdeas() {
  const mine = IDEAS[session.settings.genre] || [];
  const seen = new Set(), out = [];
  const rot = (list, k) => list.map((_, i) => list[(i + k) % list.length]);
  for (const it of [...rot(mine, ideaSeed), ...rot(IDEAS_ANY, ideaSeed)]) { if (!seen.has(it[0]) && out.length < 3) { seen.add(it[0]); out.push(it); } }
  return out;
}
// After a reply: four follow-ups that fit the beat on screen.
function followUps() {
  const props = Object.values(session.proposals || {}).filter((p) => p.parts && p.parts.length);
  const last = props[props.length - 1], parts = last ? last.parts : [];
  const has = (re) => parts.some((p) => re.test(p.name + " " + (p.role || "")));
  const drums = parts.filter((p) => p.role === "drums");
  const out = [["Darker", "Make it darker. Keep the groove."], ["Less busy", "Make it less busy: give each part more space."]];
  if (drums.length && !drums.some((p) => /hat/i.test(p.name))) out.push(["Add hats", "Add a hi-hat pattern that fits the groove. Keep everything else."]);
  else if (!drums.length) out.push(["Add drums", "Add drums that fit this. Keep everything else exactly as it is."]);
  if (has(/808|bass/)) out.push(["New 808 pattern", "Write a new 808 pattern for the same chords. Keep everything else."]);
  else out.push(["Add an 808", "Add an 808 that follows the chords. Keep everything else."]);
  if (out.length < 4) out.push(has(/lead|melody|keys|chords/) ? ["Try a new melody", "Write a different melody on the same chords. Keep the drums and 808."]
    : ["Add a melody", "Add a melody that fits. Keep everything else exactly as it is."]);
  return out.slice(0, 4);
}
let feelTimer = null;
function saveFeel(feel) {
  clearTimeout(feelTimer);
  feelTimer = setTimeout(async () => { await api("/api/feel", { feel }); session.settings.feel = feel; }, 350);
}

// The old "current beat" strip above the composer: its job moved to the Beat page and the follow-up chips.
function renderBeatStrip() { $("beatStrip").hidden = true; }
async function improveBeat() {
  showPage("studio");
  await withPending(() => api("/api/improve", {}), "Listening through the notes…");
  $("chatScroll").scrollTop = $("chatScroll").scrollHeight;
}

// ---------------------------------------------------------------- composing: what Veloura is doing right now
// A quiet line in the chat: four bars breathing, the step in shimmering text, how long is left, the stages so far and a
// thin progress line. FL actions show the same line with their own steps.
const WORK_LINES = {
  compose: ["Choosing a key that fits the mood", "Sketching the chord progression", "Writing a hook you can hum",
    "Answering the hook at the end of the phrase", "Giving each layer one job", "Picking sounds from your instruments",
    "Placing the 808 under the chords", "Choosing the drum groove", "Leaving space for a vocal", "Adding movement every four bars"],
  apply: ["Opening the right Piano Roll", "Writing the notes", "Reading them back to check"],
};
const COMPOSE_STAGES = [["Idea", 0], ["Drums", 22], ["Melody", 42], ["808", 62], ["Check", 82]];
const APPLY_STAGES = [["Open", 0], ["Write", 34], ["Check", 70]];
let workTimer = null, lastStage = "";
function startWorking() {
  if (workTimer) return;
  workTimer = setInterval(pollProgress, 450);
  pollProgress();
  const sc = $("chatScroll"); requestAnimationFrame(() => { sc.scrollTop = sc.scrollHeight; });
}
function stopWorking() {
  clearInterval(workTimer); workTimer = null; lastStage = "";
  $("wPct").textContent = ""; $("wBar").style.width = "0%"; $("wDetail").textContent = ""; $("wStages").replaceChildren();
}
function paintStages(list, pct) {
  const idx = list.reduce((k, [, at], i) => (pct >= at ? i : k), 0);
  put($("wStages"), list.map(([t], i) => h("span", { class: "cp-st" + (i < idx ? " done" : i === idx ? " now" : "") }, h("i"), t)));
}
async function pollProgress() {
  let p;
  try { p = await api("/api/progress"); } catch (_) { return; }
  if (!p.active) {   // FL writes and quick actions without server progress: a gentle indeterminate line
    $("busy").classList.add("indeterminate");
    $("wPct").textContent = "";
    const applying = busyLabel && /Adding|Writing/.test(busyLabel);
    $("wDetail").textContent = applying ? WORK_LINES.apply[Math.floor(Date.now() / 1400) % 3] : "";
    if (applying) paintStages(APPLY_STAGES, (Date.now() / 14) % 100); else $("wStages").replaceChildren();
    return;
  }
  $("busy").classList.remove("indeterminate");
  const left = typeof p.remaining === "number" ? countdown(p.remaining) : "";
  if (p.fl_action) {   // an FL action: countdown from how long this kind of action took recently
    const lines = WORK_LINES.apply, k = Math.min(lines.length - 1, Math.floor(p.pct / (96 / lines.length)));
    const line = p.detail || lines[k];   // e.g. "Downloading sounds from iCloud (2 of 7)"
    if (line !== lastStage) { $("wDetail").textContent = line; lastStage = line; }
    $("wPct").textContent = left;
    $("wBar").style.width = p.pct + "%";
    paintStages(APPLY_STAGES, p.pct);
    return;
  }
  if (!cancelRequested) $("busyText").textContent = p.stage;
  let detail = p.detail || "";
  if (p.estimated) {   // the AI works in one go: show what a producer does at this point, in order
    const lines = WORK_LINES.compose, k = Math.min(lines.length - 1, Math.floor((p.pct - 12) / (76 / lines.length)));
    detail = lines[Math.max(0, k)] + "…";
  }
  if (detail !== lastStage) { $("wDetail").textContent = detail; $("wDetail").classList.remove("swap"); void $("wDetail").offsetWidth; $("wDetail").classList.add("swap"); lastStage = detail; }
  $("wPct").textContent = left;
  $("wBar").style.width = p.pct + "%";
  paintStages(COMPOSE_STAGES, p.pct);
}
// "≈ 3 s left" while within the estimate; "almost there" once past it (never a negative or frozen 0).
function countdown(sec) {
  if (sec <= 0.05) return "almost there";
  return sec < 10 ? `about ${Math.max(1, Math.round(sec))}s` : `about ${Math.ceil(sec)}s`;
}
// A clear sign that FL confirmed the change (or didn't, with the short reason).
function landed(ok, text) {
  const el = $("landed");
  el.className = "landed " + (ok ? "ok" : "fail");
  put(el, h("span", { class: "landed-icon" }, ok ? svg(["M5 12.5l4.5 4.5L19 7.5"]) : svg(["M7 7l10 10", "M17 7L7 17"])),
    h("span", { class: "landed-text" }, text));
  el.hidden = false;
  void el.offsetWidth; el.classList.add("show");
  clearTimeout(landed.t);
  landed.t = setTimeout(() => { el.classList.remove("show"); setTimeout(() => { el.hidden = true; }, 300); }, ok ? 1800 : 4500);
}
function shortReason(msg) {
  const first = String(msg || "FL didn't confirm the change.").split(/(?<=[.!?])\s/)[0];
  return first.length > 110 ? first.slice(0, 107) + "…" : first;
}
// hook into app.js's busy indicator
const _setBusy = setBusy;
setBusy = function (label) {   // eslint-disable-line no-func-assign
  _setBusy(label);
  if (!$("busy").hidden) startWorking(); else stopWorking();
};

// ---------------------------------------------------------------- a reply as ordered steps
const MELODY_ORDER = { chords: 0, pad: 1, lead: 2, counter: 3, arp: 4, double: 5, bell: 6, harmony: 7 };
function stepBox(n, title, sub, done, ...children) {
  return h("section", { class: "rstep" + (done ? " done" : "") },
    h("div", { class: "rstep-head" }, h("span", { class: "rstep-n" }, done ? "✓" : String(n)), h("b", {}, title), sub ? h("small", {}, sub) : null),
    h("div", { class: "rstep-body" }, children));
}
function orderedProposal(prop, m) {
  const idx = prop.parts.map((p, i) => i);
  const drums = idx.filter((i) => prop.parts[i].role === "drums");
  const bass = idx.filter((i) => prop.parts[i].role === "bass");
  const melodic = idx.filter((i) => !["drums", "bass"].includes(prop.parts[i].role))
    .sort((a, b) => (MELODY_ORDER[prop.parts[a].purpose] ?? 9) - (MELODY_ORDER[prop.parts[b].purpose] ?? 9));
  const applied = (list) => list.length && list.every((i) => prop.parts[i].status === "applied");
  const steps = [];
  let n = 1;
  if (prop.kit) steps.push(stepBox(n++, "Load your kit", "Your drum sounds go onto their channels", !!prop.kit_loaded, kitCard(prop.kit, prop.id)));
  const inst = prop.instruments || [];
  if (inst.length) {
    const missing = inst.filter((x) => !x.channel);
    steps.push(stepBox(n++, "Instruments", missing.length ? `Add ${missing.length} instrument channel${missing.length === 1 ? "" : "s"}, or let Veloura use a spare one`
      : `All ${inst.length} instruments have a channel`, !missing.length, instrumentList(prop, inst)));
  }
  if (drums.length) steps.push(stepBox(n++, "Drums", `${drums.length} channels`, applied(drums), drumRack(prop, drums)));
  if (melodic.length) steps.push(stepBox(n++, "Chords & melody", melodic.map((i) => prop.parts[i].name).join(" · "), applied(melodic),
    melodic.map((i) => partCard(prop, prop.parts[i], i))));
  if (bass.length) steps.push(stepBox(n++, "808 & bass", "", applied(bass), bass.map((i) => partCard(prop, prop.parts[i], i))));
  if (prop.mix) steps.push(stepBox(n++, "Mix", "Levels, panning and EQ", ["applied", "partial"].includes(prop.mix.status), mixCard(prop)));
  if (prop.guidance && prop.guidance.length) steps.push(stepBox(n++, "Finishing touches", "Things to do in FL yourself", false,
    prop.guidance.map((g, i) => guideCard(g, m.proposal_id + i))));
  const open = prop.parts.filter((p) => p.status !== "applied");
  const doAll = (open.length > 1 || (prop.kit && !prop.kit_loaded) || (prop.mix && prop.mix.status === "proposed")) ? h("div", { class: "addall" },
    h("span", {}, "Veloura does each step in order: kit, drums, chords & melody, 808, then the mix."),
    h("button", { class: "btn primary small glow", disabled: pending > 0, onclick: () => doAllSteps(prop) }, "Do all steps")) : null;
  return h("div", { class: "rsteps" }, doAll, steps);
}
// ---------------------------------------------------------------- a reply's beat: one card, compact parts, one "Add all"
// The full step-by-step view (kit, instruments, mix, finishing touches) is still there behind "Show steps".
const MOODS = ["dark", "sad", "bouncy", "hard", "chill", "dreamy", "happy", "aggressive", "soft", "eerie", "moody", "bright", "hazy", "dusty", "cold", "emotional", "spacey"];
function beatTitle(prop) {
  const req = (prop.request || "").toLowerCase();
  const hit = Object.entries(genreInfo).sort((a, b) => b[0].length - a[0].length)
    .find(([k, v]) => req.includes(k) || (v.label && req.includes(v.label.toLowerCase())));
  const label = hit ? (hit[1].label || hit[0]) : ((genreInfo[session.settings.genre] || {}).label || "");
  const mood = MOODS.find((m) => new RegExp("\\b" + m + "\\b").test(req));
  const g = label && label !== label.toUpperCase() ? label.toLowerCase() : label;
  const t = mood ? `${mood} ${g}`.trim() : label ? `${g} beat` : "New beat";
  return t.charAt(0).toUpperCase() + t.slice(1);
}
function beatFacts(prop) {
  const info = prop.info || {}, plan = (prop.parts[0] || {}).plan || {};
  const tempo = info.tempo || plan.tempo_bpm, key = info.key || plan.key, bars = Math.max(...prop.parts.map((p) => (p.plan || {}).bars || 0));
  const kits = Object.values((prop.kit && prop.kit.roles) || {}).map((x) => x.kit).filter(Boolean);
  const kit = kits.sort((a, b) => kits.filter((k) => k === b).length - kits.filter((k) => k === a).length)[0];
  return [tempo ? `${Math.round(tempo)} BPM` : null, key, bars ? `${bars} bars` : null, kit ? `${kit} kit` : null].filter(Boolean).join(" · ");
}
const rcOpen = new Set(), rcClosed = new Set(), rcSteps = new Set();
function rowStatus(part) {
  const d = part.destination || {}, res = part.result;
  if (part.status === "applied") return ["ok", "In FL"];
  if (res && !res.ok) return ["bad", res.code === "not_empty" || res.code === "replace_failed" || res.code === "target_failed" ? "Nothing changed" : "Didn't go in"];
  if (d.missing) return ["warn", "Needs a channel"];
  if (session.parts[part.name]) return ["new", "New version"];
  return ["", "Ready"];
}
function resultCard(prop, m) {
  const idx = prop.parts.map((p, i) => i);
  const drums = idx.filter((i) => prop.parts[i].role === "drums");
  const others = idx.filter((i) => prop.parts[i].role !== "drums");
  const latest = Object.keys(session.proposals).pop() === prop.id;
  const rows = [];
  if (drums.length) rows.push({ key: "drums", idxs: drums });
  for (const i of others) rows.push({ key: "p" + i, idxs: [i] });
  // open by default: rows that need attention, and the first melodic part of the newest beat
  const firstMel = rows.find((r) => r.key !== "drums" && prop.parts[r.idxs[0]].role !== "bass");
  const needs = (r) => r.idxs.some((i) => { const p = prop.parts[i]; return (p.result && !p.result.ok) || ((p.destination || {}).missing && p.status !== "applied"); });
  const autoOpen = rows.find((r) => r.idxs.some((i) => prop.parts[i].result && !prop.parts[i].result.ok))
    || (latest && firstMel && !firstMel.idxs.every((i) => prop.parts[i].status === "applied") ? firstMel : rows.find(needs));
  const isOpen = (r) => {
    const k = prop.id + ":" + r.key;
    if (rcOpen.has(k)) return true;
    if (rcClosed.has(k)) return false;
    return r === autoOpen;
  };
  const toggle = (r, open) => { const k = prop.id + ":" + r.key; if (open) { rcClosed.add(k); rcOpen.delete(k); } else { rcOpen.add(k); rcClosed.delete(k); } renderChat(); };
  const open = prop.parts.filter((p) => p.status !== "applied");
  const instMissing = (prop.instruments || []).filter((x) => !x.channel);
  const steps = [prop.kit ? !!prop.kit_loaded : null, (prop.instruments || []).length ? !instMissing.length : null,
    ...prop.parts.map((p) => p.status === "applied"), prop.mix ? ["applied", "partial"].includes(prop.mix.status) : null].filter((x) => x !== null);
  const done = steps.filter(Boolean).length;
  const allIn = !open.length && (!prop.kit || prop.kit_loaded) && (!prop.mix || prop.mix.status !== "proposed");
  const foot = [prop.kit ? (prop.kit_loaded ? "Kit loaded" : "Kit not loaded yet") : null,
    (prop.instruments || []).length ? (instMissing.length ? `${instMissing.length} instrument${instMissing.length === 1 ? "" : "s"} need a channel` : "instruments ready") : null].filter(Boolean).join(" and ");
  const tips = (prop.guidance || []).length;
  const stepsOpen = rcSteps.has(prop.id);
  return h("div", { class: "rcard-beat" },
    h("div", { class: "rb-head" },
      h("div", { class: "rb-title" }, h("b", {}, beatTitle(prop)), h("small", {}, beatFacts(prop))),
      h("button", { class: "btn quiet small", type: "button", onclick: () => saveProposalMidi(prop) }, "Save MIDI"),
      allIn ? h("span", { class: "rb-allin" }, svg(["M5 12.5l4.5 4.5L19 7.5"]), "All in FL")
        : h("button", { class: "btn primary rb-add", type: "button", disabled: pending > 0, onclick: () => doAllSteps(prop) }, svg(["M12 4v11", "M7 10l5 5 5-5", "M5 20h14"]), "Add all to FL Studio")),
    rows.map((r) => partRow(prop, r, isOpen(r), toggle)),
    h("div", { class: "rb-foot" }, h("i", { class: "dot " + (done === steps.length ? "ok" : instMissing.length ? "warn" : "ok") }),
      h("span", {}, [foot, `${done} of ${steps.length} steps done`, tips ? `${tips} finishing touch${tips === 1 ? "" : "es"}` : null].filter(Boolean).join(" · ")),
      h("button", { class: "link-quiet", type: "button", onclick: () => { stepsOpen ? rcSteps.delete(prop.id) : rcSteps.add(prop.id); renderChat(); } }, stepsOpen ? "Hide steps" : "Show steps")),
    stepsOpen ? h("div", { class: "rb-steps" }, orderedProposal(prop, m)) : null);
}
function partRow(prop, r, open, toggle) {
  const parts = r.idxs.map((i) => prop.parts[i]), drums = r.key === "drums", p0 = parts[0];
  const color = drums ? "var(--drum)" : (ROLE_COLOR[p0.role] || ROLE_COLOR.other);
  const applied = parts.every((p) => p.status === "applied");
  const [scls, stext] = drums
    ? (applied ? ["ok", "In FL"] : parts.some((p) => p.result && !p.result.ok) ? ["bad", "Some didn't go in"] : parts.some((p) => (p.destination || {}).missing && p.status !== "applied") ? ["warn", "Needs channels"] : parts.some((p) => p.status === "applied") ? ["ok", "Partly in FL"] : ["", "Ready"])
    : rowStatus(p0);
  const d = p0.destination || {};
  const target = drums ? parts.map((p) => (p.destination || {}).channel || p.name).join(" · ") : (d.channel || d.label || "Piano Roll");
  const title = drums ? "Drums" : p0.name;
  let btn;
  if (applied) {
    const names = parts.map((p) => p.name).filter((n) => session.parts[n]);
    btn = h("button", { class: "rr-btn quiet", type: "button", disabled: pending > 0 || !names.length, onclick: async (e) => { e.stopPropagation(); for (const n of names) await undoPart(n); } }, "Undo");
  } else {
    const todo = r.idxs.filter((i) => prop.parts[i].status !== "applied");
    const blocked = todo.every((i) => (prop.parts[i].destination || {}).missing);
    btn = h("button", { class: "rr-btn", type: "button", disabled: pending > 0 || blocked, title: blocked ? (d.fix || "Choose a channel first") : "",
      onclick: async (e) => { e.stopPropagation(); if (todo.length > 1) await addAll(prop, todo); else await applyPart(prop, todo[0]); } },
      !drums && session.parts[p0.name] ? "Swap in" : "Add to FL");
  }
  const mini = drums ? drumStrip(parts.map((p) => p.plan), color) : notesStrip(planNotes(p0.plan), color);
  const head = h("div", { class: "rr-head", role: "button", tabindex: "0", "aria-expanded": open ? "true" : "false",
    onclick: () => toggle(r, open), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(r, open); } } },
    h("i", { class: "rr-dot", style: `background:${color}` }),
    h("span", { class: "rr-name" }, h("b", {}, title), h("small", { title: target }, "→ " + target)),
    mini, h("span", { class: "rr-status " + scls }, h("i"), stext), btn,
    h("span", { class: "rr-chev" + (open ? " open" : "") }, svg(["M9 6l6 6-6 6"])));
  if (!open) return h("div", { class: "rr" + (open ? " open" : "") }, head);
  const plans = parts.map((p) => p.plan), notes = plans.reduce((t, pl) => t + ((pl && pl.notes) || []).length, 0);
  const bars = Math.max(...plans.map((pl) => (pl && pl.bars) || 0));
  const playBtn = h("button", { class: "rr-act play-pv", type: "button", onclick: (e) => previewParts(parts, e.currentTarget, prop.kit) }, h("i", { class: "tri" }), "Preview");
  let body;
  if (drums) {
    body = [h("div", { class: "rack themed" }, r.idxs.map((i) => {
      const part = prop.parts[i], dd = part.destination || {};
      return h("div", {}, h("div", { class: "rack-row" },
        h("span", { class: "rack-name" + (dd.missing ? " missing" : ""), title: dd.missing ? (dd.problem + " " + (dd.fix || "")) : (dd.label || "") }, dd.channel || part.name),
        rackSteps(part.plan), h("span", { class: "rack-status row-btns" }, partActions(prop, part, i, true))),
        part.result && !part.result.ok ? resultBox(prop, part, i, part.result) : null);
    }))];
  } else {
    const i = r.idxs[0];
    body = [pianoRoll(p0.plan, color),
      d.missing && p0.status !== "applied" && !(p0.result && !p0.result.ok) ? h("div", { class: "note-box warn" }, h("b", {}, "Needs a channel. "), `${d.problem || ""} ${d.fix || ""}`) : null,
      resultBox(prop, p0, i, p0.result)];
  }
  const varBtn = !drums ? h("button", { class: "rr-act", type: "button", disabled: !session.parts[p0.name] || pending > 0,
    title: session.parts[p0.name] ? "Write three takes on this part" : "Add it to FL first", onclick: () => tryVariations(p0.name) }, "Try a variation") : null;
  const chan = !drums ? h("label", { class: "rr-act chan" }, "Change channel", channelPicker(prop, p0, r.idxs[0], "Change channel")) : null;
  const applied1 = !drums && p0.status === "applied" ? h("button", { class: "rr-act", type: "button", disabled: pending > 0, title: "Write it again (e.g. if it didn't sound right)",
    onclick: async () => { const x = await withPending(() => api("/api/reapply", { proposal_id: prop.id, index: r.idxs[0] }), `Re-applying ${p0.name}…`); if (x && x.ok) toast(`${p0.name} re-applied ✓`, "ok"); } }, "Re-apply") : null;
  return h("div", { class: "rr open" }, head,
    h("div", { class: "rr-body" }, body,
      h("div", { class: "rr-acts" }, playBtn, varBtn, chan, applied1,
        h("button", { class: "rr-act", type: "button", onclick: async () => { for (const i of r.idxs) await exportPart({ proposal_id: prop.id, index: i }); } }, "Save MIDI"),
        h("span", { class: "spacer" }), h("small", {}, `${notes} notes · ${bars} bar${bars === 1 ? "" : "s"}`))));
}
async function saveProposalMidi(prop) {
  let directory;
  if (window.velouraNative && window.velouraNative.chooseFolder) { directory = await window.velouraNative.chooseFolder(); if (directory === null) return; }
  let last;
  for (let i = 0; i < prop.parts.length; i++) last = await api("/api/export", { proposal_id: prop.id, index: i, directory }).catch((e) => toast(e.message, "err"));
  if (last && last.path) { toast(`Saved ${prop.parts.length} MIDI file${prop.parts.length === 1 ? "" : "s"}. Drag them onto channels in FL.`, "ok"); api("/api/reveal", { path: last.path }); }
}

// ---------------------------------------------------------------- Preview: a quick sketch of the notes in the app
// A tiny Web Audio synth (not your FL sounds): enough to hear the rhythm and the line before adding it.
let pvCtx = null, pvStop = null;
function stopPreview() { if (pvStop) pvStop(); pvStop = null; }
// Drums play with the actual samples from your kit (your sound library) when Veloura picked one; melodic parts and
// lanes without a sample use the small sketch synth (FL's plugins only sound inside FL).
const pvBuffers = new Map();
const laneRole = (lane) => /kick|bd\b/.test(lane) ? "kick" : /open/.test(lane) ? "open hat" : /hat|hh|shaker|ride/.test(lane) ? "hat"
  : /clap/.test(lane) ? "clap" : /snare|rim/.test(lane) ? "snare" : /perc|tom|conga|bongo/.test(lane) ? "perc" : null;
async function kitBuffers(ctx, kit) {
  const out = {};
  await Promise.all(Object.entries((kit && kit.roles) || {}).map(async ([role, sm]) => {
    if (!sm || !sm.id || role === "808") return;
    try {
      if (!pvBuffers.has(sm.id)) {
        const res = await fetch(`/api/library/audio?id=${encodeURIComponent(sm.id)}&t=${encodeURIComponent(token)}`);
        if (!res.ok) return;
        pvBuffers.set(sm.id, await ctx.decodeAudioData(await res.arrayBuffer()));
      }
      out[role] = pvBuffers.get(sm.id);
    } catch (_) {}
  }));
  return out;
}
function previewKit() {   // the kit of the newest beat, else the kit picked on the Sounds page
  const props = Object.values(session.proposals || {});
  for (let i = props.length - 1; i >= 0; i--) if (props[i].kit && props[i].kit.roles) return props[i].kit;
  return kitState && kitState.roles ? kitState : null;
}
async function previewParts(parts, btn, kit) {
  if (btn && btn.classList.contains("on")) { stopPreview(); return; }
  stopPreview();
  try { pvCtx = pvCtx || new (window.AudioContext || window.webkitAudioContext)(); } catch (_) { toast("Preview isn't available here.", "err"); return; }
  const ctx = pvCtx;
  if (ctx.state === "suspended") { try { await ctx.resume(); } catch (_) {} }
  const samples = parts.some((p) => p.role === "drums") ? await kitBuffers(ctx, kit || previewKit()) : {};
  const master = ctx.createGain(); master.gain.value = .22; master.connect(ctx.destination);
  const tempo = ((parts[0] || {}).plan || {}).tempo_bpm || (session.settings.tempo_bpm || 140), spb = 60 / tempo, t0 = ctx.currentTime + .06;
  let end = 0;
  const noise = (() => { const b = ctx.createBuffer(1, ctx.sampleRate * .5, ctx.sampleRate), d = b.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; return b; })();
  const env = (g, at, peak, dur) => { g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(peak, at + .005); g.gain.exponentialRampToValueAtTime(.0008, at + dur); };
  for (const part of parts) {
    const plan = part.plan || {}, lane = (part.name || "").toLowerCase();
    for (const n of plan.notes || []) {
      const at = t0 + n.start * spb, vel = (n.velocity || 100) / 127, dur = Math.max(.08, n.length * spb);
      end = Math.max(end, n.start * spb + dur);
      const buf = part.role === "drums" ? samples[laneRole(lane)] : null;
      if (buf) {
        const src = ctx.createBufferSource(), g = ctx.createGain(); src.buffer = buf;
        g.gain.value = vel * 2.6; src.connect(g).connect(master); src.start(at);
        end = Math.max(end, n.start * spb + Math.min(buf.duration, 1.2));
      } else if (part.role === "drums") {
        if (/kick/.test(lane)) {
          const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.setValueAtTime(130, at); o.frequency.exponentialRampToValueAtTime(42, at + .18);
          env(g, at, vel, .3); o.connect(g).connect(master); o.start(at); o.stop(at + .32);
        } else {
          const src = ctx.createBufferSource(), f = ctx.createBiquadFilter(), g = ctx.createGain(); src.buffer = noise;
          const hat = /hat|hh|shaker|ride/.test(lane), open = /open/.test(lane);
          f.type = hat ? "highpass" : "bandpass"; f.frequency.value = hat ? 7000 : /clap/.test(lane) ? 1500 : 1900;
          env(g, at, vel * (hat ? .45 : .8), hat ? (open ? .28 : .05) : .16); src.connect(f).connect(g).connect(master); src.start(at); src.stop(at + .35);
        }
      } else {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = part.role === "bass" ? "sine" : part.role === "chords" ? "triangle" : "triangle";
        o.frequency.value = 440 * Math.pow(2, (n.pitch - 69) / 12);
        const peak = vel * (part.role === "bass" ? .9 : part.role === "chords" ? .25 : .45);
        g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(peak, at + .01); g.gain.setValueAtTime(peak, at + Math.max(.02, dur - .06)); g.gain.linearRampToValueAtTime(0, at + dur);
        o.connect(g).connect(master); o.start(at); o.stop(at + dur + .02);
      }
    }
  }
  if (btn) { btn.classList.add("on"); btn.lastChild.textContent = "Stop"; }
  const timer = setTimeout(() => stopPreview(), (end + .3) * 1000);
  pvStop = () => { clearTimeout(timer); try { master.disconnect(); } catch (_) {} if (btn) { btn.classList.remove("on"); btn.lastChild.textContent = btn.dataset.label || "Preview"; } };
}

const INST_LABEL = (i) => (i || "").replace("_synth", " synth").replace("bass_808", "808").replace("_", " ");
function instrumentList(prop, inst) {
  return h("div", { class: "inst-need" }, inst.map((x) => {
    const part = prop.parts[x.index];
    return h("div", { class: "inst-row" + (x.channel ? " ok" : "") },
      h("span", { class: "lstate" }, x.channel ? "✓" : ""),
      h("div", { class: "inst-what" }, h("b", {}, INST_LABEL(x.instrument)), h("small", {}, x.channel ? `on ${x.channel}` : `for “${x.part}” · find: ${x.tip}`)),
      channelPicker(prop, part, x.index, x.channel ? "Change…" : "It's on channel…"),
      x.channel ? null : h("button", { class: "btn small", title: "Use a spare instrument channel (FLEX first) and pick a fitting sound",
        onclick: async () => { const r = await withPending(() => api("/api/auto-instrument", { proposal_id: prop.id, index: x.index }), `Finding a ${INST_LABEL(x.instrument)} sound…`);
          if (r) toast(r.message, r.ok ? "ok" : "err"); await refreshSession(); forceRender(); } }, "Use FLEX for me"));
  }));
}
async function runListen(auto) {
  const r = await withPending(() => api("/api/listen", { seconds: 8 }), "Listening to your beat (FL plays it for a few seconds)…");
  if (!r) return;
  const body = $("modalBody"), dlg = $("modal");
  const icon = { ok: "✓", warn: "!", info: "i" };
  put(body, h("h2", {}, "Veloura listened"),
    h("p", { class: "muted" }, "FL played the loop while Veloura read every mixer meter, then checked for anything ringing after stop. (It measures levels; it can't judge tone.)"),
    h("div", { class: "listen-list" }, r.findings.map((f) => h("div", { class: "listen-row " + f.level },
      h("span", { class: "lstate" }, icon[f.level] || "•"),
      h("div", {}, h("b", {}, f.title), h("small", {}, f.detail)),
      f.fix ? h("button", { class: "btn small primary", onclick: async (e) => {
        e.currentTarget.disabled = true;
        const x = await api("/api/listen/fix", f.fix).catch((err) => toast(err.message, "err"));
        if (x && x.ok) toast("Fixed ✓ (Undo everything can reverse it)", "ok"); } }, "Fix it") : null))),
    h("div", { class: "row-btns end" }, h("button", { class: "btn small", onclick: () => runListen() }, "Listen again"),
      h("button", { class: "btn small primary", onclick: () => dlg.close() }, "Done")));
  dlg.showModal();
}
async function doAllSteps(prop) {
  const missing = (prop.instruments || []).filter((x) => !x.channel).map((x) => INST_LABEL(x.instrument));
  const autoKit = !!session.settings.kit_auto_load;
  const plan = [prop.kit && !prop.kit_loaded ? (autoKit ? "load your drum kit (FL's sound is muted while it browses)" : "put your drum kit in a folder for you to drag in") : null,
    "write the drums, then chords & melody, then the 808 (one part at a time)",
    prop.mix && prop.mix.status === "proposed" ? "apply the mix" : null,
    session.settings.listen_after !== false ? "play the beat for a few seconds to check the levels" : null].filter(Boolean);
  if (!confirm(`Veloura will ${plan.join(", then ")}.${missing.length ? `\n\nSkipped until they have a channel: ${missing.join(", ")}.` : ""}\n\nYour own sounds are never changed. Go?`)) return;
  if (prop.kit && !prop.kit_loaded) {
    if (autoKit) {
      const r = await withPending(() => api("/api/kit/load", { roles: prop.kit.roles, proposal_id: prop.id }), "Step 1 · loading your kit…");
      if (r && !r.ok) toast("Some kit sounds couldn't load automatically; the rest of the steps still run.", "err");
    } else stageKit(prop.kit.roles, prop.id);   // opens the folder + drag guide; the other steps carry on
  }
  await addAll(prop);
  await refreshSession();
  const fresh = session.proposals[prop.id];
  if (fresh && fresh.mix && fresh.mix.status === "proposed") {
    const r = await withPending(() => api("/api/mix/apply", { proposal_id: prop.id }), "Last step · mixing…");
    if (r && r.ok) toast("Mix applied ✓", "ok");
  }
  if (session.settings.listen_after !== false) await runListen(true);
}

// ---------------------------------------------------------------- proposal extras
function proposalHeader(prop) {
  const info = prop.info || {};
  const chips = [];
  if (info.key) chips.push(h("span", { class: "ph-chip key" }, info.key));
  if (info.tempo) chips.push(h("span", { class: "ph-chip" }, `${Math.round(info.tempo)} BPM`));
  if (info.harmony && info.harmony.length) {
    const seen = [], syms = [];
    for (const c of info.harmony) { if (seen.length < 8) { seen.push(c.symbol); syms.push(c.symbol); } }
    chips.push(h("span", { class: "ph-chords" }, syms.map((s) => h("b", {}, s))));
  }
  if (info.groove) chips.push(h("span", { class: "ph-chip groove" }, svg(ICONS.drums), info.groove.label + (info.groove.swing ? ` · swing ${Math.round(info.groove.swing * 100)}` : "")));
  return chips.length ? h("div", { class: "prop-head" }, chips) : null;
}
function miniPreview(plan, color) {
  if (!plan || !plan.notes || !plan.notes.length) return h("div", { class: "mini empty" }, "—");
  return h("div", { class: "mini" }, roll(plan, color));
}
function improveCards(prop) {
  const cards = (prop.findings || []).map((f) => {
    const idxs = f.part_indexes || [];
    const parts = idxs.map((i) => prop.parts[i]);
    const done = parts.length && parts.every((p) => p.status === "applied");
    const color = GROUP_META[f.group] ? GROUP_META[f.group].color : "var(--accent)";
    const p0 = parts[0];
    return h("div", { class: "fcard" + (done ? " done" : ""), style: `--gc:${color}` },
      h("div", { class: "fhead" }, h("span", { class: "bdot" }), h("b", {}, f.title)),
      h("p", {}, f.detail),
      p0 && p0.before ? h("div", { class: "ab" },
        h("div", {}, h("small", {}, "Now"), miniPreview(p0.before, color)),
        h("span", { class: "ab-arrow" }, svg(ICONS.arrow)),
        h("div", {}, h("small", {}, "After"), miniPreview(p0.plan, color))) : null,
      p0 && !p0.before ? h("div", { class: "ab single" }, h("div", {}, h("small", {}, "New part"), miniPreview(p0.plan, color))) : null,
      parts.length ? h("div", { class: "row-btns" },
        done ? h("span", { class: "ok-label" }, "Added ✓") :
          h("button", { class: "btn small primary", disabled: pending > 0, onclick: async () => { for (const i of idxs) await applyPart(prop, i); } }, idxs.length > 1 ? `Add (${idxs.length} parts)` : "Add this"),
        done && session.parts[p0.name] ? h("button", { class: "btn small", onclick: () => trackOp("/api/revert", p0.name, "Going back…") }, "Undo") : null)
        : h("small", { class: "muted" }, "Veloura can't do this one by itself."),
      h("small", { class: "kind" }, "Estimate from the notes, not the audio"));
  });
  return h("div", { class: "fcards" }, cards.length ? cards : h("p", {}, "Nothing to change."));
}
function variationCards(prop) {
  const cur = session.parts[prop.variant_of];
  const color = cur ? ROLE_COLOR[cur.role] || ROLE_COLOR.other : "var(--melody)";
  return h("div", { class: "vgrid" },
    h("div", { class: "vcard current" }, h("div", { class: "vhead" }, h("span", { class: "vletter" }, "•"), h("b", {}, "Current")),
      cur ? miniPreview(cur.plan, color) : h("div", { class: "mini empty" }, "—")),
    prop.parts.map((p, i) => h("div", { class: "vcard" + (p.status === "applied" ? " chosen" : "") },
      h("div", { class: "vhead" }, h("span", { class: "vletter" }, p.option), h("b", {}, p.option_label)),
      miniPreview(p.plan, color), h("p", {}, p.description),
      p.status === "applied" ? h("span", { class: "ok-label" }, "In FL ✓") :
        h("button", { class: "btn small primary", disabled: pending > 0, onclick: () => applyPart(prop, i) }, "Use this"))));
}

// ---------------------------------------------------------------- kits (chat card + Sounds page)
let audioEl = null;
function play(id, btn) {
  if (audioEl) { audioEl.pause(); document.querySelectorAll(".play.on").forEach((b) => b.classList.remove("on")); }
  audioEl = new Audio(`/api/library/audio?id=${encodeURIComponent(id)}&t=${encodeURIComponent(token)}`);
  if (btn) { btn.classList.add("on"); audioEl.onended = () => btn.classList.remove("on"); }
  audioEl.play().catch(() => toast("Couldn't play that file.", "err"));
}
const playBtn = (id) => h("button", { class: "play", title: "Listen", onclick: (e) => play(id, e.currentTarget) }, svg(["M8 5v14l11-7z"]));
const STAR = ["M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"];
function favBtn(id, on, after) {
  return h("button", { class: "icon-btn fav" + (on ? " on" : ""), title: on ? "Favourite: Veloura picks it more often (click to un-favourite)" : "Favourite: Veloura picks it more often",
    onclick: async (e) => { e.stopPropagation(); const now = !e.currentTarget.classList.contains("on"); e.currentTarget.classList.toggle("on", now);
      await api("/api/library/favorite", { id, on: now }); toast(now ? "Favourited: it'll come up more often" : "Removed from favourites"); if (after) after(); } }, svg(STAR));
}
function hideBtn(id, after) {
  return h("button", { class: "icon-btn", title: "Remove from Veloura's picks (the file stays on your Mac; you can bring it back)",
    onclick: async (e) => { e.stopPropagation(); await api("/api/library/hide", { id, on: true }); toast("Removed: Veloura won't pick it"); if (after) after(); } }, svg(["M6 6l12 12M18 6L6 18"]));
}
const ROLE_LABEL = { kick: "Kick", snare: "Snare", clap: "Clap", hat: "Hi-hat", "open hat": "Open hat", perc: "Perc", "808": "808" };
let kitState = store.get("kitState", null), kitCheck = null, kitTimer = null;
function kitCard(kit, pid) {
  const roles = kit.roles || {};
  return h("div", { class: "kit-card" },
    h("div", { class: "kit-head" }, h("span", { class: "eyebrow" }, "Your sound"), h("b", {}, "Drums from your library")),
    h("div", { class: "kit-row" }, Object.entries(roles).map(([r, s]) => h("div", { class: "ksound" }, playBtn(s.id),
      h("div", {}, h("small", {}, ROLE_LABEL[r] || r), h("b", {}, s.name), h("span", {}, s.kit)), favBtn(s.id, s.favorite)))),
    h("div", { class: "row-btns" }, h("button", { class: "btn small primary glow", onclick: () => stageKit(roles) }, "Load into FL"),
      h("button", { class: "btn small", onclick: () => { showPage("sounds"); kitState = kit; store.set("kitState", kit); renderSounds(); } }, "Swap sounds")));
}
async function stageKit(roles, pid) {
  // Default: copy the kit into a folder and show it for one drag (fast, FL never browses or previews your sounds).
  // The Browser-walking loader is opt-in (Settings): it is slow and FL steps through every sound on the way.
  const auto = session.settings.kit_auto_load ? await withPending(() => api("/api/kit/load", { roles, proposal_id: pid }), "Loading your kit into FL…") : null;
  if (auto && auto.ok) { toast("Kit loaded into your channels ✓", "ok"); return; }
  const failed = {};
  for (const [role, res] of Object.entries((auto && auto.results) || {})) if (!res.ok) failed[role] = roles[role];
  const done = Object.keys(roles).length - Object.keys(failed).length;
  if (done) toast(`${done} sound(s) loaded automatically.`, "ok");
  const todo = Object.keys(failed).length ? failed : roles;
  const r = await withPending(() => api("/api/kit/stage", { roles: todo, label: session.settings.genre || "Kit" }), "Copying the rest…");
  if (!r) return;
  kitCheck = r.check;
  openLoadGuide(r);
}
function openLoadGuide(staged) {
  const body = $("modalBody"), dlg = $("modal");
  const list = h("div", { class: "load-list" });
  const paint = () => put(list, ...Object.entries(staged.files).map(([role, f]) => {
    const st = (kitCheck || {})[role] || {};
    return h("div", { class: "load-row" + (st.loaded ? " ok" : "") }, h("span", { class: "lstate" }, st.loaded ? "✓" : ""),
      h("b", {}, ROLE_LABEL[role] || role), h("span", {}, f.name + ".wav"), h("small", {}, st.loaded ? "in FL as “" + st.channel + "”" : "drag onto its channel"));
  }));
  paint();
  put(body, h("h2", {}, "Drag your kit into FL"),
    h("p", { class: "muted" }, "Veloura copied the sounds into a Finder window (your originals aren't touched). FL doesn't let apps load samples, so this is the one manual step:"),
    h("div", { class: "load-visual" }, h("div", { class: "lv-finder" }, h("small", {}, "Finder"), Object.values(staged.files).slice(0, 4).map((f) => h("span", {}, f.name))),
      h("span", { class: "lv-arrow" }, svg(ICONS.arrow)), h("div", { class: "lv-rack" }, h("small", {}, "Channel Rack"), ["Kick", "Snare", "Hat", "808"].map((n) => h("span", {}, n)))),
    h("p", {}, "Drop each file onto the matching channel's name to replace its sound, or onto empty space to add a new channel. Rows turn green as Veloura sees them."),
    list,
    h("div", { class: "row-btns end" }, h("button", { class: "btn small", onclick: () => api("/api/reveal", { path: Object.values(staged.files)[0].file }) }, "Show in Finder"),
      h("button", { class: "btn small primary", onclick: () => dlg.close() }, "Done")));
  dlg.showModal();
  clearInterval(kitTimer);
  kitTimer = setInterval(async () => {
    if (!dlg.open) { clearInterval(kitTimer); return; }
    try { kitCheck = await api("/api/kit/check", {}); paint(); } catch (_) {}
  }, 2000);
}

// ---------------------------------------------------------------- Beat Workspace
let beatRack = null;
const beatRackSig = () => beatRack ? JSON.stringify(beatRack.channels.map((c) => [c.name, c.steps, c.muted])) : "";
async function refreshBeatRack() {
  if (page !== "tracks" || pending) return;   // don't queue rack reads behind an FL action
  try { beatRack = await api("/api/rack", {}); if (changed("beatrack", beatRackSig())) renderBeat(); } catch (_) {}
}
setInterval(refreshBeatRack, 4000);
function syncState(name, e) {
  if (e.mode === "steps") {
    const ch = beatRack && beatRack.connected && beatRack.channels.find((c) => c.name === e.channel_name);
    if (!ch) return { cls: "unknown", text: "Channel Rack · " + e.channel_name };
    if (beatRack.pattern && beatRack.pattern.number !== e.pattern) return { cls: "unknown", text: `In pattern ${e.pattern}` };
    const want = (e.written || []).filter((s) => s.on).map((s) => s.step).join(",");
    const have = ch.steps.filter((s) => s < (e.written || []).length).join(",");
    return want === have ? { cls: "ok", text: "In FL ✓ matches" } : { cls: "warn", text: "Changed in FL" };
  }
  return { cls: "ok", text: "Written " + (e.updated || "").slice(11, 16) + " · Piano Roll" + (e.channel_name ? " · " + e.channel_name : "") };
}
function channelFor(e, name) {
  const chans = (status && status.controller && status.controller.channels) || [];
  return chans.find((c) => c.name === (e.channel_name || name));
}
function openVersions(anchor, name, e) {
  const color = ROLE_COLOR[e.role] || ROLE_COLOR.other;
  openPop(anchor, [h("h3", {}, name + " · versions"),
    h("div", { class: "vlist" }, (e.versions || []).slice().reverse().map((v, i) => h("div", { class: "vrow" + (i === 0 ? " head" : "") },
      h("div", {}, h("b", {}, v.label), h("small", {}, v.op), h("small", {}, (v.at || "").slice(5, 16))),
      miniPreview(v.plan, color),
      i === 0 ? h("span", { class: "ok-label" }, "Now") : h("button", { class: "btn tiny", onclick: async () => { closePops(); const r = await withPending(() => api("/api/restore-version", { name, id: v.id }), "Bringing it back…"); if (r && r.ok) toast(`${v.label} is back ✓`, "ok"); } }, "Bring back"))))], 360);
}
async function openInFL(name, e) {
  if (e.mode === "steps") { toast(`${name} lives in the Channel Rack (channel “${e.channel_name}”, pattern ${e.pattern}).`); return; }
  const r = await withPending(() => api("/api/open-piano-roll", { name: e.channel_name || name }), "Opening it in FL…");
  if (r) toast(r.message || "Opened", r.ok ? "ok" : "err");
}
async function tryVariations(name) {
  showPage("studio");
  await withPending(() => api("/api/variations", { name }), `Writing takes on ${name}…`);
  $("chatScroll").scrollTop = $("chatScroll").scrollHeight;
}
async function muteChannel(chan, muted) {
  try { await api("/api/rack/mute", { index: chan.index, name: chan.name, muted }); await refreshBeatRack(); renderBeat(); } catch (err) { toast(err.message, "err"); }
}
function lastInfo() {
  const props = Object.values(session.proposals || {});
  for (let i = props.length - 1; i >= 0; i--) if (props[i].info && props[i].info.key) return props[i].info;
  return null;
}
function inProject(n) {
  const ctl = status && status.controller;
  if (!ctl || !ctl.connected || !(ctl.channels || []).length) return true;
  const e = session.parts[n];
  return ctl.channels.some((c) => c.name === (e.channel_name || n));
}
const menuBtn = (label, fn, cls) => h("button", { type: "button", class: "pop-row" + (cls ? " " + cls : ""), onclick: () => { closePops(); fn(); } }, label);
const dotsIcon = () => svg(["M5 12h.01M12 12h.01M19 12h.01"]);
function beatMenu(anchor) {
  openPop(anchor, [
    menuBtn("Plan the song", planArrangement),
    menuBtn("Set up mixer", async () => { const r = await withPending(() => api("/api/mixer-setup", {}), "Setting up the mixer…"); if (r) toast(r.routed.length ? `${r.routed.length} channel(s) got their own mixer track ✓` : "Every channel already has its own track ✓", "ok"); }),
    menuBtn("Save all as MIDI", exportAll),
    menuBtn("Undo everything", undoEverything, "danger")], 220);
}
function partMenu(anchor, name, e) {
  const locked = (session.settings.locked_parts || []).includes(name), chan = channelFor(e, name);
  const muted = beatRack && beatRack.channels && chan ? (beatRack.channels.find((c) => c.index === chan.index) || {}).muted : false;
  openPop(anchor, [h("h3", {}, name),
    menuBtn("Open in FL", () => openInFL(name, e)),
    menuBtn("Try 3 variations", () => tryVariations(name)),
    chan ? menuBtn(muted ? "Unmute" : "Mute", () => muteChannel(chan, !muted)) : null,
    menuBtn(locked ? "Unlock (Veloura may change it)" : "Keep exactly as is", () => api("/api/lock", { name, locked: !locked }).then(refreshSession)),
    (e.versions || []).length > 1 ? menuBtn("Versions…", () => openVersions(anchor, name, e)) : null,
    (e.history || []).length ? menuBtn("Undo last change", () => trackOp("/api/revert", name, "Going back…")) : null,
    menuBtn("Save MIDI", () => exportPart({ name })),
    menuBtn("Remove from FL", () => trackOp("/api/remove", name, "Removing…"), "danger")].filter(Boolean), 240);
}
function latestBeatProp() {
  const props = Object.values(session.proposals || {});
  for (let i = props.length - 1; i >= 0; i--) if ((props[i].parts || []).length && !props[i].variant_of && props[i].kind !== "improve") return props[i];
  return null;
}
function leadPart(names) {
  return names.find((n) => ["lead", "melody"].includes(session.parts[n].role)) || names.find((n) => GROUP_OF[session.parts[n].role] === "melody");
}
function variationSeg(lead) {
  const props = Object.values(session.proposals || {}).filter((p) => p.variant_of === lead);
  const vp = props[props.length - 1];
  const opts = ["A", "B", "C"];
  return h("div", { class: "seg", title: lead ? `Takes on ${lead}` : "Add a melody first" }, h("span", { class: "seg-label" }, "Variation"),
    opts.map((o, i) => {
      const p = vp && vp.parts[i];
      return h("button", { type: "button", class: p && p.status === "applied" ? "on" : "", disabled: !lead || pending > 0,
        onclick: () => p ? applyPart(vp, i) : tryVariations(lead) }, o);
    }));
}
function beatRow(n, e) {
  const color = ROLE_COLOR[e.role] || ROLE_COLOR.other, sync = syncState(n, e), versions = e.versions || [];
  const locked = (session.settings.locked_parts || []).includes(n);
  const strip = e.mode === "steps" || e.role === "drums" ? drumStrip([e.plan], color) : notesStrip(planNotes(e.plan), color);
  const pv = h("button", { class: "bp-play", type: "button", title: "Preview: drums use your kit samples, other parts a quick sketch", "data-label": "Play", onclick: (ev) => previewParts([{ ...e, name: n }], ev.currentTarget) }, "Play");
  return h("div", { class: "bp-row" + (locked ? " locked" : ""), style: `--gc:${color}` },
    h("i", { class: "bp-dot" }),
    h("span", { class: "bp-name" }, h("b", {}, n, locked ? h("small", { class: "lock" }, " · kept") : null), h("small", {}, "→ " + (e.sound || e.channel_name || "Piano Roll"))),
    h("span", { class: "bp-role" }, (GROUP_META[GROUP_OF[e.role] || "other"].title || e.role).toUpperCase()),
    strip,
    h("span", { class: "bp-sync " + sync.cls }, h("i"), sync.cls === "ok" ? "In FL" : sync.cls === "warn" ? "Changed in FL" : sync.text),
    h("button", { class: "bp-ver", type: "button", disabled: versions.length < 2, onclick: (ev) => openVersions(ev.currentTarget, n, e) }, versions.length > 1 ? `v${versions.length} of ${versions.length}` : "v1"),
    h("span", { class: "bp-acts" }, pv, h("button", { class: "icon-btn", type: "button", title: "More", onclick: (ev) => partMenu(ev.currentTarget, n, e) }, dotsIcon())));
}
// All drum lanes share one row, like the mock-up: one strip with a line per lane.
function drumsRow(lanes) {
  const color = ROLE_COLOR.drums, entries = lanes.map((n) => session.parts[n]);
  const syncs = lanes.map((n) => syncState(n, session.parts[n]));
  const sync = syncs.find((x) => x.cls === "warn") || syncs.find((x) => x.cls === "unknown") || syncs[0];
  const vmax = Math.max(1, ...entries.map((e) => (e.versions || []).length));
  const names = lanes.map((n) => session.parts[n].channel_name || n).join(" · ");
  const menu = (anchor) => openPop(anchor, [h("h3", {}, "Drums"),
    menuBtn("Keep the drums as they are", async () => { await api("/api/groove", { action: "keep" }); toast("Drums locked: Veloura won't change them ✓", "ok"); refreshSession(); }),
    menuBtn("Save drums as MIDI", async () => { for (const n of lanes) await exportPart({ name: n }); }),
    ...lanes.flatMap((n) => [h("div", { class: "pop-sub" }, n), ...((session.parts[n].history || []).length ? [menuBtn("Undo last change", () => trackOp("/api/revert", n, "Going back…"))] : []),
      menuBtn("Remove from FL", () => trackOp("/api/remove", n, "Removing…"), "danger")])], 260);
  return h("div", { class: "bp-row", style: `--gc:${color}` }, h("i", { class: "bp-dot" }),
    h("span", { class: "bp-name" }, h("b", {}, "Drums"), h("small", { title: names }, "→ " + names)),
    h("span", { class: "bp-role" }, "DRUMS"), drumStrip(entries.map((e) => e.plan), color),
    h("span", { class: "bp-sync " + sync.cls }, h("i"), sync.cls === "ok" ? "In FL" : sync.cls === "warn" ? "Changed in FL" : sync.text),
    h("span", { class: "bp-ver" }, vmax > 1 ? `v${vmax} of ${vmax}` : "v1"),
    h("span", { class: "bp-acts" }, h("button", { class: "bp-play", type: "button", "data-label": "Play", onclick: (ev) => previewParts(lanes.map((n) => ({ ...session.parts[n], name: n })), ev.currentTarget) }, "Play"),
      h("button", { class: "icon-btn", type: "button", title: "More", onclick: (ev) => menu(ev.currentTarget) }, dotsIcon())));
}
function renderBeat() {
  const names = Object.keys(session.parts).filter(inProject);
  const info = lastInfo(), prop = latestBeatProp();
  if (!names.length) {
    put($("beatHero"), h("div", { class: "big-title" }, illustration("vinyl", 84), h("span", { class: "eyebrow" }, "Your beat"), h("h2", {}, "Nothing here yet."),
      h("p", {}, "Make something in Studio. Every part you add shows up here, with its notes, versions and groove."),
      h("button", { class: "btn primary", onclick: () => showPage("studio") }, "Go to Studio")));
    for (const id of ["beatGroups", "beatTools", "historyBar"]) put($(id));
    $("beatGroups").hidden = $("beatTools").hidden = $("historyBar").hidden = true; $("trackGrid").hidden = true;
    return;
  }
  $("beatGroups").hidden = $("beatTools").hidden = $("historyBar").hidden = false;
  const proj = session.project && session.project !== "Untitled" ? session.project : "This beat";
  const tempo = (info && info.tempo) || session.settings.tempo_bpm;
  const eyebrow = [proj, tempo ? Math.round(tempo) + " BPM" : null, info && info.key ? info.key : null].filter(Boolean).join(" · ").toUpperCase();
  put($("beatHero"), h("div", { class: "bh-text" }, h("span", { class: "eyebrow" }, eyebrow),
      h("h2", {}, prop ? beatTitle(prop) : proj + "."), h("p", {}, "Everything in this beat, and what is in FL right now.")),
    h("div", { class: "bh-cta" },
      h("button", { class: "icon-btn ring", type: "button", title: "More", onclick: (e) => beatMenu(e.currentTarget) }, dotsIcon()),
      h("button", { class: "btn quiet", type: "button", onclick: () => runListen() }, svg(["M4 9h4l5-4v14l-5-4H4z", "M17 9a4 4 0 0 1 0 6"]), "Listen"),
      h("button", { class: "btn primary", type: "button", onclick: improveBeat }, svg(["M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"]), "Improve this beat")));
  const changedN = names.filter((n) => syncState(n, session.parts[n]).cls === "warn").length;
  const order = { drums: 0, melody: 1, bass: 2, other: 3 };
  const sorted = names.slice().sort((a, b) => order[GROUP_OF[session.parts[a].role] || "other"] - order[GROUP_OF[session.parts[b].role] || "other"]);
  const have = new Set(names.map((n) => GROUP_OF[session.parts[n].role] || "other"));
  const missing = ["drums", "melody", "bass"].filter((g) => !have.has(g));
  put($("beatGroups"),
    h("div", { class: "pc-head" }, h("b", {}, "Parts"), h("small", {}, `${names.length} in FL${changedN ? ` · ${changedN} changed in FL` : ""}`),
      h("span", { class: "spacer" }), variationSeg(leadPart(names))),
    (() => { const drumLanes = sorted.filter((n) => GROUP_OF[session.parts[n].role] === "drums"), rest = sorted.filter((n) => !drumLanes.includes(n));
      const lead = leadPart(rest), ordered = lead ? [lead, ...rest.filter((n) => n !== lead)] : rest;
      return [...(lead ? [beatRow(lead, session.parts[lead])] : []), ...(drumLanes.length ? [drumsRow(drumLanes)] : []), ...ordered.slice(lead ? 1 : 0).map((n) => beatRow(n, session.parts[n]))]; })(),
    missing.map((g) => h("button", { class: "bp-add", type: "button", style: `--gc:${GROUP_META[g].color}`, disabled: pending > 0,
      onclick: () => { showPage("studio"); send(`Add ${g === "bass" ? "an 808 / bass part" : "a " + GROUP_META[g].title.toLowerCase() + " part"} that fits this beat. Keep everything else exactly as it is.`); } },
      h("i", { class: "bp-dot" }), "Add " + (g === "bass" ? "808" : GROUP_META[g].title.toLowerCase()))));
  const drums = names.filter((n) => GROUP_OF[session.parts[n].role] === "drums");
  put($("beatTools"), grooveLab(drums), songMap());
  const writes = names.reduce((t, n) => t + Math.max(1, (session.parts[n].versions || []).length), 0);
  put($("historyBar"), svg(["M12 7v5l3 2", "M3 12a9 9 0 1 0 3-6.7", "M3 4v4h4"]), h("b", {}, "History"), h("span", {}, "everything Veloura has written"),
    h("span", { class: "spacer" }), h("small", {}, `${writes} write${writes === 1 ? "" : "s"}`),
    h("button", { class: "link-quiet", type: "button", onclick: () => { const g = $("trackGrid"); g.hidden = !g.hidden; renderBeat(); } }, $("trackGrid").hidden ? "Show" : "Hide"));
  if (!$("trackGrid").hidden) renderTracks();
}
function grooveLab(list) {
  const lanes = list.filter((n) => session.parts[n].plan);
  const act = (a, label) => h("button", { class: "glab-btn" + (a === "keep" ? " keep" : ""), type: "button", disabled: !lanes.length || pending > 0, onclick: async () => {
    if (a === "keep") { await api("/api/groove", { action: "keep" }); toast("Drums locked: Veloura won't change them ✓", "ok"); await refreshSession(); return; }
    showPage("studio"); await withPending(() => api("/api/groove", { action: a }), label + "…"); $("chatScroll").scrollTop = $("chatScroll").scrollHeight; } }, label);
  return h("div", { class: "tool-card glab" },
    h("div", { class: "tc-head" }, h("b", {}, "Groove Lab"), h("small", {}, lanes.length ? "Drums · one tap, undoable" : "Add drums to use it")),
    h("div", { class: "glab-actions" }, act("bounce", "More bounce"), act("space", "More space"), act("swing", "Swing"),
      act("new", "New groove"), act("authentic", "Authentic"), act("keep", "Keep")));
}
async function planArrangement() {
  const r = await withPending(() => api("/api/arrangement", {}), "Planning the song…");
  if (r) { await refreshSession(); showPage("tracks"); renderBeat(); const m = document.querySelector(".songmap"); if (m) m.scrollIntoView({ behavior: "smooth" }); }
}
let mapHow = false;
function songMap() {
  const arr = session.arrangement;
  if (!arr) return h("div", { class: "tool-card songmap empty" }, h("div", { class: "tc-head" }, h("b", {}, "Song map"), h("small", {}, "Intro, hook, verse, outro"),
      h("span", { class: "spacer" }), h("button", { class: "link-accent", type: "button", disabled: pending > 0, onclick: planArrangement }, "Plan the song")),
    h("p", { class: "muted" }, "Veloura can lay your loop out as a full song and tell you what to do in each section."));
  const tip = h("div", { class: "arr-tip" });
  let sel = null;
  const lead = Object.keys(session.parts).find((n) => GROUP_OF[session.parts[n].role] === "melody") || "Melody";
  return h("div", { class: "tool-card songmap" },
    h("div", { class: "tc-head" }, h("b", {}, "Song map"), h("small", {}, `${arr.total_bars} bars · suggested`), h("span", { class: "spacer" }),
      h("button", { class: "link-accent", type: "button", onclick: () => { mapHow = !mapHow; renderBeat(); } }, mapHow ? "Hide steps" : "Use this map")),
    h("div", { class: "sm-blocks" }, arr.sections.map((s) => h("button", { type: "button", class: "sm-sec" + (s.energy >= 8 ? " peak" : ""), style: `flex:${s.bars};--e:${Math.max(.3, s.energy / 10).toFixed(2)}`,
      title: `${s.name} · ${s.bars} bars · energy ${s.energy}/10`, onclick: (e) => {
        if (sel) sel.classList.remove("sel"); sel = e.currentTarget; sel.classList.add("sel");
        put(tip, h("b", {}, `${s.name} · bars ${s.start_bar}–${s.start_bar + s.bars - 1}`), " ", s.tip, " ",
          h("button", { class: "link-accent", type: "button", onclick: () => { showPage("studio"); send(`Make a ${s.name.toLowerCase()} variation of the melody for bars ${s.start_bar}-${s.start_bar + s.bars - 1}: same chords, ${s.energy >= 8 ? "more energy" : "stripped back"}. Name it "${lead} (${s.name})".`); } }, "Write a " + s.name.toLowerCase() + " version"));
      } }, h("small", {}, s.name)))),
    tip,
    mapHow ? h("ol", { class: "sm-how" }, arr.how.map((t) => h("li", {}, t))) : null);
}

// ---------------------------------------------------------------- Sounds page
let libState = null, libCat = null, libQuery = "", libList = [], libHidden = false;
async function refreshLibrary() { try { libState = await api("/api/library", {}); if (page === "sounds") renderSounds(); } catch (_) {} }
setInterval(() => { if (page === "sounds" && libState && libState.scanning) refreshLibrary(); }, 1200);
async function loadLibList() {
  try { libList = (await api("/api/library/list", { category: libCat, q: libQuery, limit: 300, hidden: libHidden })).samples; } catch (_) { libList = []; }
  renderLibBrowse();
}
const CAT_COLORS = { kick: "var(--cat-kick)", snare: "var(--cat-snare)", clap: "var(--cat-clap)", hat: "var(--cat-hat)", "open hat": "var(--cat-open-hat)",
  perc: "var(--cat-perc)", "808": "var(--cat-808)", fx: "var(--cat-fx)", loop: "var(--cat-loop)", uncertain: "var(--cat-uncertain)" };
let libLoaded = false;
function renderSounds() {
  if (!libState) { refreshLibrary(); return; }
  const L = libState;
  if (!$("libSearch")) {
    put($("libTop"), svg(["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-4-4"]),
      h("input", { id: "libSearch", class: "lsearch", oninput: (e) => { libQuery = e.target.value; clearTimeout(window._lq); window._lq = setTimeout(loadLibList, 250); } }));
  }
  $("libSearch").placeholder = `Search ${L.total || 0} sounds`;
  const cats = Object.entries(L.counts).filter(([, n]) => n);
  put($("libCats"), h("button", { type: "button", class: "lcat" + (!libCat ? " sel" : ""), onclick: () => { libCat = null; loadLibList(); renderSounds(); } }, "All", h("small", {}, String(L.total || 0))),
    ...cats.map(([c, n]) => h("button", { type: "button", class: "lcat" + (libCat === c ? " sel" : ""), style: `--cc:${CAT_COLORS[c]}`, onclick: () => { libCat = libCat === c ? null : c; loadLibList(); renderSounds(); } },
      h("i"), L.labels[c] || c, h("small", {}, String(n)))));
  if (!libLoaded) { libLoaded = true; loadLibList(); } else renderLibBrowse();
  renderKitFolders();
  renderKitPanel();
  renderStyle();
  renderInstSounds();
}
function renderLibBrowse() {
  const box = $("libBrowse"), L = libState || { labels: {}, total: 0 };
  const cats = Object.keys(CAT_COLORS);
  const rows = libList.map((s) => h("div", { class: "lrow" + (s.category === "uncertain" ? " unsure" : "") + (s.favorite ? " fav" : ""), style: `--cc:${CAT_COLORS[s.category] || "var(--faint)"}` },
    playBtn(s.id), h("div", { class: "ls-main" }, h("b", {}, s.name), h("small", {}, `${s.kit}${s.duration ? " · " + s.duration.toFixed(2) + "s" : ""}`)),
    h("label", { class: "ls-cat", title: s.corrected ? "You set this" : `Sorted by ${s.source}` }, h("i"),
      h("select", { onchange: async (e) => { await api("/api/library/set-category", { id: s.id, category: e.target.value }); toast("Moved to " + e.target.value); refreshLibrary(); } },
        cats.map((c) => h("option", { value: c, selected: c === s.category }, (L.labels[c] || c))))),
    libHidden ? h("button", { class: "btn tiny", onclick: async () => { await api("/api/library/hide", { id: s.id, on: false }); toast("Back in your sounds ✓", "ok"); refreshLibrary(); loadLibList(); } }, "Bring back")
      : h("span", { class: "ls-btns" }, favBtn(s.id, s.favorite), hideBtn(s.id, () => { refreshLibrary(); loadLibList(); }))));
  const empty = !L.total ? h("div", { class: "lib-empty" }, illustration("vinyl", 64), h("b", {}, "No sounds yet"), h("p", {}, "Add a drum folder and Veloura sorts every sound into kicks, snares, hats, 808s and more."),
    h("button", { class: "btn primary small", onclick: addFolder }, "Add a folder")) : !libList.length ? h("p", { class: "muted pad" }, libHidden ? "Nothing removed." : "No sounds match.") : null;
  put(box, rows, empty,
    h("div", { class: "lib-foot" }, h("small", { class: "muted" }, L.total ? `${libList.length >= 300 ? "First 300" : libList.length} of ${libCat ? L.counts[libCat] : L.total}${L.duplicates ? ` · ${L.duplicates} duplicates hidden` : ""}` : ""),
      h("span", { class: "spacer" }),
      h("button", { class: "link-quiet", type: "button", onclick: () => { libHidden = !libHidden; loadLibList(); } }, libHidden ? "Back to my sounds" : `Removed sounds${L.hidden ? ` (${L.hidden})` : ""}`)));
}
async function addFolder() {
  const r = await api("/api/library/add-folder", {}).catch((e) => toast(e.message, "err"));
  if (r && r.ok) { toast("Scanning " + r.folder.split("/").pop() + "…"); libLoaded = false; refreshLibrary(); }
}
let foldersOpen = true;
function renderKitFolders() {
  const L = libState;
  put($("kitFolders"), h("div", { class: "sc-head" }, svg(["M3 7h6l2 2h10v10H3z"]), h("b", {}, "Kit folders"), h("small", {}, String(L.folders.length)), h("span", { class: "spacer" }),
      h("button", { class: "add-pill", type: "button", onclick: addFolder }, "+ Add"),
      h("button", { class: "icon-btn chev" + (foldersOpen ? " open" : ""), type: "button", title: foldersOpen ? "Collapse" : "Expand", onclick: () => { foldersOpen = !foldersOpen; renderKitFolders(); } }, svg(["M6 9l6 6 6-6"]))),
    !foldersOpen ? null : L.folders.length ? L.folders.map((f) => h("div", { class: "kf" + (f.exists ? "" : " gone") },
      h("div", {}, h("b", {}, f.name), h("small", { title: f.path }, f.exists ? f.path.replace(/^\/Users\/[^/]+/, "~") : "Folder not found")),
      h("small", { class: "kf-n" }, f.exists ? f.count.toLocaleString("en-US") : "–"),
      h("button", { class: "icon-btn", title: "Remove from library (files stay where they are)", onclick: async () => { libState = await api("/api/library/remove-folder", { path: f.path }); libLoaded = false; renderSounds(); } }, svg(["M6 6l12 12M18 6L6 18"]))))
      : h("p", { class: "muted" }, "Add the folders where your drum kits live."),
    !foldersOpen ? null : L.scanning ? h("div", { class: "scan" }, h("span", { class: "eq" }, h("i"), h("i"), h("i")), `${L.scanning.phase}… ${L.scanning.done || 0}/${L.scanning.found || 0}`)
      : L.folders.length ? h("div", { class: "kf-foot" }, h("small", { class: "muted" }, `${L.kits} kits · scanned ${(L.scanned_at || "").slice(5, 16)}`),
        h("button", { class: "link-quiet", type: "button", onclick: async () => { await api("/api/library/scan", {}); refreshLibrary(); } }, "Rescan")) : null);
}
function renderKitPanel() {
  const box = $("kitPanel");
  const head = (extra) => h("div", { class: "sc-head" }, h("b", {}, "Build a kit"), h("span", { class: "spacer" }), extra);
  if (!libState || !libState.total) { put(box, head(), h("p", { class: "muted" }, "Add a drum folder and Veloura builds kits that fit each beat.")); return; }
  const genreSel = h("select", { class: "mini-select" }, GENRES.filter((g) => g !== "other").map((g) => h("option", { value: g, selected: g === session.settings.genre }, (genreInfo[g] || {}).label || g)));
  const pick = async (keep, exclude) => { kitState = await api("/api/kit/choose", { genre: genreSel.value, keep, exclude }); store.set("kitState", kitState); renderKitPanel(); };
  const roles = (kitState && kitState.roles) || {};
  const others = (r) => { const keep = {}; for (const [k, v] of Object.entries(roles)) if (k !== r) keep[k] = v.id; return keep; };
  put(box, head(h("button", { class: "link-quiet", type: "button", onclick: () => pick() }, Object.keys(roles).length ? "Shuffle" : "Pick a kit")),
    Object.entries(roles).map(([r, s]) => h("div", { class: "kr", style: `--cc:${CAT_COLORS[r] || "var(--accent)"}`, title: s.kit }, h("i", { class: "kr-dot" }), playBtn(s.id),
      h("small", { class: "kr-role" }, ROLE_LABEL[r] || r), h("div", { class: "kr-main" }, h("b", {}, s.name)),
      h("span", { class: "kr-btns" }, favBtn(s.id, s.favorite),
        h("button", { class: "icon-btn", title: "Swap for another", onclick: () => { api("/api/kit/feedback", { id: s.id, verdict: "rejected", role: r }); pick(others(r), [s.id]); } }, svg(["M4 4v6h6", "M20 20v-6h-6", "M5 15a8 8 0 0 0 14 2M19 9A8 8 0 0 0 5 7"])),
        hideBtn(s.id, () => pick(others(r), [s.id]))))),
    Object.keys(roles).length ? h("button", { class: "btn outline full", type: "button", onclick: () => stageKit(roles) }, "Load kit into FL") : null,
    h("label", { class: "kit-genre" }, "Fits", genreSel));
}
let styleState = null;
async function renderStyle() {
  try { styleState = await api("/api/style", {}); } catch (_) { return; }
  const st = styleState;
  put($("stylePanel"), h("div", { class: "sc-head" }, h("b", {}, "My style"), h("span", { class: "spacer" }),
      h("button", { class: "link-quiet", type: "button", onclick: async () => {
        const r = await withPending(() => api("/api/style/import", {}), "Learning from your MIDI…");
        if (r && r.ok) toast(`Learned from ${r.added} file(s)${r.skipped.length ? ` (${r.skipped.length} skipped)` : ""} ✓`, "ok"); renderStyle(); } }, "Add MIDI")),
    h("p", { class: "muted" }, st.total ? `Veloura learned ${st.grooves} groove${st.grooves === 1 ? "" : "s"} and ${st.melodies} chord/melody idea${st.melodies === 1 ? "" : "s"} from your MIDI and writes in that feel.`
      : "Give Veloura MIDI of beats you love. It learns the grooves, chords and rhythms. Folders named after a genre (e.g. “plugg”) sort them."),
    st.items.length ? h("details", { class: "style-more" }, h("summary", {}, `${st.items.length} file${st.items.length === 1 ? "" : "s"}`),
      h("div", { class: "style-list" }, st.items.slice().reverse().slice(0, 40).map((i) => h("div", { class: "style-item" },
        h("div", {}, h("b", {}, i.file), h("small", {}, [i.genre || "any genre", i.groove ? "groove" : null, i.key, (i.melody || []).join(" ")].filter(Boolean).join(" · "))),
        h("button", { class: "icon-btn", title: "Forget this one", onclick: async () => { await api("/api/style/remove", { id: i.id }); renderStyle(); } }, svg(["M6 6l12 12M18 6L6 18"])))))) : null);
}
function renderInstSounds() {
  const chans = ((status && status.controller && status.controller.channels) || []).filter((c) => c.type === "plugin" || c.type === "hybrid");
  put($("instSounds"), h("div", { class: "sc-head" }, h("b", {}, "Instrument sounds"), chans.length ? h("small", {}, String(chans.length)) : null),
    ...(chans.length ? chans.map((c) => h("button", { class: "inst", type: "button", onclick: (e) => openSounds(e.currentTarget, c) },
      h("b", {}, c.name), h("small", {}, "Choose a sound ›")))
      : [h("p", { class: "muted" }, "Instrument plugins in your Channel Rack (FLEX, ZENOLOGY…) show up here once FL is connected.")]));
}

// extra render hooks
const _renderChat = renderChat;
let seenMsgs = null;
renderChat = function () {   // eslint-disable-line no-func-assign
  _renderChat();
  const kids = [...$("chat").children];
  const fresh = seenMsgs !== null ? kids.slice(seenMsgs) : [];
  fresh.forEach((k) => k.classList.add("msg-new"));   // only new messages animate in
  seenMsgs = kids.length;
  renderBeatStrip();
  const reply = fresh.filter((k) => k.classList.contains("msg-ai")).pop();
  if (reply) setTimeout(() => showReadGuide(reply), 450);
};

// ---------------------------------------------------------------- reading guide: a quiet hand-drawn arrow
let guideTarget = null, guideTimer = null;
function showReadGuide(msg) {
  if (!session || session.settings.guide_arrow === false) return;
  const sc = $("chatScroll");
  const top = msg.getBoundingClientRect().top - sc.getBoundingClientRect().top;
  if (top >= -8) return;                         // the start of the reply is already in view: no arrow needed
  guideTarget = msg;
  const g = $("readGuide");
  g.hidden = false;
  g.classList.remove("out");
  void g.offsetWidth;
  g.classList.add("in");
  clearTimeout(guideTimer);
  guideTimer = setTimeout(hideReadGuide, 9000);
}
function hideReadGuide() {
  const g = $("readGuide");
  if (g.hidden) return;
  g.classList.add("out");
  setTimeout(() => { g.hidden = true; g.classList.remove("in", "out"); }, 600);
  guideTarget = null;
}
$("readGuide").addEventListener("click", () => {
  if (guideTarget) guideTarget.scrollIntoView({ behavior: "smooth", block: "start" });
  hideReadGuide();
});
$("chatScroll").addEventListener("scroll", () => {
  if (!guideTarget) return;
  const sc = $("chatScroll");
  if (guideTarget.getBoundingClientRect().top - sc.getBoundingClientRect().top > -40) hideReadGuide();   // they found it
});
refreshLibrary();
