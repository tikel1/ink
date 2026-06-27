"use strict";

// Ink product app: account → pair frames → preferences + own API key.
// Served by the backend, so the API is same-origin (relative paths).

const TOKEN_KEY = "housekaplan.token";
const $ = (id) => document.getElementById(id);

let editing = null; // device id being edited

function token() {
  return localStorage.getItem(TOKEN_KEY);
}

function showScreen(name) {
  for (const s of ["welcome", "devices", "edit", "account"]) {
    $(`screen-${s}`).hidden = s !== name;
  }
}

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth && token()) headers.Authorization = `Bearer ${token()}`;
  const res = await fetch("/api/app" + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Error ${res.status}`);
  }
  return res.status === 204 ? null : res.json();
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
    } catch (e) {
      showError("welcome-error", e);
    }
  });
  $("restore-btn").addEventListener("click", async () => {
    const t = $("restore-token").value.trim();
    if (!t) return;
    localStorage.setItem(TOKEN_KEY, t);
    try {
      await api("/account");
      await showDevices();
    } catch (e) {
      localStorage.removeItem(TOKEN_KEY);
      showError("welcome-error", e);
    }
  });
}

// --------------------------------------------------------------------------
// Devices
// --------------------------------------------------------------------------
async function showDevices() {
  showScreen("devices");
  const list = $("device-list");
  list.innerHTML = '<p class="hint">Loading…</p>';
  const { devices } = await api("/devices");
  list.innerHTML = devices.length ? "" : '<p class="hint">No frames yet — add one below.</p>';
  for (const d of devices) {
    const btn = document.createElement("button");
    btn.className = "device-tile";
    btn.innerHTML = `<b>${d.id}</b><span>${batteryText(d)}</span>`;
    btn.addEventListener("click", () => openDevice(d.id));
    list.appendChild(btn);
  }
}

function batteryText(d) {
  return d.battery ? `${d.battery.toFixed(2)} V` : "never seen";
}

function wirePairing() {
  $("pair-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/devices/pair", { method: "POST", body: { pairing_code: $("pair-code").value.trim() } });
      $("pair-code").value = "";
      await showDevices();
    } catch (e2) {
      showError("pair-error", e2);
    }
  });
}

// --------------------------------------------------------------------------
// Editor
// --------------------------------------------------------------------------
async function openDevice(id) {
  editing = id;
  const d = await api(`/devices/${id}`);
  $("edit-title").textContent = id;
  fillForm(d);
  $("preview-img").src = `/media/current/${id}.png?t=${Date.now()}`;
  loadMeta(id);
  showScreen("edit");
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

async function loadMeta(id) {
  const meta = $("ev-meta");
  const en = $("ev-text");
  const he = $("ev-text-he");
  he.hidden = true;
  try {
    const { items } = await api(`/devices/${id}/archive?limit=1`);
    const m = items[0];
    if (!m) {
      meta.textContent = "";
      en.textContent = "No artwork generated yet.";
      return;
    }
    meta.textContent = [m.date, m.weather_summary].filter(Boolean).join(" · ");
    en.textContent = m.event_text_en || "—";
    if (m.event_text_he) { he.textContent = m.event_text_he; he.hidden = false; }
  } catch {
    meta.textContent = "";
    en.textContent = "—";
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
    const r = await api(`/devices/${editing}/regenerate`, { method: "POST" });
    flash("action-msg", r.note);
  });
  $("remove-btn").addEventListener("click", async () => {
    if (!confirm("Remove this frame and clear its settings?")) return;
    await api(`/devices/${editing}/unbind`, { method: "POST" });
    await showDevices();
  });
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
  const labels = { platform: "Using the default (shared) key.",
                   own: "Using your own key.",
                   required: "Your own key is required." };
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
      $("api-key").value = "";
      flash("key-msg", "Saved your key.");
      showAccount();
    } catch (e) { showError("key-err", e); }
  });
  $("clear-key-btn").addEventListener("click", async () => {
    try {
      await api("/account/key", { method: "DELETE" });
      flash("key-msg", "Switched to the default key.");
      showAccount();
    } catch (e) { showError("key-err", e); }
  });
}

// --------------------------------------------------------------------------
function flash(id, text) { const el = $(id); el.textContent = text; el.hidden = false; }
function showError(id, e) { const el = $(id); el.textContent = e.message; el.hidden = false; }

async function init() {
  wireWelcome(); wirePairing(); wireEditor(); wireAccount();
  const code = new URLSearchParams(location.search).get("code");
  if (token()) {
    try {
      await showDevices();
      if (code && /^\d{6}$/.test(code)) $("pair-code").value = code;
    } catch {
      localStorage.removeItem(TOKEN_KEY);
      showScreen("welcome");
    }
  } else {
    showScreen("welcome");
  }
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
}

init();
