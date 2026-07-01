"use strict";

// Ink — premium control app. Talks to the backend's /api/app endpoints.

const APP_VERSION = "2.0.0";
const TOKEN_KEY = "ink.token";
const SERVER_KEY = "ink.server";
const SERVER_MANUAL_KEY = "ink.serverManual";   // set when the user pins a server
const INSTALL_DISMISS_KEY = "ink.installDismissed";
// Permanent pointer to the current backend URL. Same file the frame reads, so
// moving the server (e.g. to Fly.io) only needs this one file edited.
const SERVER_DISCOVERY_URL = "./server.txt";
const $ = (id) => document.getElementById(id);

// Interest chips (Israel on by default for new frames; no "architecture").
const INTEREST_CHIPS = [
  ["israel", "Israel"], ["science", "Science"], ["history", "History"],
  ["sports", "Sports"], ["astronomy", "Astronomy"], ["art", "Art"],
  ["music", "Music"], ["cinema", "Cinema"],
];
const INTEREST_KEYS = INTEREST_CHIPS.map(([v]) => v);
const DAYS = [["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"],
             ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"]];

const token = () => localStorage.getItem(TOKEN_KEY);
const serverBase = () => (localStorage.getItem(SERVER_KEY) || "").replace(/\/+$/, "");
const setServer = (v) => {
  const clean = (v || "").trim().replace(/\/+$/, "");
  if (clean) localStorage.setItem(SERVER_KEY, clean); else localStorage.removeItem(SERVER_KEY);
};
const artworkUrl = (id) => `${serverBase()}/media/current/${id}.png?t=${Date.now()}`;

let devices = [];          // all paired devices
let currentId = null;      // device on the Frame screen
let currentDevice = null;
let resolvedTz = null;     // tz from the latest geocode (used when auto-tz is on)

// --------------------------------------------------------------------------
// Navigation
// --------------------------------------------------------------------------
const SCREENS = ["welcome", "home", "connect", "frame", "artwork", "settings", "account"];
let currentScreen = null;

// Toggle which screen is visible (no history side effects).
function setScreen(name) {
  for (const s of SCREENS) $(`screen-${s}`).hidden = s !== name;
  // Home and the Frame screen are fixed single viewports (no scroll). The Frame
  // screen can temporarily unlock when its description is expanded via "Read
  // more" (handled in setFrameExpanded).
  const fixed = name === "home" || name === "frame";
  $("app").classList.toggle("locked", fixed);
  // Also lock the <body> so the page itself can't scroll/rubber-band a few pixels
  // (overflow:hidden on #app alone doesn't stop body-level scroll).
  document.body.classList.toggle("home-locked", fixed);
  window.scrollTo(0, 0);
  currentScreen = name;
  // Refresh the home image on EVERY entry — including the back button (popstate),
  // which bypasses showHome — and (re)start its auto-refresh, so it's never stale.
  if (name === "home") { startHomeAutoRefresh(); refreshHomeArt(); }
  else stopHomeAutoRefresh();
  // The Frame screen shows a live status that must stay honest on its own
  // (age "just now" → "5m ago", flip to Asleep) — poll while it's open.
  if (name === "frame") { renderFrameStatus(currentDevice); startFrameStatusPoll(); }
  else stopFrameStatusPoll();
}

// Navigate to a screen and record it in history so the Android/browser back
// button steps back through the app instead of leaving the site.
function go(name) {
  if (name === currentScreen) { setScreen(name); return; }
  setScreen(name);
  const state = { screen: name };
  if (history.state && history.state.screen) history.pushState(state, "");
  else history.replaceState(state, "");
}

// Hardware/browser back: restore the previous in-app screen.
window.addEventListener("popstate", (e) => {
  if (closeLightbox()) return;   // a back press first dismisses an open lightbox
  const name = e.state && e.state.screen;
  if (name && SCREENS.includes(name)) setScreen(name);
});

async function api(path, { method = "GET", body, auth = true, timeout = 9000 } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && token()) headers.Authorization = `Bearer ${token()}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(serverBase() + "/api/app" + path, {
      method, headers, body: body ? JSON.stringify(body) : undefined, signal: ctrl.signal,
    });
  } catch (e) {
    throw new Error(e.name === "AbortError"
      ? "Server didn't respond — check the server address." : "Can't reach the server.");
  } finally { clearTimeout(timer); }
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    const err = new Error(d.detail || `Error ${res.status}`); err.status = res.status; throw err;
  }
  return res.status === 204 ? null : res.json();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MIN = 60000, HOUR = 60 * MIN, DAY = 24 * HOUR;
function relTime(iso) {
  if (!iso) return "never";
  const d = Date.now() - new Date(iso).getTime();
  if (d < 2 * MIN) return "just now";
  if (d < HOUR) return `${Math.round(d / MIN)}m ago`;
  if (d < DAY) return `${Math.round(d / HOUR)}h ago`;
  return `${Math.round(d / DAY)}d ago`;
}
// Status shown as "<State> · <when>": State = Online / Sleep / Offline, when =
// "now" (just checked in) or "Xm/Xh/Xd ago".
//
// The backend is the source of truth: it stamps last_seen on every frame
// check-in (the frame polls .ver every 60s while awake) and sets a 'sleeping'
// flag when the frame pings it just before deep sleep. So we trust the explicit
// flag immediately, and otherwise treat the device as Online only if it has
// checked in within ~2.5 poll cycles — a frame that stopped polling has gone to
// sleep (covers a dropped sleep-ping too).
const AWAKE_GRACE_MS = 150000;   // ~2.5 × the frame's 60s poll
function statusWhen(iso) {
  if (!iso) return "";
  return (Date.now() - new Date(iso).getTime()) < 90000 ? "now" : relTime(iso);
}
function frameState(d) {
  if (d && d.sleeping) return { label: "Sleep", cls: "s-sleep", sub: statusWhen(d.last_seen) };
  const seen = d.last_seen ? Date.now() - new Date(d.last_seen).getTime() : null;
  if (seen == null) return { label: "Setting up", cls: "s-setup", sub: "first check-in" };
  if (seen < AWAKE_GRACE_MS) return { label: "Online", cls: "s-on", sub: statusWhen(d.last_seen) };
  if (seen < 26 * HOUR) return { label: "Sleep", cls: "s-sleep", sub: statusWhen(d.last_seen) };
  return { label: "Offline", cls: "s-off", sub: statusWhen(d.last_seen) };
}
// Wi-Fi signal as 4 bars + a word (no dBm). Returns HTML — set via innerHTML.
function wifiLabel(r) {
  if (r == null || r === 0) return "—";   // real RSSI is always negative; 0 = no reading yet
  const level = r >= -60 ? 4 : r >= -70 ? 3 : r >= -80 ? 2 : 1;
  const word = ["", "Poor", "Weak", "Good", "Strong"][level];
  let bars = "";
  for (let i = 1; i <= 4; i++) bars += `<i class="${i <= level ? "on" : ""}"></i>`;
  return `<span class="wifi-bars" aria-hidden="true">${bars}</span>${word}`;
}
const shortId = (id) => (id || "").slice(-4).toUpperCase();
const defaultName = (id) => `Ink Frame · ${shortId(id)}`;
const displayName = (d) => (d && d.name) ? d.name : defaultName(d && d.id);

function flash(id, text, isErr) { const el = $(id); if (!el) return; el.textContent = text; el.hidden = false; el.className = isErr ? "error" : "ok"; }
function showError(id, e) { flash(id, e.message, true); }
let toastTimer = null;
function toast(text, ms = 2600) {
  const el = $("toast"); el.textContent = text; el.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), ms);
}

// Confirm a save on the button itself: "✓ Saved" with a subtle animation,
// then revert to the original label.
const SAVED_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
const SAVED_DURATION_MS = 1800;
function buttonSaved(btn) {
  if (!btn) return;
  if (btn.dataset.savedTimer) clearTimeout(Number(btn.dataset.savedTimer));
  else btn.dataset.label = btn.textContent;     // remember the real label once
  btn.classList.add("btn-saved");
  btn.innerHTML = `<span class="saved-ico" aria-hidden="true">${SAVED_CHECK}</span><span class="saved-label">Saved</span>`;
  btn.dataset.savedTimer = String(setTimeout(() => {
    btn.classList.remove("btn-saved");
    btn.textContent = btn.dataset.label;
    delete btn.dataset.savedTimer; delete btn.dataset.label;
  }, SAVED_DURATION_MS));
}
function loadArtwork(imgEl, skelEl, id, onMissing) {
  imgEl.classList.remove("loaded"); if (skelEl) skelEl.hidden = false;
  imgEl.onload = () => { imgEl.classList.add("loaded"); if (skelEl) skelEl.hidden = true; };
  imgEl.onerror = () => { if (skelEl) skelEl.hidden = true; if (onMissing) onMissing(); };
  imgEl.src = artworkUrl(id);
}

// --------------------------------------------------------------------------
// Welcome
// --------------------------------------------------------------------------
function wireWelcome() {
  $("server-url").value = serverBase();
  $("server-save").addEventListener("click", () => { setServer($("server-url").value); localStorage.setItem(SERVER_MANUAL_KEY, "1"); toast("Saved — now tap Get started"); });
  $("start-btn").addEventListener("click", async () => {
    if (!confirm("Create a NEW Ink account?\n\nIf you've set up a frame before, tap Cancel and use “I already have an account” to restore it — a new account won't show your existing frame.")) return;
    try { const { token: t } = await api("/account", { method: "POST", auth: false }); localStorage.setItem(TOKEN_KEY, t); toast("New account created"); await showHome(); }
    catch (e) { showError("welcome-error", e); $("server-details").open = true; }
  });
  $("restore-open").addEventListener("click", () => { $("restore-details").open = true; $("restore-token").focus(); });
  $("restore-btn").addEventListener("click", async () => {
    const t = $("restore-token").value.trim(); if (!t) return;
    localStorage.setItem(TOKEN_KEY, t);
    try { await api("/account"); await showHome(); }
    catch (e) { localStorage.removeItem(TOKEN_KEY); showError("welcome-error", e); }
  });
}

// --------------------------------------------------------------------------
// Home — the primary frame as a hung work of art
// --------------------------------------------------------------------------
async function showHome(preferId) {
  go("home");
  try { ({ devices } = await api("/devices")); }
  catch (e) { if (e.status === 401 || e.status === 403) { localStorage.removeItem(TOKEN_KEY); return go("welcome"); } devices = []; }

  $("screen-home").classList.toggle("is-empty", !devices.length);
  if (!devices.length) { $("home-empty").hidden = false; $("home-frame").hidden = true; maybeShowInstallBanner(); return; }
  $("home-empty").hidden = true; $("home-frame").hidden = false;

  buildHomeCards(preferId);
  startHomeAutoRefresh();
  maybeShowInstallBanner();
  checkFirmwareUpdates();   // re-evaluated on every app launch / home entry
}

// Build one card per frame into the carousel; focus the preferred (or first) one.
function buildHomeCards(preferId) {
  const track = $("home-carousel");
  track.innerHTML = "";
  const tpl = $("home-card-tpl");
  for (const d of devices) {
    const card = tpl.content.firstElementChild.cloneNode(true);
    fillHomeCard(card, d);
    card.querySelector(".home-art-btn").addEventListener("click", () => openFrame(card.dataset.id));
    card.querySelector(".home-more").addEventListener("click", () => openFrame(card.dataset.id));
    track.appendChild(card);
  }
  attachReorder(track);   // long-press drag-to-reorder (no-op for a single frame)

  const multi = devices.length >= 2;
  $("home-dots").hidden = !multi;
  $("home-swipe-hint").hidden = !multi;

  let idx = devices.findIndex((d) => d.id === preferId);
  if (idx < 0) idx = 0;
  const dev = devices[idx];
  currentId = dev.id; currentDevice = dev;
  renderHomeDots(idx);
  // Jump (no animation) to the focused card once layout is ready.
  requestAnimationFrame(() => {
    const card = track.children[idx];
    if (card) { const prev = track.style.scrollBehavior; track.style.scrollBehavior = "auto"; track.scrollLeft = card.offsetLeft; track.style.scrollBehavior = prev; }
  });
}

function fillHomeCard(card, d) {
  card.dataset.id = d.id;
  card.classList.toggle("is-portrait", d.orientation === "portrait");
  card.querySelector(".home-frame-name").textContent = displayName(d);
  const asleep = frameState(d).cls === "s-sleep";
  card.querySelector(".home-sleep-moon").hidden = !asleep;
  const cap = card.querySelector(".home-explain");
  cap.textContent = "Loading today's work…";
  loadArtwork(card.querySelector(".home-art-img"), card.querySelector(".home-skeleton"), d.id, () => {
    cap.textContent = "No artwork yet — open the frame and tap Generate.";
  });
  loadExplain(d.id, card);
}

function renderHomeDots(active) {
  const el = $("home-dots");
  if (!el || devices.length < 2) { if (el) el.innerHTML = ""; return; }
  el.innerHTML = Array.from({ length: devices.length }, (_, i) =>
    `<span class="dot-i${i === active ? " on" : ""}"></span>`).join("");
}

function activeHomeIndex() {
  const g = $("home-carousel");
  if (!g || !g.clientWidth) return 0;
  return Math.max(0, Math.min(devices.length - 1, Math.round(g.scrollLeft / g.clientWidth)));
}
function activeHomeCard() {
  const g = $("home-carousel");
  return g ? g.children[activeHomeIndex()] : null;
}

let homeScrollRAF = null;
function onHomeScroll() {
  cancelAnimationFrame(homeScrollRAF);
  homeScrollRAF = requestAnimationFrame(() => {
    const i = activeHomeIndex();
    const d = devices[i];
    if (d && d.id !== currentId) { currentId = d.id; currentDevice = d; }
    renderHomeDots(i);
  });
}

// Drag-to-reorder on the home carousel. A normal horizontal swipe navigates
// (native scroll-snap); HOLDING a card ~400ms enters reorder mode, then dragging
// left/right swaps it past neighbors. Wired once on the persistent track element;
// reads the live `devices` array + current cards each gesture.
const REORDER_HOLD_MS = 400;
const REORDER_SLOP = 10;       // movement before the hold fires => it's a swipe
function attachReorder(track) {
  if (track._reorderWired) return;
  track._reorderWired = true;
  let timer = null, dragging = false, card = null, idx = 0, startX = 0, startY = 0;
  const cardW = () => track.clientWidth || 1;
  const cancelHold = () => { if (timer) { clearTimeout(timer); timer = null; } };

  const swap = (a, b) => {
    const t = devices[a]; devices[a] = devices[b]; devices[b] = t;
    const nodes = track.children;
    if (a < b) track.insertBefore(nodes[a], nodes[b].nextSibling);
    else track.insertBefore(nodes[a], nodes[b]);
  };

  const enter = () => {
    if (devices.length < 2 || !card) return;
    dragging = true;
    track.classList.add("reordering");
    card.classList.add("dragging");
    try { navigator.vibrate && navigator.vibrate(12); } catch { /* ignore */ }
  };

  track.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || devices.length < 2) { card = null; return; }
    card = e.target.closest(".home-card");
    if (!card) return;
    idx = Array.prototype.indexOf.call(track.children, card);
    startX = e.touches[0].clientX; startY = e.touches[0].clientY;
    dragging = false; cancelHold();
    timer = setTimeout(enter, REORDER_HOLD_MS);
  }, { passive: true });

  track.addEventListener("touchmove", (e) => {
    if (!card) return;
    const dx = e.touches[0].clientX - startX;
    const dy = e.touches[0].clientY - startY;
    if (!dragging) {
      if (Math.abs(dx) > REORDER_SLOP || Math.abs(dy) > REORDER_SLOP) { cancelHold(); card = null; }
      return;   // let native scroll handle the swipe
    }
    e.preventDefault();   // own the gesture while reordering
    const w = cardW();
    card.style.transform = `translateX(${dx}px) scale(1.04)`;
    if (dx > w * 0.55 && idx < track.children.length - 1) {
      swap(idx, idx + 1); idx += 1; startX += w; card.style.transform = `translateX(${dx - w}px) scale(1.04)`; renderHomeDots(idx);
    } else if (dx < -w * 0.55 && idx > 0) {
      swap(idx, idx - 1); idx -= 1; startX -= w; card.style.transform = `translateX(${dx + w}px) scale(1.04)`; renderHomeDots(idx);
    }
  }, { passive: false });

  const end = (e) => {
    cancelHold();
    if (!dragging || !card) { card = null; return; }
    if (e && e.cancelable) e.preventDefault();   // suppress the click-through (don't open the frame)
    const dropped = card, dropIdx = idx;
    dropped.style.transition = "transform .18s var(--ease)";
    dropped.style.transform = "";
    dropped.classList.remove("dragging");
    track.classList.remove("reordering");
    requestAnimationFrame(() => { track.scrollLeft = dropIdx * cardW(); });
    setTimeout(() => { dropped.style.transition = ""; }, 220);
    renderHomeDots(dropIdx);
    currentId = devices[dropIdx].id; currentDevice = devices[dropIdx];
    dragging = false; card = null;
    api("/devices/reorder", { method: "POST", body: { order: devices.map((d) => d.id) } })
      .catch(() => toast("Couldn't save the new order"));
  };
  track.addEventListener("touchend", end);
  track.addEventListener("touchcancel", end);
}

// Keep the home image current without a manual button: re-pull silently (preload
// then swap, so no skeleton flash) on a timer while home is visible, and on focus
// / tab-visibility. Guarantees the home always shows the real, latest artwork.
async function refreshHomeArt() {
  if (!currentId || currentScreen !== "home") return;
  const card = activeHomeCard();
  if (!card) return;
  const url = artworkUrl(currentId);
  const probe = new Image();
  probe.onload = () => { const el = card.querySelector(".home-art-img"); if (el) { el.src = url; el.classList.add("loaded"); } };
  probe.src = url;
  loadExplain(currentId, card);
  // Also refresh the frame's STATUS so the Asleep moon updates on its own (no
  // manual reload) — picks up the backend 'sleeping' flag, falling back to the
  // last-seen timeout if the sleep ping didn't land.
  try {
    const r = await api("/devices");
    const d = r && r.devices && r.devices.find((x) => x.id === currentId);
    if (d) {
      currentDevice = d;
      const asleep = frameState(d).cls === "s-sleep";
      const m = card.querySelector(".home-sleep-moon");
      if (m) m.hidden = !asleep;
    }
  } catch { /* keep the last-known status */ }
}
let homeArtTimer = null;
function startHomeAutoRefresh() {
  stopHomeAutoRefresh();
  homeArtTimer = setInterval(() => {
    if (currentScreen === "home" && document.visibilityState === "visible") refreshHomeArt();
  }, 45000);
}
function stopHomeAutoRefresh() { if (homeArtTimer) { clearInterval(homeArtTimer); homeArtTimer = null; } }

// One shared device cache so Home and the Frame screen never disagree: whoever
// fetches a device writes it back into the `devices` list everyone reads from.
function syncDeviceCache(d) {
  if (!d || !Array.isArray(devices)) return;
  const i = devices.findIndex((x) => x.id === d.id);
  if (i >= 0) devices[i] = d; else devices.push(d);
}

// Live status on the Frame screen. Re-render every tick (so the relative time
// ages and crosses the Awake→Asleep threshold without a refetch) and refetch so
// the backend 'sleeping' flag + last check-in are picked up automatically.
const FRAME_STATUS_MS = 15000;
let frameStatusTimer = null;
let otaInFlight = false;   // true between pushing an OTA and the frame rebooting
function renderFrameStatus(d) {
  if (!d) return;
  const st = frameState(d);
  $("fr-dot").className = `dot ${st.cls}`;
  $("fr-status").textContent = st.sub ? `${st.label} · ${st.sub}` : st.label;
  renderMorningStatus(d, st);
}

// Was today's daily update supposed to run, and did it? Surfaces a friendly banner
// when the frame missed its morning update (it was offline at wake time), or an
// "updating now" hint while it's catching up. Uses last_auto_gen (the date the
// daily update last ran) + the wake time + reachability.
function two(n) { return String(n).padStart(2, "0"); }
function scheduledToday(d, now) {
  if ((d.schedule || "daily") === "daily") return true;
  const days = (d.schedule_days || "").toLowerCase();
  if (!days.trim()) return true;
  const wd = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"][now.getDay()];
  return days.split(",").map((s) => s.trim()).includes(wd);
}
function renderMorningStatus(d, st) {
  const el = $("frame-alert");
  if (!el) return;
  const now = new Date();
  const wakeH = d.wake_hour ?? 6, wakeM = d.wake_minute ?? 0;
  const wake = new Date(now); wake.setHours(wakeH, wakeM, 0, 0);
  const todayISO = `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`;
  const ranToday = d.last_auto_gen === todayISO;
  // No banner if: today's time hasn't arrived, not a scheduled day, or it already ran.
  if (now < wake || !scheduledToday(d, now) || ranToday) { el.hidden = true; return; }
  const when = `${two(wakeH)}:${two(wakeM)}`;
  if (st && st.label === "Online") {
    el.className = "frame-alert info"; el.hidden = false;
    el.textContent = "Creating today's artwork now…";
  } else {
    el.className = "frame-alert"; el.hidden = false;
    el.textContent = `Couldn't update this morning — your frame was offline at ${when}. It'll update the next time it wakes.`;
  }
}

// --------------------------------------------------------------------------
// Firmware updates: the app is the moderator. It compares each frame's reported
// version (fw_version) to the backend's published version (update_available),
// surfaces a top toast, and lets the user start the OTA — which the frame pulls
// + flashes itself. We never push to the frame from the browser.
// --------------------------------------------------------------------------
let updateDismissed = false;     // session-only: a Close hides the toast until relaunch
let otaTargetId = null;          // the frame the toast's Update button targets
const OTA_MIN_BATTERY = 50;      // %; below this we require USB power (flash safety)

// OTA can only succeed when the frame is awake/polling. The frame can't sense its
// own power, so the firmware's own low-voltage backstop guards the write; the app
// only needs to confirm the frame is reachable.
function otaBlockReason(d) {
  if (!d || !d.update_available) return "no-update";
  if (frameState(d).cls !== "s-on") return "offline";
  return null;   // good to go
}

// Scan all paired frames for an available update and show the toast for the
// first one (unless dismissed this session). Runs on every app launch via showHome.
function checkFirmwareUpdates() {
  const d = (devices || []).find((x) => x.update_available);
  if (!d || updateDismissed) { hideUpdateToast(); return d || null; }
  showUpdateToast(d);
  return d;
}

function showUpdateToast(d) {
  otaTargetId = d.id;
  const many = (devices || []).length > 1;
  $("fw-toast-title").textContent = many
    ? `Firmware update · ${displayName(d)}`
    : "Firmware update available";
  const reason = otaBlockReason(d);
  const sub = reason === "offline" ? "Wake the frame to update"
            : `Version ${d.fw_version || "?"} → ${d.latest_fw || "?"}`;
  $("fw-toast-sub").textContent = sub;
  const btn = $("fw-toast-update");
  btn.disabled = otaInFlight || (reason && reason !== null);
  btn.textContent = otaInFlight ? "Updating…" : "Update";
  $("fw-toast").hidden = false;
}
function hideUpdateToast() { $("fw-toast").hidden = true; }

// Has a newer app (PWA) build been published? Ask the service worker to re-check
// its script; a new worker showing up (updatefound / waiting / installing) means
// fresh assets are ready and the user should Refresh to load them.
async function checkAppUpdate() {
  if (!("serviceWorker" in navigator)) return false;
  const reg = await navigator.serviceWorker.getRegistration();
  if (!reg) return false;
  let found = false;
  const onFound = () => { found = true; };
  reg.addEventListener("updatefound", onFound);
  try { await reg.update(); } catch (_) {}
  await new Promise((r) => setTimeout(r, 1500));   // let an install begin
  reg.removeEventListener("updatefound", onFound);
  return found || !!reg.waiting || !!reg.installing;
}

// "Check for updates": checks BOTH the frame firmware and the app, shows the
// relevant toast(s), and reports "Up to date" on the button when there's nothing.
// Never navigates away — the user reloads only via the app toast's Refresh.
async function checkForUpdates(btn) {
  if (btn.dataset.busy) return;
  btn.dataset.busy = "1";
  const orig = btn.dataset.label || btn.textContent;
  btn.dataset.label = orig;
  btn.disabled = true;
  btn.innerHTML = '<span class="spin-sm" aria-hidden="true"></span>Checking…';
  let frameUpdate = false, appUpdate = false;
  try {
    updateDismissed = false;                              // an explicit check re-surfaces the toast
    try { const r = await api("/devices"); devices = r.devices || r; } catch (_) {}
    frameUpdate = !!checkFirmwareUpdates();               // shows the firmware toast if any frame is behind
    appUpdate = await checkAppUpdate();
    if (appUpdate) $("app-toast").hidden = false;         // similar toast, CTA "Refresh"
  } finally {
    btn.disabled = false;
    delete btn.dataset.busy;
    if (frameUpdate || appUpdate) {
      btn.textContent = orig;                             // a toast is showing the action
    } else {
      btn.innerHTML = '<span class="saved-ico" aria-hidden="true">' + SAVED_CHECK + '</span>Up to date';
      btn.classList.add("btn-saved");
      setTimeout(() => { btn.classList.remove("btn-saved"); btn.textContent = orig; }, 2600);
    }
  }
}

// Tracks an in-flight OTA so it can be resolved either by the poll loop OR when
// the app regains focus (the phone usually backgrounds the app while the user
// watches the frame, which pauses JS timers — so focus is the reliable signal).
let otaWatch = null;   // { deviceId, fromVer } | null

// Start the OTA for a frame: re-validate gating, confirm, queue the 'ota' command.
async function startFrameOta(deviceId) {
  const d = (devices || []).find((x) => x.id === deviceId) || currentDevice;
  const reason = otaBlockReason(d);
  if (reason === "offline") return toast("Wake the frame first — it must be online to update");
  if (reason === "battery") return toast("Plug the frame into power before updating");
  if (reason) return;
  const target = d.latest_fw || "the latest version";
  if (!confirm(`Update ${displayName(d)} to ${target}?\n\nThe frame downloads the new firmware and restarts — about a minute. Keep it powered.`)) return;
  otaInFlight = true;
  otaWatch = { deviceId, fromVer: d.fw_version };
  $("fw-toast-update").disabled = true; $("fw-toast-update").textContent = "Updating…";
  try {
    await api(`/devices/${deviceId}/command`, { method: "POST", body: { cmd: "ota" } });
    toast("Updating… the frame will download and restart.");
  } catch (e) { otaInFlight = false; otaWatch = null; renderFrameStatus(currentDevice); return toast(`Couldn't start update: ${e.message}`); }
  pollOtaResult(deviceId);
}

