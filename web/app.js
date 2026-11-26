/* Mirage interface. Talks to Python through window.pywebview.api. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = () => window.pywebview.api;
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
};

let S = { cfg: {}, status: ["loading", ""], muted: false, messages: [], options: {} };
let page = "home";
let settingsSection = "brain";
let memTab = "memories";
let level = 0;

const STATUS_TEXT = {
  loading: "Starting up…", listening: "Listening for “mirage”", awaiting: "I'm listening…",
  thinking: "Thinking…", acting: "Using your PC · Esc stops it", speaking: "Speaking…", muted: "Microphone off", error: "Needs attention",
};

/* ------------------------------------------------------------------ boot */
async function boot() {
  S = await api().get_state();
  wire();
  applyStatus(S.status[0], S.status[1]);
  setMuted(S.muted);
  renderConvo();
  show(S.start_page || "home");
  poll();
  requestAnimationFrame(drawHolo);
}
if (window.pywebview && window.pywebview.api) boot();
else window.addEventListener("pywebviewready", boot);

function poll() {
  api().poll().then(evs => {
    for (const [kind, data] of evs) onEvent(kind, data);
    setTimeout(poll, 80);
  }).catch(() => setTimeout(poll, 600));
}

function wire() {
  $$(".nav").forEach(b => b.addEventListener("click", () => show(b.dataset.page)));
  $("#micBtn").addEventListener("click", () => api().toggle_mute());
  $("#askSend").addEventListener("click", sendAsk);
  $("#askInput").addEventListener("keydown", e => { if (e.key === "Enter") sendAsk(); });
  $$("#memTabs button").forEach(b => b.addEventListener("click", () => { memTab = b.dataset.tab; renderMemory(); }));
  $("#memAdd").addEventListener("click", memAdd);
  $("#memInput").addEventListener("keydown", e => { if (e.key === "Enter") memAdd(); });
  document.addEventListener("click", e => {
    const act = e.target.closest("[data-act]");
    if (act) api()[act.dataset.act]();
  });
}

function show(p) {
  page = p;
  $$(".nav").forEach(b => b.classList.toggle("on", b.dataset.page === p));
  $$(".page").forEach(s => s.classList.toggle("on", s.id === "page-" + p));
  if (p === "memory") renderMemory();
  if (p === "shortcuts") renderShortcuts();
  if (p === "settings") renderSettings();
  if (p === "home") setTimeout(() => $("#askInput").focus(), 50);
}

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), ms);
}
function saved() {
  const s = $("#saved");
  s.textContent = "Saved";
  s.classList.add("show");
  clearTimeout(saved._t);
  saved._t = setTimeout(() => s.classList.remove("show"), 1200);
}
async function setCfg(changes, rerender = false) {
  S.cfg = await api().set_config(changes);
  saved();
  if (rerender) renderSettings();
}

/* ------------------------------------------------------------------ events */
function onEvent(kind, data) {
  switch (kind) {
    case "status": applyStatus(data[0], data[1]); break;
    case "level": level = data; { const m = $("#levelMeter"); if (m) m.style.width = Math.min(100, data * 400) + "%"; } break;
    case "heard": addLine("you", data); break;
    case "reply": addLine("mirage", data); break;
    case "system": addLine("sys", data); break;
    case "muted": setMuted(data); break;
    case "show_page": show(data); break;
    case "state": Object.assign(S, data); if (page === "settings") renderSettings(); break;
    case "memory_changed": case "reminders_changed": if (page === "memory") renderMemory(); break;
    case "toast": toast(data); break;
    case "progress": {
      if (data[0] === "speechState" && S.speech) S.speech.detail = data[1];
      if (data[0] === "localState" && S.local) S.local.detail = data[1];
      const el = $("#" + data[0]); if (el) { el.textContent = data[1]; el.className = "state " + (data[2] || "wait"); }
    } break;
    case "refresh_settings": if (page === "settings") renderSettings(); break;
  }
}

function applyStatus(s, detail) {
  S.status = [s, detail];
  const st = $("#status");
  st.dataset.s = s;
  $("#statusText").textContent = STATUS_TEXT[s] || s;
  const d = $("#statusDetail");
  d.textContent = detail || "";
  d.classList.toggle("err", s === "error");
}
function setMuted(m) {
  S.muted = m;
  const b = $("#micBtn");
  b.classList.toggle("muted", m);
  b.title = m ? "Turn microphone on" : "Mute microphone";
  b.setAttribute("aria-label", b.title);
}

