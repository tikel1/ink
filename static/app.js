"use strict";

// Ink — premium control app. Talks to the backend's /api/app endpoints.

const APP_VERSION = "1.1.0";
const TOKEN_KEY = "ink.token";
const SERVER_KEY = "ink.server";
const INTEREST_FIELDS = ["science", "history", "sports", "astronomy", "art"];
const $ = (id) => document.getElementById(id);

const token = () => localStorage.getItem(TOKEN_KEY);
const serverBase = () => (localStorage.getItem(SERVER_KEY) || "").replace(/\/+$/, "");
const setServer = (v) => {
  const clean = (v || "").trim().replace(/\/+$/, "");
  if (clean) localStorage.setItem(SERVER_KEY, clean);
  else localStorage.removeItem(SERVER_KEY);
};
// Always route media through the backend base (NOT the app origin) so images
// load even when the app is hosted separately (GitHub Pages, etc.).
const mediaUrl = (path) => `${serverBase()}${path}`;
const artworkUrl = (id) => mediaUrl(`/media/current/${id}.png?t=${Date.now()}`);

let currentId = null;          // device id on the Frame screen
let currentDevice = null;      // its last-fetched payload

// --------------------------------------------------------------------------
// Navigation
// --------------------------------------------------------------------------
const SCREENS = ["welcome", "home", "connect", "frame", "artwork", "settings", "account"];
function go(name) {
  for (const s of SCREENS) $(`screen-${s}`).hidden = s !== name;
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
}

