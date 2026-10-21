// Renders Veloura's app icon from build/veloura-icon.svg (flat Deep Sable tile, champagne bars; make-icon-flat.py writes the SVG) into
// icon.png, icon.iconset and icon.icns. Run: npx electron build/make-icon.js
const { app, BrowserWindow } = require("electron");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const svg = fs.readFileSync(path.join(__dirname, "veloura-icon.svg"), "utf8");
const render = size => `new Promise(res => {
  const img = new Image();
  img.onload = () => { const c = document.createElement("canvas"); c.width = c.height = ${size};
    const g = c.getContext("2d"); g.imageSmoothingQuality = "high"; g.drawImage(img, 0, 0, ${size}, ${size}); res(c.toDataURL("image/png")); };
  img.src = "data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}";
})`;
app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false });
  await win.loadURL("about:blank");
  const write = async (size, file) => {
    const url = await win.webContents.executeJavaScript(render(size));
    fs.writeFileSync(file, Buffer.from(url.split(",")[1], "base64"));
  };
  const set = path.join(__dirname, "icon.iconset");
  fs.mkdirSync(set, { recursive: true });
  await write(1024, path.join(__dirname, "icon.png"));
  for (const s of [16, 32, 128, 256, 512]) {
    await write(s, path.join(set, `icon_${s}x${s}.png`));
    await write(s * 2, path.join(set, `icon_${s}x${s}@2x.png`));
  }
  if (process.platform === "darwin") execFileSync("iconutil", ["-c", "icns", set, "-o", path.join(__dirname, "icon.icns")]);
  app.quit();
});
