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
// Veloura's own mark for Offline / "Other AI": the app icon itself (sable tile, champagne bars).
function velouraLogo(size) { return brandImage("veloura-mark", size || 22, "brand-logo logo-veloura"); }
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