// --------------------------------------------------------------------------
// API + helpers
// --------------------------------------------------------------------------
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
      ? "Server didn't respond — check the server address."
      : "Can't reach the server.");
  } finally { clearTimeout(timer); }
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    const err = new Error(d.detail || `Error ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MIN = 60 * 1000, HOUR = 60 * MIN, DAY = 24 * HOUR;

function relTime(iso) {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 2 * MIN) return "just now";
  if (diff < HOUR) return `${Math.round(diff / MIN)}m ago`;
  if (diff < DAY) return `${Math.round(diff / HOUR)}h ago`;
  return `${Math.round(diff / DAY)}d ago`;
}

function batteryPct(v) {
  if (v == null) return null;
  return Math.round(Math.max(0, Math.min(1, (v - 3.3) / 0.9)) * 100);
}

// Awake = checked in within the last few minutes (powered frames poll often).
function frameState(d) {
  const seen = d.last_seen ? Date.now() - new Date(d.last_seen).getTime() : null;
  if (seen == null) return { label: "Setting up", cls: "s-setup", sub: "waiting for first check‑in" };
  if (seen < 5 * MIN) return { label: "Awake", cls: "s-on", sub: `checked in ${relTime(d.last_seen)}` };
  if (seen < 26 * HOUR) return { label: "Asleep", cls: "s-sleep", sub: `last seen ${relTime(d.last_seen)}` };
  return { label: "Offline", cls: "s-off", sub: `last seen ${relTime(d.last_seen)}` };
}

function wifiLabel(rssi) {
  if (rssi == null) return "—";
  const q = rssi >= -60 ? "Strong" : rssi >= -70 ? "Good" : rssi >= -80 ? "Weak" : "Poor";
  return `${q} (${rssi} dBm)`;
}

const shortId = (id) => (id || "").slice(-4).toUpperCase();
const defaultName = (id) => `Ink Frame · ${shortId(id)}`;
const displayName = (d) => (d && d.name) ? d.name : defaultName(d && d.id);

function flash(id, text, isErr) {
  const el = $(id); if (!el) return;
  el.textContent = text; el.hidden = false;
  el.className = isErr ? "error" : "ok";
}
function showError(id, e) { flash(id, e.message, true); }

let toastTimer = null;
function toast(text) {
  const el = $("toast");
  el.textContent = text; el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

// Load an artwork image into <img> with a skeleton until it resolves.
function loadArtwork(imgEl, skelEl, id, onMissing) {
  imgEl.classList.remove("loaded");
  if (skelEl) skelEl.hidden = false;
  imgEl.onload = () => { imgEl.classList.add("loaded"); if (skelEl) skelEl.hidden = true; };
  imgEl.onerror = () => { if (skelEl) skelEl.hidden = true; if (onMissing) onMissing(); };
  imgEl.src = artworkUrl(id);
}

// --------------------------------------------------------------------------
// Welcome
// --------------------------------------------------------------------------
function wireWelcome() {
  $("server-url").value = serverBase();
  $("server-save").addEventListener("click", () => {
    setServer($("server-url").value);
    flash("server-msg", "Saved. Now tap Get started.");
  });
  $("start-btn").addEventListener("click", async () => {
    try {
      const { token: t } = await api("/account", { method: "POST", auth: false });
      localStorage.setItem(TOKEN_KEY, t);
      await showHome();
    } catch (e) {
      showError("welcome-error", e);
      $("server-details").open = true;
    }
  });
  $("restore-btn").addEventListener("click", async () => {
    const t = $("restore-token").value.trim();
    if (!t) return;
    localStorage.setItem(TOKEN_KEY, t);
    try { await api("/account"); await showHome(); }
    catch (e) { localStorage.removeItem(TOKEN_KEY); showError("welcome-error", e); }
  });
}

// --------------------------------------------------------------------------
// Home
// --------------------------------------------------------------------------
async function showHome() {
  go("home");
  const grid = $("frame-grid");
  grid.innerHTML = "";
  $("home-empty").hidden = true;
  $("add-frame-btn").hidden = true;

  let devices;
  try {
    ({ devices } = await api("/devices"));
  } catch (e) {
    if (e.status === 401) { localStorage.removeItem(TOKEN_KEY); return go("welcome"); }
    grid.innerHTML = `<p class="error">${e.message}</p>`;
    return;
  }

  const eyebrow = document.querySelector(".home-eyebrow");
  if (!devices.length) {
    $("home-empty").hidden = false;
    if (eyebrow) eyebrow.hidden = true;     // just the mark + Connect when empty
    hideInstallBanner(false);               // don't stack an install prompt on the empty state
    return;
  }
  if (eyebrow) eyebrow.hidden = false;
  for (const d of devices) grid.appendChild(frameCard(d));
  $("add-frame-btn").hidden = false;
  maybeShowInstallBanner();                 // only once they actually have a frame
}

function frameCard(d) {
  const st = frameState(d);
  const card = document.createElement("button");
  card.className = "frame-card";
  card.innerHTML =
    `<div class="fc-thumb"><div class="skeleton"></div><img alt="" /></div>` +
    `<div class="fc-body">` +
      `<span class="fc-name"><span class="dot ${st.cls}"></span>${displayName(d)}</span>` +
      `<p class="fc-desc">${st.label} · ${st.sub}</p>` +
    `</div>`;
  const img = card.querySelector("img");
  const skel = card.querySelector(".skeleton");
  const thumb = card.querySelector(".fc-thumb");
  loadArtwork(img, skel, d.id, () => {
    thumb.innerHTML = `<div class="fc-empty">No artwork yet</div>`;
  });
  // Replace the status line with the event description once the archive loads.
  api(`/devices/${d.id}/archive?limit=1`).then(({ items }) => {
    const m = items && items[0];
    if (m && m.event_text_en) card.querySelector(".fc-desc").textContent = m.event_text_en;
  }).catch(() => {});
  card.addEventListener("click", () => openFrame(d.id));
  return card;
}

// --------------------------------------------------------------------------
// Connect a frame
// --------------------------------------------------------------------------
function wireConnect() {
  $("empty-connect-btn").addEventListener("click", () => go("connect"));
  $("add-frame-btn").addEventListener("click", () => go("connect"));
  $("connect-back").addEventListener("click", showHome);
  $("pair-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const dev = await api("/devices/pair",
        { method: "POST", body: { pairing_code: $("pair-code").value.trim() } });
      const nm = $("pair-name").value.trim();
      if (nm) { try { await api(`/devices/${dev.id}/config`, { method: "PUT", body: { name: nm } }); } catch {} }
      $("pair-code").value = ""; $("pair-name").value = "";
      toast("Frame connected");
      await openFrame(dev.id);
    } catch (e2) { showError("pair-error", e2); }
  });
}

// --------------------------------------------------------------------------
// Frame detail
// --------------------------------------------------------------------------
async function openFrame(id) {
  currentId = id;
  go("frame");
  $("frame-title").textContent = defaultName(id);
  $("ev-meta").textContent = "On view today";
  $("ev-text").textContent = "Loading…";
  loadArtwork($("preview-img"), $("img-skeleton"), id, () => {
    $("ev-text").textContent = "Today's work hasn't been created yet — tap Regenerate.";
  });
  try {
    currentDevice = await api(`/devices/${id}`);
    $("frame-title").textContent = displayName(currentDevice);
    const st = frameState(currentDevice);
    $("settings-sub").textContent = `${st.label} · ${st.sub}`;
    await loadPlacard(id, currentDevice.signature);
  } catch (e) { showError("action-msg", e); }
}

async function loadPlacard(id, signature) {
  const eyebrow = $("ev-meta"), en = $("ev-text"), he = $("ev-text-he"), sign = $("ev-sign");
  he.hidden = true; sign.hidden = true;
  try {
    const { items } = await api(`/devices/${id}/archive?limit=1`);
    const m = items[0];
    if (!m) { eyebrow.textContent = "On view today"; en.textContent = "Today's work hasn't been created yet."; return; }
    eyebrow.textContent = [m.date, m.weather_summary].filter(Boolean).join("  ·  ");
    en.textContent = m.event_text_en || "—";
    if (m.event_text_he) { he.textContent = m.event_text_he; he.hidden = false; }
    if (signature) { sign.textContent = `— ${signature}`; sign.hidden = false; }
  } catch {
    eyebrow.textContent = "On view today"; en.textContent = "—";
  }
}

function setBusy(on) {
  $("regen-btn").disabled = on;
  $("regen-btn").textContent = on ? "Painting…" : "Regenerate";
  document.querySelector(".artframe").classList.toggle("busy", on);
}

async function pollGeneration(id) {
  flash("action-msg", "Painting today's work… (about 20–30 s)");
  for (let i = 0; i < 48; i++) {
    await sleep(2500);
    let s;
    try { s = await api(`/devices/${id}/generation`); } catch { continue; }
    if (s.state === "done") {
      if (id === currentId) {
        loadArtwork($("preview-img"), $("img-skeleton"), id);
        await loadPlacard(id, currentDevice && currentDevice.signature);
      }
      flash("action-msg", "Done — your frame shows it on its next refresh, or press KEY1.");
      return;
    }
    if (s.state === "error") { flash("action-msg", s.detail || "Generation failed.", true); return; }
  }
  flash("action-msg", "Still working… check back in a moment.");
}

function wireFrame() {
  $("frame-back").addEventListener("click", showHome);
  $("goto-artwork").addEventListener("click", openArtwork);
  $("goto-settings").addEventListener("click", openSettings);
  $("regen-btn").addEventListener("click", async () => {
    const id = currentId;
    setBusy(true);
    try { await api(`/devices/${id}/regenerate`, { method: "POST" }); await pollGeneration(id); }
    catch (e) { flash("action-msg", e.message, true); }
    setBusy(false);
  });
}

// --------------------------------------------------------------------------
// Artwork settings
// --------------------------------------------------------------------------
function openArtwork() {
  if (!currentDevice) return;
  fillForm(currentDevice);
  go("artwork");
}

function fillForm(d) {
  $("lat").value = d.lat; $("lon").value = d.lon; $("tz").value = d.tz;
  $("wake").value = d.wake_hour; $("language").value = d.language;
  $("temp_unit").value = d.temp_unit;
  $("orientation").value = d.orientation || "landscape";
  $("show_date").checked = d.show_date !== false;
  $("show_weather").checked = d.show_weather !== false;
  $("signature").value = d.signature || "";
  $("h-jewish").checked = d.holiday_jewish;
  $("h-israeli").checked = d.holiday_israeli;
  $("h-global").checked = d.holiday_global;
  $("enabled").checked = d.enabled;

  const tokens = (d.interests || "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  const known = new Set(INTEREST_FIELDS);
  document.querySelectorAll(".interest").forEach((cb) => { cb.checked = tokens.includes(cb.value); });
  $("interest-other").value = tokens.filter((t) => !known.has(t)).join(", ");
}

function formBody() {
  const chips = [...document.querySelectorAll(".interest:checked")].map((cb) => cb.value);
  const other = $("interest-other").value.split(",").map((s) => s.trim()).filter(Boolean);
  return {
    lat: parseFloat($("lat").value), lon: parseFloat($("lon").value),
    tz: $("tz").value.trim(), wake_hour: parseInt($("wake").value, 10),
    language: $("language").value, temp_unit: $("temp_unit").value,
    orientation: $("orientation").value,
    show_date: $("show_date").checked, show_weather: $("show_weather").checked,
    interests: [...chips, ...other].join(", "),
    signature: $("signature").value.trim() || "Ink.",
    holiday_jewish: $("h-jewish").checked, holiday_israeli: $("h-israeli").checked,
    holiday_global: $("h-global").checked, enabled: $("enabled").checked,
  };
}

function wireArtwork() {
  $("artwork-back").addEventListener("click", () => go("frame"));
  $("artwork-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body: formBody() });
      flash("save-msg", "Saved."); toast("Settings saved");
    } catch (e2) { showError("save-msg", e2); }
  });
  $("loc-btn").addEventListener("click", geocode);
  $("geo-btn").addEventListener("click", useMyLocation);
}

async function geocode() {
  const q = $("loc-search").value.trim();
  if (!q) return;
  flash("loc-msg", "Searching…");
  try {
    const data = await fetch(
      "https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + encodeURIComponent(q)
    ).then((r) => r.json());
    const hit = (data.results || [])[0];
    if (!hit) { flash("loc-msg", "Location not found.", true); return; }
    applyLocation(hit.latitude, hit.longitude, hit.timezone,
      [hit.name, hit.country].filter(Boolean).join(", "));
  } catch { flash("loc-msg", "Couldn't search right now.", true); }
}

function useMyLocation() {
  if (!navigator.geolocation) { flash("loc-msg", "Location isn't available on this device.", true); return; }
  flash("loc-msg", "Locating…");
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { latitude, longitude } = pos.coords;
    let label = "your location", tz;
    try {
      const r = await fetch(
        `https://geocoding-api.open-meteo.com/v1/search?count=1&latitude=${latitude}&longitude=${longitude}`
      ).then((x) => x.json());
      const hit = (r.results || [])[0];
      if (hit) { label = [hit.name, hit.country].filter(Boolean).join(", "); tz = hit.timezone; }
    } catch {}
    if (!tz) tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    applyLocation(latitude, longitude, tz, label);
  }, () => flash("loc-msg", "Couldn't get your location — allow access or search instead.", true),
    { timeout: 10000 });
}