// Conclude an OTA: clear state, dismiss the update toast, show the outcome.
function finishOta(msg, ms) {
  otaInFlight = false; otaWatch = null;
  hideUpdateToast();                       // the update is over -> drop the toast
  toast(msg, ms);
  api("/devices").then((r) => { devices = r.devices || r; checkFirmwareUpdates(); }).catch(() => {});
}

// Given a fresh device record, resolve the in-flight OTA if it's done. Used by
// both the poll loop and the focus handler. Returns true once resolved.
function resolveOtaFrom(d) {
  if (!otaWatch || !d || d.id !== otaWatch.deviceId) return false;
  if (d.ota_error && d.ota_error !== "0") {
    finishOta(`Update failed (error ${d.ota_error}) — the frame kept its current version.`, 5000);
    return true;
  }
  if (d.fw_version && d.fw_version !== otaWatch.fromVer && !d.update_available) {
    finishOta(`✓ Frame updated to ${d.fw_version}`, 6000);
    return true;
  }
  return false;
}

// Poll the device for the OTA outcome (a backstop to the focus handler).
async function pollOtaResult(deviceId) {
  const DEADLINE = Date.now() + 180000;   // ~3 min: download + flash + reboot + re-checkin
  const tick = async () => {
    if (!otaWatch || otaWatch.deviceId !== deviceId) return;   // already resolved elsewhere
    let d; try { d = await api(`/devices/${deviceId}`); } catch { d = null; }
    if (resolveOtaFrom(d)) return;
    if (Date.now() < DEADLINE) { setTimeout(tick, 6000); return; }
    finishOta("Update didn't complete — try “Check for updates” in Frame settings.", 5000);
  };
  setTimeout(tick, 8000);   // give the frame a beat to pick up the command
}
async function pollFrameStatus() {
  renderFrameStatus(currentDevice);              // age the relative time first
  if (currentScreen !== "frame" || !currentId || document.visibilityState !== "visible") return;
  try {
    const d = await api(`/devices/${currentId}`);
    currentDevice = d; syncDeviceCache(d);
    renderFrameStatus(d); updateRefreshState();
  } catch { /* keep the last-known status */ }
}
function startFrameStatusPoll() {
  stopFrameStatusPoll();
  frameStatusTimer = setInterval(pollFrameStatus, FRAME_STATUS_MS);
}
function stopFrameStatusPoll() { if (frameStatusTimer) { clearInterval(frameStatusTimer); frameStatusTimer = null; } }

