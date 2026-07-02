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
// Full (unfiltered) frame + account lists that populate the global filter dropdowns.
let allFrames = [];
let allAccounts = [];
// The global filter bar state. `start`/`end` are the resolved YYYY-MM-DD window
// (derived from `range`, or the custom pickers cstart/cend). Sent on every load.
const filters = { range: "30d", start: "", end: "", cstart: "", cend: "",
                  status: "active", device: "", account: "", test: "" };

// ── helpers ─────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (n) => (n == null ? "—" : Number(n).toLocaleString());
const usd = (n) => (n == null ? "—" : "$" + Number(n).toFixed(2));
const shortId = (id) => (id || "").length > 10 ? (id || "").slice(-6) : (id || "—");
// A friendly, stable, unique frame id derived from the hardware MAC (the true
// unique id). Display name is separate and may be blank/duplicated.
const frameCode = (id) => id ? "INK-" + id.replace(/[^a-zA-Z0-9]/g, "").slice(-6).toUpperCase() : "—";
const displayName = (name) => name && name.trim() ? name : "Unnamed frame";

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
    await api("/overview");                      // validates the token
    sessionStorage.setItem(TOKEN_KEY, token);
    $("login").hidden = true; $("console").hidden = false;
    computeWindow();
    await loadSelectors();                        // fill dropdowns + render the bar
    await loadTab("overview");                    // first filtered load
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

// Per-section filtering: a free-text box + dropdown facets. Each <select.facet>
// declares data-facet (the row data-* attribute it filters); "range" compares a
// row's data-ts (epoch ms) to N days; "activation" maps a row's data-enabled.
const filterBox = (ph) => `<input class="filter" placeholder="${ph}" /> <span class="filter-count"></span>`;
function selectFacet(facet, options) {
  return `<select class="facet" data-facet="${facet}">` +
    options.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("") + `</select>`;
}
// ── global filter bar ───────────────────────────────────────────────────
// One bar under the tabs drives every section: a date window (server-side, so
// even the aggregate costs respond to it), plus frame-status / frame / account.
const RANGE_LABELS = { today: "Today", "7d": "Last 7 days", "30d": "Last 30 days",
                       all: "All time", custom: "Custom range" };