function applyLocation(lat, lon, tz, label) {
  $("lat").value = (+lat).toFixed(4);
  $("lon").value = (+lon).toFixed(4);
  if (tz) $("tz").value = tz;
  flash("loc-msg", `Set to ${label}.`);
}

// --------------------------------------------------------------------------
// Frame settings
// --------------------------------------------------------------------------
function openSettings() {
  if (!currentDevice) return;
  const d = currentDevice, st = frameState(d);
  $("set-dot").className = `dot ${st.cls}`;
  $("set-state").textContent = st.label;
  $("set-sub").textContent = st.sub;
  $("spec-conn").textContent = d.last_seen ? relTime(d.last_seen) : "never";
  $("spec-wifi").textContent = wifiLabel(d.wifi_rssi);
  const bat = batteryPct(d.battery);
  $("spec-batt").textContent = bat != null ? `${bat}%` : "—";
  $("spec-fw").textContent = d.fw_version || "—";
  $("spec-id").textContent = d.id;
  $("set-name").value = d.name || "";
  $("set-name").placeholder = defaultName(d.id);
  $("name-msg").hidden = true;
  go("settings");
}

function wireSettings() {
  $("settings-back").addEventListener("click", () => go("frame"));
  $("set-name-save").addEventListener("click", async () => {
    const name = $("set-name").value.trim();
    try {
      currentDevice = await api(`/devices/${currentId}/config`, { method: "PUT", body: { name } });
      $("frame-title").textContent = displayName(currentDevice);
      flash("name-msg", "Saved."); toast("Name updated");
    } catch (e) { showError("name-msg", e); }
  });
  $("disconnect-btn").addEventListener("click", async () => {
    if (!confirm(
      "Disconnect and forget this frame?\n\n" +
      "Its settings are cleared and it returns to onboarding — it will show a " +
      "pairing QR again the next time it's online."
    )) return;
    try {
      await api(`/devices/${currentId}/unbind`, { method: "POST" });
      toast("Frame forgotten");
      await showHome();
    } catch (e) { alert(e.message); }
  });
}