// Pull-to-refresh re-syncs the APP's view only — it never commands the physical
// frame (that's the dedicated Refresh button's job).
//   • Home: re-pull the latest artwork (or re-check devices in the empty state).
//   • Frame: reload the gallery from the backend.
async function homeRefresh() {
  if (!currentId) { await showHome(); return; }
  refreshHomeArt();
}
async function frameRefresh() {
  if (!currentId) return;
  await loadGallery(currentId);
}

// Pull-to-refresh, shared by the home + frame screens via one absolute spinner.
// Touch-events implementation (the mobile-reliable best practice): engage only
// at scroll-top on a downward-dominant drag (so a horizontal gallery swipe is
// never hijacked), move the pill with resistance, preventDefault to own the
// gesture, and on release past the threshold play a pop then spring back.
const PULL_SLOP = 8, PULL_RESIST = 0.5, PULL_THRESHOLD = 56, PULL_MAX = 110, PULL_REST = 38;
function attachPullToRefresh(screenName, onRefresh) {
  const screen = $("screen-" + screenName);
  const sp = $("pull-spinner");
  let startY = null, startX = 0, pulling = false, dist = 0, busy = false;
  const atTop = () => (window.scrollY || document.documentElement.scrollTop || 0) <= 0;

  const render = (d) => {
    const p = Math.min(1, d / PULL_THRESHOLD);
    sp.style.transition = "";
    sp.style.opacity = String(p);
    sp.style.transform = `translateY(${d}px) scale(${0.7 + p * 0.3}) rotate(${d * 2.4}deg)`;
  };
  const springBack = () => {
    sp.style.transition = "opacity .25s var(--ease), transform .25s var(--ease)";
    sp.style.opacity = ""; sp.style.transform = "";
  };

  screen.addEventListener("touchstart", (e) => {
    if (busy || currentScreen !== screenName || !atTop() || e.touches.length !== 1) { startY = null; return; }
    startY = e.touches[0].clientY; startX = e.touches[0].clientX; pulling = false; dist = 0;
  }, { passive: true });

  screen.addEventListener("touchmove", (e) => {
    if (startY == null || busy || e.touches.length !== 1) return;
    const dy = e.touches[0].clientY - startY;
    const dx = e.touches[0].clientX - startX;
    if (!pulling) {
      if (dy < PULL_SLOP) return;                  // not a downward pull yet
      if (Math.abs(dx) > dy) { startY = null; return; }   // horizontal → leave it to the browser (gallery)
      pulling = true;
    }
    dist = Math.min(dy * PULL_RESIST, PULL_MAX);    // follow the finger with resistance + cap
    render(dist);
    if (e.cancelable) e.preventDefault();           // own the vertical gesture
  }, { passive: false });

  const end = () => {
    if (startY == null) return;
    const trigger = pulling && dist >= PULL_THRESHOLD;
    startY = null; pulling = false;
    if (!trigger) { dist = 0; springBack(); return; }
    // Committed: pop at the rest position, then spring back — independent of how
    // long the (background) refresh takes.
    dist = 0; busy = true;
    sp.style.transition = "";
    sp.style.opacity = "1"; sp.style.transform = `translateY(${PULL_REST}px) scale(1)`;
    sp.classList.add("engaged");
    onRefresh();
    setTimeout(() => { sp.classList.remove("engaged"); springBack(); busy = false; }, 560);
  };
  screen.addEventListener("touchend", end);
  screen.addEventListener("touchcancel", end);
}