const isoDay = (d) => d.toISOString().slice(0, 10);
function computeWindow() {
  const today = new Date();
  const end = isoDay(today);
  const daysAgo = (n) => { const x = new Date(today); x.setUTCDate(x.getUTCDate() - n); return isoDay(x); };
  // "All time" uses a floor well before any data exists (rather than an empty
  // start) so the aggregate cost call gets a real window instead of its default.
  const w = { today: [end, end], "7d": [daysAgo(6), end], "30d": [daysAgo(29), end],
              all: ["2020-01-01", end], custom: [filters.cstart, filters.cend] }[filters.range] || ["", ""];
  [filters.start, filters.end] = w;
}
function rangeLabel() {
  if (filters.range === "custom")
    return filters.start && filters.end ? `${filters.start} → ${filters.end}` : "Custom range";
  return RANGE_LABELS[filters.range] || "Last 30 days";
}
function filterQS() {
  const p = [];
  const add = (k, v) => { if (v) p.push(k + "=" + encodeURIComponent(v)); };
  add("start", filters.start); add("end", filters.end);
  add("device", filters.device); add("account", filters.account); add("status", filters.status);
  add("test", filters.test);
  return p.join("&");
}
// Append the active filters to a request path (endpoints ignore params they
// don't declare, so it's safe to send the whole set everywhere).
function withF(path) {
  const q = filterQS();
  return q ? path + (path.includes("?") ? "&" : "?") + q : path;
}
const fbOpt = (v, l, sel) => `<option value="${esc(v)}"${sel ? " selected" : ""}>${esc(l)}</option>`;
function renderFilterBar() {
  const opts = (pairs, cur) => pairs.map(([v, l]) => fbOpt(v, l, cur === v)).join("");
  const frameOpts = fbOpt("", "All frames", !filters.device) +
    allFrames.map((f) => fbOpt(f.id, `${frameCode(f.id)} · ${displayName(f.name)}`, filters.device === f.id)).join("");
  const acctOpts = fbOpt("", "All accounts", !filters.account) +
    allAccounts.map((a) => fbOpt(a.id, a.email || shortId(a.id), filters.account === a.id)).join("");
  const custom = filters.range === "custom";
  $("filterbar").innerHTML = `
    <span class="fb-label">Range</span>
    <select id="fb-range">${opts([["today", "Today"], ["7d", "Last 7 days"], ["30d", "Last 30 days"], ["all", "All time"], ["custom", "Custom range"]], filters.range)}</select>
    <span class="fb-dates${custom ? "" : " hide"}" id="fb-dates">
      <input type="date" id="fb-start" value="${esc(filters.cstart)}" aria-label="Start date" />–<input type="date" id="fb-end" value="${esc(filters.cend)}" aria-label="End date" /></span>
    <span class="fb-label">Status</span>
    <select id="fb-status">${opts([["active", "Active"], ["", "Any status"], ["online", "Online"], ["sleep", "Sleep"], ["offline", "Offline"], ["deactivated", "Deactivated"]], filters.status)}</select>
    <span class="fb-label">Traffic</span>
    <select id="fb-test">${opts([["", "All"], ["real", "Real only"], ["test", "Test only"]], filters.test)}</select>
    <span class="fb-label">Frame</span>
    <select id="fb-frame">${frameOpts}</select>
    <span class="fb-label">Account</span>
    <select id="fb-account">${acctOpts}</select>
    <button class="btn ghost sm fb-reset" id="fb-reset" type="button">Reset</button>`;
  $("fb-range").addEventListener("change", (e) => { filters.range = e.target.value; renderFilterBar(); applyFiltersGlobal(); });
  $("fb-status").addEventListener("change", (e) => { filters.status = e.target.value; applyFiltersGlobal(); });
  $("fb-test").addEventListener("change", (e) => { filters.test = e.target.value; applyFiltersGlobal(); });
  $("fb-frame").addEventListener("change", (e) => { filters.device = e.target.value; applyFiltersGlobal(); });
  $("fb-account").addEventListener("change", (e) => { filters.account = e.target.value; applyFiltersGlobal(); });
  const s = $("fb-start"), en = $("fb-end");
  if (s) s.addEventListener("change", (e) => { filters.cstart = e.target.value; if (filters.range === "custom") applyFiltersGlobal(); });
  if (en) en.addEventListener("change", (e) => { filters.cend = e.target.value; if (filters.range === "custom") applyFiltersGlobal(); });
  $("fb-reset").addEventListener("click", () => {
    Object.assign(filters, { range: "30d", status: "active", device: "", account: "", cstart: "", cend: "", test: "" });
    renderFilterBar(); applyFiltersGlobal();
  });
}
function applyFiltersGlobal() { computeWindow(); loadTab(activeTab); }
async function loadSelectors() {
  try {
    const [f, a] = await Promise.all([api("/frames"), api("/accounts")]);
    allFrames = f.frames || []; allAccounts = a.accounts || [];
  } catch (_) { /* dropdowns are best-effort */ }
  renderFilterBar();
}

function applyFilters(sec) {
  const inp = sec.querySelector(".filter");
  const q = inp ? inp.value.trim().toLowerCase() : "";
  const selects = [...sec.querySelectorAll("select.facet")];
  const items = [...sec.querySelectorAll("[data-search]")];
  let n = 0;
  items.forEach((el) => {
    let show = !q || el.dataset.search.includes(q);
    for (const sel of selects) {
      if (!show || !sel.value) continue;
      const f = sel.dataset.facet;
      if (f === "range") {
        if (el.dataset.ts && Number(el.dataset.ts) < Date.now() - Number(sel.value) * 86400000) show = false;
      } else if (f === "activation") {
        if (sel.value === "active" && el.dataset.enabled === "0") show = false;
        if (sel.value === "off" && el.dataset.enabled !== "0") show = false;
      } else if (el.dataset[f] !== undefined && el.dataset[f] !== sel.value) {
        show = false;
      }
    }
    el.style.display = show ? "" : "none";
    if (show) n++;
  });
  const c = sec.querySelector(".filter-count");
  const active = q || selects.some((s) => s.value !== s.options[0].value);
  if (c) c.textContent = active ? `${n} of ${items.length}` : "";
}
function setupFilters(sectionId) {
  const sec = $(sectionId);
  const inp = sec.querySelector(".filter");
  if (inp) inp.addEventListener("input", () => applyFilters(sec));
  sec.querySelectorAll("select.facet").forEach((s) => s.addEventListener("change", () => applyFilters(sec)));
  applyFilters(sec);
}
const tsOf = (iso) => iso ? Date.parse(iso) || 0 : 0;

// Interest chips shared by the frames table (capped), the frame popup, and the
// gallery popup. Returns "" when there are none (callers supply their own dash).
function interestChips(o, limit) {
  const chips = [
    ...(o.interests_preset || []).map((t) => [o.interests_default ? "default" : "preset", t]),
    ...(o.interests_custom || []).map((t) => ["custom", t]),
    ...(o.holidays || []).map((t) => ["holi", t]),
  ];
  if (!chips.length) return "";
  const shown = limit ? chips.slice(0, limit) : chips;
  let html = shown.map(([c, t]) => `<span class="ichip ${c}">${esc(t)}</span>`).join("");
  if (limit && chips.length > limit) html += `<span class="ichip more">+${chips.length - limit}</span>`;
  return html;
}

