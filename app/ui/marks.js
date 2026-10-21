// Veloura's small hand-drawn-style line illustrations for empty states (original drawings, 2026-10-21).
// Thin champagne strokes, slightly uneven like ink on paper. illustration(name) -> <svg>.
"use strict";
const ILLUSTRATIONS = {
  // a cable whose plug isn't in yet (Channel Rack not connected)
  cable: ["M8 52c10-1 16-9 22-18s13-16 24-15", "M54 19.5l7.5-.6.4 9.2-7.6.7z", "M61.8 21.4l5 .2M62 26.6l5.1-.1",
          "M73 23.6c3-.3 6-.1 9 .5", "M78 14.8l3.2 3.6M79 31.6l3.3-3.2"],
  // a record, ready to spin (empty beat)
  vinyl: ["M44 12c18 0 31 13.5 31 31s-13 31-31 31-31-13.6-31-31 13.4-31 31-31z", "M44 26c9.6.2 16.8 7.6 16.8 17s-7.4 16.9-16.8 16.9",
          "M44 39.6c2 0 3.5 1.5 3.5 3.4s-1.5 3.5-3.5 3.5-3.4-1.6-3.4-3.5 1.5-3.4 3.4-3.4z", "M66 16l10-6 4 7-9 7"],
  // a pencil and three notes, the first sketch of an idea (nothing in FL yet)
  sketch: ["M12 60l30-30 7 7-30 30-9 2z", "M38 34l7 7", "M58 22v20.5", "M58 42.5c-2.4-1.9-7-.6-7.4 2.3-.3 2.4 3.6 3.6 6 2.3 1-.6 1.4-1.6 1.4-2.6",
           "M58 22c5 .6 9.2 2.8 11 6.6", "M72 40v14", "M72 54c-2.2-1.7-6.4-.5-6.8 2.1-.2 2.2 3.3 3.3 5.5 2.1 .9-.5 1.3-1.4 1.3-2.4",
           "M72 40c3.4.4 6.4 1.8 7.8 4.4"],
};
function illustration(name, size) {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 88 88"); svg.setAttribute("width", size || 76); svg.setAttribute("height", size || 76);
  svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", "illo illo-" + name);
  for (const d of ILLUSTRATIONS[name] || []) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.appendChild(p);
  }
  return svg;
}

// "Not connected" scene: a cable and plug that keep reaching for FL's socket, a little spark in the gap, then pull back.
function unpluggedScene(size) {
  const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 160 80"); svg.setAttribute("width", size || 150); svg.setAttribute("height", (size || 150) / 2);
  svg.setAttribute("aria-hidden", "true"); svg.setAttribute("class", "unplugged");
  const el = (tag, attrs, parent) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); (parent || svg).appendChild(n); return n; };
  // the socket (FL), fixed on the right
  const socket = el("g", { class: "up-socket" });
  el("rect", { x: 112, y: 22, width: 34, height: 36, rx: 9 }, socket);
  el("path", { d: "M124 34v12M134 34v12" }, socket);
  el("text", { x: 129, y: 72, "text-anchor": "middle", class: "up-label" }, socket).textContent = "FL";
  // the plug and its cable, which slide together
  const plug = el("g", { class: "up-plug" });
  el("path", { d: "M6 52c14 0 20-12 34-12h22", class: "up-cable" }, plug);
  el("rect", { x: 62, y: 29, width: 28, height: 22, rx: 6 }, plug);
  el("path", { d: "M90 35h9M90 45h9" }, plug);
  // the spark that flickers in the gap
  const spark = el("g", { class: "up-spark" });
  el("path", { d: "M104 30l2 6M108 40h6M104 50l2-6" }, spark);
  return svg;
}
