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