// ── frame detail popup ────────────────────────────────────────────────────
let framesData = [];
// Build one card section: a titled card with a label/value grid; "" if empty.
function section(title, pairs) {
  const rows = pairs.filter(([, v]) => v != null && v !== "")
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
  return rows ? `<div class="fcard"><h4>${esc(title)}</h4><dl class="detail">${rows}</dl></div>` : "";
}
function openFrame(id) {
  const fr = framesData.find((f) => f.id === id); if (!fr) return;
  $("frame-title").textContent = displayName(fr.name);
  const wake = `${String(fr.wake_hour).padStart(2, "0")}:${String(fr.wake_minute).padStart(2, "0")} · ${esc(fr.schedule || "")}`;
  $("frame-detail").innerHTML =
    section("Identity", [
      ["Display name", esc(displayName(fr.name))],
      ["Frame ID", `<span class="mono">${esc(frameCode(fr.id))}</span>`],
      ["Hardware ID", `<span class="mono">${esc(fr.id)}</span>`],
      ["Account", fr.account_id ? `<span class="mono">${esc(fr.account_id)}</span>${fr.account_suspended ? ` <span class="pill fail">suspended</span>` : ""}` : "unpaired"],
      ["Created", fr.created_at ? fr.created_at.slice(0, 10) : ""],
    ]) +
    section("Status", [
      ["State", statePill(fr.state) + (fr.enabled === false ? ` <span class="pill fail">deactivated</span>` : "") + testPill(fr.test)],
      ["Test frame", fr.test ? (fr.account_is_test && !fr.is_test ? "yes — via test account" : "yes") : "no"],
      ["Battery", fr.battery != null ? fr.battery.toFixed(2) + " V" : "—"],
      ["Wi-Fi", wifiLabel(fr.wifi_rssi)],
      ["Firmware", esc(fr.fw_version || "—") + (fr.update_available ? ` → ${esc(fr.latest_fw)} available` : "")],
      ["Last seen", fr.last_seen ? relTime(fr.last_seen) : "never"],
      ["OTA error", fr.ota_error ? `<span class="pill fail">${esc(fr.ota_error)}</span>` : ""],
    ]) +
    section("Schedule & display", [
      ["Orientation", esc(fr.orientation || "—")],
      ["Update time", wake],
      ["Sleep", fr.sleep_after_minutes ? fr.sleep_after_minutes + " min" : "always on"],
    ]) +
    section("Content", [
      ["Interests", interestChips(fr)],
      ["Last artwork", fr.last_art_date ? `${esc(fr.last_art_date)} — ${esc(fr.last_art_caption || "")}` : "none"],
    ]);
  const nav = `<div class="modal-nav">
    <button class="rowbtn" data-nav="generations" data-q="${esc(fr.id)}">Generations & stats ›</button>
    <button class="rowbtn" data-nav="gallery" data-q="${esc(fr.id)}">Gallery ›</button>
    <button class="rowbtn" data-nav="api" data-q="${esc(fr.id)}">API log ›</button></div>`;
  const frameBtn = `<button class="rowbtn ${fr.enabled === false ? "" : "danger"}" data-fa="frame" data-id="${esc(fr.id)}" data-to="${fr.enabled === false ? "1" : "0"}">${fr.enabled === false ? "Activate frame" : "Deactivate frame"}</button>`;
  const acctBtn = fr.account_id ? `<button class="rowbtn ${fr.account_suspended ? "" : "danger"}" data-fa="acct" data-id="${esc(fr.account_id)}" data-to="${fr.account_suspended ? "0" : "1"}">${fr.account_suspended ? "Reactivate account" : "Deactivate account"}</button>` : "";
  const testBtn = `<button class="rowbtn" data-ftest="1" data-id="${esc(fr.id)}" data-to="${fr.is_test ? "0" : "1"}">${fr.is_test ? "Unmark test frame" : "Mark as test frame"}</button>`;
  $("frame-actions").innerHTML = nav + frameBtn + testBtn + acctBtn;
  $("frame-actions").querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => openTabFor(b.dataset.nav, b.dataset.q)));
  $("frame-actions").querySelectorAll("[data-fa]").forEach((b) => b.addEventListener("click", onFrameModalAction));
  $("frame-actions").querySelectorAll("[data-ftest]").forEach((b) => b.addEventListener("click", onFrameTestToggle));
  $("frame-modal").hidden = false;
}
const closeFrame = () => { $("frame-modal").hidden = true; };
async function onFrameTestToggle(e) {
  const b = e.currentTarget, to = b.dataset.to === "1";
  b.disabled = true;
  try {
    await apiSend(`/frames/${encodeURIComponent(b.dataset.id)}/test?test=${to}`, "POST");
    closeFrame(); await loadSelectors(); await loadTab("frames");
  } catch (err) {
    if (err.message !== "403") { alert("Action failed: " + err.message); b.disabled = false; }
  }
}
async function onFrameModalAction(e) {
  const b = e.currentTarget, to = b.dataset.to === "1", frame = b.dataset.fa === "frame";
  if (!to) {  // deactivating — confirm
    const msg = frame ? "Deactivate this frame? It stops updating until reactivated."
      : "Deactivate this account? Every frame on it stops updating until reactivated.";
    if (!confirm(msg)) return;
  }
  b.disabled = true;
  try {
    if (frame) await apiSend(`/frames/${encodeURIComponent(b.dataset.id)}/enable?enabled=${to}`, "POST");
    else await apiSend(`/accounts/${encodeURIComponent(b.dataset.id)}/suspend?suspended=${to}`, "POST");
    closeFrame();
    await loadSelectors();
    await loadTab("frames");
  } catch (err) {
    if (err.message !== "403") { alert("Action failed: " + err.message); b.disabled = false; }
  }
}

