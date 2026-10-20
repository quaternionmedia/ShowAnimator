// ShowAnimator stage page. Owns transport, fades and the debug panel; the engine module draws.
// Engine contract (see static/engines/canvas2d.js): create(canvas) -> { render(slots, t), resize(w, h), destroy() }
// where each slot is { name, scene, params, blend, opacity } with opacity already faded.

const cfg = window.SHOWANIMATOR_CONFIG;
const params = new URLSearchParams(location.search);
const debugMode = params.get("debug") === "1";
const canvas = document.getElementById("stage");
const cover = document.getElementById("cover");
const statusEl = document.getElementById("status");
const debugEl = document.getElementById("debug");
const sceneById = Object.fromEntries(cfg.engine.scenes.map((s) => [s.id, s]));

let engine = null;
let ws = null;
let lastRev = -1;
let server = { revision: 0, slots: [] };
const view = new Map(); // slot name -> displayed state with fade bookkeeping
let started = false;

function setStatus(text) {
  statusEl.textContent = text;
}

// -- transport ---------------------------------------------------------------

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const q = cfg.token ? `?k=${encodeURIComponent(cfg.token)}` : "";
  return `${proto}://${location.host}/animator/ws/${cfg.slug}${q}`;
}

function connect() {
  ws = new WebSocket(wsUrl());
  ws.onopen = () => {
    lastRev = -1; // a restarted server counts revisions from zero again
    setStatus("connected");
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "state") onState(msg.state);
    else if (msg.type === "error") setStatus(msg.message);
  };
  ws.onclose = (ev) => {
    if (ev.code === 4404) {
      setStatus("link rejected");
      return;
    }
    setStatus("reconnecting…");
    setTimeout(connect, 1000);
  };
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function onState(st) {
  if (st.revision <= lastRev) return; // stale or duplicate
  lastRev = st.revision;
  server = st;
  reconcile();
  setStatus(`connected · rev ${st.revision}`);
  renderDebug();
}

// -- fades -------------------------------------------------------------------
// A slot shown with a different scene fades out (half the fade time), swaps, then fades in.
// Same-scene changes (slider moves) apply immediately. Opacity changes take the fade time.

function reconcile() {
  for (const s of server.slots) {
    let v = view.get(s.name);
    if (!v) {
      v = { scene: null, params: {}, opacity: 0, phase: null, target: s };
      view.set(s.name, v);
    }
    const sameScene = s.scene === v.scene;
    v.target = s;
    if (sameScene) {
      v.params = { ...s.params };
      if (v.phase === "out") v.phase = null; // target came back to the shown scene
    } else if ((s.fade || 0) > 0 && v.opacity > 0) {
      v.phase = "out";
    } else {
      swap(v);
    }
  }
}

function swap(v) {
  v.scene = v.target.scene;
  v.params = { ...v.target.params };
  v.phase = v.scene ? "in" : null;
  if (!v.scene) v.opacity = 0;
}

function step(v, dt) {
  const f = v.target.fade || 0;
  if (v.phase === "out") {
    const d = f / 2;
    v.opacity = d > 0 ? Math.max(0, v.opacity - dt / d) : 0;
    if (v.opacity <= 0) {
      v.opacity = 0;
      swap(v);
    }
    return;
  }
  const goal = v.target.opacity;
  const d = v.phase === "in" ? f / 2 : f;
  if (d <= 0 || v.opacity === goal) {
    v.opacity = goal;
  } else {
    const delta = Math.min(Math.abs(goal - v.opacity), dt / d);
    v.opacity += Math.sign(goal - v.opacity) * delta;
  }
  if (v.opacity === goal) v.phase = null;
}

// -- render loop -------------------------------------------------------------

function resize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(window.innerWidth * dpr);
  canvas.height = Math.round(window.innerHeight * dpr);
  if (engine) engine.resize(canvas.width, canvas.height);
}

let last = performance.now();
const t0 = last;
function frame(now) {
  const dt = (now - last) / 1000;
  last = now;
  const live = [];
  for (const s of server.slots) {
    const v = view.get(s.name);
    if (!v) continue;
    step(v, dt);
    if (v.scene && v.opacity > 0) {
      live.push({ name: s.name, scene: v.scene, params: v.params, blend: s.blend, opacity: v.opacity });
    }
  }
  if (engine) engine.render(live, (now - t0) / 1000);
  requestAnimationFrame(frame);
}