/* ------------------------------------------------------------------ home */
function addLine(who, text) {
  S.messages.push({ who, text, at: new Date().toTimeString().slice(0, 5) });
  if (S.messages.length > 150) S.messages.shift();
  renderConvo();
}
function renderConvo() {
  const c = $("#convo");
  c.textContent = "";
  $(".holo-wrap").classList.toggle("compact", S.messages.length > 0);
  if (!S.messages.length) {
    const chips = ["What's the weather?", "What's on my to-do list?", "Remind me in 10 minutes to stretch",
                   "What do you remember about me?", "Open YouTube"];
    c.append(h("div", { class: "hello" },
      h("h2", {}, "Say “mirage” and ask."),
      h("p", {}, "Or type below. Simple commands run instantly; anything else goes to the brain."),
      h("div", { class: "chips" }, chips.map(t => h("button", { class: "chip", onclick: () => api().send(t) }, t)))));
    return;
  }
  for (const m of S.messages) {
    const cls = m.who === "you" ? "you" : m.who === "mirage" ? "mirage" : "sys";
    c.append(h("div", { class: "line " + cls },
      cls !== "sys" ? h("div", { class: "who" }, (cls === "you" ? "You" : "Mirage") + ", " + m.at) : null,
      h("div", { class: "text" }, m.text)));
  }
  c.scrollTop = c.scrollHeight;
}
function sendAsk() {
  const i = $("#askInput");
  const t = i.value.trim();
  if (!t) return;
  i.value = "";
  api().send(t);
}

/* hologram: the purple headband in gold rings, reacting to voice */
const holo = $("#holo");
const hctx = holo.getContext("2d");
const logo = new Image();
logo.src = "logo.png";
let smooth = 0;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const motes = Array.from({ length: 26 }, () => ({ a: Math.random() * 6.28, r: .55 + Math.random() * .5, s: .1 + Math.random() * .3, z: Math.random() }));

function drawHolo(ts) {
  requestAnimationFrame(drawHolo);
  if (page !== "home" || document.hidden) return;
  const t = reduceMotion ? 0 : ts / 1000;
  const W = holo.width, H = holo.height, cx = W / 2, cy = H * .46;
  const s = S.status[0];
  let target = 0;
  if (s === "awaiting") target = Math.min(1, level * 5);
  else if (s === "speaking") target = .45 + .35 * Math.abs(Math.sin(t * 9) * Math.sin(t * 3.7));
  else if (s === "thinking" || s === "acting") target = .2;
  smooth += (target - smooth) * .25;
  const ring = { listening: "#b794ff", awaiting: "#f2d17e", thinking: "#d9a93f", acting: "#ff9a76", speaking: "#ece3ff",
                 muted: "#6b5a80", error: "#e2574c", loading: "#9d8db5" }[s] || "#b794ff";
  const speed = s === "thinking" || s === "acting" ? 3 : 1;
  hctx.clearRect(0, 0, W, H);

  // glow: an ellipse that fades out well inside the canvas, so no box edge shows
  hctx.save();
  hctx.translate(cx, cy);
  hctx.scale(1, .5);
  const g = hctx.createRadialGradient(0, 0, 8, 0, 0, W * .40);
  g.addColorStop(0, `rgba(139,92,246,${.22 + smooth * .25})`);
  g.addColorStop(.6, `rgba(139,92,246,${.07 + smooth * .08})`);
  g.addColorStop(1, "rgba(139,92,246,0)");
  hctx.fillStyle = g;
  hctx.beginPath(); hctx.arc(0, 0, W * .40, 0, 6.283); hctx.fill();
  hctx.restore();

  // drifting motes
  for (const m of motes) {
    const a = m.a + t * m.s * .4;
    const x = cx + Math.cos(a) * W * .42 * m.r, y = cy + Math.sin(a) * H * .38 * m.r;
    hctx.fillStyle = `rgba(242,209,126,${.15 + .35 * m.z})`;
    hctx.beginPath(); hctx.arc(x, y, 1 + m.z * 1.4, 0, 6.28); hctx.fill();
  }

  // gold rings: elliptical arcs turning in opposite directions
  const arcs = (rx, ry, n, ext, dir, color, w) => {
    hctx.strokeStyle = color; hctx.lineWidth = w; hctx.lineCap = "round";
    for (let i = 0; i < n; i++) {
      const a0 = dir * t * .8 * speed + i * 6.283 / n;
      hctx.beginPath(); hctx.ellipse(cx, cy, rx, ry, 0, a0, a0 + ext); hctx.stroke();
    }
  };
  hctx.strokeStyle = "rgba(217,169,63,.22)"; hctx.lineWidth = 1;
  hctx.beginPath(); hctx.ellipse(cx, cy, W * .38, H * .36, 0, 0, 6.283); hctx.stroke();
  arcs(W * .42, H * .40, 3, .95, 1, ring, 2.5);
  arcs(W * .36, H * .33, 4, .5, -1, "rgba(242,209,126,.75)", 1.5);
  if (s === "thinking" || s === "acting") arcs(W * .31, H * .28, 1, .8, 6, s === "acting" ? "#ffc2a8" : "#f2d17e", 3);

  // ticks around the outside
  hctx.strokeStyle = "rgba(217,169,63,.35)"; hctx.lineWidth = 1;
  for (let i = 0; i < 90; i++) {
    const a = i * 6.283 / 90 + t * .05;
    const k = i % 5 === 0 ? 1.06 : 1.035;
    hctx.beginPath();
    hctx.moveTo(cx + Math.cos(a) * W * .445, cy + Math.sin(a) * H * .425);
    hctx.lineTo(cx + Math.cos(a) * W * .445 * k, cy + Math.sin(a) * H * .425 * k);
    hctx.stroke();
  }

  // the headband
  if (logo.complete && logo.naturalWidth) {
    const breathe = 1 + .02 * Math.sin(t * 2.2) + smooth * .08;
    const lw = W * .46 * breathe, lh = lw * logo.naturalHeight / logo.naturalWidth;
    hctx.save();
    hctx.shadowColor = "rgba(183,148,255,.6)"; hctx.shadowBlur = 18 + smooth * 30;
    if (s === "muted") hctx.globalAlpha = .45;
    hctx.drawImage(logo, cx - lw / 2, cy - lh / 2, lw, lh);
    hctx.restore();
  }

  // voice wave
  const bars = 31, span = W * .40, by = H * .93;
  hctx.fillStyle = ring;
  for (let i = 0; i < bars; i++) {
    const x = cx - span / 2 + span * i / (bars - 1);
    const edge = 1 - Math.abs(i - (bars - 1) / 2) / ((bars - 1) / 2);
    const wob = .5 + .5 * Math.sin(t * 8 + i * .9);
    const bh = H * (.012 + .07 * smooth * wob * (.35 + .65 * edge));
    hctx.fillRect(x - 1.5, by - bh, 3, bh * 2);
  }
}