// ── gallery preview lightbox ──────────────────────────────────────────────
let galleryItems = [];
function openArt(i) {
  const it = galleryItems[i]; if (!it) return;
  $("art-title").textContent = `${it.device_name || frameCode(it.device_id)} · ${it.date}`;
  const img = $("art-img"), body = img.closest(".modal-body");
  // Prefer the full-detail original (saved upright — no rotation); fall back to
  // the rotated panel PNG when the original was pruned / predates the feature.
  if (it.image_full_url) {
    body.classList.remove("portrait");
    img.onerror = () => {
      img.onerror = null;
      body.classList.toggle("portrait", it.orientation === "portrait");
      img.src = BASE + it.image_url;
    };
    img.src = BASE + it.image_full_url;
  } else {
    img.onerror = null;
    body.classList.toggle("portrait", it.orientation === "portrait");
    img.src = BASE + it.image_url;
  }
  const row = (label, val, pre) => !val ? "" :
    `<dt>${esc(label)}</dt><dd>${pre ? `<pre>${esc(val)}</pre>` : esc(val)}</dd>`;
  $("art-detail").innerHTML =
    row("Event", it.event_caption) +
    row("Final description", it.event_text_en) +
    row("Hebrew", it.event_text_he) +
    row("Iconic visual", it.event_visual) +
    row("Weather", it.weather_summary) +
    row("Orientation", it.orientation) +
    (interestChips(it) ? `<dt>Interests</dt><dd>${interestChips(it)}</dd>` : "") +
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
    bars += `<rect class="bar" x="${x + gap / 2}" y="${y}" width="${bw - gap}" height="${h}" rx="2"><title>${esc(d.label)}: ${num(d.value)}</title></rect>`;
    if (errKey && d[errKey]) {
      const eh = (d[errKey] / max) * (H - 34);
      bars += `<rect class="bar err" x="${x + gap / 2}" y="${H - 18 - eh}" width="${bw - gap}" height="${eh}" rx="2"></rect>`;
    }
    if (i % step === 0)
      labels += `<text x="${x + bw / 2}" y="${H - 4}" font-size="10" fill="#8b8473" text-anchor="middle">${esc(d.label)}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line class="axis" x1="${pad}" y1="${H - 18}" x2="${W - pad}" y2="${H - 18}"/>${bars}${labels}</svg>`;
}