// --------------------------------------------------------------------------
// Account
// --------------------------------------------------------------------------
async function showAccount() {
  go("account");
  $("token-display").value = token();
  $("acct-server-url").value = serverBase();
  $("app-version").textContent = APP_VERSION;
  $("key-msg").hidden = true; $("key-err").hidden = true;
  refreshInstallUI();
  try {
    const a = await api("/account");
    setKeyMode(a.key_status);
    $("acct-id").textContent = a.account_id || "—";
  } catch (e) { showError("key-err", e); }
}

// Reflect the key state in the segmented control. status: platform | own | required.
function setKeyMode(status) {
  const usingOwn = status === "own" || status === "required";
  $("seg-platform").classList.toggle("active", !usingOwn);
  $("seg-own").classList.toggle("active", usingOwn);
  $("own-key-fields").hidden = !usingOwn;
  $("seg-platform").disabled = status === "required";  // can't leave own key
  $("key-required-note").hidden = status !== "required";
}

function wireAccount() {
  $("menu-btn").addEventListener("click", showAccount);
  $("acct-back").addEventListener("click", showHome);
  $("acct-server-save").addEventListener("click", () => {
    setServer($("acct-server-url").value); flash("acct-server-msg", "Saved.");
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
    try {
      await api("/account/key", { method: "PUT", body: { openai_api_key: v } });
      $("api-key").value = ""; setKeyMode("own"); flash("key-msg", "Saved your key."); toast("Saved your key");
    } catch (e) { showError("key-err", e); }
  });
  $("update-btn").addEventListener("click", async () => {
    flash("update-msg", "Checking…");
    try {
      if ("serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.getRegistration();
        if (reg) await reg.update();
      }
      flash("update-msg", "Up to date. Reloading…");
      setTimeout(() => location.reload(), 700);
    } catch { flash("update-msg", "Couldn't check for updates.", true); }
  });
  $("logout-btn").addEventListener("click", () => {
    if (!confirm("Log out of this account on this device?\n\nKeep your account token saved if you want to return.")) return;
    localStorage.removeItem(TOKEN_KEY);
    go("welcome");
  });
}

