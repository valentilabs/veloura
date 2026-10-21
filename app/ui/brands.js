// Brand marks for the AI options, so each one looks like its own company. Official logo files (the developer's "good logos",
// 2026-10-21) in app/ui/brand/; the marks belong to OpenAI, Anthropic and Google and only name their services.
// Fonts: the companies' own typefaces (OpenAI Sans, Anthropic's Styrene/Tiempos, Google Sans) aren't licensed for
// bundling, so the cards use the Mac's system fonts: SF Pro for ChatGPT and Gemini, New York (ui-serif) for Claude.
"use strict";
const BRAND_FILES = { chatgpt: "chatgpt", anthropic: "claude", "claude-code": "claude", gemini: "gemini" };
function brandImage(file, size, cls) {
  const img = document.createElement("img");
  img.src = "brand/" + file + ".png";
  img.alt = "";
  img.setAttribute("aria-hidden", "true");
  img.className = cls;
  if (size) { img.width = size; img.height = size; }
  return img;
}
// Veloura's own mark for Offline: the icon's seven bars on its blue tile.
function velouraLogo(size) {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("width", size || 22); svg.setAttribute("height", size || 22);
  svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", "brand-logo logo-veloura");
  const tile = document.createElementNS(NS, "rect");
  Object.entries({ x: 0, y: 0, width: 24, height: 24, rx: 6.5, fill: "#2c4282" }).forEach(([k, v]) => tile.setAttribute(k, v));
  svg.appendChild(tile);
  [161, 315, 474, 412, 230, 358, 199].forEach((h, i) => {   // bar heights from the app icon (of 1024)
    const r = document.createElementNS(NS, "rect"), hh = h / 1024 * 24 * 1.15;
    Object.entries({ x: 4.6 + i * 2.2, y: 12 - hh / 2, width: 1.3, height: hh, rx: 0.65, fill: "#d9dde4" }).forEach(([k, v]) => r.setAttribute(k, v));
    svg.appendChild(r);
  });
  return svg;
}
function brandLogo(id, size) {
  if (id === "offline") return velouraLogo(size);
  const key = BRAND_FILES[id];
  return key ? brandImage(key + "-mark", size || 22, "brand-logo logo-" + key) : null;
}
// The company's full logo (mark + name), for light surfaces only (the Claude and Gemini files have white backgrounds).
function brandWordmark(id, height) {
  const key = BRAND_FILES[id];
  if (!key) return null;
  const img = brandImage(key + "-wordmark", null, "brand-wordmark wordmark-" + key);
  img.style.height = (height || 28) + "px";
  return img;
}
