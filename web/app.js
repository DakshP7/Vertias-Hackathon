"use strict";
/* CellIQ built-in UI (local use). Plain JS, no build step.
   All server data is inserted with textContent / text nodes, never innerHTML. */

const DISCLAIMER = "Research prototype. Not a diagnosis. All patients are fake demo records. A qualified doctor must review every result.";
const root = document.getElementById("app");

// ---------- tiny helpers ----------
const store = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* ignore */ } },
  del(k) { try { sessionStorage.removeItem(k); } catch { /* ignore */ } },
};
let token = store.get("tok");
let me = null;
try { me = JSON.parse(store.get("me") || "null"); } catch { me = null; }

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  let value;
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "value") value = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat(Infinity)) {
    if (c == null || c === false) continue;
    e.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  if (value !== undefined) e.value = value;
  return e;
}

let toastTimer;
function toast(msg, isErr) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "on" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ""; }, isErr ? 5000 : 2500);
}

function fmtDate(iso) {
  const d = new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(String(iso)) ? iso : iso + "Z");
  return isNaN(d) ? "" : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

async function api(path, { method = "GET", json, form, raw } = {}) {
  const headers = {};
  if (token) headers.Authorization = "Bearer " + token;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  else if (form) body = form;
  const r = await fetch(path, { method, headers, body });
  if (r.status === 401 && path !== "/auth/login") { logout(); throw new Error("Session expired. Please sign in again."); }
  if (!r.ok) {
    let msg = r.statusText || "Request failed";
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail
        : Array.isArray(j.detail) ? j.detail.map(d => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ")
        : msg;
    } catch { /* keep default */ }
    throw new Error(msg);
  }
  return raw ? r : r.json();
}

// Images and PDFs need the auth header, so fetch them as blobs.
async function blobUrl(path) {
  const r = await api(path, { raw: true });
  return URL.createObjectURL(await r.blob());
}
function imageBox(path, alt, emptyText) {
  const box = h("div", { class: "imgbox" });
  if (!path) { box.append(h("div", { class: "none" }, emptyText || "No image")); return box; }
  box.append(h("div", { class: "none" }, "Loading..."));
  blobUrl(path).then(u => { box.replaceChildren(h("img", { src: u, alt })); })
    .catch(e => { box.replaceChildren(h("div", { class: "none" }, e.message)); });
  return box;
}

function cleanName(n) { return String(n || "").replace(/\s*\([^)]*\)\s*$/, "").trim(); }
function can(...roles) { return me && roles.includes(me.role); }

function logout() {
  token = null; me = null; store.del("tok"); store.del("me");
  location.hash = "#/";
  render();
}

// ---------- shared UI pieces ----------
function priorityBadge(p) {
  if (!p) return h("span", { class: "badge na" }, "Not assessed");
  const cls = p === "HIGH PRIORITY" ? "high" : p === "PRIORITY REVIEW" ? "review" : "routine";
  return h("span", { class: "badge " + cls }, p);
}

function gauge(score, thrReview, thrHigh) {
  // Semi-circle gauge: green / amber / red zones plus a needle. Only numbers are used in the markup.
  const R = 80, cx = 100, cy = 100;
  const pt = (v, r = R) => { const a = Math.PI * (1 - v); return [cx + r * Math.cos(a), cy - r * Math.sin(a)]; };
  const arc = (v0, v1, color) => {
    const [x0, y0] = pt(v0), [x1, y1] = pt(v1);
    return `<path d="M ${x0.toFixed(1)} ${y0.toFixed(1)} A ${R} ${R} 0 0 1 ${x1.toFixed(1)} ${y1.toFixed(1)}" stroke="${color}" stroke-width="16" fill="none"/>`;
  };
  const [nx, ny] = pt(Math.min(1, Math.max(0, score)), 62);
  const pct = Math.round(score * 100);
  const wrap = h("div", { class: "gauge" });
  wrap.innerHTML =
    `<svg viewBox="0 0 200 125" width="240" role="img" aria-label="Risk score ${pct} percent">` +
    arc(0, thrReview, "#2E7D32") + arc(thrReview, thrHigh, "#E8A317") + arc(thrHigh, 1, "#C62828") +
    `<line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>` +
    `<circle cx="${cx}" cy="${cy}" r="6" fill="currentColor"/>` +
    `<text x="100" y="122" text-anchor="middle" font-size="18" font-weight="700" fill="currentColor">${pct}%</text></svg>`;
  return wrap;
}

function field(label, input) { return h("div", { class: "field" }, h("label", {}, label), input); }

// ---------- layout ----------
const NAV_SVG = {  // constant icon markup only
  home: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3 2 12h3v8h5v-5h4v5h5v-8h3z"/></svg>',
  people: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-3.6 3-6 7-6s7 2.4 7 6z"/><circle cx="17.5" cy="9" r="2.8"/><path d="M17 14c3 0 5 1.8 5 4.5V20h-4.5c0-2.3-.8-4.2-2.2-5.4.5-.4 1-.6 1.7-.6z"/></svg>',
  cloud: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M7 18a5 5 0 0 1-.6-9.96A6 6 0 0 1 18 9.5 4.3 4.3 0 0 1 17.5 18H13v-4l1.6 1.6 1.4-1.4L12 10l-4 4 1.4 1.4L11 14v4z"/></svg>',
  doc: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 3h8l5 5v13H6z"/><path d="M9 12h7M9 16h7M9 8h3"/></svg>',
  clock: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5M12 7.5V12l3 2"/></svg>',
  ct: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/></svg>',
  bars: '<svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><rect x="3" y="12" width="4" height="9"/><rect x="10" y="4" width="4" height="17"/><rect x="17" y="9" width="4" height="12"/></svg>',
  mail: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 7 9-7M3 18l6-6M21 18l-6-6"/></svg>',
  lock: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3M12 15v3"/></svg>',
  people2: '<svg width="46" height="38" viewBox="0 0 48 40" fill="#3bb4b0"><circle cx="24" cy="12" r="8"/><path d="M8 38c0-9 7-14 16-14s16 5 16 14z"/><circle cx="8" cy="16" r="5" opacity=".8"/><circle cx="40" cy="16" r="5" opacity=".8"/></svg>',
  lungs: '<svg width="44" height="40" viewBox="0 0 48 44" fill="#1c7a6e"><path d="M22 3h4v14c0 3 2 5 4 7l-3 2-3-4-3 4-3-2c2-2 4-4 4-7zM18 14C9 16 4 28 4 38c0 4 4 5 8 4 5-1 8-4 8-9V20c0-3-1-5-2-6zM30 14c9 2 14 14 14 24 0 4-4 5-8 4-5-1-8-4-8-9V20c0-3 1-5 2-6z"/></svg>',
  clockO: '<svg width="42" height="42" viewBox="0 0 48 48"><circle cx="24" cy="24" r="19" fill="none" stroke="#e56432" stroke-width="5"/><circle cx="24" cy="24" r="12" fill="#e56432" opacity=".25"/><path d="M24 14v10l7 4" stroke="#e56432" stroke-width="4" fill="none" stroke-linecap="round"/></svg>',
  check: '<svg width="40" height="40" viewBox="0 0 48 48"><rect x="5" y="5" width="38" height="38" rx="7" fill="none" stroke="#039244" stroke-width="5"/><path d="m13 25 8 8 15-17" stroke="#039244" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  cloudUp: '<svg width="86" height="62" viewBox="0 0 86 62" fill="#fff"><path d="M22 58C10 58 2 50 2 40c0-8 5-14 12-16 2-12 12-20 25-20 11 0 20 7 23 16 12 0 22 8 22 20 0 10-8 18-18 18z"/><path d="M43 52V32l-8 8-5-5 18-18 18 18-5 5-8-8v20z" fill="#012f46"/></svg>',
  calendar: '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#092c40" stroke-width="1.8"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/><g fill="#092c40" stroke="none"><circle cx="8" cy="14" r="1"/><circle cx="12" cy="14" r="1"/><circle cx="16" cy="14" r="1"/><circle cx="8" cy="17.5" r="1"/><circle cx="12" cy="17.5" r="1"/><circle cx="16" cy="17.5" r="1"/></g></svg>',
  longArrow: '<svg width="46" height="26" viewBox="0 0 46 26" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 13h40M31 3l11 10-11 10"/></svg>',
  arrowR: '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 12h15M13 6l6 6-6 6"/></svg>',
};
function svgEl(name) { const s = h("span", { style: "display:inline-flex" }); s.innerHTML = NAV_SVG[name]; return s; }

function personSvg(bg, fg) {
  const s = h("span", { style: "display:contents" });
  s.innerHTML = `<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="14" r="7.5" fill="${fg}"/><path d="M5 38c0-9 6.5-14 15-14s15 5 15 14z" fill="${fg}"/></svg>`;
  return s;
}
function shortName(n) {  // "Dr. Sharma" style label for the sidebar
  const parts = cleanName(n).replace(/^Dr\.?\s*/i, "").split(/\s+/);
  return "Dr. " + parts[parts.length - 1];
}