// Fill a card's caption from the latest artwork, and match the card's orientation
// to the ACTUAL artwork on screen (not the device's current setting, which may have
// changed after this image was made).
async function loadExplain(id, card) {
  const cap = card.querySelector(".home-explain");
  try {
    const { items } = await api(`/devices/${id}/archive?limit=1`);
    const m = items && items[0];
    cap.textContent = (m && m.event_text_en) ? m.event_text_en : "Today's work hasn't been created yet.";
    if (m && m.orientation) card.classList.toggle("is-portrait", m.orientation === "portrait");
  } catch { cap.textContent = "—"; }
}

// --------------------------------------------------------------------------
// Connect
// --------------------------------------------------------------------------
function wireConnect() {
  $("empty-connect-btn").addEventListener("click", () => go("connect"));
  $("add-frame-btn").addEventListener("click", () => go("connect"));   // "+" beside the gear
  $("connect-back").addEventListener("click", () => { stopScan(); showHome(); });
  $("pair-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const dev = await api("/devices/pair", { method: "POST", body: { pairing_code: $("pair-code").value.trim() } });
      const nm = $("pair-name").value.trim();
      if (nm) { try { await api(`/devices/${dev.id}/config`, { method: "PUT", body: { name: nm } }); } catch {} }
      $("pair-code").value = ""; $("pair-name").value = "";
      await openFrame(dev.id);
      toast("Paired! Tap Generate to make your first artwork");
    } catch (e2) { showError("pair-error", e2); }
  });
}

// --------------------------------------------------------------------------
// Frame detail
// --------------------------------------------------------------------------
let frameItems = [];           // last N generations shown in the gallery

async function openFrame(id) {
  currentId = id; go("frame");
  $("ev-meta").textContent = ""; $("ev-text").textContent = "Loading…"; $("ev-sign").hidden = true;
  $("gallery").innerHTML = ""; $("gallery-dots").innerHTML = "";
  try {
    currentDevice = await api(`/devices/${id}`);
    syncDeviceCache(currentDevice);
    renderFrameStatus(currentDevice);
    updateRefreshState();
  } catch (e) { toast(e.message); }
  await loadGallery(id);
}

function friendlyDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00"); const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - d) / DAY);
  if (diff === 0) return "Today"; if (diff === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
}

function slideCard(portrait, inner) {
  return `<div class="slide"><div class="art-card${portrait ? " is-portrait" : ""}"><div class="art-card-inner">${inner}</div></div></div>`;
}

// Each archived work carries its own orientation (the gallery can mix portrait +
// landscape). Older rows predate the column → fall back to the device's setting.
const isPortraitItem = (m) =>
  (((m && m.orientation) || (currentDevice && currentDevice.orientation)) === "portrait");

async function loadGallery(id) {
  let items = [];
  try { ({ items } = await api(`/devices/${id}/archive?limit=10`)); } catch {}
  frameItems = items || [];
  const g = $("gallery");
  if (!frameItems.length) {
    g.innerHTML = slideCard(isPortraitItem(null), `<div class="art-empty">No artwork yet —<br>tap Generate to create today's work.</div>`);
    setPlacard(null); renderDots(0, 0); return;
  }
  g.innerHTML = frameItems.map((m) => slideCard(isPortraitItem(m), `<img alt="artwork" />`)).join("");
  g.querySelectorAll(".slide img").forEach((img, i) => {
    img.onload = () => img.classList.add("loaded");
    img.src = serverBase() + frameItems[i].image_url + `?t=${Date.now()}`;
    img.style.cursor = "zoom-in";
    img.addEventListener("click", () => openLightbox(frameItems[i]));
  });
  g.scrollLeft = 0;
  setPlacard(frameItems[0]); renderDots(0, frameItems.length);
}

// --------------------------------------------------------------------------
// Lightbox — tap an artwork to view it large (orientation-aware)
// --------------------------------------------------------------------------
function openLightbox(item) {
  if (!item) return;
  const lb = $("lightbox"), img = $("lb-img");
  lb.classList.toggle("is-portrait", isPortraitItem(item));
  img.classList.remove("loaded");
  img.onload = () => img.classList.add("loaded");
  img.src = serverBase() + item.image_url + `?t=${Date.now()}`;
  lb.hidden = false;
  // Push a history entry so the back button / Android back closes the lightbox.
  history.pushState({ screen: currentScreen, lightbox: 1 }, "");
}
function closeLightbox() {
  const lb = $("lightbox");
  if (!lb || lb.hidden) return false;
  lb.hidden = true; $("lb-img").removeAttribute("src");
  return true;
}
function wireLightbox() {
  // Click anywhere except the image (backdrop or close button) dismisses.
  $("lightbox").addEventListener("click", (e) => { if (e.target !== $("lb-img")) history.back(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("lightbox").hidden) history.back(); });
}

function setPlacard(m) {
  const eyebrow = $("ev-meta"), en = $("ev-text"), sign = $("ev-sign");
  if (!m) { eyebrow.textContent = "On view today"; en.textContent = "Today's work hasn't been created yet."; sign.hidden = true; return; }
  eyebrow.textContent = [friendlyDate(m.date), m.weather_summary].filter(Boolean).join("  ·  ");
  en.textContent = m.event_text_en || "—";
  const sig = currentDevice && currentDevice.signature;
  if (sig) { sign.textContent = `— ${sig}`; sign.hidden = false; } else sign.hidden = true;
  renderOtherEvents(m.other_events);
  setAlsoOpen(false);          // each item starts with its runner-ups collapsed
  updateReadMore();
}

