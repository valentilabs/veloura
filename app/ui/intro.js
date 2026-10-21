// Veloura's opening: the flat blue tile, its seven bars rising and the wordmark, timed to the developer's 3-second startup
// sound (startup.mp3). Plays only when the app asks for it (#intro=1: first launch after the Mac starts, after an
// update, or after 4+ hours away). A click or Esc skips it. With Reduce Motion on it doesn't play.
"use strict";
(function () {
  if (!/(^|[#&])intro=1(&|$)/.test(location.hash)) return;
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const BARS = [161, 315, 474, 412, 230, 358, 199];   // the icon's bar heights (of a 1024 tile)
  const el = document.createElement("div");
  el.id = "intro";
  el.setAttribute("role", "presentation");
  const tile = document.createElement("div");
  tile.className = "intro-tile";
  BARS.forEach((hgt, i) => {
    const b = document.createElement("i");
    b.style.setProperty("--h", (hgt / 824 * 100).toFixed(1) + "%");   // same proportions as the icon
    b.style.setProperty("--d", (0.25 + i * 0.12).toFixed(2) + "s");
    tile.appendChild(b);
  });
  const word = document.createElement("div");
  word.className = "intro-word";
  word.textContent = "Veloura";
  const tag = document.createElement("span");
  tag.textContent = "Beta";
  word.appendChild(tag);
  const hint = document.createElement("div");
  hint.className = "intro-hint";
  hint.textContent = "Click to skip";
  el.append(tile, word, hint);

  const DURATION = 3000;            // the length of startup.mp3
  const audio = new Audio("startup.mp3");
  audio.volume = 0.6;               // the sound plays at a modest level, not full scale
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    el.classList.add("out");
    // fade the sound out with the overlay instead of cutting it
    const v0 = audio.volume, t0 = performance.now();
    const step = () => {
      const k = Math.min(1, (performance.now() - t0) / 400);
      audio.volume = v0 * (1 - k);
      if (k < 1 && !audio.paused) requestAnimationFrame(step); else audio.pause();
    };
    if (!audio.paused) requestAnimationFrame(step);
    setTimeout(() => el.remove(), 420);
  };
  el.addEventListener("click", finish);
  document.addEventListener("keydown", function esc(e) { if (e.key === "Escape") { finish(); document.removeEventListener("keydown", esc); } });
  const mount = () => {
    document.body.appendChild(el);
    audio.play().catch(() => {});   // no sound if the system refuses; the animation still plays
    setTimeout(finish, DURATION);
  };
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
