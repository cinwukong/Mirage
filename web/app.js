/* Mirage interface (3.1). Talks to Python through window.pywebview.api. */
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

/* line icons, 24 x 24, drawn in the text colour (fixed markup, never user text) */
const ICONS = {
  home: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
  memory: '<path d="M5 4h10l4 4v12H5z"/><path d="M9 11h6M9 15h6"/>',
  skills: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><path d="M16.5 13v7M13 16.5h7"/>',
  shortcuts: '<path d="M13 3 5 14h6l-1 7 8-11h-6z"/>',
  settings: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13 7 4 4"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  apps: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  play: '<path d="M7 5v14l12-7z"/>',
  speaker: '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18.5 6a8 8 0 0 1 0 12"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  keyboard: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10"/>',
  screen: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  windows: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16M3 9h18"/>',
  lock: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  cloud: '<path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 18z"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
  bell: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  list: '<path d="M10 6h10M10 12h10M10 18h10"/><path d="m3.5 6 1 1 2-2M3.5 12l1 1 2-2M3.5 18l1 1 2-2"/>',
  cube: '<path d="M12 3 4 7.5v9L12 21l8-4.5v-9z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
  chat: '<path d="M5 5h14v10H9l-4 4z"/>',
  book: '<path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2z"/><path d="M5 18a2 2 0 0 1 2-2h12"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5H5V6h5"/>',
  keys: '<rect x="3" y="7" width="8" height="10" rx="2"/><rect x="13" y="7" width="8" height="10" rx="2"/>',
  run: '<path d="m5 8 4 4-4 4M11 16h8"/>',
};
function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("class", "i");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name] || ICONS.apps;
  return s;
}

let S = { cfg: {}, status: ["loading", ""], muted: false, messages: [], options: {} };
let page = "home";
let settingsGroup = "general";
let settingsQuery = "";
let memTab = "memories";
let level = 0;
const helpOpen = new Set();    // settings rows whose "?" help is showing
const skillsOpen = new Set();  // skill cards with their settings showing
const C = () => S.cfg;

const STATUS_TEXT = {
  loading: "Starting up…", listening: "Listening for “mirage”", awaiting: "Go ahead, I'm listening",
  thinking: "Thinking…", acting: "Using your PC", speaking: "Speaking", muted: "Microphone off", error: "Needs attention",
};
const HINTS = {
  loading: "Getting my voice and hearing ready.",
  listening: "Say “mirage”, then what you want. Or type below.",
  awaiting: "I stop listening after a few seconds of quiet.",
  thinking: "Working on it.",
  acting: "Press Esc or move the mouse to stop me.",
  speaking: "Talk over me to interrupt.",
  muted: "Turn the microphone on to talk to me. You can still type.",
  error: "",
};

/* ------------------------------------------------------------------ boot */
async function boot() {
  S = await api().get_state();
  for (const b of $$(".nav")) b.prepend(icon(b.dataset.icon));
  wire();
  applyStatus(S.status[0], S.status[1]);
  setMuted(S.muted);
  renderConvo();
  renderChips();
  renderQuiet();
  show(S.start_page || "home");
  if (C().setup_done === false) openSetup();
  else if (S.whats_new && S.whats_new.length) openNews(S.whats_new, true);
  poll();
  setInterval(renderQuiet, 30000);
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
  $("#askForm").addEventListener("submit", e => { e.preventDefault(); sendAsk(); });
  $("#quietBtn").addEventListener("click", toggleQuiet);
  $$("#memTabs button").forEach(b => b.addEventListener("click", () => { memTab = b.dataset.tab; renderMemory(); }));
  $("#memTabs").addEventListener("keydown", e => {  // arrow keys move between the tabs
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const tabs = $$("#memTabs button"), i = tabs.findIndex(b => b.dataset.tab === memTab);
    const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    memTab = next.dataset.tab; renderMemory(); next.focus();
  });
  $("#interviewBtn").addEventListener("click", () => api().memory_action("interview", "").then(r => { if (r && r.message) toast(r.message); show("home"); }));
  $("#newShortcut").addEventListener("click", () => openShortcut(null));
  new MutationObserver(syncInert).observe(document.body, { attributes: true, attributeFilter: ["hidden"], subtree: true });
  let searchTimer = null;
  $("#settingsSearch").addEventListener("input", e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { settingsQuery = e.target.value; renderSettings(); }, 120);
  });
}