/* ------------------------------------------------------------------ memory */
let MEM = null;
async function renderMemory() {
  $$("#memTabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === memTab));
  MEM = await api().get_memory();
  $("#vaultName").textContent = MEM.where;
  const ph = { memories: "Something to remember, like: my favourite colour is purple",
               todos: "Add a to-do", reminders: "in 20 minutes to stretch, or at 5 pm to call mom" }[memTab];
  $("#memInput").placeholder = ph;
  const ul = $("#memList");
  ul.textContent = "";
  const items = MEM[memTab];
  if (!items.length) {
    ul.append(h("li", { class: "empty" }, {
      memories: "Nothing remembered yet. Say “mirage, remember that …” or add something above.",
      todos: "No to-dos. Say “mirage, add … to my to-do list”.",
      reminders: "No reminders. Say “mirage, remind me at 5 pm to …”.",
    }[memTab]));
    return;
  }
  for (const it of items) {
    if (memTab === "memories") {
      ul.append(h("li", {}, h("span", { class: "when" }, it.when), h("span", { class: "t" }, it.text),
        h("button", { class: "x", title: "Forget this", "aria-label": "Forget this",
          onclick: () => api().memory_action("forget", it.line).then(renderMemory) }, "✕")));
    } else if (memTab === "todos") {
      ul.append(h("li", { class: it.done ? "done" : "" },
        h("button", { class: "check" + (it.done ? " on" : ""), "aria-label": it.done ? "Mark as not done" : "Mark as done",
          onclick: () => api().memory_action("toggle_todo", it.i).then(renderMemory) }),
        h("span", { class: "t" }, it.text),
        h("button", { class: "x", title: "Delete", "aria-label": "Delete",
          onclick: () => api().memory_action("delete_todo", it.i).then(renderMemory) }, "✕")));
    } else {
      ul.append(h("li", {}, h("span", { class: "when" }, it.when), h("span", { class: "t" }, it.text),
        h("button", { class: "x", title: "Delete reminder", "aria-label": "Delete reminder",
          onclick: () => api().memory_action("delete_reminder", it.id).then(renderMemory) }, "✕")));
    }
  }
}
async function memAdd() {
  const i = $("#memInput");
  const t = i.value.trim();
  if (!t) return;
  const kind = { memories: "remember", todos: "add_todo", reminders: "add_reminder" }[memTab];
  const res = await api().memory_action(kind, t);
  if (res && res.error) { toast(res.error, 4000); return; }
  i.value = "";
  if (res && res.message) toast(res.message);
  renderMemory();
}

/* ------------------------------------------------------------------ shortcuts */
const ACTIONS = [["open", "Open a website, app or file"], ["say", "Say something"], ["type", "Type text"],
                 ["keys", "Press keys (like ctrl+shift+s)"], ["run", "Run a command"]];
function renderShortcuts() {
  const box = $("#shortcutBlocks");
  box.textContent = "";
  const cfg = S.cfg;

  // custom voice commands
  box.append(h("h2", { class: "sec" }, "Your voice commands"),
    h("p", { class: "lede" }, "Make your own: “mirage good morning” could open Spotify, or “mirage studio” could open Roblox Studio."));
  const vc = cfg.voice_commands || [];
  const t1 = h("table", { class: "table" });
  vc.forEach((c, idx) => t1.append(h("tr", {},
    h("td", { class: "k" }, "“" + c.phrase + "”"),
    h("td", { class: "v" }, (ACTIONS.find(a => a[0] === c.action) || [, c.action])[1] + ": " + c.target),
    h("td", { class: "a" }, h("button", { class: "x", "aria-label": "Delete", onclick: () => {
      vc.splice(idx, 1); setCfg({ voice_commands: vc }).then(renderShortcuts); } }, "✕")))));
  if (!vc.length) t1.append(h("tr", {}, h("td", { class: "v", colspan: 3 }, "No voice commands yet.")));
  const ph = h("input", { type: "text", placeholder: "When I say… (e.g. good morning)" });
  const act = h("select", {}, ACTIONS.map(([v, l]) => h("option", { value: v }, l)));
  const tg = h("input", { type: "text", class: "grow", placeholder: "…do this (e.g. spotify: or https://…)" });
  box.append(t1, h("div", { class: "addrow" }, ph, act, tg, h("button", { class: "btn gold", onclick: () => {
    const p = ph.value.trim().toLowerCase().replace(/^mirage[, ]+/, ""), v = tg.value.trim();
    if (!p || !v) { toast("Fill in both the phrase and what it should do."); return; }
    const same = vc.findIndex(c => c.phrase === p);
    if (same >= 0) { vc.splice(same, 1); toast("Replaced your old “" + p + "” command."); }
    vc.push({ phrase: p, action: act.value, target: v });
    setCfg({ voice_commands: vc }).then(renderShortcuts);
  } }, "Add")));

  // name -> target lists
  const lists = [
    ["websites", "Websites", "“mirage open <name>” opens the site.", "Name", "https://…"],
    ["apps", "Apps", "A program name, the full path to an .exe, or a link like discord:", "Name", "C:\\path\\to\\app.exe"],
    ["roblox_games", "Roblox games", "The path to a .rbxl file opens it in Studio; a place ID opens its Roblox page.", "Name", "C:\\path\\to\\game.rbxl"],
    ["spotify_playlists", "Spotify playlists", "“mirage play <name>” or “mirage switch to <name>” opens it in Spotify and starts it. In Spotify, right-click a playlist, then Share, Copy link to playlist.", "Name, e.g. chill", "https://open.spotify.com/playlist/…"],
  ];
  for (const [key, title, lede, p1, p2] of lists) {
    const dict = key === "apps" ? ((cfg.apps || {})[S.system] || {}) : (cfg[key] || {});
    const tbl = h("table", { class: "table" });
    Object.entries(dict).sort().forEach(([k, v]) => tbl.append(h("tr", {},
      h("td", { class: "k" }, k), h("td", { class: "v" }, v),
      h("td", { class: "a" }, h("button", { class: "x", "aria-label": "Delete " + k, onclick: () => {
        delete dict[k]; saveDict(key, dict).then(renderShortcuts); } }, "✕")))));
    if (!Object.keys(dict).length) tbl.append(h("tr", {}, h("td", { class: "v", colspan: 3 }, "Nothing added yet.")));
    const n = h("input", { type: "text", placeholder: p1 }), v = h("input", { type: "text", class: "grow", placeholder: p2 });
    box.append(h("h2", { class: "sec" }, title), h("p", { class: "lede" }, lede), tbl,
      h("div", { class: "addrow" }, n, v, h("button", { class: "btn gold", onclick: () => {
        if (!n.value.trim() || !v.value.trim()) return;
        dict[n.value.trim().toLowerCase()] = v.value.trim();
        saveDict(key, dict).then(renderShortcuts);
      } }, "Add")));
  }

  // built-in commands, each group can be switched off
  const offList = cfg.builtins_off || [];
  box.append(h("h2", { class: "sec" }, "Built-in commands"),
    h("p", { class: "lede" }, "These never use Claude. Turn a group off if it gets in the way: what you say then goes to your own commands or to Claude. Your own voice commands always win over these."));
  const bl = h("div", { class: "builtins" });
  for (const [id, name, examples] of S.builtins || []) {
    const isOn = !offList.includes(id);
    bl.append(h("div", { class: "builtin" + (isOn ? "" : " off") },
      h("div", { class: "who" }, h("b", {}, name), h("small", {}, examples.map(e => "“" + e + "”").join("  "))),
      toggleEl(isOn, v => {
        const next = (cfg.builtins_off || []).filter(x => x !== id);
        if (!v) next.push(id);
        setCfg({ builtins_off: next }).then(renderShortcuts);
      })));
  }
  box.append(bl);
}
function saveDict(key, dict) {
  if (key === "apps") { const all = S.cfg.apps || {}; all[S.system] = dict; return setCfg({ apps: all }); }
  return setCfg({ [key]: dict });
}

/* ------------------------------------------------------------------ settings */
const C = () => S.cfg;
const SECTIONS = [
  { id: "brain", name: "Brain", intro: "What answers when you ask something a shortcut can't handle. Opening apps, timers, reminders, weather and your notes are shortcuts, so they never need the brain.",
    rows: () => [
      seg("brain", "Brain", "Mirage's own brain runs on this PC: free, private, and it works offline.",
          [["local", "Mirage"], ["claude_code", "Claude Code"], ["api", "API key"], ["off", "Off"]], true),
      C().brain === "local" && custom("Mirage's brain", localInstalled() ? "" : "Downloads the engine and an AI model that run on your graphics card.", localCtl),
      C().brain === "local" && seg("local_model", "Model", "Qwen3.5 9B is smarter. Gemma 4 E4B uses less graphics memory and answers faster.",
          ((S.local || {}).models || []).map(m => [m[0], m[1]])),
      C().brain === "local" && localInstalled() && range("brain_idle_minutes", "Free graphics memory after", "When the brain isn't used, it hands graphics memory back for games, and wakes up on the next question.", 1, 30, 1, v => v + " min"),
      C().brain === "local" && toggle("think_hard_claude", "Use Claude for “think hard”", "Start a question with “think hard” for tough ones. With this on and Claude Code set up, Claude answers those; otherwise Mirage's brain takes longer to think it through."),
      C().brain !== "off" && custom("Personality", "How Mirage should come across, in your words. For example: calm and a bit cocky, like the Six-eared Macaque.", () => [areaEl("personality", "Calm, witty, a little playful…")]),
      C().brain !== "off" && row("Let Mirage use my mouse and keyboard", "So it can do things like “open Discord and go to my messages”. Press Esc or move the mouse to stop it. It never types passwords, and asks before sending, deleting or buying anything.",
          toggleEl(C().pc_control !== false, v => setCfg({ pc_control: v }))),
      C().brain === "claude_code" && custom("Claude Code", "Uses your Claude account. Install it once, then log in.", claudeCtl),
      C().brain === "claude_code" && seg("claude_model", "Model", "Fast uses the least of your Claude usage and replies quickest.",
        [["haiku", "Fast"], ["sonnet", "Balanced"], ["opus", "Smartest"]]),
      C().brain === "claude_code" && toggle("claude_power", "Let Claude run commands and edit files", "Allows running commands and creating or editing files. When off, Claude can still search the web, read files, and use Mirage's skills."),
      C().brain === "api" && text("anthropic_api_key", "Anthropic API key", "Pay-per-use. Get one at console.anthropic.com.", "sk-ant-…", true),
      C().brain !== "off" && custom("Try it", "Sends a short test question.", () => [btn("Test brain", () => api().test_brain()), stateEl("brainTest")]),
    ] },
  { id: "listening", name: "Listening", intro: "How Mirage hears you.",
    rows: () => [
      custom("Microphone", "", () => [selectEl(S.options.mics.map(m => [m, m]), C().input_device || "", v => setCfg({ input_device: v || null }), [["", "System default"]]),
                                      btn("↻", () => api().refresh_options().then(() => renderSettings()), "small", "Refresh microphones")]),
      custom("Input level", "Talk, and the bar should move.", () => [h("div", { class: "meter" }, h("i", { id: "levelMeter" }))]),
      text("wake_words_text", "Wake words", "Separate with commas. Add spellings it mishears; remove ones that trigger by accident.", "mirage", false,
           C().wake_words.join(", "), v => setCfg({ wake_words: v.split(",").map(s => s.trim().toLowerCase()).filter(Boolean) })),
      toggle("wake_sound", "Beep when I say “mirage”"),
      range("command_timeout_seconds", "Time to give a command", "After saying just “mirage”.", 3, 15, 1, v => v + " s"),
      row("Keep listening after replies", "Carry on talking without saying “mirage” again. Say “that's all” or “thanks” when you're done.",
          toggleEl(C().follow_up !== false, v => setCfg({ follow_up: v }, true))),
      C().follow_up !== false && range("follow_up_seconds", "Keep listening for", "How long Mirage waits for you after it replies.", 4, 20, 1, v => v + " s"),
      row("Interrupt by talking", C().voice_engine === "mirage"
            ? "Talk over Mirage to cut it off. On speakers, where it can hear itself, start with “mirage” instead."
            : "Talk over Mirage to cut it off. Needs Mirage's own voice (Voice page).",
          toggleEl(C().barge_in !== false, v => setCfg({ barge_in: v }))),
      custom("Hearing", spInstalled() ? "Mirage writes down what you say with NVIDIA Parakeet, on this PC."
                                      : "Install Mirage's own ears for much better hearing. They come with its voice.", () => speechCtl("ears")),
    ] },
  { id: "voice", name: "Voice", intro: "How Mirage talks back.",
    rows: () => [
      seg("reply_mode", "Replies", "Subtitles appear under the hologram in the corner of your screen.",
          [["both", "Voice and subtitles"], ["subtitles", "Subtitles only"], ["voice", "Voice only"]]),
      seg("voice_engine", "Voice engine", "Mirage's own voice runs on this PC. VoiceStudio has to be open to use it.",
          [["mirage", "Mirage"], ["windows", "Windows"], ["voicestudio", "VoiceStudio"]], true),
      C().voice_engine === "windows" && custom("Windows voice", "", () => [selectEl(S.options.voices, C().voice_id || "", v => setCfg({ voice_id: v }).then(() => api().test_voice()), [["", "System default"]])]),
      C().voice_engine === "voicestudio" && custom("VoiceStudio voice", "Voices you design or clone in VoiceStudio appear here.", vsCtl),
      C().voice_engine === "mirage" && custom("Mirage's voice", spInstalled() ? "" : "Installs Mirage's voice and hearing together, about " + ((S.speech || {}).size_mb || 830) + " MB.", () => speechCtl("voice")),
      C().voice_engine === "mirage" && spInstalled() && custom("Voice", "Kokoro voices. Bella is the default.", () => [
        selectEl(S.speech.voices, C().kokoro_voice || "af_bella", v => setCfg({ kokoro_voice: v }, true).then(() => api().test_voice()))]),
      C().voice_engine === "mirage" && spInstalled() && range("voice_pitch", "Pitch", "Lower or higher, keeping the same speed.", -6, 6, 1, v => (v > 0 ? "+" : "") + v, () => api().test_voice()),
      C().voice_engine === "mirage" && spInstalled() && range("voice_robot", "Hologram effect", "Makes the voice sound more robotic.", 0, 100, 5, v => v + "%", () => api().test_voice()),
      range("voice_rate", "Speed", "", 100, 300, 5, v => v),
      range("voice_volume", "Volume", "", 0, 1, .05, v => Math.round(v * 100) + "%"),
      custom("Test", "", () => [btn("Play a test sentence", () => api().test_voice(), "gold")]),
    ] },
  { id: "hologram", name: "Hologram", intro: "The see-through headband that appears in a corner of your screen while Mirage listens, thinks and speaks.",
    rows: () => [
      toggle("hologram_enabled", "Show the hologram"),
      seg("hologram_style", "Look", "", [["logo", "Headband"], ["orb", "Orb"]]),
      custom("Corner", "", () => [selectEl([["bottom-right", "Bottom right"], ["bottom-left", "Bottom left"], ["top-right", "Top right"], ["top-left", "Top left"]],
                                           C().hologram_corner, v => setCfg({ hologram_corner: v }).then(() => api().preview_hologram()))]),
      seg("hologram_size", "Size", "", [["small", "Small"], ["medium", "Medium"], ["large", "Large"]], false, null, () => api().preview_hologram()),
      toggle("subtitles_show_you", "Show what I said too", "Your words appear first, then Mirage's reply."),
      custom("Preview", "", () => [btn("Show me", () => api().preview_hologram(), "gold")]),
    ] },
  { id: "memory", name: "Memory", intro: "Mirage keeps what you tell it as linked notes, so they also show up in Obsidian's graph.",
    rows: () => [
      custom("Where to keep notes", "Pick your Obsidian vault; Mirage writes into a Mirage folder inside it.", () => [
        selectEl(S.options.vaults, C().vault_path || "", v => setCfg({ vault_path: v }).then(() => toast("Notes now go to " + (v || "Mirage's own folder")))),
        btn("Browse…", () => api().browse_vault().then(r => { if (r) { S.cfg = r; renderSettings(); } }))]),
      toggle("daily_log", "Daily log", "Writes what you and Mirage said into a note for each day."),
      custom("Links for the graph", "Adds links to memories saved before Mirage linked them.", () => [btn("Link old memories", () => api().relink().then(m => toast(m)))]),
    ] },
  { id: "skills", name: "Skills", intro: "Settings for Mirage's built-in abilities.",
    rows: () => [
      text("weather_city", "Weather city", "", "e.g. Stockholm", false, null, v => setCfg({ weather_city: v, weather_location: null })),
      custom("", "", () => [btn("Test weather", () => api().send("what's the weather").then(() => show("home")))]),
      seg("music_service", "Music", "What “mirage play …” uses.", [["youtube", "YouTube"], ["spotify", "Spotify"]]),
    ] },
  { id: "app", name: "App", intro: "",
    rows: () => [
      custom("Updates", "You have version " + S.version + ".", () => [stateEl("updState"), btn(S.update_available ? "Install " + S.update_available : "Check for updates",
        () => S.update_available ? api().install_update() : api().check_updates(), "gold", null, "updBtn")]),
      custom("Start with Windows", "Mirage starts hidden in the tray when you log in.", () => [toggleEl(S.startup, v => api().set_startup(v).then(r => { S.startup = r; saved(); }))]),
      toggle("close_to_tray", "Keep running when closed", "Closing the window keeps Mirage listening in the tray."),
      text("github_token", "GitHub key", "Only needed if the Mirage repository is private.", "github_pat_…", true),
      custom("Files", "", () => [btn("Open log", () => api().open_path("log")), btn("Open Mirage folder", () => api().open_path("folder"))]),
      custom("Quit Mirage", "Stops listening completely.", () => [btn("Quit", () => api().quit(), "danger")]),
    ] },
];

function renderSettings() {
  const nav = $("#settingsNav");
  nav.textContent = "";
  for (const s of SECTIONS) nav.append(h("button", { class: s.id === settingsSection ? "on" : "",
    onclick: () => { settingsSection = s.id; renderSettings(); } }, s.name));
  const sec = SECTIONS.find(s => s.id === settingsSection);
  const p = $("#settingsPanel");
  const scroll = p.scrollTop;
  p.textContent = "";
  p.append(h("h2", {}, sec.name));
  if (sec.intro) p.append(h("p", { class: "intro" }, sec.intro));
  for (const r of sec.rows()) if (r) p.append(r);
  if (sec.id === "voice" && C().voice_engine === "mirage" && S.speech && S.speech.last_error)
    p.append(h("div", { class: "note" }, "Last voice problem: " + S.speech.last_error));
  if (sec.id === "brain" && C().brain === "claude_code")
    p.append(h("div", { class: "note" }, "Shortcuts stay free: anything Mirage can do by itself (apps, websites, timers, reminders, to-dos, notes, weather, media keys, Roblox Studio) never reaches Claude. Add your own under Shortcuts."));
  p.scrollTop = scroll;
}

/* settings building blocks */
function row(label, desc, ...ctl) {
  return h("div", { class: "row" }, h("div", { class: "lbl" }, label ? h("b", {}, label) : null, desc ? h("small", {}, desc) : null),
    h("div", { class: "ctl" }, ...ctl));
}
function btn(label, fn, kind = "", title = null, id = null) {
  return h("button", { class: "btn " + kind, onclick: fn, title, id, "aria-label": title || label }, label);
}
function stateEl(id, text = "", cls = "") { return h("span", { class: "state " + cls, id }, text); }
function toggleEl(on, fn) {
  const t = h("button", { class: "toggle" + (on ? " on" : ""), role: "switch", "aria-checked": on ? "true" : "false" });
  t.addEventListener("click", () => { const v = !t.classList.contains("on"); t.classList.toggle("on", v); t.setAttribute("aria-checked", v); fn(v); });
  return t;
}
function toggle(key, label, desc = "") { return row(label, desc, toggleEl(!!C()[key], v => setCfg({ [key]: v }))); }
function segEl(options, value, fn) {
  const box = h("div", { class: "seg", role: "radiogroup" });
  for (const [v, l] of options) box.append(h("button", { class: v === value ? "on" : "", role: "radio", "aria-checked": v === value ? "true" : "false",
    onclick: () => { $$("button", box).forEach(b => b.classList.remove("on")); fn(v); } }, l));
  return box;
}
function seg(key, label, desc, options, rerender = false, guard = null, after = null) {
  return row(label, desc, segEl(options, C()[key], v => {
    const why = guard && guard(v);
    if (why) { toast(why); renderSettings(); return; }
    setCfg({ [key]: v }, rerender).then(() => { if (!rerender) renderSettings(); if (after) after(v); });
  }));
}
function selectEl(options, value, fn, extra = []) {
  const all = [...extra, ...(options || [])];
  if (value && !all.some(o => o[0] === value)) all.push([value, value]);
  const s = h("select", {}, all.map(([v, l]) => h("option", { value: v, selected: v === value }, l)));
  s.addEventListener("change", () => fn(s.value));
  return s;
}
function range(key, label, desc, min, max, step, fmt, after = null) {
  const val = h("span", { class: "val" }, fmt(C()[key]));
  const r = h("input", { type: "range", min, max, step, value: C()[key] });
  const pct = () => r.style.setProperty("--p", ((r.value - min) / (max - min) * 100) + "%");
  pct();
  let tm;
  r.addEventListener("input", () => { val.textContent = fmt(+r.value); pct(); clearTimeout(tm); tm = setTimeout(() => setCfg({ [key]: +r.value }).then(() => after && after()), 250); });
  return row(label, desc, r, val);
}
function text(key, label, desc, placeholder, secret = false, value = null, save = null) {
  const i = h("input", { type: secret ? "password" : "text", placeholder, style: "width:260px" });
  i.value = value != null ? value : (C()[key] || "");
  const commit = () => { const v = i.value.trim(); if (save) save(v); else if (v !== (C()[key] || "")) setCfg({ [key]: v }); };
  i.addEventListener("change", commit);
  i.addEventListener("keydown", e => { if (e.key === "Enter") i.blur(); });
  return row(label, desc, i);
}
function custom(label, desc, ctl) { return row(label, desc, ...ctl()); }

/* custom controls */
function claudeCtl() {
  const c = S.claude || {};
  if (!c.installed) return [stateEl("claudeState", "Not installed", "bad"), btn("Install Claude Code (about 180 MB)", () => api().install_claude(), "gold")];
  return [stateEl("claudeState", c.logged_in ? "Installed and logged in" : "Installed, not logged in", c.logged_in ? "ok" : "wait"),
          btn(c.logged_in ? "Log in again" : "Log in", () => api().claude_login(), c.logged_in ? "" : "gold")];
}
function vsCtl() {
  const vs = S.options.vs || { ok: false, voices: [] };
  const voices = [["", "VoiceStudio default"], ...vs.voices, ...["alloy", "echo", "fable", "onyx", "nova", "shimmer"].map(p => [p, "Preset: " + p])];
  return [selectEl(voices, C().voicestudio_voice || "", v => setCfg({ voicestudio_voice: v }).then(() => api().test_voice())),
          btn("↻", () => api().refresh_options().then(() => renderSettings()), "small", "Check VoiceStudio again"),
          stateEl("vsState", vs.ok ? "Connected" : "Not reachable", vs.ok ? "ok" : "bad")];
}

/* Mirage's own brain */
const localInstalled = () => !!(S.local && S.local.installed);
const fmtSize = mb => mb >= 1000 ? (mb / 1000).toFixed(1) + " GB" : Math.round(mb) + " MB";
function localCtl() {
  const L = S.local || {};
  if (L.state === "installing") return [stateEl("localState", L.detail || "Installing…", "wait")];
  if (!L.installed) return [stateEl("localState", L.state === "error" ? L.detail : "Not installed", L.state === "error" ? "bad" : ""),
    btn("Install (" + fmtSize(L.download_mb || 0) + ")", () => { S.local.state = "installing"; S.local.detail = "Starting…"; renderSettings(); api().install_local_brain(C().local_model); }, "gold")];
  if (L.state === "error") return [stateEl("localState", L.detail, "bad")];
  if (L.state === "starting") return [stateEl("localState", L.detail || "Starting…", "wait")];
  if (L.running) return [stateEl("localState", L.gpu === false ? "Running on the processor" : "Running on your graphics card", "ok")];
  return [stateEl("localState", L.gpu === false ? "Ready, on the processor. It wakes up when you ask something." : "Ready. It wakes up when you ask something.", "ok")];
}
function areaEl(key, placeholder) {
  const t = h("textarea", { placeholder, rows: 3, style: "width:340px" });
  t.value = C()[key] || "";
  t.addEventListener("change", () => setCfg({ [key]: t.value.trim() }));
  return t;
}

/* Mirage's own voice and ears */
const spInstalled = () => !!(S.speech && S.speech.installed);
function speechCtl(where) {
  const m = S.speech || {};
  if (m.state === "installing") return [stateEl("speechState", m.detail || "Installing…", "wait")];
  if (!m.installed) return [stateEl("speechState", m.state === "error" ? m.detail : "Not installed", m.state === "error" ? "bad" : ""),
    btn("Install", () => { S.speech.state = "installing"; S.speech.detail = "Starting…"; renderSettings(); api().install_speech(); }, "gold")];
  if (m.state === "ready") return [stateEl("speechState", where === "ears" ? "Ready" : "Ready", "ok")];
  if (m.state === "error") return [stateEl("speechState", m.detail, "bad"), btn("Try again", () => api().speech_reload())];
  return [stateEl("speechState", "Loading…", "wait")];
}