// "Also on this day": the date-verified runner-up events the curator didn't pick.
// Captions come from the model → render as text (never innerHTML).
function renderOtherEvents(events) {
  const sec = $("other-events"), ul = $("also-list");
  const items = (Array.isArray(events) ? events : [])
    .filter((e) => e && (e.caption || "").trim());
  ul.innerHTML = "";
  if (!items.length) { sec.hidden = true; return; }
  for (const e of items) {
    const li = document.createElement("li");
    li.className = "also-item";
    li.textContent = e.caption.trim();
    ul.appendChild(li);
  }
  sec.hidden = false;
}

// The Frame screen is a fixed one viewport. The description is clamped to 4
// lines; if it's longer, a "Read more" toggle expands it (and lets the screen
// scroll while expanded so the full text is reachable).
// The frame screen scrolls when EITHER the description is expanded (Read more) or
// the "Also on this day" section is open; otherwise it's locked to one viewport
// with the image flexed large. `.expanded` = full text (clamp lift); `.scroll` =
// layout/scroll/touch (either open).
let readMoreOpen = false;
let alsoOpen = false;
function applyFrameScroll() {
  const open = readMoreOpen || alsoOpen;
  $("screen-frame").classList.toggle("scroll", open);
  $("app").classList.toggle("locked", !open);
  document.body.classList.toggle("home-locked", !open);
  if (!open) window.scrollTo(0, 0);
}
function setFrameExpanded(on) {
  readMoreOpen = on;
  $("screen-frame").classList.toggle("expanded", on);
  $("ev-more").textContent = on ? "Read less" : "Read more";
  applyFrameScroll();
}
function setAlsoOpen(on) {
  alsoOpen = on;
  $("also-list").hidden = !on;
  $("also-toggle").setAttribute("aria-expanded", on ? "true" : "false");
  applyFrameScroll();
}
function updateReadMore() {
  const ev = $("ev-text"), btn = $("ev-more");
  if (!btn) return;
  setFrameExpanded(false);                       // collapse + measure the clamped text
  btn.hidden = ev.scrollHeight <= ev.clientHeight + 2;
}

function renderDots(active, total) {
  const el = $("gallery-dots");
  if (total < 2) { el.innerHTML = ""; return; }
  el.innerHTML = Array.from({ length: total }, (_, i) =>
    `<span class="dot-i${i === active ? " on" : ""}"></span>`).join("");
}

let galleryRAF = null;
function onGalleryScroll() {
  const g = $("gallery");
  cancelAnimationFrame(galleryRAF);
  galleryRAF = requestAnimationFrame(() => {
    const i = Math.round(g.scrollLeft / g.clientWidth);
    if (frameItems[i]) { setPlacard(frameItems[i]); renderDots(i, frameItems.length); }
  });
}

// The Generate button mirrors the backend's REAL pipeline phase, polled from
// /generation (the job's `detail` carries the phase). Image generation dominates,
// so "Painting…" naturally holds the longest; the early stages are genuinely
// quick. Falls back to "Working…" if an older backend reports no phase.
const GEN_LABELS = {
  discover: "Discovering…",   // weather + holidays
  research: "Researching…",   // the day's historical moment
  compose: "Composing…",      // building the prompt
  paint: "Painting…",         // image generation (the long phase)
  finish: "Finishing…",       // dither + upload
};
function genLabel(text) {
  $("regen-btn").innerHTML = `<span class="spin-sm" aria-hidden="true"></span><span class="gen-step">${text}</span>`;
}
function setBusy(on) {
  const b = $("regen-btn");
  b.disabled = on;
  b.classList.toggle("busy", on);
  $("gallery").classList.toggle("busy", on);
  if (on) genLabel("Starting…");
  else b.textContent = "Generate";
}
async function pollGeneration(id) {
  let last = "";
  for (let i = 0; i < 130; i++) {
    await sleep(1000);   // poll briskly so quick early phases are caught
    let s; try { s = await api(`/devices/${id}/generation`); } catch { continue; }
    if (s.state === "done") {
      genLabel(GEN_LABELS.finish);
      if (id === currentId) await loadGallery(id);
      toast("New artwork ready"); return;
    }
    if (s.state === "error") { toast(s.detail || "Couldn't create the artwork"); return; }
    const label = GEN_LABELS[s.detail] || "Working…";   // s.detail = the live phase
    if (label !== last) { genLabel(label); last = label; }
  }
  toast("Still working — check back shortly");
}

// Refresh re-pulls the app view AND tells the physical frame to re-fetch+redraw.
// Sleep tells the frame to go to sleep. Both reach the frame on its next poll
// (≤60s). Sleep is disabled when the frame is already asleep/offline.
function updateRefreshState() {
  const st = currentDevice ? frameState(currentDevice) : null;
  const asleep = st && st.cls === "s-sleep";
  const offline = st && st.cls === "s-off";
  // Refresh + sleep both need the frame awake (a sleeping frame won't pick up
  // the command until it wakes), so disable them when asleep/offline.
  $("refresh-btn").disabled = !!(asleep || offline);
  $("refresh-btn").title = (asleep || offline) ? "Frame must be awake to refresh" : "Refresh the frame";
  $("sleep-btn").disabled = !!(asleep || offline);
  $("sleep-btn").title = asleep ? "Frame is already asleep" : "Sleep the frame";
  const hint = $("refresh-hint");
  if (asleep) {
    hint.textContent = "💤 Frame is asleep — press KEY1 on it to wake it";
    hint.hidden = false;
  } else if (offline) {
    hint.textContent = "⚠ Frame is offline — check it's powered and on Wi‑Fi";
    hint.hidden = false;
  } else { hint.hidden = true; }
}

async function sendCommand(cmd, msg) {
  try { await api(`/devices/${currentId}/command`, { method: "POST", body: { cmd } }); toast(msg); }
  catch (e) { toast(e.message); }
}

function wireFrame() {
  $("frame-back").addEventListener("click", () => showHome(currentId));
  $("goto-artwork").addEventListener("click", openArtwork);
  $("goto-settings").addEventListener("click", openSettings);
  // Home cards are built dynamically; per-card Open buttons are wired in
  // buildHomeCards. Here we only wire the carousel scroll → active dot/frame.
  $("home-carousel").addEventListener("scroll", onHomeScroll, { passive: true });
  $("ev-more").addEventListener("click", () => setFrameExpanded(!$("screen-frame").classList.contains("expanded")));
  $("also-toggle").addEventListener("click", () => setAlsoOpen($("also-list").hidden));
  attachPullToRefresh("home", homeRefresh);
  attachPullToRefresh("frame", frameRefresh);
  $("gallery").addEventListener("scroll", onGalleryScroll, { passive: true });
  $("refresh-btn").addEventListener("click", async () => {
    const btn = $("refresh-btn"); btn.classList.add("busy");
    await loadGallery(currentId);                       // refresh the app view now
    await sendCommand("refresh", "Refreshing the frame…");  // and the physical frame (≤1 min)
    btn.classList.remove("busy");
  });
  $("sleep-btn").addEventListener("click", async () => {
    await sendCommand("sleep", "Putting the frame to sleep…");
  });
  $("regen-btn").addEventListener("click", async () => {
    const id = currentId; setBusy(true);
    try { await api(`/devices/${id}/regenerate`, { method: "POST" }); await pollGeneration(id); }
    catch (e) { toast(e.message); }
    setBusy(false);
  });
}

// --------------------------------------------------------------------------
// Artwork settings
// --------------------------------------------------------------------------
function renderInterestChips() {
  const box = $("interest-chips"); box.innerHTML = "";
  for (const [value, label] of INTEREST_CHIPS) {
    const l = document.createElement("label"); l.className = "chip";
    l.innerHTML = `<input type="checkbox" class="interest" value="${value}" /><span>${label}</span>`;
    box.appendChild(l);
  }
}

// ── Date format ────────────────────────────────────────────────────────────
// Token vocabulary + formatter MUST match artframe/constants.py format_date so the
// preview here equals what's drawn on the frame. Presets are previewed live on
// today's date; "Custom…" reveals a free-text field + a token reference.
const DATE_PRESETS = [
  "ddd MMM D",        // Tue Jun 30
  "dddd, MMMM Do",    // Tuesday, June 30th
  "dddd MMMM Do",     // Tuesday June 30th
  "MMMM Do",          // June 30th
  "MMM D",            // Jun 30
  "Do MMMM YYYY",     // 30th June 2026
  "DD/MM/YYYY",       // 30/06/2026
  "MM/DD/YYYY",       // 06/30/2026
];
const DATE_TOKENS = [
  ["dddd", "Weekday"], ["ddd", "Weekday, short"],
  ["MMMM", "Month"], ["MMM", "Month, short"], ["MM", "Month, 2-digit"],
  ["Do", "Day + ordinal"], ["D", "Day"], ["DD", "Day, 2-digit"],
  ["YYYY", "Year"], ["YY", "Year, 2-digit"],
];
const DATE_TOKEN_RE = /dddd|ddd|MMMM|MMM|MM|YYYY|YY|DD|Do|D/g;
const DATE_LEGACY = { weekday: "ddd, MMM DD", month_day: "MMMM DD", abbr_year: "MMM DD, YYYY", dmy: "DD/MM/YYYY", mdy: "MM/DD/YYYY" };
function dateOrdinal(n) {
  const s = (n % 100 >= 10 && n % 100 <= 20) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
  return `${n}${s}`;
}
function formatDate(d, fmt) {
  fmt = DATE_LEGACY[fmt] || fmt || DATE_LEGACY.weekday;
  const en = (opt) => d.toLocaleDateString("en-US", opt);   // English to match server strftime
  const map = {
    dddd: en({ weekday: "long" }), ddd: en({ weekday: "short" }),
    MMMM: en({ month: "long" }), MMM: en({ month: "short" }), MM: String(d.getMonth() + 1).padStart(2, "0"),
    Do: dateOrdinal(d.getDate()), D: String(d.getDate()), DD: String(d.getDate()).padStart(2, "0"),
    YYYY: String(d.getFullYear()), YY: String(d.getFullYear() % 100).padStart(2, "0"),
  };
  return fmt.replace(DATE_TOKEN_RE, (t) => map[t]);
}
function buildDateOptions() {
  const sel = $("date-format"); if (!sel) return;
  const today = new Date();
  sel.innerHTML = "";
  for (const fmt of DATE_PRESETS) {
    const o = document.createElement("option");
    o.value = fmt; o.textContent = formatDate(today, fmt);
    sel.appendChild(o);
  }
  const c = document.createElement("option");
  c.value = "custom"; c.textContent = "Custom…";
  sel.appendChild(c);
  const dl = $("date-token-list");
  if (dl && !dl.childElementCount) {
    for (const [tok, desc] of DATE_TOKENS) {
      const dt = document.createElement("dt"); dt.textContent = tok;
      const dd = document.createElement("dd"); dd.textContent = `${desc} → ${formatDate(today, tok)}`;
      dl.append(dt, dd);
    }
  }
}
const currentDateFormat = () =>
  $("date-format").value === "custom" ? ($("date-custom").value.trim() || "ddd MMM D") : $("date-format").value;