// ── renderers ─────────────────────────────────────────────────────────────
function kpi(label, value, sub, accent) {
  return `<div class="kpi${accent ? " " + accent : ""}"><div class="label">${esc(label)}</div>
    <div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}
function costCard(c) {
  c = c || {};
  const real = c.openai_actual || {};
  const cstat = (label, val, sub) =>
    `<div class="cstat"><div class="cs-label">${esc(label)}</div><div class="cs-val">${val}</div>${sub ? `<div class="cs-sub">${sub}</div>` : ""}</div>`;
  const brk = (c.items || []).map((it) =>
    `<span>${esc(it.type.split(" (")[0])} <b>${usd(it.usd)}</b> <i>${num(it.calls)}</i></span>`).join("");
  const lines = real.available && (real.by_line_item || []).length
    ? `<details class="cost-lines"><summary>OpenAI line items</summary><dl>${real.by_line_item.map((li) =>
        `<dt>${esc(li.name)}</dt><dd class="mono">${usd(li.usd)}</dd>`).join("")}</dl></details>`
    : "";
  const scoped = real.scope === "key";
  const testEst = c.test_estimate_usd || 0;
  const estSub = testEst > 0 ? `real ${usd(c.real_estimate_usd)} · test ${usd(testEst)}` : "";
  const note = real.available
    ? `Actual is ${scoped ? "the Ink generation key's" : "org-wide"} OpenAI billing (includes test frames — the key is shared), cached hourly. The estimate splits real vs test from tracked runs.`
    : `Actual OpenAI $ needs an Admin key — ${esc(real.note || "set OPENAI_ADMIN_KEY")}. Estimate is from tracked calls.`;
  return `<div class="card"><h3>Cost · ${esc(rangeLabel())}</h3>
    <div class="coststats">
      ${cstat("Est. OpenAI", usd(c.total_usd), estSub)}
      ${cstat("Actual OpenAI", real.available ? usd(real.total_usd) : "—", real.available ? (scoped ? "Ink key" : "org-wide") : "")}
      ${cstat("Fly infra", usd(c.fly_monthly_usd) + `<small>/mo</small>`)}
    </div>
    <div class="costbreak">${brk}</div>
    ${lines}
    <p class="hint">${note}</p></div>`;
}

function renderOverview(d) {
  const g = d.generation, f = d.frames, a = d.api.totals;
  const rate = g.success_rate == null ? "—" : Math.round(g.success_rate * 100) + "%";
  const genSeries = g.by_day.map((r) => ({ label: dayLabel(r.day), value: r.runs || 0, err: (r.runs || 0) - (r.ok || 0) }));
  const costSeries = g.by_day.map((r) => ({ label: dayLabel(r.day), value: Math.round((r.cost || 0) * 100) / 100 }));
  const apiSeries = d.api.by_day.map((r) => ({ label: dayLabel(r.day), value: r.calls || 0, err: r.errors || 0 }));
  const deact = f.deactivated ? ` · ${f.deactivated} deactivated` : "";
  $("tab-overview").innerHTML = `
    <h3 class="section-title">Fleet</h3>
    <div class="kpis">
      ${kpi("Active frames", num(f.active_48h), "online or asleep · 48h", f.active_48h ? "good" : "")}
      ${kpi("Frames", num(f.total), `${num(f.active)} active${esc(deact)}`)}
      ${kpi("Accounts", num(d.accounts))}
      ${kpi("Images made", num(d.artwork.ready))}
      ${kpi("Updates ready", num(f.update_available), `fw ${esc(d.latest_fw || "—")}`, f.update_available ? "warn" : "")}
    </div>
    <h3 class="section-title">Generation · ${esc(rangeLabel())}</h3>
    <div class="kpis">
      ${kpi("Success rate", rate, `${num(g.ok)}/${num(g.runs)} runs`, g.runs && g.failed ? "warn" : (g.runs ? "good" : ""))}
      ${kpi("Est. spend", usd(g.cost_usd), "images · text · search")}
      ${kpi("Failures", num(g.failed), `${num(g.retries)} retries`, g.failed ? "bad" : "")}
      ${kpi("Avg gen time", g.avg_ms ? (g.avg_ms / 1000).toFixed(1) + "s" : "—")}
    </div>
    <div class="grid2">
      <div class="card"><h3>Generations / day</h3>${barChart(genSeries, { errKey: "err" })}
        <div class="chart-legend"><span><i style="background:var(--ink)"></i>ok</span><span><i style="background:var(--danger)"></i>failed</span></div></div>
      <div class="card"><h3>Estimated cost / day</h3>${barChart(costSeries)}
        <div class="chart-legend"><span>USD per day</span></div></div>
    </div>
    ${costCard(d.costs)}
    <h3 class="section-title">Traffic · ${esc(rangeLabel())}</h3>
    <div class="card"><h3>API calls / day</h3>${barChart(apiSeries, { errKey: "err" })}
      <div class="chart-legend"><span><i style="background:var(--ink)"></i>calls ${num(a.calls)}</span><span><i style="background:var(--danger)"></i>errors ${num(a.errors)}</span><span>avg ${a.avg_ms ? Math.round(a.avg_ms) + "ms" : "—"}</span></div></div>`;
}

function statePill(s) { return `<span class="pill ${s}">${s}</span>`; }
const testPill = (on) => on ? ` <span class="pill test">test</span>` : "";

function renderFrames(d) {
  framesData = d.frames;
  const rows = d.frames.map((fr) => {
    const upd = fr.update_available ? ` <span class="pill manual">update</span>` : "";
    const off = fr.enabled === false ? ` <span class="pill fail">deactivated</span>` : "";
    const otaBad = fr.ota_error ? ` <span class="pill fail" title="${esc(fr.ota_error)}">OTA</span>` : "";
    const susp = fr.account_suspended ? ` <span class="pill fail">susp</span>` : "";
    const s = [fr.name, fr.id, fr.state, fr.fw_version, fr.account_id, fr.last_art_caption, fr.ota_error,
      ...(fr.interests_preset || []), ...(fr.interests_custom || [])].join(" ").toLowerCase();
    return `<tr class="frow" data-fid="${esc(fr.id)}" data-search="${esc(s)}" data-state="${esc(fr.state)}" data-enabled="${fr.enabled === false ? "0" : "1"}">
      <td>${statePill(fr.state)}${off}${otaBad}${testPill(fr.test)}</td>
      <td><span class="linkname">${esc(displayName(fr.name))}</span>
        <div class="mono" style="color:var(--muted)">${esc(frameCode(fr.id))}</div></td>
      <td>${relTime(fr.last_seen)}</td>
      <td>${esc(fr.fw_version || "—")}${upd}</td>
      <td>${fr.last_art_date ? esc(dayLabel(fr.last_art_date)) : "—"}<div class="wrap-cell" style="font-size:11px">${esc((fr.last_art_caption || "").slice(0, 70))}</div></td>
      <td class="mono">${fr.account_id ? esc(shortId(fr.account_id)) + susp : "—"}</td></tr>`;
  }).join("");
  $("tab-frames").innerHTML = `<div class="card">
    <h3 class="hrow">All frames <span class="filter-count-h">(${d.frames.length})</span> ${filterBox("Filter frames…")}</h3>
    <p class="chart-legend" style="margin:0 0 10px">Click a row for full details + actions. Use the Status filter above to include deactivated frames. (Battery, Wi-Fi, interests, schedule &amp; sleep are in the popup.)</p>
    <div class="tbl-wrap"><table><thead><tr>
      <th>State</th><th>Name</th><th>Last seen</th><th>Firmware</th><th>Last artwork</th><th>Account</th>
    </tr></thead><tbody>${rows || `<tr><td colspan="6" class="empty">No frames yet.</td></tr>`}</tbody></table></div></div>`;
  $("tab-frames").querySelectorAll("tr.frow").forEach((tr) => tr.addEventListener("click", () => openFrame(tr.dataset.fid)));
  setupFilters("tab-frames");
}

async function loadGenerations() {
  $("tab-generations").innerHTML = `<p class="loading">Loading…</p>`;
  const d = await api(withF("/generations?limit=300"));
  const rows = d.runs.map((r) => `<tr data-ts="${tsOf(r.created_at)}" data-trigger="${esc(r.trigger)}" data-result="${r.ok ? "ok" : "fail"}" data-search="${esc([r.device_id, r.trigger, r.ok ? "ok" : "fail failed", r.provider, r.phase, r.error].join(" ").toLowerCase())}">
    <td>${relTime(r.created_at)}</td>
    <td class="mono">${esc(frameCode(r.device_id))}${testPill(r.test)}</td>
    <td><span class="pill ${r.trigger}">${esc(r.trigger)}</span></td>
    <td><span class="pill ${r.ok ? "ok" : "fail"}">${r.ok ? "ok" : "fail"}</span></td>
    <td>${r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + "s" : "—"}</td>
    <td>${r.retries || 0}</td>
    <td>${usd(r.cost_usd)}</td>
    <td>${r.image_calls}i · ${r.text_calls}t · ${r.search_calls}s</td>
    <td>${esc(r.provider || "—")}</td>
    <td class="wrap-cell">${r.ok ? "" : `<b>${esc(r.phase || "?")}</b> ${esc(r.error || "")}`}</td></tr>`).join("");
  $("tab-generations").innerHTML = `<div class="card">
    <h3 class="hrow">Generation runs <span class="filter-count-h">(${d.runs.length})</span>
      ${selectFacet("trigger", [["", "Any trigger"], ["auto", "Auto"], ["manual", "Manual"]])}
      ${selectFacet("result", [["", "Any result"], ["ok", "OK"], ["fail", "Failed"]])} ${filterBox("Filter runs…")}</h3>
    <div class="tbl-wrap"><table><thead><tr>
      <th>When</th><th>Device</th><th>Trigger</th><th>Result</th><th>Duration</th><th>Retries</th>
      <th>Cost</th><th>Calls</th><th>Provider</th><th>Error</th>
    </tr></thead><tbody>${rows || `<tr><td colspan="10" class="empty">No generation runs recorded yet.</td></tr>`}</tbody></table></div></div>`;
  setupFilters("tab-generations");
}

async function loadGallery() {
  $("tab-gallery").innerHTML = `<p class="loading">Loading…</p>`;
  const d = await api(withF("/gallery?limit=150"));
  galleryItems = d.items;
  const shots = d.items.map((it, i) => {
    const search = [it.device_name, it.device_id, it.date, it.caption, it.event_visual, it.image_prompt].join(" ").toLowerCase();
    return `<div class="shot ${it.orientation === "portrait" ? "portrait" : "landscape"}" data-i="${i}" data-ts="${tsOf(it.created_at || it.date)}" data-search="${esc(search)}">
      <img loading="lazy" src="${esc(BASE + it.image_url)}" alt="${esc(it.caption || "")}" />
      <div class="cap"><div class="d">${esc(it.device_name || frameCode(it.device_id))} · ${esc(it.date)}${testPill(it.test)}</div>
        <div class="c">${esc(it.caption || "—")}</div></div></div>`;
  }).join("");
  $("tab-gallery").innerHTML = `<div class="card"><h3 class="hrow">Gallery <span class="filter-count-h">(${d.items.length})</span> ${filterBox("Filter by device, event, prompt…")}</h3>
    ${shots ? `<div class="gallery">${shots}</div>` : `<p class="empty">No images yet.</p>`}</div>`;
  $("tab-gallery").querySelectorAll(".shot").forEach((el) =>
    el.addEventListener("click", () => openArt(Number(el.dataset.i))));
  setupFilters("tab-gallery");
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
    return `<tr data-astatus="${st}" data-search="${esc([a.email, a.id, st, a.is_test ? "test" : ""].join(" ").toLowerCase())}">
      <td>${esc(a.email || "—")}<div class="mono" style="color:var(--muted)">${esc(shortId(a.id))}</div></td>
      <td><span class="pill ${pill}">${st}</span>${testPill(a.is_test)}</td>
      <td>${a.device_count}</td>
      <td>${a.last_active ? relTime(a.last_active) : "never"}</td>
      <td>${a.created_at ? dayLabel(a.created_at.slice(0, 10)) : "—"}</td>
      <td>${a.has_own_key ? "own key" : "platform"}</td>
      <td style="text-align:right">
        <button class="rowbtn" data-act="test" data-id="${esc(a.id)}" data-to="${a.is_test ? "0" : "1"}">${a.is_test ? "Untag test" : "Mark test"}</button>
        <button class="rowbtn" data-act="suspend" data-id="${esc(a.id)}" data-to="${a.suspended ? "0" : "1"}">${a.suspended ? "Reactivate" : "Deactivate"}</button>
        <button class="rowbtn danger" data-act="delete" data-id="${esc(a.id)}" data-label="${esc(a.email || shortId(a.id))}">Delete</button>
      </td></tr>`;
  }).join("");
  $("tab-accounts").innerHTML = `<div class="card">
    <h3 class="hrow">Accounts <span class="filter-count-h">(${d.accounts.length})</span>
      ${selectFacet("astatus", [["", "Any status"], ["active", "Active"], ["inactive", "Inactive"], ["suspended", "Suspended"]])}
      ${d.accounts.filter((a) => a.device_count === 0).length ? `<button class="rowbtn danger" id="purge-empty">Delete ${d.accounts.filter((a) => a.device_count === 0).length} empty</button>` : ""}
      ${filterBox("Filter accounts…")}</h3>
    <p class="chart-legend" style="margin:0 0 10px">Empty = anonymous accounts the app created on first launch that never paired a frame. Deactivate blocks the app + scheduler (reversible); Delete removes the account and unbinds its frames (permanent).</p>
    <div class="tbl-wrap"><table><thead><tr>
      <th>Account</th><th>Status</th><th>Frames</th><th>Last active</th><th>Created</th><th>Key</th><th></th>
    </tr></thead><tbody>${rows || `<tr><td colspan="7" class="empty">No accounts.</td></tr>`}</tbody></table></div></div>`;
  $("tab-accounts").querySelectorAll(".rowbtn").forEach((b) => b.addEventListener("click", onAccountAction));
  const purge = $("purge-empty");
  if (purge) purge.addEventListener("click", async () => {
    const n = d.accounts.filter((a) => a.device_count === 0).length;
    if (!confirm(`Delete ${n} empty account${n === 1 ? "" : "s"} (no frames paired)? This can't be undone.`)) return;
    purge.disabled = true;
    try { await apiSend("/accounts/purge-empty", "POST"); await loadSelectors(); await loadTab("accounts"); }
    catch (err) { if (err.message !== "403") { alert("Purge failed: " + err.message); purge.disabled = false; } }
  });
  setupFilters("tab-accounts");
}
async function onAccountAction(e) {
  const b = e.currentTarget, id = b.dataset.id;
  if (b.dataset.act === "delete") {
    if (!confirm(`Delete account "${b.dataset.label}"?\n\nIts frames are unbound (become re-pairable) and the account is removed. This can't be undone.`)) return;
  }
  b.disabled = true;
  try {
    if (b.dataset.act === "test") await apiSend(`/accounts/${encodeURIComponent(id)}/test?test=${b.dataset.to === "1"}`, "POST");
    else if (b.dataset.act === "suspend") await apiSend(`/accounts/${encodeURIComponent(id)}/suspend?suspended=${b.dataset.to === "1"}`, "POST");
    else await apiSend(`/accounts/${encodeURIComponent(id)}`, "DELETE");
    await loadSelectors();
    await loadAccounts();
  } catch (err) {
    if (err.message !== "403") { alert("Action failed: " + err.message); b.disabled = false; }
  }
}