// -- debug panel (?debug=1) --------------------------------------------------

function el(tag, attrs = {}, parent = null) {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  if (parent) parent.appendChild(node);
  return node;
}

function paramInput(spec, value, onChange) {
  const row = el("label");
  el("span", { textContent: spec.label }, row);
  let input;
  if (spec.kind === "color") {
    input = el("input", { type: "color", value }, row);
    input.addEventListener("input", () => onChange(input.value));
  } else {
    input = el("input", { type: "range", min: spec.min, max: spec.max, step: spec.step, value }, row);
    input.addEventListener("input", () => onChange(parseFloat(input.value)));
  }
  input.dataset.key = spec.key;
  return row;
}

function renderDebug() {
  if (!debugMode) return;
  debugEl.hidden = false;
  // Rebuild only when the slot/scene structure changes, so a dragged slider keeps focus.
  const shape = server.slots.map((s) => `${s.name}:${s.scene}`).join("|");
  if (debugEl.dataset.shape === shape) {
    for (const block of debugEl.querySelectorAll("[data-slot]")) {
      const s = server.slots.find((x) => x.name === block.dataset.slot);
      if (!s) continue;
      for (const input of block.querySelectorAll("input[data-key]")) {
        if (document.activeElement !== input && s.params[input.dataset.key] !== undefined) {
          input.value = s.params[input.dataset.key];
        }
      }
      block.querySelector('[data-role="opacity"]').value = s.opacity;
    }
    return;
  }
  debugEl.dataset.shape = shape;
  debugEl.replaceChildren();

  for (const s of server.slots) {
    const scene = sceneById[s.scene];
    const box = el("fieldset", {}, debugEl);
    box.dataset.slot = s.name;
    el("legend", { textContent: `${s.name} · ${scene ? scene.label : s.scene}` }, box);
    const row = el("div", { className: "row" }, box);
    const hide = el("button", { type: "button", textContent: "Hide" }, row);
    hide.addEventListener("click", () => send({ type: "hide", slot: s.name, fade: fadeInput.value }));
    const fadeInput = el("input", { type: "number", min: 0, step: 0.5, value: 0, title: "fade (s)" }, row);
    el("span", { textContent: "s" }, row);
    if (scene) {
      for (const spec of scene.params) {
        box.appendChild(paramInput(spec, s.params[spec.key], (value) =>
          send({ type: "set", slot: s.name, key: spec.key, value })));
      }
    }
    const op = el("label", {}, box);
    el("span", { textContent: "opacity" }, op);
    const opInput = el("input", { type: "range", min: 0, max: 1, step: 0.01, value: s.opacity }, op);
    opInput.dataset.role = "opacity";
    opInput.addEventListener("change", () => send({ type: "apply", slot: s.name, scene: s.scene,
      params: s.params, blend: s.blend, opacity: parseFloat(opInput.value), fade: fadeInput.value }));
    const blend = el("label", {}, box);
    el("span", { textContent: "blend" }, blend);
    el("span", { textContent: s.blend }, blend);
  }

  const add = el("fieldset", {}, debugEl);
  el("legend", { textContent: "apply scene" }, add);
  const slotName = el("input", { type: "text", value: "main", maxLength: 32 }, add);
  const sceneSel = el("select", {}, add);
  for (const sc of cfg.engine.scenes) el("option", { value: sc.id, textContent: sc.label }, sceneSel);
  const go = el("button", { type: "button", textContent: "Apply" }, add);
  go.addEventListener("click", () => send({ type: "apply", slot: slotName.value || "main",
    scene: sceneSel.value, params: {}, blend: "normal", opacity: 1, fade: 0 }));
}

// -- start -------------------------------------------------------------------

async function start() {
  try {
    const mod = await import(cfg.engine.script);
    engine = mod.create(canvas);
  } catch (exc) {
    setStatus(`engine failed: ${exc.message}`);
    return;
  }
  resize();
  window.addEventListener("resize", resize);
  connect();
  requestAnimationFrame(frame);
}

document.getElementById("start").addEventListener("click", () => {
  const root = document.documentElement;
  if (root.requestFullscreen) root.requestFullscreen().catch(() => {});
  cover.classList.add("hidden");
  if (!started) {
    started = true;
  }
});

document.title = `${cfg.name} · ShowAnimator`;
start();