function setDateFormat(fmt) {
  buildDateOptions();
  if (DATE_PRESETS.includes(fmt)) {
    $("date-format").value = fmt;
  } else {                                  // legacy enum key or a custom string
    $("date-format").value = "custom";
    $("date-custom").value = DATE_LEGACY[fmt] || fmt || "";
  }
}
function updateDatePreview() {
  $("date-preview").textContent = formatDate(new Date(), currentDateFormat());
}
function refreshDateUI() {
  const showDate = $("show_date").checked;
  const custom = $("date-format").value === "custom";
  $("date-format-row").hidden = !showDate;
  $("date-custom-wrap").hidden = !(showDate && custom);   // preview lives inside, custom-only
  if (!(showDate && custom)) closeDateHelp();
}
const openDateHelp = () => { $("date-help-modal").hidden = false; };
const closeDateHelp = () => { $("date-help-modal").hidden = true; };

function openArtwork() {
  if (!currentDevice) return;
  const d = currentDevice;
  $("city-name").value = d.city_name || "";
  $("city-display").textContent = d.city_name || "";
  $("lat").value = d.lat; $("lon").value = d.lon;
  $("manual-coords").checked = false; $("coords-row").hidden = true;
  hideSuggest();
  setLocEdit(!d.city_name);  // unset → start in edit mode; otherwise show static text
  $("use_weather").checked = d.use_weather !== false;
  $("loc-weather-body").hidden = d.use_weather === false;
  $("use_event").checked = d.use_event !== false;
  $("interests-body").hidden = d.use_event === false;
  $("show_date").checked = d.show_date !== false;
  setDateFormat(d.date_format || "weekday");
  updateDatePreview();
  refreshDateUI();
  setRadio("unit", d.temp_unit || "c");
  setRadio("orient", d.orientation || "landscape");
  $("language").value = d.language || "en";
  $("signature").value = d.signature || "";
  $("h-jewish").checked = d.holiday_jewish; $("h-israeli").checked = d.holiday_israeli; $("h-global").checked = d.holiday_global;
  // interests: default Israel on for a brand-new (empty) frame
  const tokens = (d.interests || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  const chosen = tokens.length ? tokens : ["israel"];
  document.querySelectorAll(".interest").forEach((cb) => { cb.checked = chosen.includes(cb.value); });
  $("interest-other").value = tokens.filter((t) => !INTEREST_KEYS.includes(t)).join(", ");
  resolvedTz = null;
  go("artwork");
}

function setRadio(name, value) {
  document.querySelectorAll(`input[name="${name}"]`).forEach((r) => { r.checked = r.value === value; });
}
const getRadio = (name) => (document.querySelector(`input[name="${name}"]:checked`) || {}).value;

function artworkBody() {
  const chips = [...document.querySelectorAll(".interest:checked")].map((cb) => cb.value);
  const other = $("interest-other").value.split(",").map((s) => s.trim()).filter(Boolean);
  const body = {
    city_name: $("city-name").value.trim(),
    lat: parseFloat($("lat").value), lon: parseFloat($("lon").value),
    temp_unit: getRadio("unit"), orientation: getRadio("orient"),
    show_date: $("show_date").checked,
    use_weather: $("use_weather").checked, use_event: $("use_event").checked,
    date_format: currentDateFormat(),
    interests: [...chips, ...other].join(", "),
    signature: $("signature").value.trim() || "Ink.", language: $("language").value,
    holiday_jewish: $("h-jewish").checked, holiday_israeli: $("h-israeli").checked, holiday_global: $("h-global").checked,
  };
  // If timezone is automatic and we just resolved one from a city, carry it along.
  if (currentDevice && currentDevice.auto_timezone && resolvedTz) body.tz = resolvedTz;
  return body;
}

function wireArtwork() {
  renderInterestChips();
  $("artwork-back").addEventListener("click", () => go("frame"));
  $("manual-coords").addEventListener("change", (e) => { $("coords-row").hidden = !e.target.checked; });
  $("show_date").addEventListener("change", refreshDateUI);
  $("date-format").addEventListener("change", () => {
    refreshDateUI(); updateDatePreview();
    if ($("date-format").value === "custom") $("date-custom").focus();
  });
  $("date-custom").addEventListener("input", updateDatePreview);
  // Mount the modal at body level so it overlays the viewport rather than being
  // trapped inside the (display:none) artwork screen subtree.
  document.body.appendChild($("date-help-modal"));
  // "?" opens the format-codes modal; close via X, backdrop click, or Esc.
  $("date-help-btn").addEventListener("click", (e) => { e.preventDefault(); openDateHelp(); });
  $("date-help-close").addEventListener("click", closeDateHelp);
  $("date-help-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeDateHelp(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDateHelp(); });
  $("use_weather").addEventListener("change", (e) => { $("loc-weather-body").hidden = !e.target.checked; });
  $("use_event").addEventListener("change", (e) => { $("interests-body").hidden = !e.target.checked; });
  $("city-edit").addEventListener("click", () => { setLocEdit(true); $("city-name").focus(); $("city-name").select(); });
  $("city-find").addEventListener("click", geocode);
  $("city-accept").addEventListener("click", acceptLocation);
  $("geo-btn").addEventListener("click", useMyLocation);
  const cityInput = $("city-name");
  cityInput.addEventListener("input", onCityInput);
  cityInput.addEventListener("keydown", onSuggestKey);
  cityInput.addEventListener("blur", () => setTimeout(hideSuggest, 150));
  $("artwork-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.submitter || $("artwork-form").querySelector('button[type="submit"]');
    try { currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body: artworkBody() }); buttonSaved(btn); }
    catch (e2) { toast(e2.message); }
  });
}

async function geocode() {
  const q = $("city-name").value.trim(); if (!q) return;
  toast("Searching…");
  try {
    const data = await fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + encodeURIComponent(q)).then((r) => r.json());
    const hit = (data.results || [])[0];
    if (!hit) { toast("Location not found"); return; }
    applyLocation(hit.latitude, hit.longitude, hit.timezone, [hit.name, hit.country].filter(Boolean).join(", "));
  } catch { toast("Couldn't search right now"); }
}

function useMyLocation() {
  if (!navigator.geolocation) { toast("Location isn't available on this device"); return; }
  toast("Locating…");
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { latitude, longitude } = pos.coords; let label = "your location", tz;
    try {
      const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?count=1&latitude=${latitude}&longitude=${longitude}`).then((x) => x.json());
      const hit = (r.results || [])[0];
      if (hit) { label = [hit.name, hit.country].filter(Boolean).join(", "); tz = hit.timezone; }
    } catch {}
    if (!tz) tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    applyLocation(latitude, longitude, tz, label);
  }, () => toast("Couldn't get your location — allow access or search instead"), { timeout: 10000 });
}

function applyLocation(lat, lon, tz, label) {
  $("lat").value = (+lat).toFixed(4); $("lon").value = (+lon).toFixed(4);
  $("city-name").value = label;
  $("city-display").textContent = label;
  if (tz) resolvedTz = tz;
  hideSuggest();
  toast(`${label} — tap ✓ to confirm`);
}

// ✓ accept: commit the current location and collapse back to the static text.
async function acceptLocation() {
  hideSuggest();
  const typed = $("city-name").value.trim();
  const display = $("city-display").textContent.trim();
  // A typed name that wasn't resolved yet (and we're not in manual mode) → look it up.
  if (!$("manual-coords").checked && typed && typed !== display) await geocode();
  const hasCoords = isFinite(parseFloat($("lat").value)) && isFinite(parseFloat($("lon").value));
  if ($("city-display").textContent.trim()) setLocEdit(false);
  else if (hasCoords) { $("city-display").textContent = typed || "Custom location"; setLocEdit(false); }
  else toast("Pick a location first");
}

// Toggle between the static "City, Country + pencil" view and the edit controls.
function setLocEdit(on) {
  $("loc-view").hidden = on;
  $("loc-edit").hidden = !on;
  if (!on) hideSuggest();
}

// ── City autocomplete ──────────────────────────────────────────────────
const SUGGEST_MIN_CHARS = 2;
const SUGGEST_DEBOUNCE_MS = 280;
const SUGGEST_LIMIT = 6;
let suggestTimer = null;
let suggestResults = [];

function onCityInput() {
  clearTimeout(suggestTimer);
  const q = $("city-name").value.trim();
  if (q.length < SUGGEST_MIN_CHARS) { hideSuggest(); return; }
  suggestTimer = setTimeout(() => fetchSuggest(q), SUGGEST_DEBOUNCE_MS);
}

async function fetchSuggest(q) {
  try {
    const data = await fetch(
      `https://geocoding-api.open-meteo.com/v1/search?count=${SUGGEST_LIMIT}&name=` + encodeURIComponent(q)
    ).then((r) => r.json());
    renderSuggest(data.results || []);
  } catch { hideSuggest(); }
}