function shell(content, active) {
  const link = (href, text, key, ic) => h("a", { href, class: active === key ? "on" : "" }, svgEl(ic), text);
  const roleLabel = me.role.charAt(0).toUpperCase() + me.role.slice(1);
  const av = h("div", { class: "avatar" }); av.append(personSvg("#9b9b9b", "#d9d1bd"));
  return [
    h("div", { class: "shell" },
      h("aside", { class: "sidebar" },
        h("a", { class: "logo", href: "#/" }, h("img", { src: "img/logo-light.png", alt: "CellIQ" })),
        h("nav", {},
          link("#/", "Dashboard", "dashboard", "home"),
          link("#/patients", "Patient Profiles", "patients", "people"),
          can("radiologist") ? link("#/upload", "Upload Scan", "upload", "cloud") : null,
          link("#/reports", "Reports", "reports", "doc"),
          link("#/ct", "CT Nodule Finder", "ct", "ct"),
          can("doctor", "admin") ? link("#/audit", "Activity Log", "audit", "clock") : null,
          link("#/model", "Model Performance", "model", "bars")),
        h("button", { class: "me", onclick: logout, title: "Click to sign out", "aria-label": "Signed in as " + cleanName(me.full_name) + ". Click to sign out." },
          av, h("div", {}, h("div", { class: "nm" }, shortName(me.full_name)), h("div", { class: "rl" }, roleLabel)))),
      h("div", { class: "content" },
        h("main", {}, content),
        h("p", { class: "foot", role: "note" }, DISCLAIMER))),
  ];
}

// ---------- views ----------
function viewLogin() {
  const err = h("p", { class: "err", role: "alert" });
  const user = h("input", { id: "u", placeholder: "Email Address", autocomplete: "username", required: true, "aria-label": "Email address or username" });
  const pass = h("input", { id: "p", type: "password", placeholder: "Password", autocomplete: "current-password", required: true, "aria-label": "Password" });
  const withIcon = (name, input) => h("div", { class: "lf" }, svgEl(name), input);
  const form = h("form", {
    onsubmit: async (ev) => {
      ev.preventDefault();
      err.textContent = "";
      try {
        const r = await api("/auth/login", { method: "POST", json: { username: user.value.trim(), password: pass.value } });
        token = r.access_token; me = r.user;
        store.set("tok", token); store.set("me", JSON.stringify(me));
        location.hash = "#/";
        render();
      } catch (e) { err.textContent = e.message; }
    },
  }, withIcon("mail", user), withIcon("lock", pass), err, h("button", { class: "btn", type: "submit" }, "Log In"));
  const art = h("div", { class: "login-art", role: "img", "aria-label": "Illustration of lungs" });
  art.style.backgroundImage = "url(img/lung-art.jpg)";
  root.replaceChildren(h("div", { class: "login-page" }, art,
    h("div", { class: "login-side" },
      h("div", { class: "login-box" },
        h("img", { class: "logo", src: "img/logo-dark.png", alt: "CellIQ" }),
        h("div", { class: "tag" }, "Smarter Review.", h("br"), "Better Care."),
        h("h1", {}, "Welcome Back"),
        h("div", { class: "sub" }, "Sign in to your account"),
        form,
        h("div", { class: "alt" }, "Don\u2019t have an account? ",
          h("a", { href: "#/", onclick: (e) => { e.preventDefault(); toast("Accounts are created by an administrator in this demo."); } }, "Sign Up"))),
      h("p", { class: "login-note" }, DISCLAIMER, " Demo logins are listed in api/seed.py."))));
}


async function randomPatient() {
  try {
    const list = await api("/patients");
    if (!list.length) { toast("No patients yet", true); return; }
    location.hash = "#/patient/" + list[Math.floor(Math.random() * list.length)].id;
  } catch (e) { toast(e.message, true); }
}

function initials(name) {
  return String(name || "?").replace(/^Dr\.?\s*/i, "").split(/\s+/).map(w => w[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}
const SVG = {  // constant icon markup only, never built from server data
  scans: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M8 9h8M8 13h5"/></svg>',
  pending: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  flag: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>',
  arrow: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M7 17 17 7M8 7h9v9"/></svg>',
};
function icon(name) { const s = h("span", { class: "ic" }); s.innerHTML = SVG[name]; return s; }
function meter(fraction, cls) {
  const filled = Math.round(Math.min(1, Math.max(0, fraction)) * 24);
  return h("div", { class: "meter " + (cls || "") }, ...Array.from({ length: 24 }, (_, i) => h("i", { class: i < filled ? "f" : "" })));
}
function statusPill(s) {
  const cls = { "Urgent": "urgent", "In review": "inreview", "Completed": "completed", "AI analysed": "analysed" }[s] || "na";
  const label = { "Completed": "Report Ready", "AI analysed": "Pending Review", "In review": "In Review", "Processing": "Analysing..." }[s] || s;
  return h("span", { class: "pill " + cls }, label);
}
const blobCache = {};
function cachedBlob(path) { return blobCache[path] || (blobCache[path] = blobUrl(path)); }
function thumbImg(path, cls) {
  const box = h("div", { class: cls });
  cachedBlob(path).then(u => box.replaceChildren(h("img", { src: u, alt: "" }))).catch(() => {});
  return box;
}
function trend(cur, prev) {
  if (!prev) return cur ? h("span", { class: "trend up" }, `${cur} this week`) : null;
  const pct = Math.round(((cur - prev) / prev) * 100);
  return h("span", { class: "trend " + (pct >= 0 ? "up" : "down") }, `${pct >= 0 ? "↑" : "↓"} ${Math.abs(pct)}%`);
}

function timeAgo(iso) {
  const d = new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(String(iso)) ? iso : iso + "Z");
  if (isNaN(d)) return "";
  const m = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  if (m < 1) return "Just now";
  if (m < 60) return `${m}m Ago`;
  if (m < 60 * 24) return `${Math.round(m / 60)}h Ago`;
  return `${Math.round(m / 1440)}d Ago`;
}
const AVATARS = [["#5a4aa6", "#b9b0e8"], ["#f764ad", "#fbd3ea"], ["#2f8fb8", "#cbe7f3"], ["#d98b2b", "#f6dfb9"]];

function donut(parts) {  // parts in drawing order from 12 o'clock, clockwise: [{value, color}]
  const total = parts.reduce((a, q) => a + q.value, 0);
  const R = 37.2, SW = 25.7, C = 2 * Math.PI * R;
  let off = 0, segs = "";
  if (total === 0) segs = `<circle cx="50" cy="50" r="${R}" fill="none" stroke="#e3eaee" stroke-width="${SW}"/>`;
  else for (const q of parts) {
    if (!q.value) continue;
    const len = (q.value / total) * C, gap = parts.filter(x => x.value).length > 1 ? 0.7 : 0;
    segs += `<circle cx="50" cy="50" r="${R}" fill="none" stroke="${q.color}" stroke-width="${SW}" stroke-dasharray="${Math.max(len - gap, 0).toFixed(2)} ${(C - len + gap).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 50 50)"/>`;
    off += len;
  }
  const box = h("div", { class: "donut" });
  box.innerHTML = `<svg viewBox="0 0 100 100" role="img" aria-label="Scan distribution by risk tier">${segs}</svg>`;
  box.append(h("div", { class: "mid" }, h("div", {}, String(total)), h("div", {}, "Total"), total === 0 ? h("small", {}, "No scans yet") : null));
  return box;
}

async function viewDashboard() {
  let d;
  try { d = await api("/dashboard"); } catch (e) { toast(e.message, true); return; }
  const c = d.counts, recent = d.recent_scans;
  const hr = new Date().getHours();
  const greeting = hr < 12 ? "Good Morning" : hr < 18 ? "Good Afternoon" : "Good Evening";
  const parts = cleanName(d.user_name).replace(/^Dr\.?\s*/i, "").split(/\s+/);
  const title = d.user_role === "admin" ? parts.join(" ") : `Doctor ${parts[parts.length - 1]}`;

  const tile = (ic, n, label) => h("div", { class: "tile" }, h("div", { class: "ic" }, svgEl(ic)), h("div", { class: "num" }, String(n)), h("div", { class: "lbl" }, label));
  const tiles = h("div", { class: "tiles" },
    tile("people2", c.patients, "Total Patients"), tile("lungs", c.scans_reviewed, "Scans Reviewed"),
    tile("clockO", c.scans_pending, "Scans Pending"), tile("check", c.reports_approved, "Reports Approved"));

  const isRad = can("radiologist");
  const upload = h("a", { class: "upload-banner", href: isRad ? "#/upload" : "#/patients" },
    h("span", { class: "cloud" }, svgEl("cloudUp")),
    h("div", { class: "txt" },
      h("div", { class: "ttl" }, isRad ? "Upload a new scan" : "Review patient scans"),
      h("div", { class: "sub" }, isRad ? "Add a patient\u2019s lung scan for A.I. analysis." : "Open a patient to see the AI score, heatmap and report.")),
    h("span", { class: "go2" }, svgEl("arrowR")));

  const open = (pid) => () => { location.hash = "#/patient/" + pid; };
  const activity = h("div", { class: "activity" },
    h("div", { class: "sec-head" }, h("h2", {}, "Recent Activity"), h("a", { href: "#/patients" }, "View All \u2192")),
    recent.length === 0 ? h("div", { class: "empty" }, svgEl("lungs"), h("b", {}, "No scans yet"),
        h("span", {}, isRad ? "Upload a scan and the AI result will appear here." : "Scans uploaded by the radiologist will appear here."),
        h("a", { href: isRad ? "#/upload" : "#/patients" }, isRad ? "Upload a scan" : "Open patient profiles")) :
      recent.slice(0, 2).map((r, i) => {
        const [bg, fg] = AVATARS[i % AVATARS.length];
        const av = h("div", { class: "av", style: `background:${bg}` }); av.append(personSvg(bg, fg));
        cachedBlob(`/scans/${r.scan_id}/image`).then(u => { av.replaceChildren(h("img", { src: u, alt: "" })); }).catch(() => {});
        return h("div", { class: "act", tabindex: "0", role: "link", onclick: open(r.patient_id), onkeydown: (e) => { if (e.key === "Enter") open(r.patient_id)(); } },
          av, h("div", { class: "who" }, h("b", { title: r.name }, r.name), h("span", {}, r.display_id)),
          statusPill(r.status), h("div", { class: "when" }, timeAgo(r.uploaded_at)));
      }));

  // ---- latest scan card (fills the top-right gap) ----
  const latest = h("div", { class: "latest" });
  const s0 = recent[0];
  if (!s0) {
    latest.classList.add("none");
    latest.append(svgEl("lungs"), h("b", {}, "Latest scan"), h("span", {}, "Your newest scan with its AI heatmap will appear here."));
  } else {
    let heat = !!s0.has_heatmap;
    const disc = h("div", { class: "disc" }, h("div", { class: "ph" }, "Loading..."));
    const pill = (label, on, fn) => h("button", { type: "button", class: "mini" + (on ? " on" : ""), onclick: fn }, label);
    const draw = () => {
      const path = heat && s0.has_heatmap ? `/scans/${s0.scan_id}/heatmap` : `/scans/${s0.scan_id}/image`;
      cachedBlob(path).then(u => disc.replaceChildren(h("img", { src: u, alt: heat ? "Scan with AI attention heatmap" : "Original scan" })))
        .catch(() => disc.replaceChildren(h("div", { class: "ph" }, "Image unavailable")));
      tg.replaceChildren(pill("AI heatmap", heat && s0.has_heatmap, () => { heat = true; draw(); }), pill("Original", !(heat && s0.has_heatmap), () => { heat = false; draw(); }));
    };
    const tg = h("div", { class: "tg" });
    latest.append(
      h("div", { class: "ring" }, disc),
      h("div", { class: "lt" },
        h("div", { class: "lab" }, "Latest scan", s0.is_placeholder ? h("em", {}, "Placeholder AI") : null),
        h("b", {}, s0.name),
        h("span", { class: "sub" }, `${s0.display_id}  \u00b7  ${s0.sex}, ${s0.age}  \u00b7  ${s0.scan_type === "ct" ? "Chest CT" : "Tissue"}`),
        h("div", { class: "row" }, priorityBadge(s0.priority), s0.risk_score != null ? h("span", { class: "risk" }, `Risk ${Math.round(s0.risk_score * 100)}%`) : null),
        s0.uncertainty ? h("span", { class: "sub" }, `Uncertainty: ${s0.uncertainty}`) : null,
        tg,
        h("a", { class: "open", href: "#/patient/" + s0.patient_id }, "Open patient file \u2192")));
    draw();
  }

  const total = c.risk_high + c.risk_medium + c.risk_low;
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0) + "%";
  const dist = h("div", { class: "donut-card" },
    h("h2", {}, "Scan Distribution"),
    donut([{ value: c.risk_low, color: "#039244" }, { value: c.risk_medium, color: "#e56432" }, { value: c.risk_high, color: "#da3433" }]),
    h("div", { class: "legend" },
      h("div", {}, h("i", { style: "background:#da3433" }), "High Risk", h("b", {}, pct(c.risk_high))),
      h("div", {}, h("i", { style: "background:#e56432" }), "Medium Risk", h("b", {}, pct(c.risk_medium))),
      h("div", {}, h("i", { style: "background:#039244" }), "Low Risk", h("b", {}, pct(c.risk_low)))));

  root.replaceChildren(...shell([
    h("div", { class: "dash" },
      h("div", { class: "greet" }, h("h1", {}, `${greeting}, ${title}.`), h("p", {}, "Here\u2019s what\u2019s happening with your patients today.")),
      tiles, latest, upload, activity, dist),
  ], "dashboard"));
}