// --------------------------------------------------------------------------
// PWA install (Add to Home Screen)
// --------------------------------------------------------------------------
const INSTALL_DISMISS_KEY = "ink.installDismissed";
let deferredPrompt = null;

const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;

function refreshInstallUI() {
  const card = $("install-card");
  if (!card) return;
  if (isStandalone()) { card.hidden = true; return; }
  card.hidden = false;
  $("install-hint").textContent = deferredPrompt
    ? "Add Ink to your home screen for a full‑screen, app‑like experience."
    : isIOS()
      ? "In Safari, tap the Share icon, then “Add to Home Screen.”"
      : "Open your browser's menu and choose “Install” or “Add to Home screen.”";
  $("install-btn").hidden = !deferredPrompt && !isIOS();
}

function maybeShowInstallBanner() {
  if (isStandalone()) return;
  if (localStorage.getItem(INSTALL_DISMISS_KEY)) return;
  if (!deferredPrompt && !isIOS()) return;   // nothing actionable to offer
  const b = $("install-banner");
  $("ib-sub").textContent = deferredPrompt
    ? "Add it to your home screen for a full‑screen experience."
    : "In Safari, tap Share → “Add to Home Screen.”";
  $("ib-install").style.display = deferredPrompt ? "" : "none";
  b.hidden = false;
  requestAnimationFrame(() => b.classList.add("show"));
}

function hideInstallBanner(persist) {
  const b = $("install-banner");
  b.classList.remove("show");
  setTimeout(() => { b.hidden = true; }, 350);
  if (persist || $("ib-dontshow").checked) localStorage.setItem(INSTALL_DISMISS_KEY, "1");
}

async function doInstall() {
  if (deferredPrompt) {
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    deferredPrompt = null;
    if (outcome === "accepted") hideInstallBanner(true);
    refreshInstallUI();
  } else if (isIOS()) {
    toast("Tap Share, then “Add to Home Screen”");
  } else {
    toast("Use your browser menu → Install");
  }
}

function wireInstall() {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); deferredPrompt = e; refreshInstallUI(); maybeShowInstallBanner();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null; hideInstallBanner(true); refreshInstallUI(); toast("Ink installed");
  });
  $("install-btn").addEventListener("click", doInstall);
  $("ib-install").addEventListener("click", doInstall);
  $("ib-dismiss").addEventListener("click", () => hideInstallBanner(false));
}

// --------------------------------------------------------------------------
// QR deep-link pairing: /app/?code=NNNNNN[&server=...]
// --------------------------------------------------------------------------
async function syncByCode(code) {
  try {
    const dev = await api("/devices/pair", { method: "POST", body: { pairing_code: code } });
    toast("Frame connected");
    await openFrame(dev.id);
  } catch (e) {
    await showHome();
    go("connect");
    $("pair-code").value = code;
    showError("pair-error", e);
  }
}

// --------------------------------------------------------------------------
function init() {
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  wireWelcome(); wireConnect(); wireFrame(); wireArtwork(); wireSettings(); wireAccount(); wireInstall();

  const params = new URLSearchParams(location.search);
  const server = params.get("server");
  if (server) setServer(server);
  const code = params.get("code");
  const valid = code && /^\d{6}$/.test(code);

  if (token()) {
    if (valid) syncByCode(code); else showHome();
  } else if (valid) {
    go("welcome");
    api("/account", { method: "POST", auth: false })
      .then(({ token: t }) => { localStorage.setItem(TOKEN_KEY, t); syncByCode(code); })
      .catch((e) => { showError("welcome-error", e); $("server-details").open = true; });
  } else {
    go("welcome");
  }

  if ("serviceWorker" in navigator) {
    addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
}

init();