async function loadApi() {
  $("tab-api").innerHTML = `<p class="loading">Loading…</p>`;
  const d = await api(withF("/api-calls?limit=250"));
  const byKind = d.stats.by_kind.map((k) => `${esc(k.kind)} ${num(k.calls)}`).join(" · ");
  const rows = d.calls.map((c) => `<tr data-ts="${tsOf(c.ts)}" data-kind="${esc(c.kind)}" data-search="${esc([c.method, c.path, c.kind, c.device_id, c.status].join(" ").toLowerCase())}">
    <td>${relTime(c.ts)}</td><td>${esc(c.method)}</td>
    <td class="mono wrap-cell">${esc(c.path)}</td>
    <td>${esc(c.kind)}</td><td class="mono">${esc(frameCode(c.device_id))}</td>
    <td><span class="pill ${c.status >= 400 ? "fail" : "ok"}">${c.status}</span></td>
    <td>${c.ms}ms</td></tr>`).join("");
  $("tab-api").innerHTML = `<div class="card"><h3 class="hrow">Recent API calls ${selectFacet("kind", [["", "All kinds"], ["app", "App"], ["media", "Media"], ["firmware", "Firmware"]])} ${filterBox("Filter by path, device, status…")}</h3>
    <div class="chart-legend" style="margin:0 0 10px">${esc(byKind || "no traffic yet")}</div>
    <div class="tbl-wrap"><table><thead><tr>
      <th>When</th><th>Method</th><th>Path</th><th>Kind</th><th>Device</th><th>Status</th><th>Latency</th>
    </tr></thead><tbody>${rows || `<tr><td colspan="7" class="empty">No API calls logged yet.</td></tr>`}</tbody></table></div></div>`;
  setupFilters("tab-api");
}

