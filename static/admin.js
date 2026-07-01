"use strict";
// Ink admin/monitoring console. Served from the backend origin, so the API is
// same-origin (/api/admin/*) and images are same-origin (/media/*). Auth is the
// ADMIN_TOKEN, kept in sessionStorage and sent as X-Admin-Token on every call.

// Same-origin by default (the console is served from the backend). `?api=<url>`
// lets it point at a remote backend (e.g. a github.io copy → Fly).
const BASE = (new URLSearchParams(location.search).get("api") || "").replace(/\/+$/, "");
const API = BASE + "/api/admin";
const TOKEN_KEY = "ink.admin.token";
const $ = (id) => document.getElementById(id);
let token = sessionStorage.getItem(TOKEN_KEY) || "";
let activeTab = "overview";

// ── helpers ─────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (n) => (n == null ? "—" : Number(n).toLocaleString());
const usd = (n) => (n == null ? "—" : "$" + Number(n).toFixed(2));
const shortId = (id) => (id || "").length > 10 ? (id || "").slice(-6) : (id || "—");

function relTime(iso) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}
const dayLabel = (d) => { // "2026-06-30" -> "Jun 30"
  const p = (d || "").split("-"); if (p.length !== 3) return d || "";
  return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]))
    .toLocaleDateString("en-US", { month: "short", day: "numeric" });
};
const wifiLabel = (r) => (r == null || r === 0) ? "—"
  : (r >= -60 ? "Strong" : r >= -70 ? "Good" : r >= -80 ? "Weak" : "Poor") + ` (${r})`;

