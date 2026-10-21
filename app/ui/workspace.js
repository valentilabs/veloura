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
function renderHero() {
  const fresh = !session.messages.length;
  $("heroExtra").hidden = !fresh;
  const hasParts = Object.keys(session.parts).length > 0;
  const card = (cls, icon, title, sub, fn) => h("button", { class: "qcard " + cls, type: "button", onclick: fn },
    h("span", { class: "qicon" }, svg(icon)), h("b", {}, title), h("small", {}, sub));
  put($("quickCards"), 
    card("q-beat", MI.bars, "Make a beat", "From an idea", () => { genreChip = false; renderModeChip(); $("input").focus(); }),
    card("q-sample", MI.sample, "Build on a sample", "Drop in a loop", () => pickFile("sample")),
    card("q-ref", MI.song, "Use a reference", "A song you love", () => pickFile("inspiration")),
    card("q-cont", ICONS.arrow, "Keep going", hasParts ? "Continue this beat" : "Nothing yet", () => hasParts ? send("Continue this beat: add the layer it needs most, and keep everything else.") : toast("Make a beat first.")));
  const cur = session.settings.genre;
  put($("genreTiles"), ...TILE_GENRES.map((g) => {
    const [base, a, b] = TILE_LOOK[g], info = genreInfo[g] || {};
    return h("button", { class: "gtile" + (g === cur && genreChip ? " sel" : ""), type: "button", style: `--g0:${base};--ga:${a};--gb:${b}`,
      onclick: async () => { await api("/api/settings", { genre: g }); genreChip = true; await refreshSession(); renderModeChip(); renderPills(); renderHero(); $("input").focus(); } },
      h("span", { class: "gname" }, info.label || g), info.tempo_range ? h("small", {}, `${info.tempo_range[0]}–${info.tempo_range[1]} BPM`) : null);
  }));
  const feel = Object.assign({}, FEEL_DEFAULT, session.settings.feel || {});
  $("feelSummary").textContent = FEEL.filter(([k]) => Math.abs(feel[k] - FEEL_DEFAULT[k]) > 10).map(([k, lo, hi]) => feel[k] > FEEL_DEFAULT[k] ? hi : lo).join(" · ") || "Balanced";
  put($("feelGrid"), ...FEEL.map(([k, lo, hi]) => h("label", { class: "feel-row" }, h("span", {}, lo),
    h("input", { type: "range", min: 0, max: 100, value: feel[k], oninput: (e) => { feel[k] = +e.target.value; saveFeel(feel); } }), h("span", {}, hi))));
}
let feelTimer = null;
function saveFeel(feel) {
  clearTimeout(feelTimer);
  feelTimer = setTimeout(async () => { await api("/api/feel", { feel }); session.settings.feel = feel; $("feelSummary").textContent = "Saved"; }, 350);
}

// current beat strip above the composer
function renderBeatStrip() {
  const strip = $("beatStrip"), names = Object.keys(session.parts).filter(inProject);
  strip.hidden = !names.length || !session.messages.length;
  if (strip.hidden) return;
  const groups = {};
  for (const n of names) (groups[GROUP_OF[session.parts[n].role] || "other"] ||= []).push(n);
  strip.replaceChildren(...["melody", "drums", "bass", "other"].filter((g) => groups[g]).map((g) =>
    h("button", { class: "bchip", style: `--gc:${GROUP_META[g].color}`, onclick: () => showPage("tracks") },
      h("span", { class: "bdot" }), GROUP_META[g].title, h("small", {}, String(groups[g].length)))),
    h("span", { class: "spacer" }),
    h("button", { class: "btn small glow improve-btn", onclick: improveBeat }, svg(["M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z"]), "Improve this beat"));
}
async function improveBeat() {
  showPage("studio");
  await withPending(() => api("/api/improve", {}), "Listening through the notes…");
  $("chatScroll").scrollTop = $("chatScroll").scrollHeight;
}