function show(p) {
  page = p;
  $$(".nav").forEach(b => { const on = b.dataset.page === p; b.classList.toggle("on", on); b.setAttribute("aria-current", on ? "page" : "false"); });
  $$(".page").forEach(s => s.classList.toggle("on", s.id === "page-" + p));
  if (p === "memory") renderMemory();
  if (p === "skills") renderSkills();
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
function saved() { toast("Saved", 1400); }
async function setCfg(changes, rerender = false) {
  S.cfg = await api().set_config(changes);
  saved();
  if (rerender && page === "settings") renderSettings();
}

/* ------------------------------------------------------------------ events */
function onEvent(kind, data) {
  switch (kind) {
    case "status": applyStatus(data[0], data[1]); break;
    case "level":
      level = data;
      for (const m of $$("#levelMeter, #setupMeter, #diagMeter")) m.style.width = Math.min(100, data * 400) + "%";
      if (S.status[0] === "awaiting") $("#orb").style.setProperty("--lvl", Math.min(1, data * 5).toFixed(2));
      break;
    case "heard": addLine("you", data); break;
    case "reply": addLine("mirage", data); break;
    case "system": addLine("sys", data); break;
    case "muted": setMuted(data); break;
    case "show_page": show(data); break;
    case "state":
      Object.assign(S, data);
      if (page === "settings") renderSettings();
      if (page === "skills") renderSkills();
      if (setupStep >= 0) renderSetup();
      renderQuiet(); renderChips();
      break;
    case "quiet": S.cfg.dnd_until = data; renderQuiet(); break;
    case "memory_changed": case "reminders_changed": if (page === "memory") renderMemory(); break;
    case "toast": toast(data); break;
    case "phrase": if (shortcutDraft && shortcutDraft.step === 0) { shortcutDraft.phrase = data; const i = $("#scPhraseIn"); if (i) i.value = data; } break;
    case "progress": {
      if (data[0] === "speechState" && S.speech) S.speech.detail = data[1];
      if (data[0] === "localState" && S.local) S.local.detail = data[1];
      S.prog = S.prog || {};
      S.prog[data[0]] = data;  // kept, so the page shows it again when you come back to it
      for (const el of $$("#setup [data-progress='" + data[0] + "']")) setState(el, data[1], data[2]);
      const el = $("#" + data[0]); if (el) setState(el, data[1], data[2]);
      setBar(data[0], data);
    } break;
    case "refresh_settings": if (page === "settings") renderSettings(); break;
  }
}

function applyStatus(s, detail) {
  S.status = [s, detail];
  $("#status").dataset.s = s;
  $("#statusText").textContent = STATUS_TEXT[s] || s;
  const orb = $("#orb");
  orb.dataset.s = s;
  if (s !== "awaiting") orb.style.setProperty("--lvl", "0");
  const hint = $("#hint");
  hint.textContent = detail || (s === "speaking" && C().barge_in === false ? "" : HINTS[s] || "");
  hint.classList.toggle("err", s === "error");
}
function setMuted(m) {
  S.muted = m;
  const b = $("#micBtn");
  b.classList.toggle("muted", m);
  b.title = m ? "Turn the microphone on" : "Mute the microphone";
  b.setAttribute("aria-label", b.title);
  b.setAttribute("aria-pressed", m ? "true" : "false");
}

/* quiet mode from Home: an hour without speaking up on its own (reminders still come through) */
const quietUntil = () => (C().dnd_until || 0) * 1000;
const hhmm = ms => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
function renderQuiet() {
  const b = $("#quietBtn"), on = quietUntil() > Date.now();
  b.textContent = "";
  b.append(icon("moon"), on ? "Quiet until " + hhmm(quietUntil()) : "Quiet for an hour");
  b.classList.toggle("on", on);
  b.title = on ? "Click to let Mirage speak up again" : "Mirage won't speak up on its own for an hour. Reminders still come through.";
  b.setAttribute("aria-pressed", on ? "true" : "false");
}
async function toggleQuiet() {
  const on = quietUntil() > Date.now();
  S.cfg = await api().set_config({ dnd_until: on ? 0 : Date.now() / 1000 + 3600 });
  renderQuiet();
  toast(on ? "I can speak up again." : "Quiet until " + hhmm(quietUntil()) + ". Reminders still come through.");
}

/* ------------------------------------------------------------------ home */
/* a new message is added to the end (so a screen reader announces just that one), never the whole chat redrawn */
function addLine(who, text) {
  const m = { who, text, at: new Date().toTimeString().slice(0, 5) };
  S.messages.push(m);
  const c = $("#convo");
  if (S.messages.length > 150) { S.messages.shift(); if (c.firstChild) c.firstChild.remove(); }
  c.append(lineEl(m));
  afterLines();
}
function lineEl(m) {
  if (m.who === "you") return h("div", { class: "line you" }, h("div", { class: "who" }, "You · " + m.at), h("div", { class: "text" }, m.text));
  if (m.who === "mirage") return h("div", { class: "line mirage" }, h("div", { class: "who" }, h("b", {}, "Mirage"), " · " + m.at), h("div", { class: "text" }, m.text));
  return h("div", { class: "line sys" }, m.text);
}
function renderConvo() {
  const c = $("#convo");
  c.textContent = "";
  for (const m of S.messages) c.append(lineEl(m));
  afterLines();
}
function afterLines() {
  $("#orb").classList.toggle("small", S.messages.length > 0);
  const sc = $("#homeScroll");
  sc.scrollTop = sc.scrollHeight;
}
function sendAsk() {
  const i = $("#askInput");
  const t = i.value.trim();
  if (!t) return;
  i.value = "";
  api().send(t);
}
/* suggestions from what Mirage can do right now (a group you turned off isn't suggested) */
const CHIPS = [["weather", "What's the weather?"], ["todos", "What's on my to-do list?"], ["timers", "Set a timer for 10 minutes"],
               ["open", "Open YouTube"], ["memory", "What do you remember about me?"], ["reminders", "What are my reminders?"],
               ["time", "What time is it?"], ["search", "Search for cheap headphones"]];
function renderChips() {
  const off = C().builtins_off || [];
  const box = $("#chips");
  box.textContent = "";
  for (const [group, text] of CHIPS.filter(c => !off.includes(c[0])).slice(0, 4))
    box.append(h("button", { class: "chip", type: "button", onclick: () => api().send(text) }, text));
}

/* ------------------------------------------------------------------ memory */
let chatTimer = null;
/* every delete is a bin button that needs a second click (see sureIcon) */
const delBtn = (label, fn) => sureIcon(label, fn);
function adder(placeholder, label, kind, onDone) {
  const i = h("input", { type: "text", placeholder, "aria-label": label, autocomplete: "off" });
  const go = async () => {
    const t = i.value.trim();
    if (!t) return;
    const res = await api().memory_action(kind, t);
    if (res && res.error) { toast(res.error, 4000); return; }
    i.value = "";
    if (res && res.message) toast(res.message);
    onDone();
  };
  i.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  return h("div", { class: "adder" }, i, h("button", { class: "btn primary", onclick: go }, "Add"));
}
async function renderMemory() {
  $$("#memTabs button").forEach(b => { const on = b.dataset.tab === memTab; b.setAttribute("aria-selected", on ? "true" : "false"); b.tabIndex = on ? 0 : -1; });
  const body = $("#memBody");
  if (memTab === "chats") return renderChatsTab(body);
  const M = await api().get_memory();
  if (page !== "memory") return;
  body.textContent = "";
  if (memTab === "memories") {
    const ul = h("ul", { class: "list" });
    body.append(h("div", { class: "mem-section" },
      adder("Something to remember, like: my favourite colour is purple", "Something to remember", "remember", renderMemory), ul));
    if (!M.memories.length) ul.append(h("li", { class: "empty" }, "Nothing remembered yet. Say “mirage, remember that …” or “mirage, get to know me”. Mirage also notices things about you as you talk."));
    else renderFacts(ul, M.memories);
    return;
  }
  // calendar: reminders, then the to-do list
  const rem = h("ul", { class: "list" });
  if (!M.reminders.length) rem.append(h("li", { class: "empty" }, "No reminders. Say “mirage, remind me at 5 pm to …”."));
  for (const it of M.reminders)
    rem.append(h("li", {}, h("span", { class: "when" }, it.when), h("span", { class: "t" }, it.text),
      delBtn("Delete the reminder “" + it.text + "”", () => api().memory_action("delete_reminder", it.id).then(renderMemory))));
  const todo = h("ul", { class: "list" });
  if (!M.todos.length) todo.append(h("li", { class: "empty" }, "Nothing on your to-do list. Say “mirage, add … to my to-do list”."));
  for (const it of M.todos)
    todo.append(h("li", { class: it.done ? "done" : "" },
      h("button", { class: "check" + (it.done ? " on" : ""), role: "checkbox", "aria-checked": it.done ? "true" : "false", "aria-label": it.text,
        onclick: () => api().memory_action("toggle_todo", it.i).then(renderMemory) }),
      h("span", { class: "t" }, it.text),
      delBtn("Delete “" + it.text + "”", () => api().memory_action("delete_todo", it.i).then(renderMemory))));
  body.append(
    h("section", { class: "mem-section", "aria-labelledby": "remH" }, h("h2", { class: "label", id: "remH" }, "Reminders"),
      adder("in 20 minutes to stretch, or at 5 pm to call mom", "New reminder", "add_reminder", renderMemory), rem),
    h("section", { class: "mem-section", "aria-labelledby": "todoH", style: "margin-top: 28px" }, h("h2", { class: "label", id: "todoH" }, "To-do"),
      adder("Add a to-do", "New to-do", "add_todo", renderMemory), todo));
}
function renderFacts(ul, items) {
  // grouped by who or what they're about: you first, then the rest A to Z
  const groups = {};
  for (const it of items) (groups[it.topic] = groups[it.topic] || []).push(it);
  const names = Object.keys(groups).sort((a, b) => (a === "Me" ? -1 : b === "Me" ? 1 : a === "Other" ? 1 : b === "Other" ? -1 : a.localeCompare(b)));
  for (const name of names) {
    ul.append(h("li", { class: "group" }, h("h3", {}, name === "Me" ? "You" : name), h("span", { class: "count" }, String(groups[name].length))));
    for (const it of groups[name]) {
      ul.append(h("li", {}, h("span", { class: "when" }, it.when),
        h("span", { class: "t" }, it.text, it.noticed ? h("span", { class: "tag", title: "Mirage picked this up from a conversation" }, "noticed") : null),
        delBtn("Forget “" + it.text + "”", () => api().memory_action("forget", it.id).then(renderMemory))));
    }
  }
}
function renderChatsTab(body) {
  body.textContent = "";
  const i = h("input", { type: "search", placeholder: "Search what you and Mirage said", "aria-label": "Search past chats", autocomplete: "off" });
  const ul = h("ul", { class: "list" });
  i.addEventListener("input", () => { clearTimeout(chatTimer); chatTimer = setTimeout(() => fillChats(ul, i.value.trim()), 250); });
  body.append(h("div", { class: "mem-section" }, h("div", { class: "adder" }, i), ul));
  fillChats(ul, "");
}
async function fillChats(ul, q) {
  const days = await api().get_chats(q);
  if (memTab !== "chats") return;
  ul.textContent = "";
  if (!days.length) {
    ul.append(h("li", { class: "empty" }, q ? "Nothing found." : (C().chat_history === false
      ? "Chat history is off (Settings, Privacy and data)." : "No conversations yet. They show up here, and Mirage can look back at them: “mirage, what did we talk about yesterday?”")));
    return;
  }
  for (const d of days) {
    ul.append(h("li", { class: "group" }, h("h3", {}, d.day), h("span", { class: "count" }, String(d.items.length))));
    for (const it of d.items)
      ul.append(h("li", { class: "chat" }, h("span", { class: "when" }, it.time),
        h("span", { class: "t" }, h("span", {}, it.you), it.mirage ? h("span", { class: "said" }, it.mirage) : null)));
  }
}

/* ------------------------------------------------------------------ skills */
/* In 3.1 these are Mirage's built-in abilities. The skill store (3.2) turns them into skills you add. */
const CORE = ["mirage", "memory", "quiet", "time", "greetings", "facts"];
const SKILL_INFO = {
  todos: ["list", "Add to your to-do list, read it out and check things off."],
  timers: ["clock", "Timers by voice, with an alarm when they're done."],
  reminders: ["bell", "Reminders at a time, read back or cleared."],
  roblox: ["cube", "Playtest, stop and save in Roblox Studio."],
  spotify: ["music", "Your saved Spotify playlists, play, stop and what's playing."],
  play: ["play", "Play a song or video on YouTube or Spotify."],
  media: ["speaker", "Volume, next, previous, pause and mute."],
  search: ["search", "Search the web or YouTube."],
  open: ["apps", "Open apps, websites and games by name."],
  typing: ["keyboard", "Type text where your cursor is."],
  screen: ["screen", "Tells you what's on your screen."],
  screenshot: ["camera", "Takes a screenshot."],
  windows: ["windows", "Switch, snap, move and close windows."],
  pc: ["lock", "Lock the PC and close windows or tabs."],
  weather: ["cloud", "Weather for your city, today and tomorrow."],
};
const SKILL_MORE = {
  weather: () => {
    const i = h("input", { type: "text", placeholder: "e.g. Stockholm", "aria-label": "Weather city" });
    i.value = C().weather_city || "";
    i.addEventListener("change", () => setCfg({ weather_city: i.value.trim(), weather_location: null }));
    return [h("div", { class: "line-row" }, h("b", {}, "City"), i),
            h("div", { class: "line-row" }, h("span"), btn("Test the weather", () => api().send("what's the weather").then(() => show("home"))))];
  },
  play: () => [h("div", { class: "line-row" }, h("span", {}, "“Play …” uses"),
    segEl([["youtube", "YouTube"], ["spotify", "Spotify"]], C().music_service || "youtube", v => setCfg({ music_service: v }).then(renderSkills), "Music service"))],
  spotify: () => [h("div", { class: "line-row" }, h("p", {}, "Your saved playlists are under Shortcuts."), btn("Go to Shortcuts", () => show("shortcuts")))],
  open: () => [h("div", { class: "line-row" }, h("p", {}, "Give websites and apps your own names under Shortcuts."), btn("Go to Shortcuts", () => show("shortcuts")))],
};
const cleanExample = e => e.replace(/\s*\(.*?\)\s*/g, " ").trim();
function setBuiltin(id, on) {
  const next = (C().builtins_off || []).filter(x => x !== id);
  if (!on) next.push(id);
  return setCfg({ builtins_off: next }).then(() => { renderSkills(); renderChips(); });
}
function renderSkills() {
  const box = $("#skillsBox");
  const scroll = box.parentElement.scrollTop;
  box.textContent = "";
  const off = C().builtins_off || [];
  const groups = S.builtins || [];
  const skills = groups.filter(g => !CORE.includes(g[0])), core = groups.filter(g => CORE.includes(g[0]));
  const onCount = skills.filter(g => !off.includes(g[0])).length;
  box.append(h("div", { class: "page-head" },
    h("div", {}, h("h1", {}, "Skills"), h("p", { class: "lede" }, "What Mirage can do by itself. Turn off what gets in the way: what you say then goes to your shortcuts or the brain.")),
    h("span", { class: "muted" }, onCount + " of " + skills.length + " on")));

  const grid = h("div", { class: "skill-grid" });
  for (const [id, name, examples] of skills) {
    const [ic, desc] = SKILL_INFO[id] || ["apps", ""];
    const isOn = !off.includes(id), more = SKILL_MORE[id], open = skillsOpen.has(id);
    const moreId = "more-" + id;
    grid.append(h("article", { class: "card skill" + (isOn ? "" : " off") },
      h("div", { class: "skill-top" },
        h("div", { class: "skill-icon" }, icon(ic)),
        h("div", { class: "skill-text" }, h("h3", {}, name), desc ? h("p", {}, desc) : null,
          examples.length ? h("p", { class: "try" }, "Try: ", h("q", {}, cleanExample(examples[0]))) : null),
        toggleEl(isOn, v => setBuiltin(id, v), name)),
      more ? h("div", { class: "skill-foot" }, h("span", { class: "state-txt" }, isOn ? "On" : "Off"),
        h("button", { class: "btn small", "aria-expanded": open ? "true" : "false", "aria-controls": moreId,
          onclick: () => { open ? skillsOpen.delete(id) : skillsOpen.add(id); renderSkills(); } }, "Settings", icon("chevron"))) : null,
      more && open ? h("div", { class: "skill-more", id: moreId }, ...more()) : null));
  }
  box.append(h("section", { class: "mem-section", style: "max-width: none", "aria-labelledby": "skH" },
    h("div", { class: "page-head" }, h("h2", { class: "label", id: "skH" }, "Built in"),
      h("p", { class: "note-line" }, "The skill store opens in Mirage 3.2: then you add only the skills you want.")), grid));

  if (core.length) {
    const card = h("div", { class: "card core-list" });
    for (const [id, name, examples] of core)
      card.append(statusRow(name, examples.slice(0, 2).map(e => "“" + cleanExample(e) + "”").join("  "), toggleEl(!off.includes(id), v => setBuiltin(id, v), name)));
    box.append(h("section", { class: "mem-section", style: "max-width: none", "aria-labelledby": "coreH" },
      h("h2", { class: "label", id: "coreH" }, "Part of Mirage"), card));
  }
  box.parentElement.scrollTop = scroll;
}

/* ------------------------------------------------------------------ shortcuts */
const ACTIONS = {
  open: { label: "Open a website, app or file", icon: "open", field: "Website, app or file", ph: "youtube.com, spotify: or C:\\Users\\…\\file.pdf",
          help: "A website, a link like spotify:, or the full path to an app, file or folder." },
  say: { label: "Say something", icon: "chat", field: "What Mirage says", ph: "Good morning! Ready when you are.", help: "" },
  type: { label: "Type text", icon: "keyboard", field: "Text to type", ph: "Thanks, talk soon!", help: "Typed wherever your cursor is." },
  keys: { label: "Press keys", icon: "keys", field: "Keys", ph: "ctrl+shift+s", help: "Key names joined by +, like ctrl+shift+s or volumeup." },
  run: { label: "Run a command", icon: "run", field: "Command", ph: "notepad", help: "Runs in a Windows command prompt without asking, so only use commands you trust." },
};
const doText = c => (ACTIONS[c.action] || { label: c.action }).label + ": " + c.target;
function renderShortcuts() {
  const box = $("#shortcutBlocks");
  box.textContent = "";
  const cfg = C();

  const vc = cfg.voice_commands || [];
  const list = h("div", { class: "card sc-list" });
  for (const c of vc) {
    list.append(h("div", { class: "sc-item" },
      h("div", { class: "sc-icon" }, icon((ACTIONS[c.action] || ACTIONS.open).icon)),
      h("div", { class: "sc-text" }, h("span", { class: "sc-phrase" }, h("q", {}, c.phrase)), h("span", { class: "sc-do" }, doText(c))),
      h("button", { class: "icon-btn", title: "Change", "aria-label": "Change “" + c.phrase + "”", onclick: () => openShortcut(c) }, icon("edit")),
      sureIcon("Delete “" + c.phrase + "”", () => api().delete_shortcut(c.phrase).then(cfgNow => { S.cfg = cfgNow; renderShortcuts(); toast("Deleted."); }))));
  }
  box.append(h("section", { class: "mem-section", style: "max-width: none", "aria-labelledby": "scH" },
    h("h2", { class: "label", id: "scH" }, "Your shortcuts"),
    vc.length ? list : h("div", { class: "empty" }, "No shortcuts yet. “Mirage good morning” could open Spotify, or “mirage work” your work folder. Press New shortcut to make one.")));

  // names for "open …" and "play …"
  const lists = [
    ["websites", "Websites", "“mirage open <name>” opens the site.", "Name", "https://…"],
    ["apps", "Apps", "A program name, the full path to an .exe, or a link like discord:", "Name", "C:\\path\\to\\app.exe"],
    !(cfg.builtins_off || []).includes("roblox") && ["roblox_games", "Roblox games", "A .rbxl file opens in Studio; a place ID opens its Roblox page.", "Name", "C:\\path\\to\\game.rbxl"],
    ["spotify_playlists", "Spotify playlists", "“mirage play <name>” starts it. In Spotify: right-click a playlist, Share, Copy link.", "Name, e.g. chill", "https://open.spotify.com/playlist/…"],
  ].filter(Boolean);
  const grid = h("div", { class: "names-grid" });
  for (const [key, title, lede, p1, p2] of lists) {
    const dict = key === "apps" ? ((cfg.apps || {})[S.system] || {}) : (cfg[key] || {});
    const ul = h("ul", { class: "list" });
    Object.entries(dict).sort().forEach(([k, v]) => ul.append(h("li", {},
      h("span", { class: "k" }, k), h("span", { class: "v" }, v),
      delBtn("Delete " + k, () => { delete dict[k]; saveDict(key, dict).then(renderShortcuts); }))));
    if (!Object.keys(dict).length) ul.append(h("li", { class: "none" }, "Nothing added yet."));
    const n = h("input", { type: "text", placeholder: p1, "aria-label": title + ": name" });
    const v = h("input", { type: "text", class: "grow", placeholder: p2, "aria-label": title + ": what it opens" });
    const add = () => {
      if (!n.value.trim() || !v.value.trim()) { toast("Fill in both the name and what it opens."); return; }
      dict[n.value.trim().toLowerCase()] = v.value.trim();
      saveDict(key, dict).then(renderShortcuts);
    };
    v.addEventListener("keydown", e => { if (e.key === "Enter") add(); });
    grid.append(h("div", { class: "card names" },
      h("div", { class: "names-head" }, h("h3", {}, title), h("p", {}, lede)), ul,
      h("div", { class: "addrow" }, n, v, h("button", { class: "btn", onclick: add }, "Add"))));
  }
  // folded away by default, so the page is your shortcuts first and not a long scroll of lists
  const savedCount = lists.reduce((n, [key]) => n + Object.keys(key === "apps" ? ((cfg.apps || {})[S.system] || {}) : (cfg[key] || {})).length, 0);
  const fold = h("details", { class: "names-wrap", open: namesOpen },
    h("summary", {}, h("span", { class: "names-title" }, "Names for “open …” and “play …”"), h("span", { class: "muted" }, savedCount + " saved")),
    h("p", { class: "note-line" }, "Your own names for websites, apps and playlists, so “mirage open <name>” or “mirage play <name>” finds them."),
    grid);
  fold.addEventListener("toggle", () => { namesOpen = fold.open; });
  box.append(fold);
}
let namesOpen = false;
function saveDict(key, dict) {
  if (key === "apps") { const all = S.cfg.apps || {}; all[S.system] = dict; return setCfg({ apps: all }); }
  return setCfg({ [key]: dict });
}

/* the "+ New shortcut" dialog: the phrase, then what it does, then try it and save */
let shortcutDraft = null;
function openShortcut(existing) {
  shortcutDraft = { step: 0, old: existing ? existing.phrase : "", phrase: existing ? existing.phrase : "",
         action: existing ? existing.action : "open", target: existing ? existing.target : "", opener: document.activeElement };
  if (S.prog) { delete S.prog.scPhrase; delete S.prog.scTest; }
  $("#scDialog").hidden = false;
  renderShortcutDialog();
}
/* while a dialog is open, the page behind it can't be reached (Tab stays in the dialog). Closing calls this
   straight away too, so focus can go back to the page before the observer catches up. */
function syncInert() { $(".app").inert = $$(".setup").some(d => !d.hidden); }
function closeShortcut() {
  const opener = shortcutDraft && shortcutDraft.opener;
  shortcutDraft = null;
  $("#scDialog").hidden = true;
  syncInert();
  // back to what opened it; if the list was redrawn meanwhile, to the New shortcut button
  (opener && opener.isConnected && opener !== document.body ? opener : $("#newShortcut")).focus();
}
const scCmd = () => ({ phrase: shortcutDraft.phrase, action: shortcutDraft.action, target: shortcutDraft.target });
async function scNext() {
  const d = shortcutDraft;
  if (!d || d.busy) return;  // pressed twice, or already closed
  d.busy = true;
  const cmd = d.step === 0 ? { phrase: d.phrase, action: "say", target: "-" } : scCmd();  // step one only checks the phrase
  const why = await api().check_shortcut(cmd);
  d.busy = false;
  if (shortcutDraft !== d) return;  // closed while it was checking
  if (why) { const el = $(d.step === 0 ? "#scPhrase" : "#scTargetState"); if (el) setState(el, why, "bad"); return; }
  d.step += 1;
  renderShortcutDialog();
}
async function scSave() {
  const d = shortcutDraft;
  if (!d || d.busy) return;
  d.busy = true;
  const r = await api().save_shortcut(scCmd(), d.old);
  d.busy = false;
  if (shortcutDraft !== d) return;
  if (r.error) { setState($("#scTest"), r.error, "bad"); return; }
  S.cfg = r.cfg;
  renderShortcuts();
  closeShortcut();
  toast(r.message, 3500);
}
function renderShortcutDialog() {
  const box = $("#scDialog");
  if (!shortcutDraft) return;
  const steps = ["phrase", "action", "test"];
  const dots = h("ol", { class: "dots", "aria-label": "Step " + (shortcutDraft.step + 1) + " of 3" },
    steps.map((_, i) => h("li", { class: i === shortcutDraft.step ? "on" : i < shortcutDraft.step ? "done" : "" })));
  const close = h("button", { class: "icon-btn dlg-close", "aria-label": "Close", title: "Close", onclick: closeShortcut }, icon("close"));
  const back = shortcutDraft.step > 0 ? btn("Back", () => { shortcutDraft.step -= 1; renderShortcutDialog(); }) : btn("Cancel", closeShortcut);
  let body, focus;
  if (shortcutDraft.step === 0) {
    const i = h("input", { type: "text", id: "scPhraseIn", placeholder: "good morning", autocomplete: "off", maxlength: "80" });
    i.value = shortcutDraft.phrase;
    i.addEventListener("input", () => { shortcutDraft.phrase = i.value; });
    i.addEventListener("keydown", e => { if (e.key === "Enter") scNext(); });
    focus = i;
    body = [h("h1", { id: "scTitle" }, shortcutDraft.old ? "Change shortcut" : "When I say…"),
      h("p", {}, "Type the phrase, or press Say it and say it. Mirage listens for it right after “mirage”."),
      h("label", { for: "scPhraseIn" }, "Phrase"),
      h("div", { class: "phrase-field" }, h("span", { class: "wake" }, "mirage"), i,
        h("button", { class: "btn", onclick: () => api().listen_phrase() }, icon("mic"), "Say it")),
      stateEl("scPhrase", "", "", "result"),
      h("div", { class: "setup-actions" }, back, btn("Next", scNext, "primary"))];
  } else if (shortcutDraft.step === 1) {
    const a = ACTIONS[shortcutDraft.action] || ACTIONS.open;
    const t = h("input", { type: "text", id: "scTargetIn", placeholder: a.ph, autocomplete: "off" });
    t.value = shortcutDraft.target;
    t.addEventListener("input", () => { shortcutDraft.target = t.value; });
    t.addEventListener("keydown", e => { if (e.key === "Enter") scNext(); });
    const radios = h("div", { class: "actions-list", role: "radiogroup", "aria-label": "What it does" },
      Object.entries(ACTIONS).map(([k, v]) => h("button", { class: "act", role: "radio", "aria-checked": k === shortcutDraft.action ? "true" : "false",
        tabindex: k === shortcutDraft.action ? "0" : "-1",
        onclick: () => { shortcutDraft.action = k; renderShortcutDialog(); $("#scTargetIn").focus(); } }, h("span", { class: "sc-icon" }, icon(v.icon)), v.label)));
    radios.addEventListener("keydown", e => {  // arrow keys move the choice, like any radio group
      const keys = Object.keys(ACTIONS), i = keys.indexOf(shortcutDraft.action);
      if (e.key === "ArrowDown" || e.key === "ArrowRight") shortcutDraft.action = keys[(i + 1) % keys.length];
      else if (e.key === "ArrowUp" || e.key === "ArrowLeft") shortcutDraft.action = keys[(i + keys.length - 1) % keys.length];
      else return;
      e.preventDefault(); renderShortcutDialog(); $("#scDialog .act[aria-checked='true']").focus();
    });
    focus = $$(".act", radios).find(b => b.getAttribute("aria-checked") === "true");
    body = [h("h1", { id: "scTitle" }, "…do this"),
      h("p", {}, "When you say “mirage " + shortcutDraft.phrase.trim() + "”:"),
      radios,
      h("label", { for: "scTargetIn" }, a.field), t,
      a.help ? h("p", { class: "small", style: "margin-top: 6px" }, a.help) : null,
      stateEl("scTargetState", "", "", "result"),
      h("div", { class: "setup-actions" }, back, btn("Next", scNext, "primary"))];
  } else {
    const test = btn("Try it now", () => { setState($("#scTest"), "Trying it…", "wait"); api().test_shortcut(scCmd()); });
    focus = test;
    body = [h("h1", { id: "scTitle" }, "Try it"),
      h("div", { class: "summary" }, h("q", {}, "mirage " + shortcutDraft.phrase.trim()), h("span", {}, doText(scCmd()))),
      h("p", { class: "small" }, "Try it now to check it does what you want, then save it."),
      h("div", { class: "setup-row" }, test),
      stateEl("scTest", "", "", "result"),
      h("div", { class: "setup-actions" }, back, btn(shortcutDraft.old ? "Save changes" : "Save shortcut", scSave, "primary"))];
  }
  box.textContent = "";
  box.append(h("div", { class: "setup-card" }, close, dots, ...body));
  box.onkeydown = e => { if (e.key === "Escape") closeShortcut(); };
  if (focus) setTimeout(() => focus.focus(), 30);
}

/* ------------------------------------------------------------------ settings */
/* Four groups. Each row has a short label; longer help sits behind its "?". Search looks through every row. */
const hours = () => Array.from({ length: 24 }, (_, i) => [String(i), String(i).padStart(2, "0") + ":00"]);
const GROUPS = [
  { id: "general", name: "General", blurb: "Your name, updates, startup", sections: [
    { name: "You", rows: () => [
      text("name", "Your name", "What Mirage calls you. Leave it empty and it won't use a name.", "What should I call you?", false,
        S.name || "", v => api().set_name(v).then(n => { S.name = n; saved(); })),
    ] },
    { name: "Updates", rows: () => [(() => {
        const r = testRow("Mirage " + S.version, "", "updState",
          btn("What's new", () => api().get_whats_new().then(n => openNews(n, false))),
          btn(S.update_available ? "Install " + S.update_available : "Check for updates",
            () => S.update_available ? api().install_update() : api().check_updates(), "primary", null, "updBtn"));
        r.querySelector(".lbl").append(barEl("updState"));  // the progress bar sits under the update's status
        r.dataset.find += " update version new";
        return r;
      })()] },
    { name: "Startup", rows: () => [
      row("Start with Windows", "Mirage starts hidden in the tray when you log in.", toggleEl(S.startup, v => api().set_startup(v).then(r => { S.startup = r; saved(); }), "Start with Windows")),
      toggle("close_to_tray", "Keep running when closed", "Closing the window keeps Mirage listening in the tray."),
    ] },
    { name: "Speaking up", rows: () => {
      const dnd = quietUntil() > Date.now();
      const on = C().nudges !== false;
      return [
        row("Speak up on its own", "Only when it's worth it: a birthday or date it remembers is coming up, and once a day your to-do list. It waits until you're at the PC and not busy. Your own reminders and timers always come through.",
          toggleEl(on, v => setCfg({ nudges: v }, true), "Speak up on its own")),
        on && toggle("nudge_todos", "Mention my to-do list", "Once a day, in the afternoon or evening, if there's something on it."),
        on && row("Quiet hours", "No speaking up on its own during these hours.",
          selectEl(hours(), String(C().quiet_from ?? 23), v => setCfg({ quiet_from: +v }), [], "Quiet from"), h("span", { class: "muted" }, "to"),
          selectEl(hours(), String(C().quiet_to ?? 8), v => setCfg({ quiet_to: +v }), [], "Quiet until"),
          toggleEl(C().quiet_hours !== false, v => setCfg({ quiet_hours: v }), "Quiet hours")),
        row("Stay quiet in full-screen games", "While a game or video fills the screen, Mirage doesn't speak up and the hologram stays hidden. Reminders still play.",
          toggleEl(C().quiet_in_games !== false, v => setCfg({ quiet_in_games: v }), "Stay quiet in full-screen games")),
        on && row("Break reminders", "Suggests a stretch after a long time at the PC without a pause.",
          toggleEl(!!C().break_reminders, v => setCfg({ break_reminders: v }, true), "Break reminders")),
        on && C().break_reminders && range("break_minutes", "Remind me after", "", 30, 180, 15, v => v + " min"),
        statusRow("Quiet mode", dnd ? "On until " + hhmm(quietUntil()) + ". Or say “mirage, you can talk again”." : "Or say “mirage, do not disturb for two hours”.",
          dnd ? btn("End quiet mode", () => setCfg({ dnd_until: 0 }, true).then(renderQuiet))
              : btn("Quiet for an hour", () => setCfg({ dnd_until: Date.now() / 1000 + 3600 }, true).then(renderQuiet))),
      ];
    } },
    { name: "Mirage", rows: () => [
      row("First-time setup", "Name, microphone, voice and brain, step by step.", btn("Run it again", openSetup)),
      C().github_token && text("github_token", "GitHub key", "Only needed if the Mirage repository is private.", "github_pat_…", true),
      row("About", "Mirage " + S.version + ". Built on: Kokoro voice (Apache-2.0), NVIDIA Parakeet hearing (CC-BY-4.0), Silero VAD (MIT), sherpa-onnx (Apache-2.0), llama.cpp (MIT), Qwen 3.5 (Apache-2.0), Gemma 4 (Gemma Terms of Use), Vosk (Apache-2.0), Figtree and Sora fonts (OFL) and Python (PSF).",
        btn("Licenses", () => api().open_url("https://github.com/cinwukong/Mirage#credits"))),
      row("Quit Mirage", "Stops listening completely until you open Mirage again.", btn("Quit", () => api().quit(), "danger")),
    ] },
  ] },
  { id: "voice", name: "Voice and hearing", blurb: "Microphone, wake word, voice, subtitles", sections: [
    { name: "Hearing", rows: () => [
      row("Microphone", "", selectEl((S.options.mics || []).map(m => [m, m]), C().input_device || "", v => setCfg({ input_device: v || null }), [["", "System default"]], "Microphone"),
        btn("↻", () => api().refresh_options().then(o => { S.options = o; renderSettings(); }), "small", "Look for microphones again")),
      row("Input level", "Talk, and the bar should move. If it doesn't, pick another microphone.", h("div", { class: "meter" }, h("i", { id: "levelMeter" }))),
      text("wake_words_text", "Wake words", "Separate with commas. Add spellings it mishears, remove ones that trigger by accident.", "mirage", false,
        (C().wake_words || []).join(", "), v => setCfg({ wake_words: v.split(",").map(s => s.trim().toLowerCase()).filter(Boolean) })),
      toggle("wake_sound", "Beep when I say “mirage”"),
      range("command_timeout_seconds", "Time to give a command", "After saying just “mirage”.", 3, 15, 1, v => v + " s"),
      row("Keep listening after replies", "Carry on talking without saying “mirage” again. Say “that's all” or “thanks” when you're done.",
        toggleEl(C().follow_up !== false, v => setCfg({ follow_up: v }, true), "Keep listening after replies")),
      C().follow_up !== false && range("follow_up_seconds", "Keep listening for", "How long Mirage waits for you after it replies.", 4, 20, 1, v => v + " s"),
      row("Interrupt by talking", C().voice_engine === "mirage"
          ? "Talk over Mirage to cut it off. On speakers, where it can hear itself, start with “mirage” instead."
          : "Talk over Mirage to cut it off. Needs Mirage's own voice.",
        toggleEl(C().barge_in !== false, v => setCfg({ barge_in: v }), "Interrupt by talking")),
      spInstalled() ? row("Hearing", "Mirage writes down what you say with NVIDIA Parakeet, on this PC.", ...speechCtl("ears"))
                    : statusRow("Hearing", "Install Mirage's own ears for much better hearing. They come with its voice.", ...speechCtl("ears")),
      testRow("Test the microphone", "Listens for four seconds, then says how loud it was and what it heard.", "micTest", btn("Test", () => api().test_mic())),
    ] },
    { name: "Voice", rows: () => [
      seg("reply_mode", "Replies", "Subtitles appear in the corner of your screen.",
        [["both", "Voice and subtitles"], ["subtitles", "Subtitles only"], ["voice", "Voice only"]]),
      seg("voice_engine", "Voice engine", "Mirage's own voice runs on this PC." + (C().voice_engine === "voicestudio" ? " VoiceStudio has to be open to use it." : ""),
        [["mirage", "Mirage"], ["windows", "Windows"], ...(C().voice_engine === "voicestudio" ? [["voicestudio", "VoiceStudio"]] : [])], true),
      C().voice_engine === "windows" && row("Windows voice", "", selectEl(S.options.voices, C().voice_id || "", v => setCfg({ voice_id: v }).then(() => api().test_voice()), [["", "System default"]], "Windows voice")),
      C().voice_engine === "voicestudio" && row("VoiceStudio voice", "Voices you design or clone in VoiceStudio appear here.", ...vsCtl()),
      C().voice_engine === "mirage" && !spInstalled() && statusRow("Mirage's voice", "Installs Mirage's voice and hearing together, about " + ((S.speech || {}).size_mb || 830) + " MB.", ...speechCtl("voice")),
      C().voice_engine === "mirage" && spInstalled() && row("Voice", "Kokoro voices, made on this PC. Bella is the default.",
        selectEl(S.speech.voices, C().kokoro_voice || "af_bella", v => setCfg({ kokoro_voice: v }, true).then(() => api().test_voice()), [], "Voice")),
      C().voice_engine === "mirage" && spInstalled() && range("voice_pitch", "Pitch", "Lower or higher, keeping the same speed.", -6, 6, 1, v => (v > 0 ? "+" : "") + v, () => api().test_voice()),
      C().voice_engine === "mirage" && spInstalled() && range("voice_robot", "Robot effect", "Makes the voice sound more like a machine.", 0, 100, 5, v => v + "%", () => api().test_voice()),
      range("voice_rate", "Speed", "", 100, 300, 5, v => v),
      range("voice_volume", "Volume", "", 0, 1, .05, v => Math.round(v * 100) + "%"),
      row("Hear it", "", btn("Play a test sentence", () => api().test_voice())),
      C().voice_engine === "mirage" && S.speech && S.speech.last_error && statusRow("Last voice problem", S.speech.last_error),
    ] },
    { name: "Corner hologram", rows: () => [
      toggle("hologram_enabled", "Show in the corner", "The hologram and subtitles appear in a corner of the screen while Mirage listens, thinks and speaks."),
      C().hologram_enabled !== false && seg("hologram_style", "Look", "", [["logo", "Headband"], ["orb", "Orb"]], false, null, () => api().preview_hologram()),
      C().hologram_enabled !== false && row("Corner", "", selectEl([["bottom-right", "Bottom right"], ["bottom-left", "Bottom left"], ["top-right", "Top right"], ["top-left", "Top left"]],
        C().hologram_corner, v => setCfg({ hologram_corner: v }).then(() => api().preview_hologram()), [], "Corner")),
      C().hologram_enabled !== false && seg("hologram_size", "Size", "", [["small", "Small"], ["medium", "Medium"], ["large", "Large"]], false, null, () => api().preview_hologram()),
      C().hologram_enabled !== false && toggle("subtitles_show_you", "Show what I said too", "Your words appear first, then Mirage's reply."),
      C().hologram_enabled !== false && row("Preview", "", btn("Show me", () => api().preview_hologram())),
    ] },
  ] },
  { id: "brain", name: "Brain", blurb: "Who answers, model, personality", sections: [
    { name: "Who answers", rows: () => [
      seg("brain", "Brain", "Mirage's own brain runs on this PC: free, private, and it works offline. Claude is smarter and uses your Claude account or an API key. Shortcuts and built-in skills never need a brain.",
        [["local", "Mirage"], ["claude_code", "Claude Code"], ["api", "API key"], ["off", "Off"]], true),
      C().brain === "local" && (localInstalled() ? row("Mirage's brain", "", ...localCtl())
                                                  : statusRow("Mirage's brain", "Downloads the engine and an AI model that run on your graphics card.", ...localCtl())),
      C().brain === "local" && seg("local_model", "Model", "Qwen 3.5 9B is smarter. Gemma 4 E4B uses less graphics memory and answers faster (Google's Gemma Terms of Use apply).",
        ((S.local || {}).models || []).map(m => [m[0], m[1]])),
      C().brain === "local" && localInstalled() && range("brain_idle_minutes", "Free graphics memory after", "When the brain isn't used, it hands graphics memory back for games, and wakes up on the next question.", 1, 30, 1, v => v + " min"),
      C().brain === "local" && toggle("think_hard_claude", "Use Claude for “think hard”", "Start a question with “think hard” for tough ones. With this on and Claude Code set up, Claude answers those; otherwise Mirage's brain takes longer to think it through."),
      C().brain === "claude_code" && statusRow("Claude Code", "Uses your Claude account. Install it once, then log in.", ...claudeCtl()),
      C().brain === "claude_code" && seg("claude_model", "Model", "Fast uses the least of your Claude usage and replies quickest.",
        [["haiku", "Fast"], ["sonnet", "Balanced"], ["opus", "Smartest"]]),
      C().brain === "claude_code" && toggle("claude_power", "Let Claude run commands and edit files", "Lets Claude run commands and read, create or edit any file on this PC without asking. Only turn this on if you trust everything it reads: a web page could tell it to run something. When off, Claude can still search the web and use Mirage's skills."),
      C().brain === "api" && text("anthropic_api_key", "Anthropic API key", "Pay-per-use. Get one at console.anthropic.com.", "sk-ant-…", true),
      C().brain !== "off" && testRow("Try it", "Sends a short test question.", "brainTest", btn("Test the brain", () => api().test_brain())),
    ] },
    { name: "Personality", when: () => C().brain !== "off", rows: () => [
      row("How Mirage comes across", "In your words. For example: calm and dry, like a butler who's seen it all.", areaEl("personality", "Calm, witty, a little playful…", "Personality")),
    ] },
    { name: "Allowed to", when: () => C().brain !== "off", rows: () => [
      row("Use my mouse and keyboard", "So it can do things like “open Discord and go to my messages”. Press Esc or move the mouse to stop it. It never types passwords, and asks before sending, deleting or buying anything.",
        toggleEl(C().pc_control !== false, v => setCfg({ pc_control: v }), "Use my mouse and keyboard")),
    ] },
  ] },
  { id: "privacy", name: "Privacy and data", blurb: "Memory, history, diagnostics", sections: [
    { name: "Memory", rows: () => [
      row("Learn from our conversations", "Mirage's own brain notices lasting things about you as you talk (what you like, your projects, people) and saves them, tagged “noticed”. Never passwords, codes or card numbers.",
        toggleEl(C().auto_learn !== false, v => setCfg({ auto_learn: v }), "Learn from our conversations")),
      row("Keep a history of our chats", "Saved on this PC only, so Mirage can look back: “what did we talk about yesterday?” Shown under Memory, Past chats.",
        toggleEl(C().chat_history !== false, v => setCfg({ chat_history: v }), "Keep a history of our chats")),
      row("Delete chat history", "Removes every saved chat. What Mirage remembers about you stays.",
        sureBtn("Delete history", "Click again to delete", () => api().memory_action("clear_chats", "").then(r => toast(r.message)))),
      row("Get to know me", "Mirage asks you a few questions and remembers the answers.", btn("Start", () => api().memory_action("interview", "").then(r => { toast(r.message); show("home"); }))),
    ] },
    { name: "Help and diagnostics", rows: () => {
      const d = S.diag;
      const again = () => btn("↻", () => { S.diag = null; renderSettings(); }, "small", "Check again");
      if (!d) return [statusRow("Checking this PC…", "")];
      if (d.failed) return [statusRow("Couldn't check this PC", "The log may say why.", again())];
      const facts = h("div", { class: "facts" }, h("h3", {}, "This PC"),
        h("dl", {}, Object.entries(d.pc).map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]).flat()));
      facts.dataset.find = "this pc " + Object.keys(d.pc).join(" ").toLowerCase() + " graphics gpu memory ram processor windows";
      const brain = testRow("Brain", "", "brainTest", btn("Test the brain", () => api().test_brain()));
      brain.querySelector(".lbl-top").after(h("span", { class: "sub" }, d.brain + "."));
      brain.dataset.find += " " + d.brain.toLowerCase();
      return [
        row("Report for help", "This PC, Mirage's parts and the end of the log, without your name or anything you said. Paste it where you ask for help.",
          btn("Copy report", copyReport, "primary"), again()),
        statusRow("Microphone", d.mic, h("div", { class: "meter" }, h("i", { id: "diagMeter" }))),
        statusRow("Hearing and voice", d.hearing + ". " + d.voice + "."),
        brain,
        facts,
      ];
    } },
    { name: "Files", rows: () => [
      row("Log and data", "Your settings, memory, log and downloads.", btn("Open log", () => api().open_path("log")), btn("Open data folder", () => api().open_path("folder"))),
    ] },
  ] },
];