const suggestLabel = (h) => [h.name, h.admin1, h.country].filter(Boolean).join(", ");

function renderSuggest(results) {
  suggestResults = results;
  const ul = $("city-suggest");
  ul.innerHTML = "";
  if (!results.length) { hideSuggest(); return; }
  results.forEach((hit, i) => {
    const li = document.createElement("li");
    li.textContent = suggestLabel(hit);
    li.dataset.index = String(i);
    // mousedown (not click) so it fires before the input's blur handler hides the list
    li.addEventListener("mousedown", (e) => { e.preventDefault(); chooseSuggest(i); });
    ul.appendChild(li);
  });
  ul.hidden = false;
}

function chooseSuggest(i) {
  const h = suggestResults[i];
  if (!h) return;
  applyLocation(h.latitude, h.longitude, h.timezone, [h.name, h.country].filter(Boolean).join(", "));
}

function hideSuggest() {
  suggestResults = [];
  const ul = $("city-suggest");
  if (ul) { ul.hidden = true; ul.innerHTML = ""; }
}

// Keyboard nav: ↑/↓ move the highlight, Enter picks it.
function onSuggestKey(e) {
  const ul = $("city-suggest");
  const open = !ul.hidden && suggestResults.length;
  if (e.key === "Enter") {
    // Never let Enter submit the whole settings form from the city field.
    e.preventDefault();
    const active = open ? [...ul.children].findIndex((li) => li.classList.contains("active")) : -1;
    if (active >= 0) chooseSuggest(active); else acceptLocation();
    return;
  }
  if (!open) return;
  const items = [...ul.children];
  let active = items.findIndex((li) => li.classList.contains("active"));
  if (e.key === "ArrowDown") { e.preventDefault(); active = (active + 1) % items.length; }
  else if (e.key === "ArrowUp") { e.preventDefault(); active = (active - 1 + items.length) % items.length; }
  else if (e.key === "Escape") { hideSuggest(); return; }
  else return;
  items.forEach((li, i) => li.classList.toggle("active", i === active));
}

// --------------------------------------------------------------------------
// Frame settings
// --------------------------------------------------------------------------
function renderDayChips(selected) {
  const box = $("day-chips"); box.innerHTML = "";
  const set = new Set(selected);
  for (const [value, label] of DAYS) {
    const l = document.createElement("label"); l.className = "chip";
    l.innerHTML = `<input type="checkbox" class="day" value="${value}" ${set.has(value) ? "checked" : ""}/><span>${label}</span>`;
    box.appendChild(l);
  }
}

function openSettings() {
  if (!currentDevice) return;
  const d = currentDevice, st = frameState(d);
  $("set-dot").className = `dot ${st.cls}`; $("set-state").textContent = st.label; $("set-sub").textContent = st.sub;
  $("set-name").value = d.name || ""; $("set-name").placeholder = defaultName(d.id);
  setRadio("sched", d.schedule || "daily");
  renderDayChips((d.schedule_days || "").split(",").map((s) => s.trim()).filter(Boolean));
  $("day-chips").hidden = (d.schedule || "daily") === "daily";
  const pad2 = (n) => String(n).padStart(2, "0");
  $("wake").value = `${pad2(d.wake_hour || 0)}:${pad2(d.wake_minute || 0)}`;
  // Power: a single choice — stay always on, or sleep after N minutes of uptime.
  // (0 = always on.) The frame can't sense its own power, so there's no plugged/
  // battery distinction or battery %.
  const sleepMin = d.sleep_after_minutes || 0;           // 0 = always on
  setRadio("sleepmode", sleepMin > 0 ? "sleep" : "always_on");
  $("sleep-after").value = sleepMin > 0 ? sleepMin : 30;
  $("sleep-after-row").hidden = !(sleepMin > 0);
  $("auto-tz").checked = d.auto_timezone !== false;
  $("tz-row").hidden = d.auto_timezone !== false; $("tz").value = d.tz || "";
  $("spec-conn").textContent = d.last_seen ? relTime(d.last_seen) : "never";
  $("spec-wifi").innerHTML = wifiLabel(d.wifi_rssi);
  $("spec-fw").textContent = d.fw_version || "—"; $("spec-id").textContent = d.id;
  setSettingsDirty(false);   // freshly loaded → nothing to save yet
  go("settings");
}

// The Frame-settings screen has a single Save in the header, enabled only once
// the user changes something.
let settingsDirty = false;
function setSettingsDirty(on) {
  settingsDirty = on;
  const b = $("settings-save");
  if (b) b.disabled = !on;
}

function wireSettings() {
  $("settings-back").addEventListener("click", () => go("frame"));
  // Section-wide dirty tracking: any edit enables the header Save.
  const section = $("screen-settings");
  section.addEventListener("input", () => setSettingsDirty(true));
  section.addEventListener("change", () => setSettingsDirty(true));
  // Conditional rows follow their controls.
  document.querySelectorAll('input[name="sched"]').forEach((r) =>
    r.addEventListener("change", () => { $("day-chips").hidden = getRadio("sched") === "daily"; }));
  document.querySelectorAll('input[name="sleepmode"]').forEach((r) =>
    r.addEventListener("change", () => { $("sleep-after-row").hidden = getRadio("sleepmode") !== "sleep"; }));
  $("auto-tz").addEventListener("change", (e) => { $("tz-row").hidden = e.target.checked; });

  // One global save: send only what actually changed.
  $("settings-save").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const d = currentDevice || {};
    const body = {};
    const name = $("set-name").value.trim();
    if (name !== (d.name || "")) body.name = name;
    const sched = getRadio("sched");
    if (sched !== d.schedule) body.schedule = sched;
    const days = sched === "daily" ? "" : [...document.querySelectorAll(".day:checked")].map((c) => c.value).join(",");
    if (days !== (d.schedule_days || "")) body.schedule_days = days;
    const [wh, wm] = ($("wake").value || "").split(":").map((n) => parseInt(n, 10));
    const m = isNaN(wm) ? 0 : wm;
    if (!isNaN(wh) && (wh !== d.wake_hour || m !== d.wake_minute)) { body.wake_hour = wh; body.wake_minute = m; }
    // Sleep policy: "always on" stores 0; "sleep after" stores the minutes.
    const sleepMin = getRadio("sleepmode") === "sleep"
      ? Math.max(1, parseInt($("sleep-after").value, 10) || 30)
      : 0;
    if (sleepMin !== (d.sleep_after_minutes || 0)) body.sleep_after_minutes = sleepMin;
    const auto = $("auto-tz").checked;
    if (auto !== (d.auto_timezone !== false)) body.auto_timezone = auto;
    const tz = $("tz").value.trim();
    if (!auto && tz && tz !== d.tz) body.tz = tz;
    if (!Object.keys(body).length) { setSettingsDirty(false); return; }
    btn.disabled = true;
    try { currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body }); setSettingsDirty(false); toast("Saved"); }
    catch (err) { toast(err.message); setSettingsDirty(true); }
  });
  $("disconnect-btn").addEventListener("click", async () => {
    if (!confirm("Disconnect and forget this frame?\n\nIts settings are cleared and it returns to onboarding.")) return;
    const btn = $("disconnect-btn"); btn.disabled = true;
    try {
      // Only treat the frame as removed once the server confirms the unbind —
      // otherwise a failed call would falsely "disconnect" it in the app.
      await api(`/devices/${currentId}/unbind`, { method: "POST" });
      toast("Frame forgotten");
      await showHome();
    } catch (e) {
      // Unbind didn't go through: keep the frame connected, stay on this screen.
      toast("Couldn't disconnect — frame is still connected");
    } finally { btn.disabled = false; }
  });
  // Same behavior as the app-settings "Check for updates" button: animates,
  // stays on screen, toasts per source (frame firmware / app), else "Up to date".
  $("check-fw-btn").addEventListener("click", (e) => {
    const hint = $("fw-status-hint"); if (hint) hint.hidden = true;
    checkForUpdates(e.currentTarget);
  });
  $("factory-btn").addEventListener("click", async () => {
    if (frameState(currentDevice).cls !== "s-on") {
      toast("Wake the frame first — it must be online to factory restore");
      return;
    }
    if (!confirm("Factory restore this frame?\n\nIt wipes Wi‑Fi AND pairing on the device and returns it to onboarding from scratch. You'll set it up again like new.")) return;
    const btn = $("factory-btn"); btn.disabled = true;
    try {
      // 'reset' both queues the on-device wipe and unbinds server-side (one call).
      await api(`/devices/${currentId}/command`, { method: "POST", body: { cmd: "reset" } });
      toast("Factory restore sent — the frame will wipe and reboot");
      await showHome();
    } catch (e) {
      toast("Couldn't reach the server — frame not reset");
    } finally { btn.disabled = false; }
  });
}

