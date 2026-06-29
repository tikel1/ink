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
  // Home is a single, fixed viewport (no scroll); every other screen scrolls
  // normally. Lock #app to the viewport only on home so its padding can't push
  // the page past 100dvh.
  $("app").classList.toggle("locked", name === "home");
  // Also lock the <body> on home so the page itself can't scroll/rubber-band a
  // few pixels (overflow:hidden on #app alone doesn't stop body-level scroll).
  document.body.classList.toggle("home-locked", name === "home");
  window.scrollTo(0, 0);
  currentScreen = name;
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
function batteryPct(v) { return v == null ? null : Math.round(Math.max(0, Math.min(1, (v - 3.3) / 0.9)) * 100); }
function frameState(d) {
  const seen = d.last_seen ? Date.now() - new Date(d.last_seen).getTime() : null;
  if (seen == null) return { label: "Setting up", cls: "s-setup", sub: "waiting for first check‑in" };
  if (seen < 5 * MIN) return { label: "Awake", cls: "s-on", sub: `checked in ${relTime(d.last_seen)}` };
  if (seen < 26 * HOUR) return { label: "Asleep", cls: "s-sleep", sub: `last seen ${relTime(d.last_seen)}` };
  return { label: "Offline", cls: "s-off", sub: `last seen ${relTime(d.last_seen)}` };
}
function wifiLabel(r) {
  if (r == null) return "—";
  const q = r >= -60 ? "Strong" : r >= -70 ? "Good" : r >= -80 ? "Weak" : "Poor";
  return `${q} (${r} dBm)`;
}
const shortId = (id) => (id || "").slice(-4).toUpperCase();
const defaultName = (id) => `Ink Frame · ${shortId(id)}`;
const displayName = (d) => (d && d.name) ? d.name : defaultName(d && d.id);

function flash(id, text, isErr) { const el = $(id); if (!el) return; el.textContent = text; el.hidden = false; el.className = isErr ? "error" : "ok"; }
function showError(id, e) { flash(id, e.message, true); }
let toastTimer = null;
function toast(text) {
  const el = $("toast"); el.textContent = text; el.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
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
  $("server-save").addEventListener("click", () => { setServer($("server-url").value); localStorage.setItem(SERVER_MANUAL_KEY, "1"); flash("server-msg", "Saved. Now tap Get started."); });
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
  catch (e) { if (e.status === 401) { localStorage.removeItem(TOKEN_KEY); return go("welcome"); } devices = []; }

  if (!devices.length) { $("home-empty").hidden = false; $("home-frame").hidden = true; maybeShowInstallBanner(); return; }
  $("home-empty").hidden = true; $("home-frame").hidden = false;

  const dev = devices.find((d) => d.id === preferId) || devices[0];
  renderHomeFrame(dev);
  renderFrameSwitch(dev.id);
  maybeShowInstallBanner();
}

function renderHomeFrame(d) {
  currentId = d.id; currentDevice = d;
  $("home-frame").classList.toggle("is-portrait", d.orientation === "portrait");
  $("home-frame-name").textContent = displayName(d);
  // Sleep indicator: moon badge + wake hint when the frame is asleep.
  const asleep = frameState(d).cls === "s-sleep";
  $("home-sleep").hidden = !asleep;
  $("home-sleep-hint").hidden = !asleep;
  $("home-explain").textContent = "Loading today's work…";
  loadArtwork($("home-art-img"), $("home-skeleton"), d.id, () => {
    $("home-explain").textContent = "No artwork yet — open the frame and tap Regenerate.";
  });
  loadExplain(d.id);
}

async function loadExplain(id) {
  try {
    const { items } = await api(`/devices/${id}/archive?limit=1`);
    const m = items && items[0];
    $("home-explain").textContent = (m && m.event_text_en) ? m.event_text_en : "Today's work hasn't been created yet.";
  } catch { $("home-explain").textContent = "—"; }
}

function renderFrameSwitch(activeId) {
  const el = $("frame-switch");
  if (devices.length < 2) { el.hidden = true; el.innerHTML = ""; return; }
  el.hidden = false; el.innerHTML = "";
  for (const d of devices) {
    const b = document.createElement("button");
    b.textContent = displayName(d);
    if (d.id === activeId) b.className = "active";
    b.addEventListener("click", () => { renderHomeFrame(d); renderFrameSwitch(d.id); });
    el.appendChild(b);
  }
}