/* Diagnostics: fetched when its group opens or a search needs it, and again with ↻ */
let diagLoading = false;
function loadDiag() {
  if (diagLoading) return;
  diagLoading = true;
  api().diagnostics().then(d => { S.diag = d; }).catch(() => { S.diag = { failed: true }; toast("Couldn't check everything."); })
    .finally(() => { diagLoading = false; if (page === "settings") renderSettings(); });
}
async function copyReport() {
  const text = await api().diagnostic_report();
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied. Paste it where you're asking for help.", 3500);
  } catch (e) {  // no clipboard: show the text so it can be copied by hand
    const t = h("textarea", { class: "report", rows: 10, readonly: true, "aria-label": "Diagnostic report" });
    t.value = text;
    $("#settingsPanel").append(t);
    t.focus(); t.select();
    toast("Press Ctrl+C to copy the report.", 4000);
  }
}

function renderSettings() {
  const q = settingsQuery.trim().toLowerCase();
  const nav = $("#settingsNav");
  nav.textContent = "";
  for (const g of GROUPS)
    nav.append(h("button", { class: "group-btn", "aria-current": !q && g.id === settingsGroup ? "true" : "false",
      onclick: () => { settingsGroup = g.id; settingsQuery = ""; $("#settingsSearch").value = ""; renderSettings(); $("#settingsScroll").scrollTop = 0; } },
      h("b", {}, g.name), h("small", {}, g.blurb)));
  if ((q || settingsGroup === "privacy") && !S.diag) loadDiag();

  const panel = $("#settingsPanel"), sc = $("#settingsScroll"), top = sc.scrollTop;
  const focusId = document.activeElement && panel.contains(document.activeElement) ? document.activeElement.id : null;
  panel.textContent = "";
  let found = 0;
  for (const g of GROUPS) {
    if (!q && g.id !== settingsGroup) continue;
    for (const sec of g.sections) {
      if (sec.when && !sec.when()) continue;
      let rows = sec.rows().filter(Boolean);
      if (q) {
        const inName = (g.name + " " + sec.name).toLowerCase().includes(q);
        rows = rows.filter(r => inName || (r.dataset.find || "").includes(q));
      }
      if (!rows.length) continue;
      found += rows.length;
      panel.append(h("section", { class: "card sec-card" }, h("h2", { class: "label" }, q ? g.name + " · " + sec.name : sec.name), ...rows));
    }
  }
  if (q) panel.prepend(h("p", { class: "found", role: "status" }, found
    ? (found === 1 ? "1 setting matches “" : found + " settings match “") + settingsQuery.trim() + "”."
    : "Nothing matches “" + settingsQuery.trim() + "”. Try “voice”, “startup” or “history”."));
  sc.scrollTop = top;
  const again = focusId && panel.querySelector("#" + CSS.escape(focusId));  // the same control, redrawn
  if (again) again.focus();
}

