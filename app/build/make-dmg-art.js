// Renders the Veloura-Beta.dmg window background (Deep Sable, Electric Champagne, Instrument Serif) into
// dmg-background.png (660x420) and dmg-background@2x.png, combined into dmg-background.tiff for Retina.
// Run: npx electron build/make-dmg-art.js   (icon spots used by make-dmg.sh: app at 170,200 and Applications at 490,200)
const { app, BrowserWindow } = require("electron");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const font = path.join(__dirname, "..", "ui", "fonts", "InstrumentSerif-Regular.ttf");
const html = `<!doctype html><meta charset="utf-8"><style>
@font-face { font-family: Serif; src: url("file://${font}"); }
html, body { margin: 0; width: 660px; height: 420px; overflow: hidden; }
body { background: radial-gradient(420px 260px at 50% 30%, rgb(255 209 123 / .10), transparent 70%), #17181F;
  font-family: -apple-system, "SF Pro Text", sans-serif; color: #FFF8ED; }
h1 { position: absolute; top: 30px; width: 100%; text-align: center; margin: 0; font: 400 40px/1 Serif; letter-spacing: .01em;
  background: linear-gradient(180deg, #FFF8ED 30%, #FFD17B); -webkit-background-clip: text; color: transparent; }
.by { position: absolute; top: 76px; width: 100%; text-align: center; font-size: 11px; letter-spacing: .22em; text-transform: uppercase; color: #C4B8BB; }
svg { position: absolute; left: 262px; top: 186px; }
.hint { position: absolute; top: 318px; width: 100%; text-align: center; font-size: 13px; color: #C4B8BB; }
.hint b { color: #FFD17B; font-weight: 600; }
.line { position: absolute; bottom: 24px; left: 210px; right: 210px; height: 1px; background: linear-gradient(90deg, transparent, rgb(255 209 123 / .35), transparent); }
</style><h1>Veloura</h1><div class="by">by Valenti Labs · Beta</div>
<svg width="136" height="34" viewBox="0 0 136 34"><path d="M6 17c34-1.5 74-1.4 114 .4" fill="none" stroke="#FFD17B" stroke-width="2.4" stroke-linecap="round"/>
<path d="M108 7c5 3.6 9.6 6.8 14 10.2-4.6 3.4-9.1 6.6-13.6 10" fill="none" stroke="#FFD17B" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
<div class="hint">Drag <b>Veloura</b> into <b>Applications</b></div><div class="line"></div>`;
app.disableHardwareAcceleration();   // plain software rendering is enough for a still image
app.whenReady().then(async () => {
  try {
    const page = path.join(require("os").tmpdir(), "veloura-dmg-art.html");
    fs.writeFileSync(page, html);
    const win = new BrowserWindow({ show: false, width: 660, height: 420, useContentSize: true, paintWhenInitiallyHidden: true });
    await win.loadFile(page);
    for (const [scale, file] of [[1, "dmg-background.png"], [2, "dmg-background@2x.png"]]) {
      win.setContentSize(660 * scale, 420 * scale);
      win.webContents.setZoomFactor(scale);
      await new Promise((r) => setTimeout(r, 900));   // let the font load and the zoom apply
      const img = await win.webContents.capturePage();
      fs.writeFileSync(path.join(__dirname, file), img.resize({ width: 660 * scale, height: 420 * scale, quality: "best" }).toPNG());
    }
    win.destroy();
    execFileSync("/usr/bin/tiffutil", ["-cathidpicheck", path.join(__dirname, "dmg-background.png"),
      path.join(__dirname, "dmg-background@2x.png"), "-out", path.join(__dirname, "dmg-background.tiff")]);
  } catch (e) { console.error(e); process.exitCode = 1; }
  app.quit();
});