// --------------------------------------------------------------------------
// App settings (account)
// --------------------------------------------------------------------------
async function showAccount() {
  go("account");
  $("token-display").value = token(); $("acct-server-url").value = serverBase();
  $("app-version").textContent = APP_VERSION; $("key-err").hidden = true;
  refreshInstallUI();
  try { const a = await api("/account"); setKeyMode(a.key_status); $("acct-id").textContent = a.account_id || "—"; }
  catch (e) { showError("key-err", e); }
}
function setKeyMode(status) {
  const own = status === "own" || status === "required";
  $("seg-platform").classList.toggle("active", !own);
  $("seg-own").classList.toggle("active", own);
  $("own-key-fields").hidden = !own;
  $("seg-platform").disabled = status === "required";
  $("key-required-note").hidden = status !== "required";
}
function wireAccount() {
  $("app-settings-btn").addEventListener("click", showAccount);
  $("acct-back").addEventListener("click", () => showHome(currentId));
  $("acct-server-save").addEventListener("click", () => {
    const v = $("acct-server-url").value.trim();
    if (v) { setServer(v); localStorage.setItem(SERVER_MANUAL_KEY, "1"); toast("Saved — pinned to this server"); }
    else { setServer(""); localStorage.removeItem(SERVER_MANUAL_KEY); toast("Cleared — following the published server"); }
  });
  $("seg-own").addEventListener("click", () => { setKeyMode("own"); $("api-key").focus(); });
  $("seg-platform").addEventListener("click", async () => {
    $("key-err").hidden = true;
    try { await api("/account/key", { method: "DELETE" }); setKeyMode("platform"); toast("Using Ink's key"); }
    catch (e) { showError("key-err", e); }
  });
  $("save-key-btn").addEventListener("click", async () => {
    const v = $("api-key").value.trim();
    if (!v) { showError("key-err", new Error("Enter your API key first.")); return; }
    try { await api("/account/key", { method: "PUT", body: { openai_api_key: v } }); $("api-key").value = ""; setKeyMode("own"); toast("Saved your key"); }
    catch (e) { showError("key-err", e); }
  });
  $("update-btn").addEventListener("click", (e) => checkForUpdates(e.currentTarget));
  $("app-toast-refresh").addEventListener("click", () => location.reload());
  $("app-toast-close").addEventListener("click", () => { $("app-toast").hidden = true; });
  $("logout-btn").addEventListener("click", () => {
    if (!confirm("Log out of this account on this device?\n\nKeep your account token saved if you want to return.")) return;
    localStorage.removeItem(TOKEN_KEY); go("welcome");
  });
}

// --------------------------------------------------------------------------
// PWA install
// --------------------------------------------------------------------------
let deferredPrompt = null;
const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
function refreshInstallUI() {
  const card = $("install-card"); if (!card) return;
  if (isStandalone()) { card.hidden = true; return; }
  card.hidden = false;
  $("install-hint").textContent = deferredPrompt
    ? "Add Ink to your home screen for a full‑screen, app‑like experience."
    : isIOS() ? "In Safari, tap the Share icon, then “Add to Home Screen.”"
              : "Open your browser's menu and choose “Install” or “Add to Home screen.”";
  $("install-btn").hidden = !deferredPrompt && !isIOS();
}
function maybeShowInstallBanner() {
  if (isStandalone() || localStorage.getItem(INSTALL_DISMISS_KEY)) return;
  if (!deferredPrompt && !isIOS()) return;
  if ($("home-empty") && !$("home-empty").hidden) return;  // not during first-run
  const b = $("install-banner");
  $("ib-sub").textContent = deferredPrompt ? "Add it to your home screen for a full‑screen experience." : "In Safari, tap Share → “Add to Home Screen.”";
  $("ib-install").style.display = deferredPrompt ? "" : "none";
  b.hidden = false; requestAnimationFrame(() => b.classList.add("show"));
}
function hideInstallBanner(persist) {
  const b = $("install-banner"); b.classList.remove("show"); setTimeout(() => { b.hidden = true; }, 350);
  if (persist || $("ib-dontshow").checked) localStorage.setItem(INSTALL_DISMISS_KEY, "1");
}
async function doInstall() {
  if (deferredPrompt) { deferredPrompt.prompt(); const { outcome } = await deferredPrompt.userChoice; deferredPrompt = null; if (outcome === "accepted") hideInstallBanner(true); refreshInstallUI(); }
  else if (isIOS()) toast("Tap Share, then “Add to Home Screen”"); else toast("Use your browser menu → Install");
}
function wireInstall() {
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredPrompt = e; refreshInstallUI(); maybeShowInstallBanner(); });
  window.addEventListener("appinstalled", () => { deferredPrompt = null; hideInstallBanner(true); refreshInstallUI(); toast("Ink installed"); });
  $("install-btn").addEventListener("click", doInstall);
  $("ib-install").addEventListener("click", doInstall);
  $("ib-dismiss").addEventListener("click", () => hideInstallBanner(false));
}

// --------------------------------------------------------------------------
// In-app QR scanner (camera) to pair
// --------------------------------------------------------------------------
let scanStream = null, scanRAF = null, scanDetector = null;

function wireScanner() {
  $("scan-btn").addEventListener("click", startScan);
  $("scan-cancel").addEventListener("click", stopScan);
}

function wireUpdateToast() {
  $("fw-toast-update").addEventListener("click", () => { if (otaTargetId) startFrameOta(otaTargetId); });
  // Close hides it for this session only — a relaunch re-checks and re-shows it.
  $("fw-toast-close").addEventListener("click", () => { updateDismissed = true; hideUpdateToast(); });
}

async function startScan() {
  $("pair-error").hidden = true;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("manual-pair").open = true; toast("Camera not available — enter the code"); return;
  }
  try { scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }); }
  catch { $("manual-pair").open = true; toast("Camera blocked — enter the code instead"); return; }

  const v = $("scan-video"); v.srcObject = scanStream; await v.play().catch(() => {});
  $("scanner").hidden = false; $("scan-btn").hidden = true;
  scanDetector = null;
  if ("BarcodeDetector" in window) { try { scanDetector = new BarcodeDetector({ formats: ["qr_code"] }); } catch {} }

  const canvas = document.createElement("canvas"); const ctx = canvas.getContext("2d");
  const tick = async () => {
    if (!scanStream) return;
    let text = null;
    if (v.readyState >= 2) {
      if (scanDetector) { try { const c = await scanDetector.detect(v); if (c.length) text = c[0].rawValue; } catch {} }
      else if (window.jsQR) {
        canvas.width = v.videoWidth; canvas.height = v.videoHeight;
        ctx.drawImage(v, 0, 0, canvas.width, canvas.height);
        const d = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const r = window.jsQR(d.data, d.width, d.height); if (r) text = r.data;
      }
    }
    if (text) {
      let code = null, server = null;
      try { const u = new URL(text); code = u.searchParams.get("code"); server = u.searchParams.get("server"); } catch {}
      if (!code) { const m = String(text).match(/\b(\d{6})\b/); if (m) code = m[1]; }
      if (code) { stopScan(); if (server) setServer(server); toast("QR found — pairing…"); syncByCode(code); return; }
    }
    scanRAF = requestAnimationFrame(tick);
  };
  tick();
}

function stopScan() {
  if (scanRAF) { cancelAnimationFrame(scanRAF); scanRAF = null; }
  if (scanStream) { scanStream.getTracks().forEach((t) => t.stop()); scanStream = null; }
  if ($("scanner")) { $("scanner").hidden = true; $("scan-btn").hidden = false; }
}

// --------------------------------------------------------------------------
// QR deep-link pairing
// --------------------------------------------------------------------------
async function syncByCode(code) {
  try {
    const dev = await api("/devices/pair", { method: "POST", body: { pairing_code: code } });
    await openFrame(dev.id);
    toast("Paired! Tap Generate to make your first artwork");
  } catch (e) { await showHome(); go("connect"); $("pair-code").value = code; showError("pair-error", e); }
}

// Auto-follow the published backend URL so the app survives a server move.
// Skipped if the user has pinned a server in Advanced.
// On focus/visibility: refresh home art, then re-pull devices to resolve an
// in-flight OTA and re-evaluate the update toast (dismiss if no longer needed).
async function onAppFocus() {
  refreshHomeArt();
  try {
    const r = await api("/devices");
    devices = r.devices || r;
    if (otaWatch) {
      const d = devices.find((x) => x.id === otaWatch.deviceId);
      if (d && resolveOtaFrom(d)) return;   // finishOta already refreshes the toast
    }
    checkFirmwareUpdates();
  } catch { /* offline — leave current state */ }
}

async function resolveServer() {
  if (localStorage.getItem(SERVER_MANUAL_KEY)) return;
  try {
    const r = await fetch(SERVER_DISCOVERY_URL, { cache: "no-store" });
    if (!r.ok) return;
    const url = (await r.text()).trim().replace(/\/+$/, "");
    if (/^https?:\/\//i.test(url)) setServer(url);
  } catch { /* keep whatever server we already have */ }
}

async function init() {
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  wireWelcome(); wireConnect(); wireFrame(); wireArtwork(); wireSettings(); wireAccount(); wireInstall(); wireScanner(); wireLightbox(); wireUpdateToast();
  // When the app/tab regains focus, refresh the home art AND re-check firmware:
  // this resolves an OTA that finished while the app was backgrounded (timers
  // pause in the background) — showing "✓ updated" and dismissing the toast.
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") onAppFocus(); });
  window.addEventListener("focus", onAppFocus);
  const params = new URLSearchParams(location.search);
  const server = params.get("server"); if (server) setServer(server);
  await resolveServer();   // published server.txt wins unless the user pinned one
  const code = params.get("code"); const valid = code && /^\d{6}$/.test(code);
  if (token()) { if (valid) syncByCode(code); else showHome(); }
  else if (valid) {
    go("welcome");
    api("/account", { method: "POST", auth: false })
      .then(({ token: t }) => { localStorage.setItem(TOKEN_KEY, t); syncByCode(code); })
      .catch((e) => { showError("welcome-error", e); $("server-details").open = true; });
  } else go("welcome");
  if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
init();