/* settings building blocks */
let rowSeq = 0;
function rowEl(label, help, sub, ctl) {
  const lbl = h("div", { class: "lbl" });
  const top = h("div", { class: "lbl-top" }, h("b", {}, label));
  lbl.append(top);
  if (sub) lbl.append(h("span", { class: "sub" }, sub));
  if (help) {
    const id = "help-" + label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const p = h("p", { class: "help", id }, help);
    p.hidden = !helpOpen.has(label);
    const q = h("button", { class: "qbtn", id: "q" + id, "aria-expanded": p.hidden ? "false" : "true", "aria-controls": id,
      "aria-label": "About “" + label + "”", title: "About “" + label + "”" }, h("span", { "aria-hidden": "true" }, "?"));
    q.addEventListener("click", () => {
      p.hidden = !p.hidden;
      q.setAttribute("aria-expanded", p.hidden ? "false" : "true");
      if (p.hidden) helpOpen.delete(label); else helpOpen.add(label);
    });
    top.append(q);
    lbl.append(p);
  }
  const r = h("div", { class: "row" }, lbl, h("div", { class: "ctl" }, ...ctl));
  r.dataset.find = (label + " " + (help || "") + " " + (sub || "")).toLowerCase();
  return r;
}
function row(label, help, ...ctl) { return rowEl(label, help, "", ctl); }
function statusRow(label, sub, ...ctl) { return rowEl(label, "", sub, ctl); }
/* a row for a test: its answer (often a sentence or two) shows in a box under the label */
function testRow(label, help, id, ...ctl) {
  const r = row(label, help, ...ctl);
  r.classList.add("test");
  r.querySelector(".lbl").append(stateEl(id, "", "", "result"));
  return r;
}
/* two clicks for things that can't be undone: the first arms the button (show(true)), the second does it;
   left alone for four seconds it goes back (show(false)) */