async function viewReports() {
  let pats;
  try { pats = await api("/patients?sort=name"); } catch (e) { toast(e.message, true); return; }
  const lists = await Promise.all(pats.map(p => api(`/patients/${p.id}/reports`).then(r => r.map(x => ({ ...x, p })), () => [])));
  const rows = lists.flat().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  root.replaceChildren(...shell([
    h("div", { class: "pageh" }, h("h1", {}, "Reports"), h("p", { class: "muted" }, "AI-assisted drafts and doctor-approved reports. Open a patient to edit, approve, download or email.")),
    h("div", { class: "card" }, rows.length === 0 ? h("p", { class: "muted" }, "No reports yet. Open a patient with a scan to draft one.") :
      h("table", {}, h("thead", {}, h("tr", {}, ...["Patient", "Status", "Created", "Approved"].map(t => h("th", {}, t)))),
        h("tbody", {}, rows.map(r => h("tr", { class: "click", tabindex: "0", onclick: () => { location.hash = "#/patient/" + r.patient_id; },
          onkeydown: (e) => { if (e.key === "Enter") location.hash = "#/patient/" + r.patient_id; } },
          h("td", {}, h("b", {}, r.p.name), h("div", { class: "muted small" }, r.p.display_id)),
          h("td", {}, h("span", { class: "pill " + (r.status === "approved" ? "completed" : "analysed") }, r.status === "approved" ? "Report Ready" : "Draft")),
          h("td", {}, fmtDate(r.created_at)),
          h("td", {}, r.approved_at ? fmtDate(r.approved_at) : "-")))))),
  ], "reports"));
}


async function viewUpload(preselect) {
  if (!can("radiologist")) { toast("Only radiologists can upload scans", true); location.hash = "#/"; return; }
  let pats;
  try { pats = await api("/patients?sort=name"); } catch (e) { toast(e.message, true); return; }
  const sel = h("select", { class: "pbox", "aria-label": "Select patient" }, h("option", { value: "" }, ""),
    ...pats.map(p => h("option", { value: String(p.id) }, `${p.display_id}  ${p.name}`)));
  if (preselect && pats.some(p => p.id === preselect)) sel.value = String(preselect);

  const d = new Date(), pad = (n) => String(n).padStart(2, "0");
  const dateText = `${pad(d.getDate())} / ${pad(d.getMonth() + 1)} / ${d.getFullYear()}`;
  const dateBox = h("div", { class: "dbox", role: "text", "aria-label": "Scan date: today" }, h("span", {}, dateText), svgEl("calendar"));

  let kind = "";
  const typeCard = (value, title, sub, img) => {
    const radio = h("input", { type: "radio", name: "scan_type", value, class: "sr-only", onchange: () => { kind = value; } });
    return h("label", { class: "scard" },
      h("div", { class: "pic", style: `background-image:url(${img})` }),
      h("div", { class: "foot2" }, h("div", {}, h("b", {}, title), h("span", {}, sub)), h("i", { class: "dot" })),
      radio);
  };

  let chosen = null;
  const msg = h("div", { class: "line1" }, "Drag and drop your file here");
  const fileInput = h("input", { type: "file", accept: "image/png,image/jpeg,.nii,.nii.gz,.mhd,.mha,.nrrd,.zip", class: "sr-only", "aria-label": "Scan file",
    onchange: () => setFile(fileInput.files[0]) });
  function setFile(f) {
    chosen = f || null;
    msg.textContent = f ? `Selected: ${f.name} (${(f.size / 1024).toFixed(0)} KB)` : "Drag and drop your file here";
  }
  const browse = h("a", { href: "#/upload", onclick: (e) => { e.preventDefault(); fileInput.click(); } }, "Browse Files");
  const drop = h("div", { class: "drop",
    ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
    ondragleave: () => drop.classList.remove("over"),
    ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); const f = e.dataTransfer.files[0];
      if (f && (/^image\/(png|jpeg)$/.test(f.type) || /\.(nii|nii\.gz|mhd|mha|nrrd|zip)$/i.test(f.name))) { setFile(f); } else toast("Please drop a PNG, JPEG, NIfTI, MetaImage or zip file", true); } },
    msg, h("div", { class: "line2" }, "or ", browse), h("div", { class: "hint" }, "Tissue: PNG or JPEG.  CT: a whole volume (.nii, .nii.gz, .mhd, or a .zip of a DICOM series)."), fileInput);

  const btn = h("button", { class: "analyse", type: "button", onclick: async () => {
    if (!sel.value) { toast("Select a patient first", true); return; }
    if (!kind) { toast("Choose Chest CT or Tissue Slide", true); return; }
    if (!chosen) { toast("Choose a scan file first", true); return; }
    const fd = new FormData(); fd.append("scan_type", kind); fd.append("file", chosen);
    btn.disabled = true; btn.firstChild.textContent = kind === "ct" ? "Uploading..." : "Analysing...";
    try { const made = await api(`/patients/${sel.value}/scans`, { method: "POST", form: fd }); toast(made.result && made.result.status === "processing" ? "CT uploaded. The detector is running." : "Scan analysed"); location.hash = "#/patient/" + sel.value; }
    catch (e) { toast(e.message, true); btn.disabled = false; btn.firstChild.textContent = "Analyse Scan"; }
  } }, h("span", {}, "Analyse Scan"), svgEl("longArrow"));

  root.replaceChildren(...shell([
    h("div", { class: "upl" },
      h("h1", {}, "Upload Scan"),
      h("p", { class: "lead" }, "Select a patient and upload a lung scan for analysis."),
      h("a", { class: "back", href: "#/" }, "\u2190 Back to Dashboard"),
      h("div", { class: "toprow" },
        h("div", { class: "pcol" }, h("div", { class: "lab" }, "Select Patient"), sel),
        h("div", { class: "dcol" }, h("div", { class: "lab" }, "Scan Date"), dateBox)),
      h("div", { class: "cards" },
        typeCard("ct", "Chest CT", "Upload CT Scan", "img/upload-ct.jpg"),
        typeCard("tissue", "Tissue Slide", "Upload Tissue Slide", "img/upload-tissue.jpg")),
      drop,
      h("div", { class: "actrow" }, btn)),
  ], "upload"));
}