// --------------------------------------------------------------------------
// Connect
// --------------------------------------------------------------------------
function wireConnect() {
  $("empty-connect-btn").addEventListener("click", () => go("connect"));
  $("connect-back").addEventListener("click", () => { stopScan(); showHome(); });
  $("pair-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const dev = await api("/devices/pair", { method: "POST", body: { pairing_code: $("pair-code").value.trim() } });
      const nm = $("pair-name").value.trim();
      if (nm) { try { await api(`/devices/${dev.id}/config`, { method: "PUT", body: { name: nm } }); } catch {} }
      $("pair-code").value = ""; $("pair-name").value = ""; toast("Paired!");
      await openFrame(dev.id);
      flash("action-msg", "Paired! Go ahead and tap Regenerate to create your first artwork.");
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
    const st = frameState(currentDevice);
    $("fr-dot").className = `dot ${st.cls}`;
    $("fr-status").textContent = `${st.label} · ${st.sub}`;
  } catch (e) { showError("action-msg", e); }
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
    g.innerHTML = slideCard(isPortraitItem(null), `<div class="art-empty">No artwork yet —<br>tap Regenerate to create today's work.</div>`);
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

function setBusy(on) {
  $("regen-btn").disabled = on; $("regen-btn").textContent = on ? "Painting…" : "Regenerate";
  $("gallery").classList.toggle("busy", on);
}
async function pollGeneration(id) {
  flash("action-msg", "Painting today's work… (about 20–30 s)");
  for (let i = 0; i < 48; i++) {
    await sleep(2500);
    let s; try { s = await api(`/devices/${id}/generation`); } catch { continue; }
    if (s.state === "done") {
      if (id === currentId) await loadGallery(id);
      flash("action-msg", "Done — your frame shows it on its next refresh, or press KEY1."); return;
    }
    if (s.state === "error") { flash("action-msg", s.detail || "Generation failed.", true); return; }
  }
  flash("action-msg", "Still working… check back in a moment.");
}

function wireFrame() {
  $("frame-back").addEventListener("click", () => showHome(currentId));
  $("goto-artwork").addEventListener("click", openArtwork);
  $("goto-settings").addEventListener("click", openSettings);
  $("home-art-btn").addEventListener("click", () => openFrame(currentId));
  $("home-more").addEventListener("click", () => openFrame(currentId));
  $("gallery").addEventListener("scroll", onGalleryScroll, { passive: true });
  $("refresh-btn").addEventListener("click", async () => {
    $("refresh-btn").disabled = true;
    await loadGallery(currentId);
    $("refresh-btn").disabled = false; toast("Refreshed");
  });
  $("regen-btn").addEventListener("click", async () => {
    const id = currentId; setBusy(true);
    try { await api(`/devices/${id}/regenerate`, { method: "POST" }); await pollGeneration(id); }
    catch (e) { flash("action-msg", e.message, true); }
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

function openArtwork() {
  if (!currentDevice) return;
  const d = currentDevice;
  $("city-name").value = d.city_name || "";
  $("city-edit").hidden = !d.city_name;
  $("lat").value = d.lat; $("lon").value = d.lon;
  $("manual-coords").checked = false; $("coords-row").hidden = true;
  $("show_weather").checked = d.show_weather !== false;
  $("show_date").checked = d.show_date !== false;
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
  $("loc-msg").hidden = true; $("save-msg").hidden = true;
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
    show_weather: $("show_weather").checked, show_date: $("show_date").checked,
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
  $("city-edit").addEventListener("click", () => { $("city-name").focus(); $("city-name").select(); });
  $("city-find").addEventListener("click", geocode);
  $("geo-btn").addEventListener("click", useMyLocation);
  $("artwork-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body: artworkBody() }); flash("save-msg", "Saved."); toast("Saved"); }
    catch (e2) { showError("save-msg", e2); }
  });
}

async function geocode() {
  const q = $("city-name").value.trim(); if (!q) return;
  flash("loc-msg", "Searching…");
  try {
    const data = await fetch("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + encodeURIComponent(q)).then((r) => r.json());
    const hit = (data.results || [])[0];
    if (!hit) { flash("loc-msg", "Location not found.", true); return; }
    applyLocation(hit.latitude, hit.longitude, hit.timezone, [hit.name, hit.country].filter(Boolean).join(", "));
  } catch { flash("loc-msg", "Couldn't search right now.", true); }
}

function useMyLocation() {
  if (!navigator.geolocation) { flash("loc-msg", "Location isn't available on this device.", true); return; }
  flash("loc-msg", "Locating…");
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { latitude, longitude } = pos.coords; let label = "your location", tz;
    try {
      const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?count=1&latitude=${latitude}&longitude=${longitude}`).then((x) => x.json());
      const hit = (r.results || [])[0];
      if (hit) { label = [hit.name, hit.country].filter(Boolean).join(", "); tz = hit.timezone; }
    } catch {}
    if (!tz) tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    applyLocation(latitude, longitude, tz, label);
  }, () => flash("loc-msg", "Couldn't get your location — allow access or search instead.", true), { timeout: 10000 });
}

function applyLocation(lat, lon, tz, label) {
  $("lat").value = (+lat).toFixed(4); $("lon").value = (+lon).toFixed(4);
  $("city-name").value = label; $("city-edit").hidden = false;
  if (tz) resolvedTz = tz;
  flash("loc-msg", `Set to ${label}.`);
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
  $("wake").value = d.wake_hour;
  setRadio("power", d.power_source || "usb");
  $("sleep-after").value = d.sleep_after_minutes || 10;
  $("sleep-row").hidden = (d.power_source || "usb") !== "battery";
  $("auto-tz").checked = d.auto_timezone !== false;
  $("tz-row").hidden = d.auto_timezone !== false; $("tz").value = d.tz || "";
  $("spec-conn").textContent = d.last_seen ? relTime(d.last_seen) : "never";
  $("spec-wifi").textContent = wifiLabel(d.wifi_rssi);
  const bat = batteryPct(d.battery); $("spec-batt").textContent = bat != null ? `${bat}%` : "—";
  $("spec-fw").textContent = d.fw_version || "—"; $("spec-id").textContent = d.id;
  ["name-msg", "sched-msg", "tz-msg", "power-msg"].forEach((i) => { $(i).hidden = true; });
  go("settings");
}

function wireSettings() {
  $("settings-back").addEventListener("click", () => go("frame"));
  $("set-name-save").addEventListener("click", async () => {
    try { currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body: { name: $("set-name").value.trim() } }); flash("name-msg", "Saved."); toast("Name updated"); }
    catch (e) { showError("name-msg", e); }
  });
  document.querySelectorAll('input[name="sched"]').forEach((r) =>
    r.addEventListener("change", () => { $("day-chips").hidden = getRadio("sched") === "daily"; }));
  $("sched-save").addEventListener("click", async () => {
    const sched = getRadio("sched");
    const days = sched === "daily" ? "" : [...document.querySelectorAll(".day:checked")].map((c) => c.value).join(",");
    const wake = parseInt($("wake").value, 10);
    try { currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body: { schedule: sched, schedule_days: days, wake_hour: isNaN(wake) ? undefined : wake } }); flash("sched-msg", "Saved."); toast("Schedule saved"); }
    catch (e) { showError("sched-msg", e); }
  });
  document.querySelectorAll('input[name="power"]').forEach((r) =>
    r.addEventListener("change", () => { $("sleep-row").hidden = getRadio("power") !== "battery"; }));
  $("power-save").addEventListener("click", async () => {
    const body = { power_source: getRadio("power") };
    const s = parseInt($("sleep-after").value, 10);
    if (!isNaN(s)) body.sleep_after_minutes = s;
    try { currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body }); flash("power-msg", "Saved."); toast("Power saved"); }
    catch (e) { showError("power-msg", e); }
  });
  $("auto-tz").addEventListener("change", (e) => { $("tz-row").hidden = e.target.checked; });
  $("tz-save").addEventListener("click", async () => {
    const auto = $("auto-tz").checked;
    const body = { auto_timezone: auto };
    if (!auto && $("tz").value.trim()) body.tz = $("tz").value.trim();
    try { currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body }); flash("tz-msg", "Saved."); toast("Time zone saved"); }
    catch (e) { showError("tz-msg", e); }
  });
  $("disconnect-btn").addEventListener("click", async () => {
    if (!confirm("Disconnect and forget this frame?\n\nIts settings are cleared and it returns to onboarding.")) return;
    try { await api(`/devices/${currentId}/unbind`, { method: "POST" }); toast("Frame forgotten"); await showHome(); }
    catch (e) { alert(e.message); }
  });
}

// --------------------------------------------------------------------------
// App settings (account)
// --------------------------------------------------------------------------
async function showAccount() {
  go("account");
  $("token-display").value = token(); $("acct-server-url").value = serverBase();
  $("app-version").textContent = APP_VERSION; $("key-msg").hidden = true; $("key-err").hidden = true;
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
    if (v) { setServer(v); localStorage.setItem(SERVER_MANUAL_KEY, "1"); flash("acct-server-msg", "Saved (pinned to this server)."); }
    else { setServer(""); localStorage.removeItem(SERVER_MANUAL_KEY); flash("acct-server-msg", "Cleared — following the published server again."); }
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
    try { await api("/account/key", { method: "PUT", body: { openai_api_key: v } }); $("api-key").value = ""; setKeyMode("own"); flash("key-msg", "Saved your key."); toast("Saved your key"); }
    catch (e) { showError("key-err", e); }
  });
  $("update-btn").addEventListener("click", async () => {
    flash("update-msg", "Checking…");
    try { if ("serviceWorker" in navigator) { const reg = await navigator.serviceWorker.getRegistration(); if (reg) await reg.update(); } flash("update-msg", "Up to date. Reloading…"); setTimeout(() => location.reload(), 700); }
    catch { flash("update-msg", "Couldn't check for updates.", true); }
  });
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
    toast("Paired!"); await openFrame(dev.id);
    flash("action-msg", "Paired! Go ahead and tap Regenerate to create your first artwork.");
  } catch (e) { await showHome(); go("connect"); $("pair-code").value = code; showError("pair-error", e); }
}

// Auto-follow the published backend URL so the app survives a server move.
// Skipped if the user has pinned a server in Advanced.
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
  wireWelcome(); wireConnect(); wireFrame(); wireArtwork(); wireSettings(); wireAccount(); wireInstall(); wireScanner(); wireLightbox();
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
