# Veloura Beta

An AI music producer for **FL Studio 2024 and FL Studio 2026 on macOS** (Apple silicon), by Valenti Labs. You chat with it; it drafts melodies, 808s and drum lanes,
shows a preview, and writes **real, editable notes into FL Studio**, then reads them back to verify. What it can't
automate, it walks you through step by step. Anything can also be exported as a MIDI file.

## Launch

* **App:** `/Applications/Veloura.app`. It is self-contained (its own Python and Veloura's code); your data lives in
  `~/Library/Application Support/Veloura`.
* **Development:** `cd app && npm start`
* Build the app: `cd app && npm run package:clean` (builds from git outside iCloud; output in
  `~/Library/Caches/Cadence Build/dist`).
* Share a build: `ditto -c -k --sequesterRsrc --keepParent "Veloura Beta 0.9.0" Veloura-Beta-0.9.0.zip` (never plain `zip`, which
  breaks Electron's framework links). The build signs everything inside-out and checks that a zipped, downloaded copy
  verifies; an unsigned beta then gets macOS's "Open Anyway" prompt instead of "damaged".
* Developer mode (the developer's copy only): create `~/Library/Application Support/Veloura/dev_mode` to get the personal Claude
  Code provider and Opus as the default. Customer builds never include it.

Only one Veloura can run at a time. Quitting Veloura also stops its background service; FL Studio is never affected.

## Using Veloura

The app has five tabs (left rail):

* **Studio**: four ways to start a beat (tabs at the top): **Describe** it in your own words, pick a **Genre**
  (trap, plugg, rage, jerk, drill, melodic trap, cloud rap, boom bap, R&B, Detroit, pop), drop in a **Sample** to build
  around (Veloura finds its tempo, key and chords, and shows you how to load it on a channel), or drop in an
  **Inspiration** song to sound like (Veloura studies its tempo, key, groove, tone and drum pattern, and makes something
  original). The control strip sets tempo (slider, ±1 arrows, type box, Set in FL), key and bars (Auto picks what suits
  the genre) and genre, and shows the sounds in your Channel Rack. Veloura writes parts for the channels you've
  loaded. Drums preview like FL's Channel Rack and melodies like its Piano Roll.
  **Add to FL** writes a part, **Undo** takes it back, and **Add everything to FL** adds all parts (drums first, then
  prompts for each Piano Roll). FL's tempo is matched automatically.
* **Tracks**: everything Veloura has put into FL, with *Previous version*, *Remove from FL* and *Save MIDI*.
* **Setup**: a five-step checklist that checks itself live (AI, Accessibility, FL's one-time MIDI setup, the bridge, your
  kit folder). It opens automatically on first launch.
* **Settings**: AI provider and keys, project defaults, maintenance and the activity log.
* **Help**: how it works, good prompts, troubleshooting.

The status light at the bottom of the rail reads **Ready**, **Wake up** (run veloura_bridge once since FL started),
**No drums** (controller not connected), **Setup** or **FL closed**. Click it to open Setup.

## How it works

```
Veloura.app (Electron window)
   └─ starts ─► Python service (127.0.0.1 only, per-launch token)           veloura/service.py
                  ├─ AI layer: offline composer | Claude API | Claude Code    veloura/ai.py, composer.py
                  ├─ validation of every musical plan                         veloura/melody_plan.py
                  ├─ Piano Roll bridge ─ files + Cmd+Opt+Y ─► veloura_bridge.pyscript (in FL)
                  └─ Controller link ─ SysEx over Veloura's virtual MIDI ports ─► Veloura Controller (FL MIDI script)
```

* **Melodies, 808s, chords → Piano Roll bridge.** Veloura writes into **the Piano Roll you have open and focused**.
  (FL gives scripts no way to choose which channel the Piano Roll shows, so you pick it by opening it.) A first write
  only goes into an empty Piano Roll unless you allow it. A revision swaps Veloura's previous notes for the new ones in
  one step, and is refused if you edited those notes. Every write is checked twice: FL's readback, then a separate
  snapshot.
* **Drums → step sequencer** (needs the Controller, below). Lanes are matched by name to channels you already loaded
  ("Kick", "Snare", "Hat"…) and written into the current pattern, with a named FL undo point. Lanes with 1/32 rolls go
  through that channel's Piano Roll instead. Without the Controller, every drum lane uses the Piano Roll path.
* **Undo:** one Cmd+Z in FL reverses any Veloura write: Piano Roll notes and step-sequencer drums (both verified).
  In the app, **Remove** puts things back exactly as they were before Veloura, and **Revert** restores the previous
  version. Your own notes and steps are left alone either way.

## Tip

**Best way to get a melody:** load the sound you want into the Channel Rack first, then tell Veloura which chords to add to it, e.g. *"add slow string chords in ZENOLOGY 2"*.

## If Veloura can't connect to FL

Do these in order (the app shows the same steps in Setup, Help and its connection messages):

1. Quit FL Studio and quit Veloura.
2. Open Veloura first.
3. Then open FL Studio.
4. Open your project.
5. Go straight to the Piano Roll.
6. Link the bridge (Tools ▸ Scripts ▸ veloura_bridge).

## One-time setup

1. **FL bridge.** Already installed (`veloura_bridge.pyscript` and `veloura_io/` in FL's *Piano roll scripts* folder).
   **Repair bridge** in the app reinstalls it. After restarting FL, run **Tools ▸ Scripts ▸ veloura_bridge** once from
   any Piano Roll, so that Cmd+Opt+Y ("run last script") runs Veloura's script.
2. **Accessibility** (lets Veloura press Cmd+Opt+Y in FL): System Settings ▸ Privacy & Security ▸ Accessibility,
   enable **Veloura** (for Veloura.app). Development runs from Claude Code use Claude Code's own `claude.app`. You
   grant this; Veloura never changes privacy settings.
3. **Controller (optional, for drums in the step sequencer, tempo and live project info):**
   No macOS setup needed: while Veloura is open it creates two virtual MIDI ports, **Veloura to FL** and
   **FL to Veloura** (macOS 26 no longer shows the IAC Driver in MIDI Studio, so Veloura doesn't rely on it).
   1. Open Veloura first, then FL Studio (if FL was already open, restart it once so it sees the ports).
   2. In FL: **Options ▸ MIDI settings**.
   3. In **Input**, select *Veloura to FL*, set **Controller type** to *Veloura Controller*, enable it, **Port** 10.
   4. In **Output**, select *FL to Veloura*, **Port** 10.
   5. The app's *FL controller* row turns green.
4. **AI provider** (Settings ⚙ in the app):
   * *Google Gemini*: free tier. Get a key at aistudio.google.com ▸ *Get API key*, and paste it into Veloura's Settings
     (stored in your macOS Keychain). Default model `gemini-3.8-flash`. On the free tier Google may use requests to
     improve its products, and there are per-minute and per-day limits.
   * *Offline composer*: rule-based patterns, **not AI**. Free; works now.
   * *Claude (Anthropic API)*: paste an API key from console.anthropic.com in Settings. It is stored in your **macOS
     Keychain**, never in these files. Billed per use by Anthropic. Model default: `claude-opus-5-5`.
   * *Claude Code*: works if the Claude Code CLI is logged in (run it in Terminal and use `/login`).

## Capability matrix (first verified in FL Studio 2024 on 2026-10-13; re-checked in FL Studio 2026)

| Feature | Status |
|---|---|
| Write melody/808/chord notes into the open Piano Roll, verified | **Automated and verified** (20/20 reliability run) |
| Revise / revert / remove Veloura's notes without touching yours | **Automated and verified** in FL |
| One Cmd+Z undoes a Veloura write | **Verified** for Piano Roll adds and step-sequencer drums (2026-10-14) |
| Choose which channel's Piano Roll gets the notes | **Guided**: open it yourself (no FL scripting API for this) |
| Drum lanes into the step sequencer of your loaded channels | **Automated and verified** (2026-10-14: 808 Kick, 808 Snare) |
| Set FL tempo; read channel names, pattern and tempo | **Automated and verified** (2026-10-14) |
| Load samples, plugins, presets; insert effects | **Guided** (Mode B steps); not exposed by FL's scripting API |
| Mixer, plugin parameters, Playlist arrangement | **Not yet supported** (planned; parameters possible via the Controller) |
| Beat critique from audio | **Not yet supported** (Veloura can't hear yet; critiques from notes only) |
| Export any part as a verified MIDI file | **MIDI fallback**: automated and verified |
| AI conversation (Gemini / Claude API / Claude account) | **Built and unit-tested**; needs a key or sign-in to run live |

## Safety and recovery

* Veloura only ever creates or changes its own files: `veloura_bridge.pyscript` and `veloura_io/` (Piano roll
  scripts), `Hardware/Veloura Controller/`, and this folder. It never opens or edits your `.flp` projects, samples or
  other scripts.
* Use a test project until you trust it. Every FL change is checked first, verified afterwards, and logged.
* **If something looks wrong in FL:** press Cmd+Z in FL (undoes Veloura's last write), or use **Revert/Remove** in the
  app. *Read Piano Roll* shows what is really there.
* **If Veloura says "FL did not respond":** focus the target Piano Roll and run *Tools ▸ Scripts ▸ veloura_bridge* once.
  Known risk: Cmd+Opt+Y re-runs the **last** Piano Roll script, so after using another script (Humanize, etc.), run
  veloura_bridge from the menu once before using Veloura again.
* Logs: `logs/attempts.jsonl` (every operation), `data/session.json` (conversation and parts), `DEVLOG.md`
  (what was verified when), `backups/` (known-good bridge script, old README).

## Removing Veloura

Delete these, then optionally this folder:
* `~/Documents/Image-Line/FL Studio/Settings/Piano roll scripts/veloura_bridge.pyscript` and `veloura_io/`
* `~/Documents/Image-Line/FL Studio/Settings/Hardware/Veloura Controller/`
* Keychain item "Veloura Anthropic API key" (Settings ▸ Remove, or Keychain Access)

FL Studio works normally without them.

## Development

* Tests: `python3 -m unittest discover -s tests -v` (FL is **simulated** in tests; real-FL checks are done by hand
  and recorded in `DEVLOG.md`).
* Dependencies (project-local only): `app/node_modules` (Electron, Anthropic SDK, packager) and `.venv`
  (python-rtmidi). Recreate with `cd app && npm install` and
  `python3 -m venv .venv && .venv/bin/pip install python-rtmidi`.