async function viewDirectory() {
  const state = { q: "", status: "", sort: "risk" };
  const body = h("div", {});
  async function load() {
    const params = new URLSearchParams({ sort: state.sort });
    if (state.q) params.set("q", state.q);
    if (state.status) params.set("status", state.status);
    try {
      const list = await api("/patients?" + params);
      body.replaceChildren(list.length === 0 ? h("p", { class: "muted" }, "No patients match.") :
        h("table", {},
          h("thead", {}, h("tr", {}, ...["ID", "Patient", "Age / sex", "Status", "Highest risk", "Priority", "Scans"].map(t => h("th", {}, t)))),
          h("tbody", {}, list.map(p => h("tr", { class: "click", tabindex: "0",
            onclick: () => { location.hash = "#/patient/" + p.id; },
            onkeydown: (e) => { if (e.key === "Enter") location.hash = "#/patient/" + p.id; } },
            h("td", {}, p.display_id), h("td", {}, p.name, " ", p.is_demo ? h("span", { class: "badge demo" }, "Demo") : null),
            h("td", {}, `${p.age} / ${p.sex}`), h("td", {}, h("span", { class: "badge status" }, p.status)),
            h("td", {}, p.highest_risk == null ? "n/a" : Math.round(p.highest_risk * 100) + "%"),
            h("td", {}, priorityBadge(p.highest_priority)), h("td", {}, String(p.scan_count)))))));
    } catch (e) { toast(e.message, true); }
  }
  const search = h("input", { type: "search", placeholder: "Search name or ID (e.g. CIQ-0001)", "aria-label": "Search patients",
    oninput: (() => { let t; return (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); load(); }, 250); }; })() });
  const status = h("select", { "aria-label": "Filter by status", onchange: (e) => { state.status = e.target.value; load(); } },
    h("option", { value: "" }, "All statuses"), ...["New", "AI analysed", "Under review", "Report ready"].map(s => h("option", { value: s }, s)));
  const sort = h("select", { "aria-label": "Sort", value: "risk", onchange: (e) => { state.sort = e.target.value; load(); } },
    h("option", { value: "risk" }, "Highest risk first"), h("option", { value: "recent" }, "Most recent"), h("option", { value: "name" }, "Name A-Z"));
  root.replaceChildren(...shell([
    h("div", { class: "row", style: "justify-content:space-between" }, h("h1", {}, "Patient directory"),
      h("div", { class: "row" }, h("button", { class: "btn secondary", onclick: randomPatient }, "Random patient"),
        can("radiologist", "doctor") ? h("button", { class: "btn", onclick: () => patientDialog(null) }, "+ New patient") : null)),
    h("p", { class: "muted" }, "Sorted by highest AI risk so the most urgent files are at the top."),
    h("div", { class: "card" }, h("div", { class: "row toolbar" }, search, status, sort), body),
  ], "patients"));
  load();
}

