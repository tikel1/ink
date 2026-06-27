"use strict";

// Ink — premium control app. Served by the backend (same-origin API).

const TOKEN_KEY = "ink.token";
const $ = (id) => document.getElementById(id);

let editing = null; // device id being edited

const token = () => localStorage.getItem(TOKEN_KEY);

function showScreen(name) {
  for (const s of ["welcome", "devices", "edit", "account"]) {
    $(`screen-${s}`).hidden = s !== name;
  }
}

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && token()) headers.Authorization = `Bearer ${token()}`;
  const res = await fetch("/api/app" + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Error ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

// --------------------------------------------------------------------------
// Status helpers
// --------------------------------------------------------------------------
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
  const pct = Math.round(Math.max(0, Math.min(1, (v - 3.3) / 0.9)) * 100);
  return pct;
}

// E-ink frames sleep most of the day, so "connected" = checked in recently.
function statusInfo(d) {
  const seen = d.last_seen ? Date.now() - new Date(d.last_seen).getTime() : null;
  const bat = batteryPct(d.battery);
  const batTxt = bat != null ? ` · ${bat}%` : "";
  if (seen == null) return { label: "Setting up", cls: "s-setup", sub: "waiting for first check‑in" };
  if (seen < 26 * HOUR) return { label: "Connected", cls: "s-on", sub: `updated ${relTime(d.last_seen)}${batTxt}` };
  if (seen < 4 * DAY) return { label: "Asleep", cls: "s-sleep", sub: `last seen ${relTime(d.last_seen)}${batTxt}` };
  return { label: "Offline", cls: "s-off", sub: `last seen ${relTime(d.last_seen)}${batTxt}` };
}

// --------------------------------------------------------------------------
// Account lifecycle
// --------------------------------------------------------------------------
function wireWelcome() {
  $("start-btn").addEventListener("click", async () => {
    try {
      const { token: t } = await api("/account", { method: "POST", auth: false });
      localStorage.setItem(TOKEN_KEY, t);
      await showDevices();
    } catch (e) { showError("welcome-error", e); }
  });
  $("restore-btn").addEventListener("click", async () => {
    const t = $("restore-token").value.trim();
    if (!t) return;
    localStorage.setItem(TOKEN_KEY, t);
    try { await api("/account"); await showDevices(); }
    catch (e) { localStorage.removeItem(TOKEN_KEY); showError("welcome-error", e); }
  });
}

// --------------------------------------------------------------------------
// Frames list
// --------------------------------------------------------------------------
async function showDevices() {
  showScreen("devices");
  const list = $("device-list");
  list.innerHTML = '<p class="hint">Loading…</p>';
  const { devices } = await api("/devices");
  list.innerHTML = devices.length ? "" : '<p class="hint">No frames yet — connect one below.</p>';
  for (const d of devices) list.appendChild(deviceTile(d));
}

function deviceTile(d) {
  const s = statusInfo(d);
  const el = document.createElement("button");
  el.className = "device-tile";
  el.innerHTML =
    `<span class="dot ${s.cls}"></span>` +
    `<span class="ti-col"><span class="tname">${d.id}</span>` +
    `<span class="tsub">${s.label} · ${s.sub}</span></span>`;
  el.addEventListener("click", () => openDevice(d.id));
  return el;
}

function wirePairing() {
  $("pair-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/devices/pair", { method: "POST", body: { pairing_code: $("pair-code").value.trim() } });
      $("pair-code").value = "";
      await showDevices();
    } catch (e2) { showError("pair-error", e2); }
  });
}

// --------------------------------------------------------------------------
// Frame detail
// --------------------------------------------------------------------------
async function openDevice(id) {
  editing = id;
  const d = await api(`/devices/${id}`);
  $("edit-title").textContent = id;
  renderStatus(d);
  fillForm(d);
  $("preview-img").src = `/media/current/${id}.png?t=${Date.now()}`;
  loadPlacard(id, d.signature);
  showScreen("edit");
}

function renderStatus(d) {
  const s = statusInfo(d);
  $("status-dot").className = `dot ${s.cls}`;
  $("status-text").textContent = s.label;
  $("status-sub").textContent = s.sub;
}

function fillForm(d) {
  $("lat").value = d.lat; $("lon").value = d.lon; $("tz").value = d.tz;
  $("wake").value = d.wake_hour; $("language").value = d.language;
  $("temp_unit").value = d.temp_unit; $("interests").value = d.interests;
  $("signature").value = d.signature;
  $("h-jewish").checked = d.holiday_jewish;
  $("h-israeli").checked = d.holiday_israeli;
  $("h-global").checked = d.holiday_global;
  $("enabled").checked = d.enabled;
}

async function loadPlacard(id, signature) {
  const eyebrow = $("ev-meta"), en = $("ev-text"), he = $("ev-text-he"), sign = $("ev-sign");
  he.hidden = true; sign.hidden = true;
  try {
    const { items } = await api(`/devices/${id}/archive?limit=1`);
    const m = items[0];
    if (!m) { eyebrow.textContent = "On view today"; en.textContent = "No artwork generated yet."; return; }
    eyebrow.textContent = [m.date, m.weather_summary].filter(Boolean).join("  ·  ");
    en.textContent = m.event_text_en || "—";
    if (m.event_text_he) { he.textContent = m.event_text_he; he.hidden = false; }
    if (signature) { sign.textContent = `— ${signature}`; sign.hidden = false; }
  } catch {
    eyebrow.textContent = "On view today"; en.textContent = "—";
  }
}