function confirmTwice(b, show, fn) {
  let armed = null;
  b.addEventListener("click", () => {
    if (armed) { clearTimeout(armed); armed = null; show(false); fn(); return; }
    show(true);
    armed = setTimeout(() => { armed = null; show(false); }, 4000);
  });
  return b;
}
function sureBtn(label, sure, fn) {
  const b = btn(label, null, "danger");
  return confirmTwice(b, on => { b.textContent = on ? sure : label; b.classList.toggle("armed", on); }, fn);
}
function sureIcon(label, fn) {
  const b = h("button", { class: "icon-btn del", title: label, "aria-label": label }, icon("trash"));
  return confirmTwice(b, on => {
    const t = on ? "Click again to delete" : label;
    b.classList.toggle("armed", on); b.title = t; b.setAttribute("aria-label", t);
  }, fn);
}
function btn(label, fn, kind = "", title = null, id = null) {
  return h("button", { class: "btn " + kind, onclick: fn, title, id, "aria-label": title || null }, label);
}
function stateEl(id, text = "", cls = "", extra = "") {
  const last = !text && S.prog && S.prog[id];  // the latest progress message, if any came in
  return h("span", { class: "state " + extra + " " + (last ? last[2] || "wait" : cls), id, role: "status" }, last ? last[1] : text);
}
/* new text and colour for a stateEl, keeping its other classes (a result box) */
function setState(el, text, how) {
  if (!el) return;
  el.textContent = text;
  el.classList.remove("ok", "bad", "wait");
  el.classList.add("state", how || "wait");
}
/* a progress bar for a stateEl: shown while there's a fraction (0-1), hidden when it's done or failed */
function barEl(id) {
  const b = h("div", { class: "pbar", id: id + "Bar", role: "progressbar", "aria-label": "Progress", "aria-valuemin": "0", "aria-valuemax": "100" }, h("i"));
  setBar(id, S.prog && S.prog[id], b);
  return b;
}
function setBar(id, data, el = null) {
  const b = el || $("#" + id + "Bar");
  if (!b) return;
  const done = data && typeof data[3] === "number" ? Math.max(0, Math.min(1, data[3])) : null;
  b.hidden = done === null || data[2] === "bad";
  if (done !== null) { b.firstChild.style.width = Math.round(done * 100) + "%"; b.setAttribute("aria-valuenow", String(Math.round(done * 100))); }
}
function toggleEl(on, fn, label = "") {
  const t = h("button", { class: "toggle" + (on ? " on" : ""), role: "switch", "aria-checked": on ? "true" : "false", "aria-label": label || null,
    id: "t-" + (++rowSeq) });
  if (label) t.id = "t-" + label.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  t.addEventListener("click", () => { const v = !t.classList.contains("on"); t.classList.toggle("on", v); t.setAttribute("aria-checked", v); fn(v); });
  return t;
}
function toggle(key, label, help = "") { return row(label, help, toggleEl(!!C()[key], v => setCfg({ [key]: v }, true), label)); }
function segEl(options, value, fn, label = "") {
  const box = h("div", { class: "seg", role: "radiogroup", "aria-label": label || null });
  const slug = v => "g-" + (label + "-" + v).toLowerCase().replace(/[^a-z0-9]+/g, "-");  // so focus comes back after a redraw
  for (const [v, l] of options) box.append(h("button", { class: v === value ? "on" : "", role: "radio", "aria-checked": v === value ? "true" : "false", id: slug(v),
    onclick: () => { $$("button", box).forEach(b => { b.classList.remove("on"); b.setAttribute("aria-checked", "false"); }); fn(v); } }, l));
  return box;
}
function seg(key, label, help, options, rerender = false, guard = null, after = null) {
  return row(label, help, segEl(options, C()[key], v => {
    const why = guard && guard(v);
    if (why) { toast(why); renderSettings(); return; }
    setCfg({ [key]: v }, rerender).then(() => { if (!rerender) renderSettings(); if (after) after(v); });
  }, label));
}
function selectEl(options, value, fn, extra = [], label = "") {
  const all = [...extra, ...(options || [])];
  if (value && !all.some(o => o[0] === value)) all.push([value, value]);
  const s = h("select", { "aria-label": label || null, id: label ? "s-" + label.toLowerCase().replace(/[^a-z0-9]+/g, "-") : null },
    all.map(([v, l]) => h("option", { value: v, selected: v === value }, l)));
  s.addEventListener("change", () => fn(s.value));
  return s;
}
function range(key, label, help, min, max, step, fmt, after = null) {
  const val = h("output", { class: "val" }, fmt(C()[key]));
  const r = h("input", { type: "range", min, max, step, value: C()[key], "aria-label": label, id: "r-" + key });
  const pct = () => r.style.setProperty("--p", ((r.value - min) / (max - min) * 100) + "%");
  pct();
  let tm;
  r.addEventListener("input", () => { val.textContent = fmt(+r.value); pct(); clearTimeout(tm); tm = setTimeout(() => setCfg({ [key]: +r.value }).then(() => after && after()), 250); });
  return row(label, help, r, val);
}
function text(key, label, help, placeholder, secret = false, value = null, save = null) {
  const i = h("input", { type: secret ? "password" : "text", placeholder, "aria-label": label, id: "x-" + key, autocomplete: "off" });
  i.value = value != null ? value : (C()[key] || "");
  const commit = () => { const v = i.value.trim(); if (save) save(v); else if (v !== (C()[key] || "")) setCfg({ [key]: v }); };
  i.addEventListener("change", commit);
  i.addEventListener("keydown", e => { if (e.key === "Enter") i.blur(); });
  return row(label, help, i);
}
function areaEl(key, placeholder, label) {
  const t = h("textarea", { placeholder, rows: 3, "aria-label": label, id: "a-" + key });
  t.value = C()[key] || "";
  t.addEventListener("change", () => setCfg({ [key]: t.value.trim() }));
  return t;
}