function patientDialog(p, onSaved) {
  const f = (k, def) => (p ? p[k] : def);
  const name = h("input", { value: f("name", ""), required: true, maxlength: "120" });
  const age = h("input", { type: "number", min: "0", max: "120", value: String(f("age", "")), required: true });
  const sex = h("select", { value: f("sex", "female") }, ...["female", "male", "other"].map(s => h("option", { value: s }, s)));
  const contact = h("input", { value: f("contact", ""), maxlength: "200", placeholder: "Fake demo contact only" });
  const smoke = h("select", { value: f("smoking_status", "unknown") }, ...["unknown", "never", "former", "current"].map(s => h("option", { value: s }, s)));
  const pack = h("input", { type: "number", min: "0", max: "300", step: "0.5", value: String(f("pack_years", 0)) });
  const fam = h("input", { type: "checkbox" }); fam.checked = !!f("family_history", false);
  const cond = h("textarea", { rows: "2", maxlength: "2000", value: f("conditions", "") });
  const sym = h("textarea", { rows: "2", maxlength: "2000", value: f("symptoms", "") });
  const err = h("p", { class: "small", style: "color:#C62828" });
  const dlg = h("dialog", {},
    h("h2", {}, p ? "Edit patient" : "New patient"),
    h("p", { class: "small muted" }, "Demo data only. Do not enter real patient details."),
    h("form", { method: "dialog", onsubmit: async (ev) => {
      ev.preventDefault(); err.textContent = "";
      const json = { name: name.value.trim(), age: Number(age.value), sex: sex.value, contact: contact.value, smoking_status: smoke.value,
        pack_years: Number(pack.value || 0), family_history: fam.checked, conditions: cond.value, symptoms: sym.value };
      try {
        const saved = await api(p ? "/patients/" + p.id : "/patients", { method: p ? "PUT" : "POST", json });
        dlg.close(); dlg.remove(); toast("Saved");
        if (onSaved) onSaved(saved); else location.hash = "#/patient/" + saved.id;
      } catch (e) { err.textContent = e.message; }
    } },
      h("div", { class: "grid2" }, field("Name", name), field("Age", age), field("Sex", sex), field("Contact (fake)", contact),
        field("Smoking status", smoke), field("Pack-years", pack)),
      h("div", { class: "field" }, h("label", {}, fam, " Family history of cancer")),
      field("Known conditions", cond), field("Symptoms", sym), err,
      h("div", { class: "row" }, h("button", { class: "btn", type: "submit" }, "Save"),
        h("button", { class: "btn secondary", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Cancel"))));
  document.body.append(dlg);
  dlg.showModal();
}

function reviewPanel(scan) {
  const VERB = { agree: "Agrees with AI", disagree: "Disagrees with AI", needs_more: "Needs further tests" };
  const box = h("div", { class: "card" }, h("h3", {}, "Doctor review of AI result"));
  const list = h("div", {});
  async function load() {
    try {
      const rows = await api(`/scans/${scan.id}/reviews`);
      list.replaceChildren(...(rows.length ? rows.map(r => h("div", { class: "note" },
        h("div", { class: "meta" }, `${r.doctor_name}, ${fmtDate(r.created_at)}`),
        h("p", {}, h("b", {}, VERB[r.verdict] || r.verdict), r.note ? ": " + r.note : "")))
        : [h("p", { class: "muted small" }, "No doctor has reviewed this scan yet.")]));
    } catch (e) { list.replaceChildren(h("p", { class: "small" }, e.message)); }
  }
  box.append(list);
  if (can("doctor")) {
    const verdict = h("select", { "aria-label": "Verdict" },
      h("option", { value: "agree" }, "I agree with the AI result"), h("option", { value: "disagree" }, "I disagree with the AI result"),
      h("option", { value: "needs_more" }, "Needs further tests or imaging"));
    const note = h("input", { placeholder: "Short note (optional)", maxlength: "2000", "aria-label": "Review note" });
    box.append(h("div", { class: "row toolbar" }, verdict, note, h("button", { class: "btn", onclick: async () => {
      try { await api(`/scans/${scan.id}/reviews`, { method: "POST", json: { verdict: verdict.value, note: note.value } }); toast("Review saved"); load(); }
      catch (e) { toast(e.message, true); } } }, "Save review")));
  }
  load();
  return box;
}

function emailDialog(rep, patient, onDone) {
  const looksLikeEmail = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(patient.contact || "");
  const to = h("input", { type: "email", required: true, value: looksLikeEmail ? patient.contact : "", placeholder: "recipient@example.com", "aria-label": "Recipient email" });
  const modeNote = h("p", { class: "placeholder-note" }, "Checking email mode...");
  const err = h("p", { class: "small", style: "color:#C62828" });
  let mode = "outbox";
  api("/health").then(hh => {
    mode = hh.email_mode;
    modeNote.textContent = mode === "gmail"
      ? "This sends the approved report PDF from the configured Gmail account. Check the address carefully: a sent email cannot be taken back."
      : "Demo outbox mode: nothing is actually sent. The email is saved as a file in data/outbox.";
  }).catch(() => { modeNote.textContent = "Could not check email mode."; });
  const send = h("button", { class: "btn", type: "submit" }, "Send report");
  const dlg = h("dialog", {}, h("h2", {}, "Email report to patient"),
    h("p", { class: "small muted" }, `Report ${rep.id} for ${patient.display_id}. Only the approved PDF is attached. No scans are sent.`), modeNote,
    h("form", { method: "dialog", onsubmit: async (ev) => {
      ev.preventDefault(); err.textContent = ""; send.disabled = true; send.textContent = "Sending...";
      try {
        await api(`/reports/${rep.id}/send`, { method: "POST", json: { recipient: to.value.trim() } });
        dlg.close(); dlg.remove(); toast(mode === "gmail" ? "Email sent" : "Saved to outbox (nothing was sent)");
        if (onDone) onDone();
      } catch (e) { err.textContent = e.message; send.disabled = false; send.textContent = "Send report"; }
    } }, field("Recipient email", to), err,
      h("div", { class: "row" }, send, h("button", { class: "btn secondary", type: "button", onclick: () => { dlg.close(); dlg.remove(); } }, "Cancel"))));
  document.body.append(dlg);
  dlg.showModal();
}

// ---------- CT detector results for an uploaded volume ----------
const ctSliceCache = {};
async function ctResultViewer(scanId) {
  const meta = await api(`/scans/${scanId}/ct`);
  const S = 512, st = { slice: 0, thr: 0.5, token: 0 };
  const sliceUrl = (i) => { const k = scanId + "/" + i; return ctSliceCache[k] || (ctSliceCache[k] = blobUrl(`/scans/${scanId}/ct/slice/${i}`)); };
  const img = h("img", { alt: "CT slice", style: "width:100%;height:100%;display:block" });
  const canvas = h("canvas", { width: S, height: S, style: "position:absolute;inset:0;width:100%;height:100%;pointer-events:none" });
  const stage = h("div", { style: "position:relative;width:min(100%,512px);aspect-ratio:1;background:#000;border-radius:14px;overflow:hidden;margin:0 auto" }, img, canvas);
  const slider = h("input", { type: "range", min: "0", max: String(meta.n_slices - 1), value: "0", "aria-label": "Slice number", style: "flex:1" });
  const sliceLabel = h("span", { class: "small muted", style: "min-width:110px;text-align:right" }, "");
  const thrLabel = h("span", { class: "small" }, "");
  const thr = h("input", { type: "range", min: "0.1", max: "0.99", step: "0.01", value: String(st.thr), "aria-label": "Minimum score to show", style: "width:160px" });
  const list = h("div", {});

  function draw() {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, S, S);
    const k = S / meta.slice_size;
    for (const d of meta.detections) {
      if (d.score < st.thr || Math.abs(st.slice - d.slice) > Math.max(1, d.depth_slices / 2)) continue;
      const [cx, cy] = d.center_px, [w, hh] = d.size_px;
      ctx.setLineDash([]); ctx.strokeStyle = "#ff5c5c"; ctx.lineWidth = 2;
      ctx.strokeRect((cx - w / 2) * k - 3, (cy - hh / 2) * k - 3, w * k + 6, hh * k + 6);
      ctx.fillStyle = "#ff5c5c"; ctx.font = "13px sans-serif";
      ctx.fillText(d.score.toFixed(2), (cx - w / 2) * k - 3, (cy - hh / 2) * k - 8);
    }
  }
  async function show(i) {
    st.slice = Math.max(0, Math.min(meta.n_slices - 1, Math.round(i)));
    slider.value = String(st.slice);
    sliceLabel.textContent = `Slice ${st.slice + 1} / ${meta.n_slices}`;
    draw();
    const my = ++st.token;
    try { const u = await sliceUrl(st.slice); if (my === st.token) img.src = u; } catch (e) { toast(e.message, true); }
    for (const j of [st.slice + 1, st.slice + 2]) if (j < meta.n_slices) sliceUrl(j).catch(() => {});
  }
  function renderList() {
    const rows = meta.detections.filter(d => d.score >= st.thr);
    list.replaceChildren(
      h("p", { class: "small muted" }, `${rows.length} candidate${rows.length === 1 ? "" : "s"} at score ${st.thr.toFixed(2)} or higher. Click one to jump to its slice.`),
      rows.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Score", "Size", "Slice"].map(t => h("th", {}, t)))),
        h("tbody", {}, rows.map(d => h("tr", { class: "click", tabindex: "0", onclick: () => show(d.slice), onkeydown: (e) => { if (e.key === "Enter") show(d.slice); } },
          h("td", {}, d.score.toFixed(3)), h("td", {}, d.diameter_mm + " mm"), h("td", {}, String(d.slice + 1)))))) : null);
  }
  slider.addEventListener("input", () => show(Number(slider.value)));
  stage.addEventListener("wheel", (e) => { e.preventDefault(); show(st.slice + (e.deltaY > 0 ? 1 : -1)); }, { passive: false });
  thr.addEventListener("input", () => { st.thr = Number(thr.value); thrLabel.textContent = "Show candidates with score " + st.thr.toFixed(2) + " or higher"; renderList(); draw(); });
  thrLabel.textContent = "Show candidates with score " + st.thr.toFixed(2) + " or higher";
  renderList();
  const best = [...meta.detections].sort((a, b) => b.score - a.score)[0];
  await show(best ? best.slice : Math.floor(meta.n_slices / 2));
  return h("div", {}, stage,
    h("div", { class: "row", style: "margin-top:10px;flex-wrap:nowrap" }, slider, sliceLabel),
    h("div", { class: "row", style: "margin-top:8px" }, thr, thrLabel),
    h("p", { class: "small muted" }, "Red boxes are nodule candidates found by the detector. Scroll over the image to move through the scan."),
    list);
}

async function viewPatient(id, selectedScanId) {
  let patient, scans, notes, reports, visits;
  try {
    [patient, scans, notes, reports, visits] = await Promise.all([
      api("/patients/" + id), api(`/patients/${id}/scans`), api(`/patients/${id}/notes`),
      api(`/patients/${id}/reports`), api(`/patients/${id}/visits`)]);
  } catch (e) { toast(e.message, true); location.hash = "#/"; return; }

  const reload = (scanId) => viewPatient(id, scanId);
  let selected = scans.find(s => s.id === selectedScanId) || scans[0] || null;

  // --- header and facts ---
  const LABELS = { lung_aca: "Adenocarcinoma", lung_scc: "Squamous cell carcinoma", lung_n: "Normal lung tissue" };
  const predicted = (res) => { const m = /slide type: (lung_\w+) \((\d+)%\)/.exec((res && res.message) || ""); return m ? { name: LABELS[m[1]] || m[1], pct: m[2] } : null; };
  const toDate = (iso) => new Date(/[zZ]$|[+-]\d\d:?\d\d$/.test(String(iso)) ? iso : iso + "Z");
  const ico = (path) => { const e = h("span", { class: "fic" }); e.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`; return e; };
  const ICON = {  // constant icon markup only
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
    smoke: '<path d="M3 17h13v3H3zM19 17v3M16 14c0-2 3-2 3-4s-3-2-3-4"/>',
    family: '<circle cx="8" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M2 20c0-3.5 2.7-6 6-6s6 2.5 6 6M14 20c0-2.5 1.8-4.5 4-4.5s4 2 4 4.5"/>',
    heart: '<path d="M12 21s-8-5.2-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.8-8 11-8 11z"/>',
    pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 7 9-7"/>',
  };
  const fact = (ic, label, value) => h("div", { class: "pfact" }, ico(ICON[ic]), h("div", {}, h("span", {}, label), h("b", {}, value)));
  const hero = h("div", { class: "phero" },
    h("div", { class: "avatar big" }, initials(patient.name)),
    h("div", { class: "pname" }, h("h1", {}, patient.name),
      h("div", { class: "row" }, h("span", { class: "chip2" }, patient.display_id), statusPill(patient.status === "Report ready" ? "Completed" : patient.status === "AI analysed" ? "AI analysed" : patient.status === "Under review" ? "In review" : patient.status),
        patient.is_demo ? h("span", { class: "chip2 demo" }, "Demo data") : null)),
    h("div", { class: "pact" },
      can("radiologist", "doctor") ? h("button", { class: "btn secondary", onclick: () => patientDialog(patient, () => reload(selected && selected.id)) }, "Edit profile") : null,
      can("radiologist") ? h("a", { class: "btn", href: "#/upload/" + patient.id }, "Upload scan") : null));
  const facts = h("div", { class: "pfacts" },
    fact("user", "Age / sex", `${patient.age} / ${patient.sex}`),
    fact("smoke", "Smoking", `${patient.smoking_status}${patient.pack_years ? `, ${patient.pack_years} pack-yrs` : ""}`),
    fact("family", "Family history", patient.family_history ? "Yes" : "No"),
    fact("heart", "Conditions", patient.conditions || "None recorded"),
    fact("pulse", "Symptoms", patient.symptoms || "None recorded"),
    fact("mail", "Contact", patient.contact || "n/a"));

  // --- scans: big viewer on the left, AI result and review on the right ---
  const viewerMain = h("div", { class: "pview" });
  const viewerSide = h("div", { class: "pside-in" });
  function tissueViewer(sc) {
    const res = sc.result;
    let heat = !!(res && res.has_heatmap);
    const box = h("div", { class: "tbox" }), tg = h("div", { class: "tg" }), legend = h("div", { class: "lbar" });
    const draw = () => {
      box.replaceChildren(imageBox(heat ? `/scans/${sc.id}/heatmap` : `/scans/${sc.id}/image`, heat ? "Scan with AI attention heatmap" : "Original scan", "No image"));
      tg.replaceChildren(
        h("button", { type: "button", class: "mini" + (heat ? " on" : ""), disabled: !(res && res.has_heatmap), onclick: () => { heat = true; draw(); } }, "AI heatmap"),
        h("button", { type: "button", class: "mini" + (!heat ? " on" : ""), onclick: () => { heat = false; draw(); } }, "Original"));
      legend.replaceChildren(...(heat ? [h("span", {}, "Low attention"), h("i", {}), h("span", {}, "High attention")] : []));
    };
    draw();
    return h("div", {}, tg, box, legend, h("p", { class: "small muted" }, "The heatmap (Grad-CAM) shows where the model looked. It is not proof that the model is right."));
  }
  function renderViewer() {
    if (!selected) {
      viewerMain.replaceChildren(h("div", { class: "empty" }, h("b", {}, "No scans yet"), h("span", {}, can("radiologist") ? "Upload a tissue slide or a CT volume to see the AI result here." : "A radiologist has not uploaded a scan for this patient yet."),
        can("radiologist") ? h("a", { href: "#/upload/" + patient.id }, "Upload a scan") : null));
      viewerSide.replaceChildren(h("div", { class: "card" }, h("h3", {}, "AI result"), h("p", { class: "muted" }, "Appears once a scan is analysed.")));
      return;
    }
    const res = selected.result;
    const isCtDet = selected.scan_type === "ct" && res && !res.is_placeholder;
    const main = [], side = [];
    if (isCtDet && res.status === "processing") {
      main.push(h("div", { class: "grid2" }, h("div", {}, h("h3", {}, "CT preview (middle slice)"), imageBox(`/scans/${selected.id}/image`, "CT middle slice")),
        h("div", { class: "card" }, h("h3", {}, "Analysing the CT volume..."),
          h("p", { class: "muted" }, "The nodule detector is running. Without a GPU this can take several minutes. This page updates by itself when it is done."))));
      const sc = selected;
      const poll = () => setTimeout(async () => {
        if (!selected || selected.id !== sc.id || !document.body.contains(viewerMain)) return;
        try {
          const fresh = (await api(`/patients/${id}/scans`)).find(x => x.id === sc.id);
          if (fresh && fresh.result && fresh.result.status !== "processing") { sc.result = fresh.result; renderChips(); renderViewer(); } else poll();
        } catch (e) { poll(); }
      }, 8000);
      poll();
    } else if (isCtDet && res.status === "analysed") {
      const holder = h("div", {}, h("p", { class: "muted" }, "Loading slices..."));
      main.push(h("h3", {}, "CT nodule candidates"), holder);
      ctResultViewer(selected.id).then(el => holder.replaceChildren(el)).catch(e => holder.replaceChildren(h("p", { class: "muted" }, e.message)));
    } else if (selected.scan_type === "tissue") {
      main.push(tissueViewer(selected));
    } else {
      main.push(h("div", { class: "grid2" }, h("div", {}, h("h3", {}, "Original scan"), imageBox(`/scans/${selected.id}/image`, "Original scan")),
        h("div", { class: "card" }, h("p", { class: "muted" }, "No AI overlay for this scan."))));
    }

    // AI result card
    if (res && res.status !== "processing") {
      const card = h("div", { class: "card aires" }, h("div", { class: "lab" }, isCtDet ? "Nodule detector" : "AI result"));
      if (res.status === "analysed") {
        const pr = predicted(res);
        if (pr) card.append(h("div", { class: "pred" }, h("b", {}, pr.name), h("span", {}, `${pr.pct}% confidence`)));
        if (isCtDet) card.append(h("div", { class: "pred" }, h("b", {}, res.risk_score.toFixed(2)), h("span", {}, "top candidate score (not a cancer probability)")));
        else card.append(gauge(res.risk_score, res.threshold_review, res.threshold_high));
        card.append(h("div", { class: "row", style: "justify-content:center" }, priorityBadge(res.priority), res.uncertainty ? h("span", { class: "chip2" }, "Uncertainty: " + res.uncertainty) : null));
        card.append(h("p", { class: "small muted" }, isCtDet ? "Priority review means at least one candidate scored 0.50 or higher."
          : `Review at ${Math.round(res.threshold_review * 100)}% risk, high priority at ${Math.round(res.threshold_high * 100)}%. Priority orders the review queue; it is not a diagnosis.`));
      } else {
        card.append(h("span", { class: "badge na" }, "CANNOT ASSESS"));
      }
      card.append(h("p", { class: "small muted" }, res.is_placeholder ? [h("b", {}, "Not a real result. "), res.message] : res.message), h("p", { class: "small muted" }, "Model: " + res.model_version));
      side.push(card);
    }
    side.push(reviewPanel(selected));
    side.push(h("p", { class: "small muted" }, `${selected.scan_type === "ct" ? "Chest CT" : "Tissue image"}, uploaded ${fmtDate(selected.uploaded_at)}. ${selected.disclaimer}`));
    viewerMain.replaceChildren(...main);
    viewerSide.replaceChildren(...side);
  }
  const chips = h("div", { class: "scan-list" });
  function renderChips() {
    chips.replaceChildren(...scans.map((sc, i) => {
      const b = h("button", { class: "scan-chip sc2" + (selected && sc.id === selected.id ? " on" : ""), onclick: () => { selected = sc; renderChips(); renderViewer(); } });
      const th = h("span", { class: "th" });
      cachedBlob(`/scans/${sc.id}/image`).then(u => th.replaceChildren(h("img", { src: u, alt: "" }))).catch(() => {});
      b.append(th, h("span", {}, h("b", {}, `#${scans.length - i} ${sc.scan_type === "ct" ? "CT" : "Tissue"}`),
        h("small", {}, sc.result && sc.result.status === "processing" ? "Analysing..." : sc.result && sc.result.risk_score != null ? (sc.scan_type === "ct" && !sc.result.is_placeholder ? "score " + sc.result.risk_score.toFixed(2) : Math.round(sc.result.risk_score * 100) + "% risk") : "n/a")));
      return b;
    }));
  }
  const scanCard = h("div", { class: "card" }, h("div", { class: "sec-head" }, h("h2", {}, "Scans"),
    can("radiologist") ? h("a", { href: "#/upload/" + patient.id }, "Upload a scan \u2192") : null), chips, viewerMain);
  renderChips(); renderViewer();

  // --- timeline (visits, scans, notes and reports in one list) ---
  const events = [];
  for (const v of visits) events.push({ t: new Date(v.visit_date + "T12:00:00"), kind: "visit", title: "Visit", text: v.reason, day: true });
  for (const sc of scans) events.push({ t: toDate(sc.uploaded_at), kind: "scan", title: `${sc.scan_type === "ct" ? "CT" : "Tissue"} scan uploaded`,
    text: sc.result && sc.result.priority ? sc.result.priority.toLowerCase() : (sc.result && sc.result.status === "processing" ? "analysing" : "not assessed") });
  for (const n of notes) events.push({ t: toDate(n.created_at), kind: "note", title: `Note by ${cleanName(n.author_name)}`, text: n.text.length > 90 ? n.text.slice(0, 90) + "..." : n.text });
  for (const rep of reports) events.push({ t: toDate(rep.approved_at || rep.created_at), kind: "report", title: rep.status === "approved" ? "Report approved" : "Report drafted", text: "Report " + rep.id });
  events.sort((x, y) => y.t - x.t);
  const timeline = h("div", { class: "card" }, h("h3", {}, "Timeline"),
    events.length ? h("div", { class: "tl" }, events.slice(0, 12).map(e => h("div", { class: "tli " + e.kind },
      h("i", {}), h("div", {}, h("b", {}, e.title), h("span", {}, e.text), h("small", {}, e.day ? e.t.toLocaleDateString([], { dateStyle: "medium" }) : fmtDate(e.t.toISOString())))))) : h("p", { class: "muted small" }, "Nothing has happened for this patient yet."));
  if (can("radiologist", "doctor")) {
    const d = h("input", { type: "date", "aria-label": "Visit date" }), r = h("input", { placeholder: "Reason", "aria-label": "Visit reason" });
    timeline.append(h("div", { class: "row addvisit" }, d, r, h("button", { class: "btn secondary", onclick: async () => {
      try { await api(`/patients/${id}/visits`, { method: "POST", json: { visit_date: d.value, reason: r.value } }); reload(selected && selected.id); }
      catch (e) { toast(e.message, true); } } }, "Add visit")));
  }

  // --- notes ---
  const noteText = h("textarea", { rows: "3", maxlength: "5000", placeholder: "Add a note for the other doctors...", "aria-label": "New note" });
  const notesCard = h("div", { class: "card" }, h("h2", {}, "Doctors' notes"),
    notes.length ? notes.map(n => h("div", { class: "note" }, h("div", { class: "meta" }, `${n.author_name} (${n.author_role}), ${fmtDate(n.created_at)}${n.scan_id ? `, scan ${n.scan_id}` : ""}`), h("p", {}, n.text)))
      : h("p", { class: "muted" }, "No notes yet."));
  if (can("radiologist", "doctor")) {
    notesCard.append(noteText, h("p", {}, h("button", { class: "btn", onclick: async () => {
      if (!noteText.value.trim()) return;
      try { await api(`/patients/${id}/notes`, { method: "POST", json: { text: noteText.value, scan_id: selected ? selected.id : null } }); reload(selected && selected.id); }
      catch (e) { toast(e.message, true); } } }, "Add note")));
  }

  // --- reports ---
  const reportsCard = h("div", { class: "card" }, h("h2", {}, "Patient reports"),
    h("p", { class: "small muted" }, "Drafted from approved findings and notes (Gemini if configured, otherwise a template). A doctor must review and approve before it can be downloaded."));
  if (can("doctor")) {
    reportsCard.append(h("p", {}, h("button", { class: "btn", disabled: scans.length === 0, onclick: async (ev) => {
      ev.target.disabled = true; ev.target.textContent = "Drafting...";
      try { await api(`/patients/${id}/report`, { method: "POST" }); toast("Draft created"); reload(selected && selected.id); }
      catch (e) { toast(e.message, true); ev.target.disabled = false; ev.target.textContent = "Generate report draft"; } } }, "Generate report draft")));
  }
  if (!reports.length) reportsCard.append(h("p", { class: "muted" }, "No reports yet."));
  for (const rep of reports) {
    const box = h("div", { class: "report card", style: "background:#fafcfd" },
      h("div", { class: "row" }, h("b", {}, `Report ${rep.id}`), h("span", { class: "badge status" }, rep.status),
        h("span", { class: "badge status" }, "source: " + rep.source), h("span", { class: "small muted" }, fmtDate(rep.created_at))));
    if (rep.status === "approved") {
      const sentLog = h("div", { class: "small muted" });
      const loadLog = () => api(`/reports/${rep.id}/emails`).then(rows => {
        sentLog.replaceChildren(...rows.map(r => h("p", {}, (r.mode === "gmail" ? "Emailed to " : "Saved to outbox for ") + r.recipient + ", " + fmtDate(r.created_at))));
      }).catch(() => {});
      box.append(h("pre", { class: "final" }, rep.final_text),
        h("div", { class: "row" },
          h("button", { class: "btn", onclick: async () => {
            try { const u = await blobUrl(`/reports/${rep.id}/pdf`); const a = h("a", { href: u, download: `${patient.display_id}-report.pdf` }); document.body.append(a); a.click(); a.remove(); }
            catch (e) { toast(e.message, true); } } }, "Download PDF"),
          can("doctor") ? h("button", { class: "btn secondary", onclick: () => emailDialog(rep, patient, loadLog) }, "Email to patient") : null),
        sentLog);
      loadLog();
    } else if (can("doctor")) {
      const ta = h("textarea", { value: rep.draft_text, "aria-label": "Report draft" });
      box.append(ta, h("div", { class: "row" },
        h("button", { class: "btn secondary", onclick: async () => {
          try { await api("/reports/" + rep.id, { method: "PUT", json: { draft_text: ta.value } }); toast("Draft saved"); } catch (e) { toast(e.message, true); } } }, "Save draft"),
        h("button", { class: "btn", onclick: async () => {
          try { await api("/reports/" + rep.id, { method: "PUT", json: { draft_text: ta.value } }); await api(`/reports/${rep.id}/approve`, { method: "PUT" }); toast("Report approved"); reload(selected && selected.id); }
          catch (e) { toast(e.message, true); } } }, "Approve report")));
    } else {
      box.append(h("pre", { class: "final" }, rep.draft_text), h("p", { class: "small muted" }, "Draft awaiting doctor approval."));
    }
    reportsCard.append(box);
  }

  root.replaceChildren(...shell([
    h("p", { class: "crumbs" }, h("a", { href: "#/" }, "Dashboard"), " / ", h("a", { href: "#/patients" }, "Patient Profiles"), " / ", patient.name),
    hero, facts,
    h("div", { class: "pgrid" }, h("div", { class: "pleft" }, scanCard, notesCard, reportsCard), h("div", { class: "pright" }, viewerSide, timeline)),
  ], "patients"));
}