function formBody() {
  return {
    lat: parseFloat($("lat").value), lon: parseFloat($("lon").value),
    tz: $("tz").value.trim(), wake_hour: parseInt($("wake").value, 10),
    language: $("language").value, temp_unit: $("temp_unit").value,
    interests: $("interests").value.trim(),
    signature: $("signature").value.trim() || "House Kaplan",
    holiday_jewish: $("h-jewish").checked, holiday_israeli: $("h-israeli").checked,
    holiday_global: $("h-global").checked, enabled: $("enabled").checked,
  };
}

function wireEditor() {
  $("back-btn").addEventListener("click", showDevices);
  $("edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    await api(`/devices/${editing}/config`, { method: "PUT", body: formBody() });
    flash("save-msg", "Saved.");
  });
  $("loc-btn").addEventListener("click", geocode);
  $("regen-btn").addEventListener("click", async () => {
    const id = editing;
    setBusy(true);
    try {
      await api(`/devices/${id}/regenerate`, { method: "POST" });
      await pollGeneration(id);
    } catch (e) {
      flash("action-msg", e.message);
    }
    setBusy(false);
  });
  $("remove-btn").addEventListener("click", async () => {
    if (!confirm("Remove this frame and clear its settings?")) return;
    await api(`/devices/${editing}/unbind`, { method: "POST" });
    await showDevices();
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function setBusy(on) {
  $("regen-btn").disabled = on;
  $("regen-btn").textContent = on ? "Creating…" : "Regenerate";
  document.querySelector(".artframe").classList.toggle("busy", on);
}

// Poll generation status (~2 min max) and reveal the result when done.
async function pollGeneration(id) {
  flash("action-msg", "Creating today's art… (about 20–30s)");
  for (let i = 0; i < 48; i++) {
    await sleep(2500);
    let s;
    try { s = await api(`/devices/${id}/generation`); } catch { continue; }
    if (s.state === "done") {
      if (id === editing) {
        $("preview-img").src = `/media/current/${id}.png?t=${Date.now()}`;
        await loadPlacard(id, $("signature").value);
      }
      flash("action-msg", "Updated. The frame shows it on its next wake or KEY1 press.");
      return;
    }
    if (s.state === "error") { flash("action-msg", s.detail || "Generation failed."); return; }
  }
  flash("action-msg", "Still working… check back in a moment.");
}

async function geocode() {
  const q = $("loc-search").value.trim();
  if (!q) return;
  const data = await fetch(
    "https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + encodeURIComponent(q)
  ).then((r) => r.json());
  const hit = (data.results || [])[0];
  if (!hit) return alert("Location not found");
  $("lat").value = hit.latitude; $("lon").value = hit.longitude;
  if (hit.timezone) $("tz").value = hit.timezone;
}

// --------------------------------------------------------------------------
// Account / API key
// --------------------------------------------------------------------------
async function showAccount() {
  showScreen("account");
  $("token-display").value = token();
  const a = await api("/account");
  const labels = {
    platform: "Using the default (shared) key.",
    own: "Using your own key.",
    required: "Your own key is required.",
  };
  $("key-status").textContent = labels[a.key_status] || a.key_status;
  $("key-required-note").hidden = a.key_status !== "required";
  $("clear-key-btn").disabled = a.key_status === "required";
}

function wireAccount() {
  $("account-btn").addEventListener("click", showAccount);
  $("acct-back").addEventListener("click", showDevices);
  $("save-key-btn").addEventListener("click", async () => {
    try {
      await api("/account/key", { method: "PUT", body: { openai_api_key: $("api-key").value.trim() } });
      $("api-key").value = ""; flash("key-msg", "Saved your key."); showAccount();
    } catch (e) { showError("key-err", e); }
  });
  $("clear-key-btn").addEventListener("click", async () => {
    try { await api("/account/key", { method: "DELETE" }); flash("key-msg", "Switched to the default key."); showAccount(); }
    catch (e) { showError("key-err", e); }
  });
}

// --------------------------------------------------------------------------
function flash(id, text) { const el = $(id); el.textContent = text; el.hidden = false; }
function showError(id, e) { const el = $(id); el.textContent = e.message; el.hidden = false; }

// Scanning the QR on the frame opens /app/?code=NNNNNN — pair in one tap.
async function syncByCode(code) {
  try {
    const dev = await api("/devices/pair", { method: "POST", body: { pairing_code: code } });
    await showDevices();
    await openDevice(dev.id);
    flash("action-msg", "Frame connected. Set its location below.");
  } catch (e) {
    await showDevices();
    $("pair-code").value = code;
    showError("pair-error", e);
  }
}

async function init() {
  wireWelcome(); wirePairing(); wireEditor(); wireAccount();
  const code = new URLSearchParams(location.search).get("code");
  const valid = code && /^\d{6}$/.test(code);
  try {
    // QR scanned with no account yet → create one silently, then pair.
    if (!token() && valid) {
      const { token: t } = await api("/account", { method: "POST", auth: false });
      localStorage.setItem(TOKEN_KEY, t);
    }
    if (token()) {
      if (valid) await syncByCode(code);
      else await showDevices();
    } else {
      showScreen("welcome");
    }
  } catch {
    localStorage.removeItem(TOKEN_KEY);
    showScreen("welcome");
  }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

init();