/* custom controls */
function claudeCtl() {
  const c = S.claude || {};
  if (!c.installed) return [stateEl("claudeState", "Not installed", "bad"), btn("Install Claude Code (about 180 MB)", () => api().install_claude(), "primary")];
  return [stateEl("claudeState", c.logged_in ? "Installed and logged in" : "Installed, not logged in", c.logged_in ? "ok" : "wait"),
          btn(c.logged_in ? "Log in again" : "Log in", () => api().claude_login(), c.logged_in ? "" : "primary")];
}
function vsCtl() {
  const vs = S.options.vs || { ok: false, voices: [] };
  const voices = [["", "VoiceStudio default"], ...vs.voices, ...["alloy", "echo", "fable", "onyx", "nova", "shimmer"].map(p => [p, "Preset: " + p])];
  return [selectEl(voices, C().voicestudio_voice || "", v => setCfg({ voicestudio_voice: v }).then(() => api().test_voice()), [], "VoiceStudio voice"),
          btn("↻", () => api().refresh_options().then(o => { S.options = o; renderSettings(); }), "small", "Check VoiceStudio again"),
          stateEl("vsState", vs.ok ? "Connected" : "Not reachable", vs.ok ? "ok" : "bad")];
}

/* Mirage's own brain */
const localInstalled = () => !!(S.local && S.local.installed);
const fmtSize = mb => mb >= 1000 ? (mb / 1000).toFixed(1) + " GB" : Math.round(mb) + " MB";
function localCtl() {
  const L = S.local || {};
  if (L.state === "installing") return [stateEl("localState", L.detail || "Installing…", "wait")];
  if (!L.installed) return [stateEl("localState", L.state === "error" ? L.detail : "Not installed", L.state === "error" ? "bad" : ""),
    btn("Install (" + fmtSize(L.download_mb || 0) + ")", () => { S.local.state = "installing"; S.local.detail = "Starting…"; renderSettings(); api().install_local_brain(C().local_model); }, "primary")];
  if (L.state === "error") return [stateEl("localState", L.detail, "bad")];
  if (L.state === "starting") return [stateEl("localState", L.detail || "Starting…", "wait")];
  if (L.running) return [stateEl("localState", L.gpu === false ? "Running on the processor" : "Running on your graphics card", "ok")];
  return [stateEl("localState", L.gpu === false ? "Ready, on the processor. It wakes up when you ask something." : "Ready. It wakes up when you ask something.", "ok")];
}