async function viewAudit() {
  let rows;
  try { rows = await api("/audit?limit=200"); } catch (e) { toast(e.message, true); location.hash = "#/"; return; }
  root.replaceChildren(...shell([
    h("h1", {}, "Activity Log"), h("p", { class: "muted" }, "Who viewed or changed what. Newest first."),
    h("div", { class: "card" }, h("table", {}, h("thead", {}, h("tr", {}, ...["Time", "User", "Action", "Patient", "Detail"].map(t => h("th", {}, t)))),
      h("tbody", {}, rows.map(r => h("tr", {}, h("td", {}, fmtDate(r.timestamp)), h("td", {}, r.user_name ? cleanName(r.user_name) : (r.user_id == null ? "n/a" : "User " + r.user_id)),
        h("td", {}, r.action), h("td", {}, r.patient_id == null ? "" : "CIQ-" + String(r.patient_id).padStart(4, "0")), h("td", {}, r.detail))))))], "audit"));
}

async function viewModel() {
  let mc;
  try { mc = await api("/model-card"); } catch (e) { toast(e.message, true); return; }
  const li = (arr) => h("ul", {}, arr.map(x => h("li", {}, x)));
  const t = mc.models.tissue, ct = mc.models.ct, cd = mc.models.ct_detector_demo, m = t.measured;
  const pct = (v) => (v * 100).toFixed(1) + "%";
  const cm = m ? m.confusion_matrix : null;
  const cmTable = cm ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Truth \\ AI guess"), ...m.classes.map(c => h("th", {}, c)))),
    h("tbody", {}, cm.map((row, i) => h("tr", {}, h("td", {}, m.classes[i]), ...row.map(v => h("td", {}, String(v))))))) : null;
  root.replaceChildren(...shell([
    h("div", { class: "row", style: "justify-content:space-between" }, h("h1", {}, "Model performance"),
      h("a", { class: "btn secondary", href: "#/ct" }, "CT nodule demo")),
    h("div", { class: "card" }, h("h2", {}, "Intended use"), h("p", {}, mc.intended_use), h("h3", {}, "Not intended for"), h("p", {}, mc.not_intended_for)),
    h("div", { class: "card" }, h("h2", {}, "Tissue model"),
      h("p", {}, h("span", { class: "badge status" }, t.state), " ", t.version),
      h("p", {}, h("b", {}, "Data: "), t.data), h("p", {}, h("b", {}, "Method: "), t.method), h("p", {}, h("b", {}, "Risk score: "), t["risk_score"]),
      m ? h("div", {}, h("h3", {}, "Measured on the held-out test set"),
        h("div", { class: "stats" },
          h("div", { class: "card stat-card" }, h("div", { class: "num" }, pct(m.test_accuracy)), h("div", { class: "muted small" }, `Accuracy (n = ${m.n_test})`)),
          h("div", { class: "card stat-card" }, h("div", { class: "num" }, pct(m.test_accuracy_grayscale)), h("div", { class: "muted small" }, "Accuracy with colour removed")),
          h("div", { class: "card stat-card" }, h("div", { class: "num" }, pct(m.cancer_vs_normal.sensitivity)), h("div", { class: "muted small" }, "Cancer vs normal sensitivity"))),
        h("p", { class: "small muted" }, `Cancer vs normal specificity ${pct(m.cancer_vs_normal.specificity)}, AUC ${m.cancer_vs_normal.auc}.`),
        cmTable,
        h("p", { class: "small muted" }, `Why these numbers are probably optimistic: in a random split, ${pct(m.leak_rate_random_split["0.9"])} of test images had a near-identical twin in training. We grouped near-duplicates, but ${pct(m.leak_rate_group_split["0.85"])} of test images still have a lookalike in training at a lower similarity (0.85).`))
        : h("p", { class: "muted" }, "No measured results found.")),
    cd ? h("div", { class: "card" }, h("h2", {}, "CT nodule detector (precomputed demo)"),
      h("p", {}, h("span", { class: "badge ph" }, cd.state)), h("p", {}, h("b", {}, "Model: "), cd.model), h("p", {}, h("b", {}, "Data: "), cd.data),
      cd.evaluation ? h("p", {}, `Tested on ${cd.evaluation.n_scans} public scans with ${cd.evaluation.n_marked_nodules} marked nodules: it found ` +
        `${Math.round(cd.evaluation.sensitivity_at_false_alarms_per_scan["1"] * 100)}% of them at 1 false alarm per scan ` +
        `(95% range ${Math.round(cd.evaluation.bootstrap_95_interval["1"][0] * 100)}% to ${Math.round(cd.evaluation.bootstrap_95_interval["1"][1] * 100)}%).`) : null,
      cd.measured ? h("p", {}, `Found ${cd.measured["0.5"].nodules_found} of ${cd.measured["0.5"].marked_nodules} radiologist-marked nodules in a 4-scan test.`) : null,
      h("p", { class: "small muted" }, cd.caveat), h("p", {}, h("a", { href: "#/ct" }, "Open the CT nodule demo"))) : null,
    h("div", { class: "card" }, h("h2", {}, "CT model (uploaded scans)"), h("p", {}, h("span", { class: "badge ph" }, ct.state)), h("p", {}, ct.note)),
    h("div", { class: "card" }, h("h2", {}, "Triage tiers"), h("p", {}, `Tissue: high priority at risk >= ${mc.thresholds.tissue_high}, review at >= ${mc.thresholds.tissue_review}. `, mc.thresholds.note)),
    h("div", { class: "card" }, h("h2", {}, "Limitations"), li(mc.limitations)),
    h("p", { class: "small muted" }, mc.disclaimer)], "model"));
}

