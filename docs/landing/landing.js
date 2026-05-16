/* =========================================================
   Spine landing — vanilla ES2020+, no framework, no CDN.
   - Boots theme from prefers-color-scheme + localStorage
   - Loads demo-script.json and animates the 5-move dialogue
   - Smooth scroll for nav links
   - Respects prefers-reduced-motion (skips typewriter pacing)
   ========================================================= */

(() => {
  "use strict";

  /* ---------- Theme handling ---------- */
  const root = document.documentElement;
  const toggleBtn = document.getElementById("theme-toggle");
  const themeIcon = toggleBtn?.querySelector(".theme-icon");
  const STORAGE_KEY = "spine.landing.theme";

  const initialTheme = (() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "light" || stored === "dark") return stored;
    } catch (_) { /* private mode */ }
    return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
  })();
  applyTheme(initialTheme);

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    if (themeIcon) themeIcon.textContent = theme === "light" ? "sun" : "moon";
    if (toggleBtn) toggleBtn.setAttribute("aria-pressed", String(theme === "light"));
  }

  toggleBtn?.addEventListener("click", () => {
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    applyTheme(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch (_) { /* ignore */ }
  });

  /* ---------- Smooth scroll for nav anchors ---------- */
  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (ev) => {
      const id = link.getAttribute("href").slice(1);
      const target = id ? document.getElementById(id) : null;
      if (!target) return;
      ev.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      target.setAttribute("tabindex", "-1");
      target.focus({ preventScroll: true });
    });
  });

  /* ---------- Demo player ---------- */
  const terminal = document.getElementById("demo-terminal");
  const moveIndicator = document.getElementById("move-indicator");
  const btnPlay = document.getElementById("demo-play");
  const btnPause = document.getElementById("demo-pause");
  const btnStep = document.getElementById("demo-step");
  const btnReset = document.getElementById("demo-reset");

  if (!terminal || !btnPlay) return;

  const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const TYPE_DELAY_MS = reducedMotion ? 0 : 14;
  const PAUSE_BETWEEN_TURNS_MS = reducedMotion ? 0 : 700;

  let script = null;
  let currentTurn = 0;
  let isPlaying = false;
  let cancelToken = 0;
  let activeTurnEl = null;

  fetch("demo-script.json")
    .then((r) => {
      if (!r.ok) throw new Error(`demo-script.json: HTTP ${r.status}`);
      return r.json();
    })
    .then((data) => {
      script = data;
      renderEmpty();
    })
    .catch((err) => {
      terminal.textContent = `Could not load demo script (${err.message}). The dialogue file lives at docs/landing/demo-script.json.`;
      btnPlay.disabled = true;
      btnStep.disabled = true;
    });

  function renderEmpty() {
    terminal.innerHTML = "";
    const hint = document.createElement("p");
    hint.className = "demo-turn";
    hint.innerHTML = `<em>Scenario: ${escapeHtml(script.scenario)}</em><br><span class="turn-move">Press <strong>Play</strong> to start the 5-move dialogue. <strong>Step</strong> advances one turn at a time.</span>`;
    terminal.appendChild(hint);
    updateMoveIndicator(0);
  }

  function updateMoveIndicator(moveNum) {
    moveIndicator.textContent = `Move ${moveNum} / 5`;
  }

  function makeTurnElement(turn) {
    const el = document.createElement("p");
    el.className = `demo-turn ${turn.actor}`;
    const prefix = turn.actor === "user" ? "user" : "product";
    el.innerHTML = `<span class="turn-prefix">${prefix}</span><span class="turn-move">Move ${turn.move} — ${escapeHtml(turn.label)}</span><span class="turn-text cursor-blink"></span>`;
    return el;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  async function typeInto(el, text, token) {
    const textNode = el.querySelector(".turn-text");
    textNode.textContent = "";
    if (TYPE_DELAY_MS === 0) {
      textNode.textContent = text;
      textNode.classList.remove("cursor-blink");
      return;
    }
    for (let i = 0; i < text.length; i++) {
      if (token !== cancelToken) return;
      textNode.textContent += text[i];
      const delay = ",.;:!?".includes(text[i]) ? TYPE_DELAY_MS * 4 : TYPE_DELAY_MS;
      await sleep(delay);
      terminal.scrollTop = terminal.scrollHeight;
    }
    textNode.classList.remove("cursor-blink");
  }

  function sleep(ms) { return new Promise((res) => setTimeout(res, ms)); }

  async function playFromCurrent() {
    if (!script) return;
    const token = ++cancelToken;
    isPlaying = true;
    setControlState(true);

    while (currentTurn < script.turns.length) {
      if (token !== cancelToken) { isPlaying = false; setControlState(false); return; }
      await advanceOneTurn(token);
      if (token !== cancelToken) return;
      await sleep(PAUSE_BETWEEN_TURNS_MS);
    }

    isPlaying = false;
    setControlState(false);
    btnPlay.disabled = true;
  }

  async function advanceOneTurn(token) {
    if (!script || currentTurn >= script.turns.length) return;
    const turn = script.turns[currentTurn];
    const el = makeTurnElement(turn);
    terminal.appendChild(el);
    if (activeTurnEl) {
      activeTurnEl.querySelector(".turn-text")?.classList.remove("cursor-blink");
    }
    activeTurnEl = el;
    updateMoveIndicator(turn.move);
    terminal.scrollTop = terminal.scrollHeight;
    await typeInto(el, turn.text, token);
    currentTurn++;
  }

  function setControlState(playing) {
    btnPlay.disabled = playing || (script && currentTurn >= script.turns.length);
    btnPause.disabled = !playing;
    btnStep.disabled = playing || !script;
  }

  function resetDemo() {
    cancelToken++;
    isPlaying = false;
    currentTurn = 0;
    activeTurnEl = null;
    if (script) renderEmpty();
    btnPlay.disabled = false;
    btnPause.disabled = true;
    btnStep.disabled = false;
  }

  btnPlay.addEventListener("click", () => {
    if (script && currentTurn === 0) terminal.innerHTML = "";
    playFromCurrent();
  });
  btnPause.addEventListener("click", () => { cancelToken++; isPlaying = false; setControlState(false); });
  btnStep.addEventListener("click", async () => {
    if (isPlaying) return;
    if (script && currentTurn === 0) terminal.innerHTML = "";
    const token = ++cancelToken;
    setControlState(false);
    btnStep.disabled = true;
    await advanceOneTurn(token);
    setControlState(false);
  });
  btnReset.addEventListener("click", resetDemo);
})();