/* Mirage's own voice and ears */
const spInstalled = () => !!(S.speech && S.speech.installed);
function speechCtl(where) {
  const m = S.speech || {};
  if (m.state === "installing") return [stateEl("speechState", m.detail || "Installing…", "wait")];
  if (!m.installed) return [stateEl("speechState", m.state === "error" ? m.detail : "Not installed", m.state === "error" ? "bad" : ""),
    btn("Install", () => { S.speech.state = "installing"; S.speech.detail = "Starting…"; renderSettings(); api().install_speech(); }, "primary")];
  if (m.state === "ready") return [stateEl("speechState", "Ready", "ok")];
  if (m.state === "error") return [stateEl("speechState", m.detail, "bad"), btn("Try again", () => api().speech_reload())];
  return [stateEl("speechState", "Loading…", "wait")];
}

/* ------------------------------------------------------------------ what's new */
/* shown once after an update, and from Settings, General, Updates */
function openNews(notes, afterUpdate) {
  const box = $("#news");
  box.textContent = "";
  const opener = document.activeElement;
  const close = () => { box.hidden = true; syncInert(); if (afterUpdate) api().whats_new_seen(); if (opener && opener.focus) opener.focus(); };
  const sections = (notes || []).map(([v, items]) => h("section", {},
    h("h2", {}, "Mirage " + v), h("ul", {}, items.map(t => h("li", {}, t)))));
  box.append(h("div", { class: "setup-card news" },
    h("h1", { id: "newsTitle" }, afterUpdate ? "What's new" : "Recent changes"),
    sections.length ? sections : h("p", {}, "No notes for this version."),
    h("div", { class: "setup-actions" }, h("span"), btn("Got it", close, "primary"))));
  box.onkeydown = e => { if (e.key === "Escape") close(); };
  box.hidden = false;
  setTimeout(() => { const b = box.querySelector(".btn.primary"); if (b) b.focus(); }, 30);
}