// ---------- CT nodule demo (precomputed results of an open-source detector) ----------
const ctCache = {};
function ctSlice(caseId, i) {
  const key = caseId + "/" + i;
  return ctCache[key] || (ctCache[key] = blobUrl(`/ct-demo/${caseId}/slice/${i}`));
}

async function viewCT() {
  let info;
  try { info = await api("/ct-demo"); } catch (e) { toast(e.message, true); return; }
  if (!info.cases.length) {
    root.replaceChildren(...shell([h("h1", {}, "CT nodule demo"), h("p", { class: "muted" }, "No demo cases found on the server.")], "ct"));
    return;
  }
  const S = 512; // display size in px for the slice and its overlay
  const st = { id: info.cases[0].case, meta: null, slice: 0, thr: 0.5, marks: true, token: 0 };

  const img = h("img", { alt: "CT slice", style: "width:100%;height:100%;display:block" });
  const canvas = h("canvas", { width: S, height: S, style: "position:absolute;inset:0;width:100%;height:100%;pointer-events:none" });
  const stage = h("div", { style: "position:relative;width:min(100%,512px);aspect-ratio:1;background:#000;border-radius:14px;overflow:hidden;margin:0 auto" }, img, canvas);
  const slider = h("input", { type: "range", min: "0", max: "0", value: "0", "aria-label": "Slice number", style: "flex:1" });
  const sliceLabel = h("span", { class: "small muted", style: "min-width:110px;text-align:right" }, "");
  const thrLabel = h("span", { class: "small" }, "");
  const thr = h("input", { type: "range", min: "0.1", max: "0.99", step: "0.01", value: String(st.thr), "aria-label": "Minimum score to show", style: "width:160px" });
  const marksBox = h("input", { type: "checkbox", id: "marks" }); marksBox.checked = true;
  const candidates = h("div", {});
  const caseButtons = h("div", { class: "scan-list" });

  function draw() {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, S, S);
    if (!st.meta) return;
    const k = S / st.meta.slice_size, sp = st.meta.spacing_mm;
    for (const d of st.meta.detections) {
      if (d.score < st.thr) continue;
      if (Math.abs(st.slice - d.slice) > Math.max(1, d.depth_slices / 2)) continue;
      const [cx, cy] = d.center_px, [w, hh] = d.size_px;
      ctx.setLineDash([]); ctx.strokeStyle = "#ff5c5c"; ctx.lineWidth = 2;
      ctx.strokeRect((cx - w / 2) * k - 3, (cy - hh / 2) * k - 3, w * k + 6, hh * k + 6);
      ctx.fillStyle = "#ff5c5c"; ctx.font = "13px sans-serif";
      ctx.fillText(d.score.toFixed(2), (cx - w / 2) * k - 3, (cy - hh / 2) * k - 8);
    }
    if (st.marks) {
      for (const a of st.meta.radiologist_nodules) {
        if (Math.abs(st.slice - a.slice) > Math.max(1, a.diameter_mm / sp[2] / 2)) continue;
        const r = Math.max(7, (a.diameter_mm / 2 / sp[0]) * (st.meta.slice_size / 512) * k + 6);
        ctx.setLineDash([6, 4]); ctx.strokeStyle = "#4fdb92"; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.arc(a.center_px[0] * k, a.center_px[1] * k, r, 0, 2 * Math.PI); ctx.stroke();
      }
    }
  }

  async function show(i) {
    if (!st.meta) return;
    st.slice = Math.max(0, Math.min(st.meta.n_slices - 1, Math.round(i)));
    slider.value = String(st.slice);
    sliceLabel.textContent = `Slice ${st.slice + 1} / ${st.meta.n_slices}`;
    draw();
    const my = ++st.token;
    try {
      const url = await ctSlice(st.id, st.slice);
      if (my === st.token) img.src = url;
    } catch (e) { toast(e.message, true); }
    for (const j of [st.slice + 1, st.slice + 2, st.slice - 1]) if (j >= 0 && j < st.meta.n_slices) ctSlice(st.id, j).catch(() => {});
  }

  function renderCandidates() {
    const list = st.meta.detections.filter(d => d.score >= st.thr).sort((a, b) => b.score - a.score);
    candidates.replaceChildren(
      h("p", { class: "small muted" }, `${list.length} candidate${list.length === 1 ? "" : "s"} at score ${st.thr.toFixed(2)} or higher. ` +
        `${st.meta.radiologist_nodules.length} nodule${st.meta.radiologist_nodules.length === 1 ? "" : "s"} marked by radiologists in the dataset (green dashed circles).`),
      list.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Score", "Size", "Slice"].map(t => h("th", {}, t)))),
        h("tbody", {}, list.map(d => h("tr", { class: "click", tabindex: "0", onclick: () => show(d.slice), onkeydown: (e) => { if (e.key === "Enter") show(d.slice); } },
          h("td", {}, d.score.toFixed(3)), h("td", {}, d.diameter_mm + " mm"), h("td", {}, String(d.slice + 1)))))) : null);
  }

  async function loadCase(id) {
    st.id = id;
    caseButtons.replaceChildren(...info.cases.map(c => h("button", { class: "scan-chip" + (c.case === id ? " on" : ""), onclick: () => loadCase(c.case) },
      c.case.replace("_", " "), ` (${c.n_slices} slices)`)));
    try { st.meta = await api(`/ct-demo/${id}`); } catch (e) { toast(e.message, true); return; }
    slider.max = String(st.meta.n_slices - 1);
    renderCandidates();
    const best = [...st.meta.detections].sort((a, b) => b.score - a.score)[0];
    await show(best ? best.slice : Math.floor(st.meta.n_slices / 2));
  }

  slider.addEventListener("input", () => show(Number(slider.value)));
  stage.addEventListener("wheel", (e) => { e.preventDefault(); show(st.slice + (e.deltaY > 0 ? 1 : -1)); }, { passive: false });
  thr.addEventListener("input", () => { st.thr = Number(thr.value); thrLabel.textContent = "Show detections with score " + st.thr.toFixed(2) + " or higher"; if (st.meta) { renderCandidates(); draw(); } });
  thrLabel.textContent = "Show detections with score " + st.thr.toFixed(2) + " or higher";
  marksBox.addEventListener("change", () => { st.marks = marksBox.checked; draw(); });

  const ev = info.evaluation;
  const froc = h("div", { class: "imgbox", style: "min-height:60px" });
  if (ev) blobUrl("/ct-demo/eval/froc.png").then(u => froc.replaceChildren(h("img", { src: u, alt: "FROC curve: share of marked nodules found against false alarms per scan" }))).catch(() => {});
  const pct = (v) => Math.round(v * 100) + "%";
  root.replaceChildren(...shell([
    h("div", { class: "row", style: "justify-content:space-between" }, h("h1", {}, "CT nodule demo"),
      h("span", { class: "badge ph" }, "PRECOMPUTED DEMO RESULTS")),
    can("radiologist") ? h("p", {}, h("a", { class: "btn", href: "#/upload" }, "Upload your own CT volume"), h("span", { class: "small muted", style: "margin-left:10px" }, "The same detector then runs on your scan and its candidates appear in the patient file.")) : null,
    h("p", { class: "muted" }, "An open-source detector (MONAI lung nodule detection) was run offline on four public CT scans. This page only shows the saved results. " +
      "Boxes mark nodule candidates for a doctor to review. They are not a diagnosis, and a nodule is not necessarily cancer."),
    h("div", { class: "dash" },
      h("div", { class: "card" }, caseButtons, stage,
        h("div", { class: "row", style: "margin-top:12px;flex-wrap:nowrap" }, slider, sliceLabel),
        h("div", { class: "row", style: "margin-top:8px" }, thr, thrLabel),
        h("div", { class: "row", style: "margin-top:8px" }, marksBox, h("label", { for: "marks", style: "margin:0;display:inline" }, "Show nodules marked by radiologists (green dashed circles)")),
        h("p", { class: "small muted" }, "Scroll over the image or use the slider to move through the scan. Click a candidate to jump to its slice. Red boxes: detector. ")),
      h("div", { class: "stack" },
        h("div", { class: "card" }, h("h2", {}, "Detector candidates"), candidates),
        h("div", { class: "card" }, h("h2", {}, "How well does the detector do?"),
          ev ? h("div", {},
            h("p", {}, `Tested separately on ${ev.n_scans} randomly chosen public scans containing ${ev.n_marked_nodules} nodules marked by radiologists (the 4 scans shown here are for viewing). ` +
              "A nodule counts as found when a detection's centre lies inside the marked nodule's radius (LUNA16's rule)."),
            h("table", {}, h("thead", {}, h("tr", {}, ...["False alarms per scan", "Marked nodules found", "95% range"].map(t => h("th", {}, t)))),
              h("tbody", {}, ["0.5", "1", "2", "4"].map(k => h("tr", {}, h("td", {}, k), h("td", {}, pct(ev.sensitivity_at_false_alarms_per_scan[k])),
                h("td", {}, ev.bootstrap_95_interval[k] ? pct(ev.bootstrap_95_interval[k][0]) + " to " + pct(ev.bootstrap_95_interval[k][1]) : "not computed"))))),
            h("p", { class: "small muted" }, `With the score slider at 0.9 or higher it found ${pct(ev.by_score_threshold["0.9"].sensitivity)} of nodules with about ${ev.by_score_threshold["0.9"].false_alarms_per_scan} false alarms per scan; at 0.5 or higher, ${pct(ev.by_score_threshold["0.5"].sensitivity)} with ${ev.by_score_threshold["0.5"].false_alarms_per_scan}.`),
            froc,
            h("p", { class: "small muted" }, "The ranges are wide because there are only " + ev.n_marked_nodules + " nodules. False alarms are probably overstated: real small nodules that the reference list omits count as false alarms. Only scans with smaller files were used, to keep the test quick."))
            : h("p", { class: "muted" }, "No evaluation available."),
          h("p", { class: "small muted" }, "A detection is a nodule candidate, not a diagnosis. This is a demonstration, not a clinical validation.")),
        h("div", { class: "card" }, h("h2", {}, "Credits"), h("p", { class: "small muted" }, info.credits), h("p", { class: "small muted" }, info.disclaimer)))),
  ], "ct"));
  await loadCase(st.id);
}

// ---------- router ----------
async function render() {
  if (!token || !me) { viewLogin(); return; }
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  try {
    if (parts[0] === "patient" && /^\d+$/.test(parts[1] || "")) await viewPatient(Number(parts[1]));
    else if (parts[0] === "patients") await viewDirectory();
    else if (parts[0] === "ct") await viewCT();
    else if (parts[0] === "reports") await viewReports();
    else if (parts[0] === "upload") await viewUpload(Number(parts[1]) || null);
    else if (parts[0] === "audit") await viewAudit();
    else if (parts[0] === "model") await viewModel();
    else await viewDashboard();
  } catch (e) { toast(e.message, true); }
}
window.addEventListener("hashchange", render);
render();
