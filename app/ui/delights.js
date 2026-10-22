// Small delights (2026-10-21): little touches that make Veloura feel alive. All of them stay out of the way, respect
// Reduce Motion, and never touch FL or the music.
"use strict";
(function () {
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // A champagne star burst at a point on the screen.
  function burst(x, y, count) {
    if (calm) return;
    const layer = document.createElement("div");
    layer.className = "vl-burst";
    layer.style.left = x + "px"; layer.style.top = y + "px";
    for (let i = 0; i < (count || 10); i++) {
      const s = document.createElement("i");
      const a = (Math.PI * 2 * i) / (count || 10) + Math.random() * .5, r = 26 + Math.random() * 30;
      s.style.setProperty("--dx", Math.cos(a) * r + "px"); s.style.setProperty("--dy", Math.sin(a) * r + "px");
      s.style.setProperty("--s", (.5 + Math.random() * .7).toFixed(2));
      s.style.animationDelay = (Math.random() * 80) + "ms";
      layer.appendChild(s);
    }
    document.body.appendChild(layer);
    setTimeout(() => layer.remove(), 1100);
  }
  window.vlBurst = burst;

  // 1. (The Studio eyebrow is set by workspace.js heroEyebrow: time of day plus session context.)

  // 2. Click the logo five times quickly: a burst and a small note from the people who made it.
  const brand = document.getElementById("brandBtn");
  if (brand) {
    let clicks = [];
    brand.addEventListener("click", (e) => {
      const now = Date.now();
      clicks = clicks.filter((t) => now - t < 2000).concat(now);
      if (clicks.length >= 5) {
        clicks = [];
        const r = brand.getBoundingClientRect();
        burst(r.left + r.width / 2, r.top + r.height / 2, 16);
        if (typeof toast === "function") toast("✦ Made with care by Valenti Labs. Go make something great.", "ok");
      }
    });
  }

  // 3. A sparkle when a part lands in FL.
  if (typeof landed === "function") {
    const _landed = landed;
    landed = function (ok, text) {   // eslint-disable-line no-global-assign
      _landed(ok, text);
      if (ok) { const el = document.getElementById("landed"); if (el) { const r = el.getBoundingClientRect(); burst(r.left + 26, r.top + r.height / 2, 10); } }
    };
  }

  // 4. Notes drifting slowly behind the Studio headline.
  const hero = document.getElementById("heroTitle");
  if (hero && !calm) {
    const sky = document.createElement("div");
    sky.className = "vl-notes"; sky.setAttribute("aria-hidden", "true");
    ["♪", "♫", "✦", "♩", "♪"].forEach((ch, i) => {
      const n = document.createElement("span");
      n.textContent = ch;
      n.style.left = (8 + i * 21) + "%"; n.style.animationDelay = (i * 2.3) + "s"; n.style.animationDuration = (11 + (i % 3) * 3) + "s";
      sky.appendChild(n);
    });
    hero.appendChild(sky);
  }

  // 5. A signature at the bottom of Help, with the little plug drawing tucked in.
  const help = document.querySelector("#page-help .help");
  if (help && typeof unpluggedScene === "function") {
    const sig = document.createElement("div");
    sig.className = "vl-signature";
    const art = unpluggedScene(64); art.classList.add("mini");
    sig.append(art, Object.assign(document.createElement("span"), { textContent: "Made with care by Valenti Labs ✦" }));
    help.appendChild(sig);
  }
})();