/* ------------------------------------------------------------------ first-run setup */
let setupStep = -1;
const SETUP_STEPS = ["hello", "mic", "voice", "brain", "done"];
function openSetup() { setupStep = 0; $("#setup").hidden = false; renderSetup(); }
function closeSetup() {
  setupStep = -1; $("#setup").hidden = true;
  setCfg({ setup_done: true }).then(() => { show("home"); });
}
function setupGo(d) { setupStep = Math.max(0, Math.min(SETUP_STEPS.length - 1, setupStep + d)); renderSetup(); }
function renderSetup() {
  const box = $("#setup");
  if (setupStep < 0) return;
  const step = SETUP_STEPS[setupStep];
  const dots = h("ol", { class: "dots", "aria-label": "Step " + (setupStep + 1) + " of " + SETUP_STEPS.length },
    SETUP_STEPS.map((_, i) => h("li", { class: i === setupStep ? "on" : i < setupStep ? "done" : "" })));
  const back = setupStep > 0 && step !== "done" ? btn("Back", () => setupGo(-1)) : h("span");
  let body;
  if (step === "hello") {
    const name = h("input", { type: "text", id: "setupName", placeholder: "Your name", autocomplete: "off", maxlength: "40" });
    const next = () => { api().setup_name(name.value).then(() => setupGo(1)); };
    name.addEventListener("keydown", e => { if (e.key === "Enter") next(); });
    body = [h("img", { class: "setup-logo", src: "logo.png", alt: "" }),
      h("h1", { id: "setupTitle" }, "Hello. I'm Mirage."),
      h("p", {}, "Say my name, then what you want: open apps, set timers and reminders, answer questions, remember things for you, even use your mouse and keyboard. I run on this PC."),
      h("label", { for: "setupName" }, "What should I call you?"), name,
      h("div", { class: "setup-actions" }, h("span"), btn("Next", next, "primary"))];
    setTimeout(() => name.focus(), 50);
  } else if (step === "mic") {
    body = [h("h1", { id: "setupTitle" }, "Let me hear you"),
      h("p", {}, "Pick your microphone and say something. The bar should move. A headset works best."),
      h("div", { class: "setup-row" }, selectEl((S.options.mics || []).map(m => [m, m]), C().input_device || "", v => setCfg({ input_device: v || null }), [["", "System default"]], "Microphone")),
      h("div", { class: "meter wide" }, h("i", { id: "setupMeter" })),
      h("p", { class: "small" }, "My name is the wake word: “Mirage, what time is it?” You can add others later in Settings."),
      h("div", { class: "setup-actions" }, back, btn("Next", () => setupGo(1), "primary"))];
  } else if (step === "voice") {
    const m = S.speech || {};
    const ctl = m.installed ? h("span", { class: "state ok" }, m.state === "ready" ? "Installed and ready" : "Installed")
      : m.state === "installing" ? h("span", { class: "state wait", "data-progress": "speechState" }, m.detail || "Installing…")
      : h("span", {}, btn("Install (about " + (m.size_mb || 830) + " MB)", () => { S.speech.state = "installing"; S.speech.detail = "Starting…"; renderSetup(); api().install_speech(); }, "primary"),
          m.state === "error" ? h("span", { class: "state bad" }, " " + m.detail) : null);
    body = [h("h1", { id: "setupTitle" }, "My voice and hearing"),
      h("p", {}, "My own voice and ears run on this PC, so nothing you say leaves it. Without them I use the Windows voice and a basic recognizer that mishears more."),
      h("div", { class: "setup-row" }, ctl),
      h("p", { class: "small" }, m.state === "installing" ? "It keeps downloading if you go on." : "Kokoro voice and NVIDIA Parakeet hearing."),
      h("div", { class: "setup-actions" }, back, btn(m.installed || m.state === "installing" ? "Next" : "Skip for now", () => setupGo(1), m.installed || m.state === "installing" ? "primary" : ""))];
  } else if (step === "brain") {
    const L = S.local || {};
    const own = L.installed ? h("span", { class: "state ok" }, "Installed")
      : L.state === "installing" ? h("span", { class: "state wait", "data-progress": "localState" }, L.detail || "Installing…")
      : btn("Install (" + fmtSize(L.download_mb || 0) + ")", () => { setCfg({ brain: "local" }); S.local.state = "installing"; S.local.detail = "Starting…"; renderSetup(); api().install_local_brain(C().local_model); }, "primary");
    body = [h("h1", { id: "setupTitle" }, "My brain"),
      h("p", {}, "Shortcuts like timers, apps and reminders work without one. For questions, conversation and using your PC, pick a brain:"),
      h("div", { class: "choice" + (C().brain === "local" ? " on" : "") },
        h("div", {}, h("b", {}, "Mirage's own brain"), h("small", {}, "Free and private, runs on your graphics card." +
          (L.installed ? "" : L.nvidia ? " Your NVIDIA card can run it." : " I couldn't find an NVIDIA graphics card, so it would run slowly on the processor."))),
        own),
      h("div", { class: "choice" + (C().brain === "claude_code" || C().brain === "api" ? " on" : "") },
        h("div", {}, h("b", {}, "Claude"), h("small", {}, "Smarter, uses your Claude account or an API key. Set it up later in Settings, Brain.")),
        btn("Use Claude", () => setCfg({ brain: "claude_code" }, false).then(() => setupGo(1)))),
      h("div", { class: "setup-actions" }, back, btn(L.installed || L.state === "installing" ? "Next" : "Decide later", () => setupGo(1), L.installed || L.state === "installing" ? "primary" : ""))];
  } else {
    const start = toggleEl(!!S.startup, v => api().set_startup(v).then(r => { S.startup = r; }), "Start Mirage when I log in to Windows");
    body = [h("h1", { id: "setupTitle" }, "All set"),
      h("p", {}, "Try it: “Mirage, what time is it?” Then talk to me without saying my name again until I go quiet."),
      h("p", {}, "Say “Mirage, get to know me” and I'll ask a few questions, so I can help you better."),
      h("div", { class: "setup-row" }, h("span", {}, "Start Mirage when I log in to Windows"), start),
      h("div", { class: "setup-actions" }, back, btn("Start using Mirage", closeSetup, "primary"))];
  }
  box.textContent = "";
  box.append(h("div", { class: "setup-card" }, dots, ...body));
}