async function api(path) {
  const url = API + path;
  console.log("[admin] fetch", url);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 12000);   // never hang forever
  try {
    const res = await fetch(url, { headers: { "X-Admin-Token": token }, cache: "no-store", signal: ctrl.signal });
    if (res.status === 403) throw new Error("403");
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  } catch (e) {
    if (e.name === "AbortError") throw new Error("timed out (12s) reaching " + url);
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

async function apiSend(path, method) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 12000);
  try {
    const res = await fetch(API + path, { method, headers: { "X-Admin-Token": token }, cache: "no-store", signal: ctrl.signal });
    if (res.status === 403) { logout("Session expired — re-enter the token."); throw new Error("403"); }
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

// ── auth ────────────────────────────────────────────────────────────────
function logout(msg) {
  token = ""; sessionStorage.removeItem(TOKEN_KEY);
  $("console").hidden = true; $("login").hidden = false;
  if (msg) $("login-err").textContent = msg;
}
async function unlock(candidate) {
  token = candidate;
  try {
    const data = await api("/overview");        // validates the token
    sessionStorage.setItem(TOKEN_KEY, token);
    $("login").hidden = true; $("console").hidden = false;
    renderOverview(data); stamp();
  } catch (e) {
    token = "";
    console.error("admin unlock failed:", e, "API base:", API);
    $("login-err").textContent =
      e.message === "403" ? "Token rejected — check the ADMIN_TOKEN."
      : e.message && e.message.startsWith("HTTP")
        ? `API returned ${e.message} at ${API} — wrong URL? Open it from the backend, or add ?api=<backend>.`
        : `Couldn't reach the API at ${API} (${e.message}).`;
  }
}
function stamp() { $("refreshed").textContent = "updated " + new Date().toLocaleTimeString(); }

// A per-section text filter: show only rows/cards whose data-search contains the query.
const filterBox = (ph) => `<input class="filter" placeholder="${ph}" /> <span class="filter-count"></span>`;
function wireFilter(sectionId) {
  const sec = $(sectionId), inp = sec.querySelector(".filter");
  if (!inp) return;
  const items = [...sec.querySelectorAll("[data-search]")];
  const count = sec.querySelector(".filter-count");
  const apply = () => {
    const q = inp.value.trim().toLowerCase();
    let n = 0;
    items.forEach((el) => {
      const show = !q || el.dataset.search.includes(q);
      el.style.display = show ? "" : "none";
      if (show) n++;
    });
    if (count) count.textContent = q ? `${n} of ${items.length}` : "";
  };
  inp.addEventListener("input", apply);
}

// ── gallery preview lightbox ──────────────────────────────────────────────
let galleryItems = [];
function openArt(i) {
  const it = galleryItems[i]; if (!it) return;
  $("art-title").textContent = `${it.device_name || shortId(it.device_id)} · ${it.date}`;
  $("art-img").src = BASE + it.image_url;
  const row = (label, val, pre) => !val ? "" :
    `<dt>${esc(label)}</dt><dd>${pre ? `<pre>${esc(val)}</pre>` : esc(val)}</dd>`;
  $("art-detail").innerHTML =
    row("Event", it.event_caption) +
    row("Final description", it.event_text_en) +
    row("Hebrew", it.event_text_he) +
    row("Iconic visual", it.event_visual) +
    row("Weather", it.weather_summary) +
    row("Orientation", it.orientation) +
    row("Image prompt", it.image_prompt, true);
  $("art-modal").hidden = false;
}
const closeArt = () => { $("art-modal").hidden = true; };

// ── charts (inline SVG, no libs) ──────────────────────────────────────────
function barChart(series, { errKey } = {}) {
  if (!series || !series.length) return `<p class="empty">No data yet.</p>`;
  const W = 640, H = 150, pad = 18, n = series.length;
  const max = Math.max(1, ...series.map((d) => d.value));
  const bw = (W - pad * 2) / n, gap = Math.min(6, bw * 0.25);
  const step = Math.ceil(n / 10);
  let bars = "", labels = "";
  series.forEach((d, i) => {
    const x = pad + i * bw;
    const h = (d.value / max) * (H - 34);
    const y = H - 18 - h;
    bars += `<rect class="bar" x="${x + gap / 2}" y="${y}" width="${bw - gap}" height="${h}"><title>${esc(d.label)}: ${num(d.value)}</title></rect>`;
    if (errKey && d[errKey]) {
      const eh = (d[errKey] / max) * (H - 34);
      bars += `<rect class="bar err" x="${x + gap / 2}" y="${H - 18 - eh}" width="${bw - gap}" height="${eh}"></rect>`;
    }
    if (i % step === 0)
      labels += `<text x="${x + bw / 2}" y="${H - 4}" font-size="10" fill="#8b8473" text-anchor="middle">${esc(d.label)}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line class="axis" x1="${pad}" y1="${H - 18}" x2="${W - pad}" y2="${H - 18}"/>${bars}${labels}</svg>`;
}

// ── renderers ─────────────────────────────────────────────────────────────
function kpi(label, value, sub) {
  return `<div class="kpi"><div class="label">${esc(label)}</div>
    <div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function renderOverview(d) {
  const g = d.generation, f = d.frames, a = d.api.totals;
  const rate = g.success_rate == null ? "—" : Math.round(g.success_rate * 100) + "%";
  const genSeries = g.by_day.map((r) => ({ label: dayLabel(r.day), value: r.runs || 0, err: (r.runs || 0) - (r.ok || 0) }));
  const costSeries = g.by_day.map((r) => ({ label: dayLabel(r.day), value: Math.round((r.cost || 0) * 100) / 100 }));
  const apiSeries = d.api.by_day.map((r) => ({ label: dayLabel(r.day), value: r.calls || 0, err: r.errors || 0 }));
  $("tab-overview").innerHTML = `
    <div class="kpis">
      ${kpi("Frames", num(f.total), `<span class="pill online">${f.online} online</span> <span class="pill sleep">${f.sleep} sleep</span> <span class="pill offline">${f.offline} off</span>`)}
      ${kpi("Accounts", num(d.accounts))}
      ${kpi("Images made", num(d.artwork.ready), `${num(d.artwork.total)} total rows`)}
      ${kpi("Success rate", rate, `${num(g.ok)}/${num(g.runs)} runs`)}
      ${kpi("Est. spend", usd(g.cost_usd), "images + text + search")}
      ${kpi("Failures", num(g.failed), `${num(g.retries)} retries`)}
      ${kpi("Avg gen time", g.avg_ms ? (g.avg_ms / 1000).toFixed(1) + "s" : "—")}
      ${kpi("Updates ready", num(f.update_available), `fw ${esc(d.latest_fw || "—")}`)}
    </div>
    <div class="grid2">
      <div class="card"><h3>Generations / day (30d)</h3>${barChart(genSeries, { errKey: "err" })}
        <div class="chart-legend"><span><i style="background:var(--ink)"></i>ok</span><span><i style="background:var(--danger)"></i>failed</span></div></div>
      <div class="card"><h3>Estimated cost / day</h3>${barChart(costSeries)}
        <div class="chart-legend"><span>USD per day</span></div></div>
    </div>
    <div class="card"><h3>API calls / day (14d)</h3>${barChart(apiSeries, { errKey: "err" })}
      <div class="chart-legend"><span><i style="background:var(--ink)"></i>calls ${num(a.calls)}</span><span><i style="background:var(--danger)"></i>errors ${num(a.errors)}</span><span>avg ${a.avg_ms ? Math.round(a.avg_ms) + "ms" : "—"}</span></div></div>`;
}

function statePill(s) { return `<span class="pill ${s}">${s}</span>`; }

function renderFrames(d) {
  const rows = d.frames.map((fr) => {
    const bat = fr.state === "online" || fr.battery ? (fr.battery != null ? fr.battery.toFixed(2) + "V" : "—") : "—";
    const upd = fr.update_available ? ` <span class="pill manual">upd</span>` : "";
    const s = [fr.name, fr.id, fr.state, fr.fw_version, fr.account_id, fr.last_art_caption, fr.ota_error].join(" ").toLowerCase();
    return `<tr data-search="${esc(s)}">
      <td>${statePill(fr.state)}</td>
      <td>${esc(fr.name || shortId(fr.id))}<div class="mono" style="color:var(--muted)">${esc(shortId(fr.id))}</div></td>
      <td>${bat}</td><td>${esc(wifiLabel(fr.wifi_rssi))}</td>
      <td>${esc(fr.fw_version || "—")}${upd}</td>
      <td>${relTime(fr.last_seen)}</td>
      <td>${fr.last_art_date ? esc(dayLabel(fr.last_art_date)) : "—"}<div class="wrap-cell" style="font-size:11px">${esc((fr.last_art_caption || "").slice(0, 80))}</div></td>
      <td>${String(fr.wake_hour).padStart(2, "0")}:${String(fr.wake_minute).padStart(2, "0")} · ${esc(fr.schedule || "")}</td>
      <td>${fr.sleep_after_minutes ? fr.sleep_after_minutes + "m" : "always on"}</td>
      <td class="mono">${esc(shortId(fr.account_id))}</td>
      <td>${fr.ota_error ? `<span class="pill fail">${esc(fr.ota_error)}</span>` : "—"}</td></tr>`;
  }).join("");
  $("tab-frames").innerHTML = `<div class="card"><h3 class="hrow">All frames (${d.frames.length}) ${filterBox("Filter frames…")}</h3>
    <div class="tbl-wrap"><table><thead><tr>
      <th>State</th><th>Name</th><th>Battery</th><th>Wi-Fi</th><th>Firmware</th><th>Last seen</th>
      <th>Last art</th><th>Wake</th><th>Sleep</th><th>Account</th><th>OTA</th>
    </tr></thead><tbody>${rows || `<tr><td colspan="11" class="empty">No frames yet.</td></tr>`}</tbody></table></div></div>`;
  wireFilter("tab-frames");
}

let genFailedOnly = false;
async function loadGenerations() {
  $("tab-generations").innerHTML = `<p class="loading">Loading…</p>`;
  const d = await api("/generations?limit=200" + (genFailedOnly ? "&failed=true" : ""));
  const rows = d.runs.map((r) => `<tr data-search="${esc([r.device_id, r.trigger, r.ok ? "ok" : "fail failed", r.provider, r.phase, r.error].join(" ").toLowerCase())}">
    <td>${relTime(r.created_at)}</td>
    <td class="mono">${esc(shortId(r.device_id))}</td>
    <td><span class="pill ${r.trigger}">${esc(r.trigger)}</span></td>
    <td><span class="pill ${r.ok ? "ok" : "fail"}">${r.ok ? "ok" : "fail"}</span></td>
    <td>${r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + "s" : "—"}</td>
    <td>${r.retries || 0}</td>
    <td>${usd(r.cost_usd)}</td>
    <td>${r.image_calls}i · ${r.text_calls}t · ${r.search_calls}s</td>
    <td>${esc(r.provider || "—")}</td>
    <td class="wrap-cell">${r.ok ? "" : `<b>${esc(r.phase || "?")}</b> ${esc(r.error || "")}`}</td></tr>`).join("");
  $("tab-generations").innerHTML = `<div class="card">
    <h3 class="hrow">Generation runs (${d.runs.length})
      <label style="font-size:12px;font-weight:400;color:var(--soft)"><input type="checkbox" id="gen-failed" ${genFailedOnly ? "checked" : ""}/> failures only</label>
      ${filterBox("Filter runs…")}</h3>
    <div class="tbl-wrap"><table><thead><tr>
      <th>When</th><th>Device</th><th>Trigger</th><th>Result</th><th>Duration</th><th>Retries</th>
      <th>Cost</th><th>Calls</th><th>Provider</th><th>Error</th>
    </tr></thead><tbody>${rows || `<tr><td colspan="10" class="empty">No generation runs recorded yet.</td></tr>`}</tbody></table></div></div>`;
  $("gen-failed").addEventListener("change", (e) => { genFailedOnly = e.target.checked; loadGenerations(); });
  wireFilter("tab-generations");
}

async function loadGallery() {
  $("tab-gallery").innerHTML = `<p class="loading">Loading…</p>`;
  const d = await api("/gallery?limit=150");
  galleryItems = d.items;
  const shots = d.items.map((it, i) => {
    const search = [it.device_name, it.device_id, it.date, it.caption, it.event_visual, it.image_prompt].join(" ").toLowerCase();
    return `<div class="shot ${it.orientation === "portrait" ? "portrait" : "landscape"}" data-i="${i}" data-search="${esc(search)}">
      <img loading="lazy" src="${esc(BASE + it.image_url)}" alt="${esc(it.caption || "")}" />
      <div class="cap"><div class="d">${esc(it.device_name || shortId(it.device_id))} · ${esc(it.date)}</div>
        <div class="c">${esc(it.caption || "—")}</div></div></div>`;
  }).join("");
  $("tab-gallery").innerHTML = `<div class="card"><h3 class="hrow">Gallery (${d.items.length}) ${filterBox("Filter by device, event, prompt…")}</h3>
    ${shots ? `<div class="gallery">${shots}</div>` : `<p class="empty">No images yet.</p>`}</div>`;
  $("tab-gallery").querySelectorAll(".shot").forEach((el) =>
    el.addEventListener("click", () => openArt(Number(el.dataset.i))));
  wireFilter("tab-gallery");
}

const INACTIVE_DAYS = 30;
function acctStatus(a) {
  if (a.suspended) return "suspended";
  const s = a.last_active ? (Date.now() - new Date(a.last_active).getTime()) / 86400000 : Infinity;
  return s > INACTIVE_DAYS ? "inactive" : "active";
}
async function loadAccounts() {
  $("tab-accounts").innerHTML = `<p class="loading">Loading…</p>`;
  const d = await api("/accounts");
  const rows = d.accounts.map((a) => {
    const st = acctStatus(a);
    const pill = st === "active" ? "online" : st === "suspended" ? "fail" : "sleep";
    return `<tr data-search="${esc([a.email, a.id, st].join(" ").toLowerCase())}">
      <td>${esc(a.email || "—")}<div class="mono" style="color:var(--muted)">${esc(shortId(a.id))}</div></td>
      <td><span class="pill ${pill}">${st}</span></td>
      <td>${a.device_count}</td>
      <td>${a.last_active ? relTime(a.last_active) : "never"}</td>
      <td>${a.created_at ? dayLabel(a.created_at.slice(0, 10)) : "—"}</td>
      <td>${a.has_own_key ? "own key" : "platform"}</td>
      <td style="text-align:right">
        <button class="rowbtn" data-act="suspend" data-id="${esc(a.id)}" data-to="${a.suspended ? "0" : "1"}">${a.suspended ? "Reactivate" : "Deactivate"}</button>
        <button class="rowbtn danger" data-act="delete" data-id="${esc(a.id)}" data-label="${esc(a.email || shortId(a.id))}">Delete</button>
      </td></tr>`;
  }).join("");
  $("tab-accounts").innerHTML = `<div class="card">
    <h3 class="hrow">Accounts (${d.accounts.length}) ${filterBox("Filter accounts…")}</h3>
    <p class="chart-legend" style="margin:0 0 10px">Deactivate blocks the app + scheduler (reversible). Delete unbinds its frames and removes the account (permanent).</p>
    <div class="tbl-wrap"><table><thead><tr>
      <th>Account</th><th>Status</th><th>Frames</th><th>Last active</th><th>Created</th><th>Key</th><th></th>
    </tr></thead><tbody>${rows || `<tr><td colspan="7" class="empty">No accounts.</td></tr>`}</tbody></table></div></div>`;
  $("tab-accounts").querySelectorAll(".rowbtn").forEach((b) => b.addEventListener("click", onAccountAction));
  wireFilter("tab-accounts");
}
async function onAccountAction(e) {
  const b = e.currentTarget, id = b.dataset.id;
  if (b.dataset.act === "delete") {
    if (!confirm(`Delete account "${b.dataset.label}"?\n\nIts frames are unbound (become re-pairable) and the account is removed. This can't be undone.`)) return;
  }
  b.disabled = true;
  try {
    if (b.dataset.act === "suspend") await apiSend(`/accounts/${encodeURIComponent(id)}/suspend?suspended=${b.dataset.to === "1"}`, "POST");
    else await apiSend(`/accounts/${encodeURIComponent(id)}`, "DELETE");
    await loadAccounts();
  } catch (err) {
    if (err.message !== "403") { alert("Action failed: " + err.message); b.disabled = false; }
  }
}

async function loadApi() {
  $("tab-api").innerHTML = `<p class="loading">Loading…</p>`;
  const d = await api("/api-calls?limit=250");
  const byKind = d.stats.by_kind.map((k) => `${esc(k.kind)} ${num(k.calls)}`).join(" · ");
  const rows = d.calls.map((c) => `<tr data-search="${esc([c.method, c.path, c.kind, c.device_id, c.status].join(" ").toLowerCase())}">
    <td>${relTime(c.ts)}</td><td>${esc(c.method)}</td>
    <td class="mono wrap-cell">${esc(c.path)}</td>
    <td>${esc(c.kind)}</td><td class="mono">${esc(shortId(c.device_id))}</td>
    <td><span class="pill ${c.status >= 400 ? "fail" : "ok"}">${c.status}</span></td>
    <td>${c.ms}ms</td></tr>`).join("");
  $("tab-api").innerHTML = `<div class="card"><h3 class="hrow">Recent API calls ${filterBox("Filter by path, device, status…")}</h3>
    <div class="chart-legend" style="margin:0 0 10px">${esc(byKind || "no traffic yet")}</div>
    <div class="tbl-wrap"><table><thead><tr>
      <th>When</th><th>Method</th><th>Path</th><th>Kind</th><th>Device</th><th>Status</th><th>Latency</th>
    </tr></thead><tbody>${rows || `<tr><td colspan="7" class="empty">No API calls logged yet.</td></tr>`}</tbody></table></div></div>`;
  wireFilter("tab-api");
}

// ── tab routing ────────────────────────────────────────────────────────────
async function loadTab(tab) {
  activeTab = tab;
  try {
    if (tab === "overview") renderOverview(await api("/overview"));
    else if (tab === "frames") renderFrames(await api("/frames"));
    else if (tab === "generations") await loadGenerations();
    else if (tab === "gallery") await loadGallery();
    else if (tab === "accounts") await loadAccounts();
    else if (tab === "api") await loadApi();
    stamp();
  } catch (e) {
    if (e.message === "403") logout("Session expired — re-enter the token.");
    else $("tab-" + tab).innerHTML = `<p class="empty">Failed to load: ${esc(e.message)}</p>`;
  }
}

// ── wiring ──────────────────────────────────────────────────────────────
$("login-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const v = $("token").value.trim();
  $("login-err").textContent = v ? "Checking…" : "Enter the admin token.";
  if (v) unlock(v);
});
$("logout-btn").addEventListener("click", () => logout(""));
$("refresh-btn").addEventListener("click", () => loadTab(activeTab));
$("art-close").addEventListener("click", closeArt);
$("art-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeArt(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeArt(); });
document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + b.dataset.tab));
    loadTab(b.dataset.tab);
  }));

// Auto-unlock if a token is already in this session.
if (token) unlock(token); else { $("login").hidden = false; }