// ---------------------------------------------------------------- working animation + progress
const WORK_LINES = {
  compose: ["Choosing a key that fits the mood", "Sketching the chord progression", "Writing a hook you can hum",
    "Answering the hook at the end of the phrase", "Giving each layer one job", "Picking sounds from your instruments",
    "Placing the 808 under the chords", "Choosing the drum groove", "Leaving space for a vocal", "Adding movement every four bars"],
  apply: ["Opening the right Piano Roll", "Writing the notes", "Reading them back to check"],
};
const GLYPHS = ["♪", "♫", "♩", "♬", "𝄞"];
let workTimer = null, noteTimer = null, lineIdx = 0, lastStage = "";
function startWorking() {
  if (workTimer) return;
  lineIdx = 0;
  workTimer = setInterval(pollProgress, 450);
  noteTimer = setInterval(spawnNote, 380);
  pollProgress();
}
function stopWorking() {
  clearInterval(workTimer); clearInterval(noteTimer); workTimer = noteTimer = null;
  $("wPct").textContent = ""; $("wBar").style.width = "0%"; $("wDetail").textContent = "";
  for (const n of document.querySelectorAll(".fnote")) n.remove();
}
function spawnNote() {
  const stage = $("notesStage");
  if (!stage || $("busy").hidden) return;
  const n = h("span", { class: "fnote", style: `left:${8 + Math.random() * 84}%;animation-duration:${1.8 + Math.random() * 1.4}s;font-size:${12 + Math.random() * 12}px;--drift:${(Math.random() * 30 - 15).toFixed(0)}px;--hue:${Math.random() < .5 ? "var(--accent)" : "var(--melody)"}` },
    GLYPHS[Math.floor(Math.random() * GLYPHS.length)]);
  stage.append(n);
  setTimeout(() => n.remove(), 3400);
}
async function pollProgress() {
  let p;
  try { p = await api("/api/progress"); } catch (_) { return; }
  if (!p.active) {   // FL writes and quick actions: no server progress, show a gentle indeterminate bar
    $("busy").classList.add("indeterminate");
    $("wPct").textContent = "";
    $("wDetail").textContent = busyLabel && /Adding|Writing/.test(busyLabel) ? WORK_LINES.apply[Math.floor(Date.now() / 1400) % 3] : "";
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
    return;
  }
  if (!cancelRequested) $("busyText").textContent = p.stage;
  let detail = p.detail || "";
  if (p.estimated) {   // the AI works in one go: show what a producer does at this point, in order
    const lines = WORK_LINES.compose, k = Math.min(lines.length - 1, Math.floor((p.pct - 12) / (76 / lines.length)));
    detail = lines[Math.max(0, k)] + "…";
  }
  if (detail !== lastStage) { $("wDetail").textContent = detail; $("wDetail").classList.remove("swap"); void $("wDetail").offsetWidth; $("wDetail").classList.add("swap"); lastStage = detail; }
  $("wPct").textContent = left ? `${p.pct}% · ${left}` : p.pct + "%";
  $("wBar").style.width = p.pct + "%";
}
// "≈ 3 s left" while within the estimate; "almost there" once past it (never a negative or frozen 0).
function countdown(sec) {
  if (sec <= 0.05) return "almost there";
  return sec < 10 ? `≈ ${sec.toFixed(1)} s left` : `≈ ${Math.ceil(sec)} s left`;
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
function beatCard(name, e) {
  const meta = GROUP_META[GROUP_OF[e.role] || "other"], color = ROLE_COLOR[e.role] || ROLE_COLOR.other;
  const sync = syncState(name, e), locked = (session.settings.locked_parts || []).includes(name);
  const chan = channelFor(e, name), versions = e.versions || [];
  const muted = beatRack && beatRack.channels && chan ? (beatRack.channels.find((c) => c.index === chan.index) || {}).muted : false;
  return h("div", { class: "bcard" + (locked ? " locked" : "") + (muted ? " muted" : ""), style: `--gc:${color}` },
    h("div", { class: "bc-head" }, h("b", {}, name), e.sound ? h("span", { class: "bc-sound" }, e.sound) : null,
      h("span", { class: "sync " + sync.cls }, sync.text)),
    miniPreview(e.plan, color),
    h("div", { class: "bc-actions" },
      h("button", { class: "icon-btn", title: "Open in FL", onclick: () => openInFL(name, e) }, svg(["M14 4h6v6", "M20 4l-9 9", "M18 14v6H4V6h6"])),
      h("button", { class: "icon-btn", title: "Try 3 variations", onclick: () => tryVariations(name) }, svg(["M4 7h10M4 12h16M4 17h7", "M18 4l3 3-3 3"])),
      chan ? h("button", { class: "icon-btn" + (muted ? " on" : ""), title: muted ? "Unmute" : "Mute", onclick: () => muteChannel(chan, !muted) }, svg(muted ? ["M4 9h4l5-4v14l-5-4H4z", "M17 9l4 6M21 9l-4 6"] : ["M4 9h4l5-4v14l-5-4H4z", "M17 9a4 4 0 0 1 0 6"])) : null,
      h("button", { class: "icon-btn" + (locked ? " on" : ""), title: locked ? "Unlock (Veloura may change it)" : "Keep exactly as is", onclick: () => api("/api/lock", { name, locked: !locked }).then(refreshSession) }, svg(locked ? ["M6 11h12v9H6z", "M8 11V8a4 4 0 0 1 8 0v3"] : ["M6 11h12v9H6z", "M8 11V8a4 4 0 0 1 7.5-2"])),
      h("span", { class: "spacer" }),
      versions.length > 1 ? h("button", { class: "btn tiny", onclick: (ev) => openVersions(ev.currentTarget, name, e) }, `v${versions.length} ▾`) : null,
      h("button", { class: "btn tiny", disabled: !(e.history || []).length || pending > 0, onclick: () => trackOp("/api/revert", name, "Going back…") }, "Undo"),
      h("button", { class: "btn tiny ghost", onclick: () => exportPart({ name }) }, "MIDI")));
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
function renderBeat() {
  const names = Object.keys(session.parts).filter(inProject);
  const info = lastInfo();
  if (!names.length) {
    put($("beatHero"), h("div", { class: "big-title" }, illustration("vinyl", 84), h("span", { class: "eyebrow" }, "Your beat"), h("h2", {}, "Nothing here yet."),
      h("p", {}, "Make something in Studio. Every part you add shows up here, grouped, with its notes."),
      h("button", { class: "btn primary", onclick: () => showPage("studio") }, "Go to Studio")));
    put($("beatGroups"), ); put($("arrangement"), ); return;
  }
  put($("beatHero"), h("div", { class: "big-title row" },
    h("div", {}, h("span", { class: "eyebrow" }, "Your beat"), h("h2", {}, info && info.key ? info.key : "In progress"),
      h("div", { class: "beat-facts" }, info && info.tempo ? h("span", {}, Math.round(info.tempo) + " BPM") : null,
        info && info.harmony ? h("span", { class: "ph-chords" }, info.harmony.slice(0, 8).map((c) => h("b", {}, c.symbol))) : null,
        info && info.groove ? h("span", {}, info.groove.label) : null)),
    h("div", { class: "beat-cta" }, h("button", { class: "btn primary glow big", onclick: improveBeat }, "Improve this beat"),
      h("button", { class: "btn", onclick: () => runListen() }, "Listen"),
      h("button", { class: "btn", onclick: planArrangement }, "Plan the song"),
      h("button", { class: "btn", title: "Give every channel its own mixer track", onclick: async () => { const r = await withPending(() => api("/api/mixer-setup", {}), "Setting up the mixer…"); if (r) toast(r.routed.length ? `${r.routed.length} channel(s) got their own mixer track ✓` : "Every channel already has its own track ✓", "ok"); } }, "Set up mixer"),
      h("button", { class: "btn ghost danger", onclick: undoEverything }, "Undo all"))));
  const groups = {};
  for (const n of names) (groups[GROUP_OF[session.parts[n].role] || "other"] ||= []).push(n);
  put($("beatGroups"), ...["melody", "drums", "bass", "other"].map((g) => {
    const meta = GROUP_META[g], list = groups[g] || [];
    const missing = !list.length;
    return h("section", { class: "bgroup" + (missing ? " missing" : ""), style: `--gc:${meta.color}` },
      h("div", { class: "bg-head" }, h("span", { class: "bg-icon" }, svg(ICONS[meta.icon])), h("h3", {}, meta.title.toUpperCase()),
        h("small", {}, missing ? "Missing" : `${list.length} part${list.length === 1 ? "" : "s"}`), h("span", { class: "spacer" }),
        missing ? h("button", { class: "btn small", onclick: () => send(`Add ${g === "other" ? "a texture or FX layer" : "a " + meta.title.toLowerCase() + " part"} that fits this beat. Keep everything else exactly as it is.`) }, "Add " + meta.title.toLowerCase())
          : groupAsk(g, list)),
      g === "drums" && list.length ? grooveLab(list) : null,
      list.length ? h("div", { class: "bcards" }, list.map((n) => beatCard(n, session.parts[n]))) : null);
  }));
  renderArrangement();
}
function groupAsk(g, list) {
  const input = h("input", { class: "gask", placeholder: `Change only the ${GROUP_META[g].title.toLowerCase()}…`,
    onkeydown: (e) => { if (e.key === "Enter" && input.value.trim()) { const t = input.value.trim(); input.value = ""; showPage("studio");
      send(`${t}. Only revise these parts: ${list.join(", ")}. Keep every other part exactly as it is.`); } } });
  return input;
}
function grooveLab(list) {
  const lanes = list.filter((n) => session.parts[n].plan);
  const grid = h("div", { class: "glab-grid" }, lanes.map((n) => h("div", { class: "glab-row" }, h("span", {}, n), rackSteps(session.parts[n].plan))));
  const act = (a, label, icon) => h("button", { class: "glab-btn", onclick: async () => {
    if (a === "keep") { const r = await api("/api/groove", { action: "keep" }); toast("Drums locked: Veloura won't change them ✓", "ok"); await refreshSession(); return r; }
    showPage("studio"); await withPending(() => api("/api/groove", { action: a }), label + "…"); $("chatScroll").scrollTop = $("chatScroll").scrollHeight; } },
    svg(icon), label);
  return h("div", { class: "glab" }, h("div", { class: "glab-title" }, h("span", { class: "eyebrow" }, "Groove Lab"), h("b", {}, "Find your groove")), grid,
    h("div", { class: "glab-actions" },
      act("bounce", "More bounce", ["M3 17c3 0 3-10 6-10s3 10 6 10 3-6 6-6"]), act("space", "More space", ["M4 12h3M17 12h3M10 12h4"]),
      act("swing", "Add swing", ["M4 16c4-10 12-10 16 0"]), act("new", "Different groove", ["M4 4v6h6", "M20 20v-6h-6", "M5 15a8 8 0 0 0 14 2M19 9A8 8 0 0 0 5 7"]),
      act("authentic", "More authentic", ["M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z"]), act("keep", "Keep this feel", ["M6 11h12v9H6z", "M8 11V8a4 4 0 0 1 8 0v3"])));
}
async function planArrangement() {
  const r = await withPending(() => api("/api/arrangement", {}), "Planning the song…");
  if (r) { await refreshSession(); renderArrangement(); $("arrangement").scrollIntoView({ behavior: "smooth" }); }
}
function renderArrangement() {
  const arr = session.arrangement;
  const box = $("arrangement");
  if (!arr) { put(box, ); return; }
  const total = arr.total_bars, NS = "http://www.w3.org/2000/svg";
  const curve = document.createElementNS(NS, "svg");
  curve.setAttribute("viewBox", `0 0 ${total} 10`); curve.setAttribute("preserveAspectRatio", "none"); curve.setAttribute("class", "energy");
  const pts = arr.sections.flatMap((s) => [[s.start_bar - 1, 10 - s.energy], [s.start_bar - 1 + s.bars, 10 - s.energy]]);
  const pl = document.createElementNS(NS, "polyline"); pl.setAttribute("points", pts.map((p) => p.join(",")).join(" ")); curve.append(pl);
  const groups = ["melody", "drums", "bass", "other"].filter((g) => arr.sections.some((s) => g in s.groups));
  let sel = null;
  const tip = h("div", { class: "arr-tip" }, "Click a section for what to do there.");
  put(box, h("div", { class: "section-label big" }, "Song map"),
    h("div", { class: "arr" }, h("div", { class: "arr-curve" }, curve),
      h("div", { class: "arr-sections" }, arr.sections.map((s) => h("button", { class: "arr-sec", style: `flex:${s.bars}`, onclick: (e) => {
        if (sel) sel.classList.remove("sel"); sel = e.currentTarget; sel.classList.add("sel");
        put(tip, h("b", {}, `${s.name} · bars ${s.start_bar}–${s.start_bar + s.bars - 1}`), " ", s.tip,
          h("button", { class: "btn tiny", onclick: () => { showPage("studio"); send(`Make a ${s.name.toLowerCase()} variation of the melody for bars ${s.start_bar}-${s.start_bar + s.bars - 1}: same chords, ${s.energy >= 8 ? "more energy" : "stripped back"}. Name it "${Object.keys(session.parts).find((n) => GROUP_OF[session.parts[n].role] === "melody") || "Melody"} (${s.name})".`); } }, "Write a " + s.name.toLowerCase() + " version"));
      } }, h("b", {}, s.name), h("small", {}, `${s.bars} bars`),
        groups.map((g) => h("i", { class: "arr-cell " + (s.groups[g] || "off"), style: `--gc:${GROUP_META[g].color}`, title: `${GROUP_META[g].title}: ${s.groups[g] || "off"}` }))))),
      h("div", { class: "arr-legend" }, groups.map((g) => h("span", { style: `--gc:${GROUP_META[g].color}` }, h("i", {}), GROUP_META[g].title)),
        h("span", { class: "muted" }, `${total} bars · plays your ${arr.loop_bars}-bar loop`))),
    tip, h("ol", { class: "arr-how" }, arr.how.map((t) => h("li", {}, t))));
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
function renderSounds() {
  if (!libState) { refreshLibrary(); return; }
  const L = libState;
  put($("libTop"), 
    h("div", { class: "lib-folders" }, L.folders.length ? L.folders.map((f) => h("div", { class: "lf" + (f.exists ? "" : " gone") },
      svg(["M3 7h6l2 2h10v10H3z"]), h("div", {}, h("b", {}, f.name), h("small", {}, f.exists ? `${f.count} sounds` : "Folder not found")),
      h("button", { class: "icon-btn", title: "Remove from library (files stay where they are)", onclick: async () => { libState = await api("/api/library/remove-folder", { path: f.path }); renderSounds(); } }, svg(["M6 6l12 12M18 6L6 18"]))))
      : h("div", { class: "lf empty" }, "No folders yet")),
    h("div", { class: "lib-actions" },
      h("button", { class: "btn primary glow", onclick: async () => { const r = await api("/api/library/add-folder", {}).catch((e) => toast(e.message, "err")); if (r && r.ok) { toast("Scanning " + r.folder.split("/").pop() + "…"); refreshLibrary(); } } }, "Add a folder"),
      L.folders.length ? h("button", { class: "btn", disabled: !!L.scanning, onclick: async () => { await api("/api/library/scan", {}); refreshLibrary(); } }, "Rescan") : null),
    L.scanning ? h("div", { class: "scan" }, h("span", { class: "eq" }, h("i"), h("i"), h("i")), `${L.scanning.phase}… ${L.scanning.done || 0}/${L.scanning.found || 0}`)
      : L.total ? h("small", { class: "muted" }, `${L.total} sounds · ${L.kits} kits${L.duplicates ? ` · ${L.duplicates} duplicates hidden` : ""} · scanned ${(L.scanned_at || "").slice(5, 16)}`) : null);
  put($("libCats"), ...Object.entries(L.counts).filter(([c, n]) => n || c === "uncertain" && false).map(([c, n]) =>
    h("button", { class: "lcat" + (libCat === c ? " sel" : ""), style: `--cc:${CAT_COLORS[c]}`, onclick: () => { libCat = libCat === c ? null : c; loadLibList(); renderSounds(); } },
      h("b", {}, String(n)), h("span", {}, L.labels[c] || c))));
  if (libCat || libQuery || libHidden) renderLibBrowse(); else put($("libBrowse"), h("button", { class: "btn small ghost", onclick: () => { libHidden = true; loadLibList(); } },
    `Removed sounds${L.hidden ? ` (${L.hidden})` : ""}`));
  renderKitPanel();
  renderStyle();
  renderInstSounds();
}
function renderLibBrowse() {
  const box = $("libBrowse");
  if (!libCat && !libQuery && !libHidden) { put(box); return; }
  const search = h("input", { class: "lsearch", placeholder: "Search names and kits", value: libQuery, oninput: (e) => { libQuery = e.target.value; clearTimeout(window._lq); window._lq = setTimeout(loadLibList, 250); } });
  const cats = Object.keys(CAT_COLORS);
  const hiddenToggle = h("button", { class: "btn small ghost", onclick: () => { libHidden = !libHidden; loadLibList(); } },
    libHidden ? "Back to my sounds" : `Removed sounds${libState && libState.hidden ? ` (${libState.hidden})` : ""}`);
  put(box, h("div", { class: "lib-browse-top" }, search, hiddenToggle), h("div", { class: "lgrid" }, libList.map((s) => h("div", { class: "lsound" + (s.category === "uncertain" ? " unsure" : "") + (s.favorite ? " fav" : "") },
    playBtn(s.id), h("div", { class: "ls-main" }, h("b", {}, s.name), h("small", {}, `${s.kit}${s.duration ? " · " + s.duration.toFixed(2) + "s" : ""}`)),
    libHidden ? h("button", { class: "btn tiny", onclick: async () => { await api("/api/library/hide", { id: s.id, on: false }); toast("Back in your sounds ✓", "ok"); refreshLibrary(); loadLibList(); } }, "Bring back")
      : [favBtn(s.id, s.favorite), hideBtn(s.id, () => { refreshLibrary(); loadLibList(); })],
    h("select", { title: s.corrected ? "You set this" : `Sorted by ${s.source}`, onchange: async (e) => { await api("/api/library/set-category", { id: s.id, category: e.target.value }); toast("Moved to " + e.target.value); refreshLibrary(); } },
      cats.map((c) => h("option", { value: c, selected: c === s.category }, (libState.labels[c] || c))))))),
    libList.length ? null : h("p", { class: "muted" }, "No sounds here."));
}
function renderKitPanel() {
  const box = $("kitPanel");
  if (!libState || !libState.total) { put(box, h("p", { class: "muted" }, "Add a drum folder above and Veloura will build kits from it.")); return; }
  const genreSel = h("select", {}, GENRES.filter((g) => g !== "other").map((g) => h("option", { value: g, selected: g === session.settings.genre }, (genreInfo[g] || {}).label || g)));
  const pick = async (keep, exclude) => { kitState = await api("/api/kit/choose", { genre: genreSel.value, keep, exclude }); store.set("kitState", kitState); renderKitPanel(); };
  const roles = (kitState && kitState.roles) || {};
  put(box, h("div", { class: "kit-controls" }, genreSel, h("button", { class: "btn primary", onclick: () => pick() }, kitState ? "New kit" : "Pick a kit")),
    Object.keys(roles).length ? h("div", { class: "kit-row big" }, Object.entries(roles).map(([r, s]) => h("div", { class: "ksound" }, playBtn(s.id),
      h("div", {}, h("small", {}, ROLE_LABEL[r] || r), h("b", {}, s.name), h("span", {}, s.kit)),
      h("div", { class: "kbtns" },
        favBtn(s.id, s.favorite),
        hideBtn(s.id, () => { const keep = {}; for (const [k, v] of Object.entries(roles)) if (k !== r) keep[k] = v.id; pick(keep, [s.id]); }),
        h("button", { class: "icon-btn", title: "Swap for another", onclick: () => { api("/api/kit/feedback", { id: s.id, verdict: "rejected", role: r }); const keep = {}; for (const [k, v] of Object.entries(roles)) if (k !== r) keep[k] = v.id; pick(keep, [s.id]); } }, svg(["M4 4v6h6", "M20 20v-6h-6", "M5 15a8 8 0 0 0 14 2M19 9A8 8 0 0 0 5 7"])))))) : null,
    Object.keys(roles).length ? h("div", { class: "row-btns" }, h("button", { class: "btn primary glow", onclick: () => stageKit(roles) }, "Load into FL")) : null);
}
let styleState = null;
async function renderStyle() {
  try { styleState = await api("/api/style", {}); } catch (_) { return; }
  const st = styleState;
  put($("stylePanel"), h("p", { class: "muted" }, "Give Veloura MIDI files of beats you love (yours or MIDI packs). It learns their drum grooves, chords and rhythms, then writes in that feel. Put files in folders named after the genre (e.g. “plugg”) to sort them."),
    h("div", { class: "row-btns" }, h("button", { class: "btn primary", onclick: async () => {
      const r = await withPending(() => api("/api/style/import", {}), "Learning from your MIDI…");
      if (r && r.ok) toast(`Learned from ${r.added} file(s)${r.skipped.length ? ` (${r.skipped.length} skipped)` : ""} ✓`, "ok"); renderStyle(); } }, "Add a MIDI folder"),
      st.total ? h("span", { class: "muted" }, `${st.grooves} grooves · ${st.melodies} chord/melody ideas`) : null),
    st.items.length ? h("div", { class: "style-list" }, st.items.slice().reverse().slice(0, 40).map((i) => h("div", { class: "style-item" },
      h("b", {}, i.file), h("small", {}, [i.genre || "any genre", i.groove ? "groove" : null, i.key, (i.melody || []).join(" ")].filter(Boolean).join(" · ")),
      h("button", { class: "icon-btn", title: "Forget this one", onclick: async () => { await api("/api/style/remove", { id: i.id }); renderStyle(); } }, svg(["M6 6l12 12M18 6L6 18"]))))) : null);
}
function renderInstSounds() {
  const chans = ((status && status.controller && status.controller.channels) || []).filter((c) => c.type === "plugin" || c.type === "hybrid");
  put($("instSounds"), ...(chans.length ? chans.map((c) => h("button", { class: "inst", onclick: (e) => openSounds(e.currentTarget, c) },
    svg(ICONS.melody), h("b", {}, c.name), h("small", {}, "Choose a sound"))) : [h("p", { class: "muted" }, "Instrument plugins in your Channel Rack (FLEX, ZENOLOGY…) show up here once FL is connected.")]));
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