// ── tab routing ────────────────────────────────────────────────────────────
let pendingFilter = "";   // set when jumping to a tab pre-filtered for one frame
async function loadTab(tab) {
  activeTab = tab;
  try {
    if (tab === "overview") renderOverview(await api(withF("/overview")));
    else if (tab === "frames") renderFrames(await api(withF("/frames")));
    else if (tab === "generations") await loadGenerations();
    else if (tab === "gallery") await loadGallery();
    else if (tab === "accounts") await loadAccounts();
    else if (tab === "api") await loadApi();
    if (pendingFilter) {
      const inp = $("tab-" + tab).querySelector(".filter");
      if (inp) { inp.value = pendingFilter; applyFilters($("tab-" + tab)); }
      pendingFilter = "";
    }
    stamp();
  } catch (e) {
    if (e.message === "403") logout("Session expired — re-enter the token.");
    else $("tab-" + tab).innerHTML = `<p class="empty">Failed to load: ${esc(e.message)}</p>`;
  }
}
function switchTab(tab) {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + tab));
  loadTab(tab);
}
// Jump to a tab pre-filtered to a frame (used by the frame popup's view links).
function openTabFor(tab, query) { pendingFilter = query; closeFrame(); switchTab(tab); }

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
$("frame-close").addEventListener("click", closeFrame);
$("frame-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeFrame(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeArt(); closeFrame(); } });
document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => switchTab(b.dataset.tab)));

// Auto-unlock if a token is already in this session.
if (token) unlock(token); else { $("login").hidden = false; }
