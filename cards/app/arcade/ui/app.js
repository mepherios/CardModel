// Cardmodel Arcade's pages. The arcade service (same origin) gives the catalog, the store pages, the builds and
// the repository's work in progress; the native app (window.webkit.messageHandlers.arcade) installs, verifies,
// launches and reports back through window.arcade.event(...). In a plain browser the store still works and
// installing says where to go. Every program has versions: the one in the service's checkout and one per branch
// (a session's work in progress), installable like betas.
"use strict";

const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.arcade;
const S = {
  catalog: [], details: {}, native: { library: {}, settings: { bandwidth: 0, user: "" }, downloading: null, native: !!bridge },
  progress: {}, rates: [], peak: 0, totalDown: 0, completed: [], view: "store", arg: null, history: [], future: [],
  gear: false, shot: 0, libSel: null, lastErr: {}, notice: {}, dismissed: {},
  lib: { systems: [], roms: [], drawing: {} }, libQuery: "", libLoaded: 0,
  work: null, workAt: 0, workFilter: "", open: {}, collapsed: {}, ver: {}, storeQuery: "", service: null,
};

function send(cmd, extra) {
  if (!bridge) { toast("Open the Cardmodel Arcade app to install and play."); return; }
  bridge.postMessage(Object.assign({ cmd }, extra || {}));
}
window.arcade = {
  event(e) {
    if (e.type === "state") { S.native = e.state; render(); return; }
    if (e.type === "progress") {
      S.progress[e.id] = e;
      if (e.phase === "downloading") {
        S.rates.push(e.rate || 0); if (S.rates.length > 240) S.rates.shift();
        S.peak = Math.max(S.peak, e.rate || 0); S.totalDown = Math.max(S.totalDown, e.done || 0);
      }
      renderProgress(); return;
    }
    if (e.type === "done") {
      const g = game(e.id); delete S.progress[e.id]; delete S.lastErr[e.id];
      S.completed.unshift({ id: e.id, at: Date.now() });
      toast(`${g ? g.title : e.id} is ready to play.`); refresh(); return;
    }
    if (e.type === "error") { delete S.progress[e.id]; S.lastErr[e.id] = e.message; toast("Problem: " + e.message); render(); return; }
    if (e.type === "notice") { S.notice[e.id] = e.message; toast(e.message); render(); return; }
    if (e.type === "verified") {
      toast(e.ok ? `All ${e.files} files validated.` : `${e.bad} file(s) failed to validate and will be reacquired.`); return;
    }
    if (e.type === "running") { toast(`${(game(e.id) || rom(e.id) || {}).title || e.id} is running.`); }
    if (e.type === "stopped") { refresh(); }
    if (e.type === "folder") { folders({ system: e.system, add: e.path }); }
  },
};

const $ = (sel, el) => (el || document).querySelector(sel);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const game = (id) => S.catalog.find((g) => g.id === id);
const rom = (id) => S.lib.roms.find((r) => r.id === id);
const sysOf = (r) => S.lib.systems.find((s) => s.id === r.system_card) || {};
const playerOf = (r) => game(sysOf(r).player || "");
const subLabel = (r) => ((sysOf(r).systems || []).find((x) => x.id === r.system) || {}).label || r.system;
const media = (g, key) => (g && g.media && g.media[key]) || "";
const mb = (n) => (n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : (n / 1024).toFixed(0) + " KB");
const rate = (r) => (r >= 1048576 ? (r / 1048576).toFixed(1) + " MB/s" : (r / 1024).toFixed(0) + " KB/s");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many || one + "s"}`;
function playtime(s) {
  if (!s) return "None yet";
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + " minutes";
  return (s / 3600).toFixed(1) + " hours";
}
function when(t) {
  if (!t) return "Never";
  const d = new Date(t * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return "Today";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
function since(t) {
  if (!t) return "";
  const s = Date.now() / 1000 - t;
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + " minutes ago";
  if (s < 129600) return Math.round(s / 3600) + " hours ago";
  return when(t);
}

// -- versions: the service's own checkout ("") and every branch that has the program -----------------------------
const wtOf = (v) => (v && v.worktree) || "";
function versions(g) {
  const list = g.worktree ? [] : [g];
  for (const b of g.branches || []) if (!list.some((x) => wtOf(x) === wtOf(b))) list.push(b);
  return list;
}
const versionOf = (g, wt) => versions(g).find((v) => wtOf(v) === (wt || "")) || null;
const branchName = (v) => (v && v.branch) || (v && v.worktree) || "this checkout";
// the version an installation came from; one installed before the launcher remembered branches is found by its build
function sourceOf(g) {
  const inst = S.native.library[g.id];
  if (!inst) return null;
  const v = versionOf(g, inst.source || "");
  if (!inst.source && !(v && v.build && v.build.build === inst.build)) {
    const same = versions(g).find((x) => x.build && x.build.build === inst.build);
    if (same) return same;
  }
  return v;
}
const instWt = (g) => { const s = sourceOf(g), inst = S.native.library[g.id]; return s ? wtOf(s) : inst ? inst.source || "" : null; };
// the version a page of g shows: the one picked there, else the installed one, else the program's own
function shown(g) {
  const inst = S.native.library[g.id];
  const want = S.ver[g.id] != null ? S.ver[g.id] : inst ? instWt(g) : wtOf(g);
  return versionOf(g, want) || g;
}
const art = (g, key) => media(shown(g), key) || versions(g).map((v) => media(v, key)).find(Boolean) || "";
const shots = (v) => Object.keys((v && v.media) || {}).filter((k) => /^screenshot_\d+$/.test(k))
  .sort((a, b) => parseInt(a.slice(11), 10) - parseInt(b.slice(11), 10)).map((k) => v.media[k]);

// -- data ------------------------------------------------------------------------------------------------------------
async function refresh() {
  try {
    const r = await fetch("/api/catalog");
    S.catalog = await r.json();
    $("#service").className = "dot ok";
    $("#service").title = "Arcade service: connected";
    S.service = true;
  } catch (e) {
    $("#service").className = "dot bad";
    $("#service").title = "Arcade service: unreachable";
    S.service = false;
    // the service stopped (a restart, a crash): the app starts it again and reloads the pages
    if (bridge && Date.now() - (S.reconnectAt || 0) > 20000) { S.reconnectAt = Date.now(); send("reconnect"); }
  }
  if (!S.libLoaded || (S.lib.drawing && S.lib.drawing.busy)) {
    try {
      const r = await fetch("/api/library");
      S.lib = await r.json();
      S.libLoaded = Date.now();
    } catch (e) { /* the service is older or down: no cartridges */ }
  }
  if (S.view === "dev" || !S.work || Date.now() - S.workAt > 60000) loadWork();
  if (bridge) send("state");
  render();
}
async function loadWork(force) {
  try {
    const r = await fetch("/api/work" + (force ? "?force=1" : ""));
    if (!r.ok) return;
    S.work = await r.json();
    S.workAt = Date.now();
    footer();
    if (S.view === "dev") render();
  } catch (e) { /* an older service: no work overview */ }
}
// a store page's full text (about, statement), fetched again only when that version's build changes
const stampOf = (v) => (v ? `${v.version}+${(v.build || {}).build || ""}` : "");
const detail = (id, wt) => { const d = S.details[id + "@" + (wt || "")]; return d && d.data; };
async function details(id, wt) {
  const key = id + "@" + (wt || "");
  const g = game(id);
  const stamp = stampOf(g && versionOf(g, wt));
  if (S.details[key] && S.details[key].stamp === stamp) return false;
  const r = await fetch("/api/game/" + encodeURIComponent(id) + (wt ? "?branch=" + encodeURIComponent(wt) : ""));
  S.details[key] = { stamp, data: await r.json() };
  return true;
}

// -- what the big button says -------------------------------------------------------------------------------------
function status(g) {
  const inst = S.native.library[g.id];
  const p = S.progress[g.id];
  if (S.native.downloading === g.id || p) return { kind: "busy", label: p ? phaseLabel(p) : "Queued" };
  if (!inst) return { kind: "install", label: "Install" };
  if (inst.running) return { kind: "stop", label: "Stop" };
  const v = sourceOf(g);
  if (v && v.build && v.build.build !== inst.build) return { kind: "update", label: "Update" };
  if (v && v.build_due && !v.build_error && !v.building) return { kind: "update", label: "Update" };
  return { kind: "play", label: "Play" };
}
function phaseLabel(p) {
  if (p.phase === "building") return `Building from cards ${p.done}/${p.total}`;
  if (p.phase === "downloading") return p.total ? `Downloading ${Math.floor((100 * p.done) / p.total)}%` : "Downloading";
  if (p.phase === "verifying" || p.phase === "validating") return "Validating";
  if (p.phase === "installing") return "Installing";
  return "Preparing";
}
function act(g) {
  const st = status(g);
  const inst = S.native.library[g.id];
  const branch = inst ? instWt(g) : wtOf(shown(g));
  if (st.kind === "install" || st.kind === "update") send(st.kind, { id: g.id, branch });
  else if (st.kind === "play") send("play", { id: g.id });
  else if (st.kind === "stop") send("stop", { id: g.id });
}
function bigButton(g, small) {
  const st = status(g);
  const cls = st.kind === "busy" ? "busy" : st.kind;
  const icon = st.kind === "play" ? "&#9654;&nbsp; " : st.kind === "install" || st.kind === "update" ? "&#11015;&nbsp; " : "";
  return `<button class="btn ${cls}${small ? " small" : ""}" data-act="${esc(g.id)}">${icon}${esc(st.label)}</button>`;
}
// one version of a program: what its build is, and the button that installs exactly it
function verState(v) {
  if (v.building) return "building now";
  if (v.build_error) return "the cards in progress don't build yet";
  if (!v.build) return "not built yet: it builds when you install it";
  const d = v.build.created.slice(0, 10);
  if (v.build_due) return `build ${v.build.build} of ${d}; the cards changed since: installing builds them first`;
  if (v.build_due == null) return `build ${v.build.build} of ${d}; asking the branch whether its cards changed`;
  return `build ${v.build.build} of ${d}, current with its cards`;
}
function verButton(g, v) {
  const inst = S.native.library[g.id];
  const wt = wtOf(v);
  if (S.native.downloading === g.id || S.progress[g.id]) return `<button class="btn small busy">${esc(status(g).label)}</button>`;
  if (inst && instWt(g) === wt) {
    if ((v.build && v.build.build !== inst.build) || (v.build_due && !v.build_error))
      return `<button class="btn small update" data-verinstall="${esc(g.id)}" data-wt="${esc(wt)}">Update</button>`;
    return `<span class="okmark">&#10003; Installed</span>`;
  }
  if (!v.build && v.build_error) return `<span class="badmark">Doesn't build</span>`;
  return `<button class="btn small ${inst ? "ghost" : "install"}" data-verinstall="${esc(g.id)}" data-wt="${esc(wt)}">${inst ? "Switch to this" : "Install"}</button>`;
}
function versionsCard(g) {
  const list = versions(g);
  const sel = wtOf(shown(g));
  const inst = S.native.library[g.id];
  return `<div class="card versions"><h4>Versions and branches</h4>
    <p class="dim">Each branch is a session's work in progress on this program. Pick one to see it; install it like a beta.</p>
    ${list.map((v) => `<div class="ver ${wtOf(v) === sel ? "on" : ""}">
      <a class="vt" data-ver="${esc(g.id)}" data-wt="${esc(wtOf(v))}"><b>v${esc(v.version)}</b> <span>${esc(branchName(v))}</span>
        ${v.newer && v.worktree ? `<span class="tag new">newer</span>` : ""}${inst && instWt(g) === wtOf(v) ? `<span class="tag">installed</span>` : ""}</a>
      <div class="dim">${esc(verState(v))}${v.build ? ` &middot; <a data-build="${esc(g.id)}" data-wt="${esc(wtOf(v))}">details</a>` : ""}</div>
      <div class="ctl">${verButton(g, v)}</div></div>`).join("")}</div>`;
}
function problem(g) {
  const inst = S.native.library[g.id];
  const v = sourceOf(g) || shown(g);
  const err = v && v.build_error && S.dismissed[g.id] !== v.build_error ? v.build_error : null;
  const n = S.notice[g.id];
  const last = S.lastErr[g.id];
  if (!err && !n && !last) return "";
  return `<div class="banner">
    ${n ? `<p>${esc(n)}</p>` : ""}
    ${err ? `<p>The cards in progress${v.worktree ? " on " + esc(branchName(v)) : ""} don't build yet. ${inst ? `You keep playing build ${esc(inst.build)}.` : ""}</p>
      <pre class="err">${esc(err)}</pre>` : ""}
    ${last && !err ? `<p class="err">${esc(last)}</p>` : ""}
    <div class="row">${err ? `<button class="btn small ghost" data-retry="${esc(g.id)}" data-wt="${esc(wtOf(v))}">Try the build again</button>` : ""}
      <a data-dismiss="${esc(g.id)}">Dismiss</a></div></div>`;
}

// -- views ----------------------------------------------------------------------------------------------------------
function go(view, arg, noHistory) {
  const toBranches = view === "work";              // every branch is a section of IN PROGRESS (dev.js)
  if (toBranches) view = "dev";
  if (!noHistory) { S.history.push([S.view, S.arg]); S.future = []; }
  S.view = view; S.arg = arg; S.gear = false;
  if (view === "library" && arg) S.libSel = arg;
  if (view === "dev") loadWork();
  render();
  const at = toBranches && $("#branches");
  if (at) at.scrollIntoView(); else $("#view").scrollTop = 0;
}
function render() {
  const tabFor = { app: "store", browse: "store" };
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.view === (tabFor[S.view] || S.view)));
  $("#username").textContent = S.native.settings.user || "";
  $("#usertab").textContent = (S.native.settings.user || "YOU").split(" ")[0].toUpperCase();
  const v = $("#view");
  // a re-render keeps where the library's lists were scrolled (selecting something scrolls its page itself)
  const kept = S.view === "library" ? [...v.querySelectorAll(".side, .gamepage")].map((el) => el.scrollTop) : [];
  const focus = document.activeElement && document.activeElement.id;
  const caret = focus && document.activeElement.selectionStart;
  if (S.view === "store") v.innerHTML = storeHome();
  else if (S.view === "browse") v.innerHTML = browseView(S.arg || { mode: "all" });
  else if (S.view === "app") {
    const g = game(S.arg), wt = g ? wtOf(shown(g)) : "";
    v.innerHTML = `<div class="store">${storePage(S.arg)}</div>`;
    if (g) details(S.arg, wt).then((fresh) => { if (fresh && S.view === "app" && game(S.arg) && wtOf(shown(game(S.arg))) === wt) { v.innerHTML = `<div class="store">${storePage(S.arg)}</div>`; bind(); } }).catch(() => {});
  }
  else if (S.view === "library") v.innerHTML = libraryView();
  else if (S.view === "downloads") v.innerHTML = downloadsView();
  else if (S.view === "news") v.innerHTML = newsView();
  else if (S.view === "dev") v.innerHTML = devView();          // dev.js: everything in progress, live
  else if (S.view === "profile") v.innerHTML = profileView();
  if (S.view === "library") v.querySelectorAll(".side, .gamepage").forEach((el, k) => { if (kept[k] != null) el.scrollTop = kept[k]; });
  bind();
  if (focus && (focus === "search" || focus === "libsearch")) { const n = $("#" + focus); if (n) { n.focus(); if (caret != null) n.setSelectionRange(caret, caret); } }
  renderProgress();
  footer();
}
function footer() {
  const el = $("#worklink");
  if (!el) return;
  const w = S.work ? S.work.worktrees : [];
  const busy = w.filter((x) => x.ahead_count || x.uncommitted).length;
  el.textContent = w.length ? `${plural(busy, "branch", "branches")} in progress · every rule is a card` : "Built from cards · every rule is a card";
}

const tagChips = (list, kind) => (list || []).map((t) => `<a class="tag" data-filter="${esc(kind)}" data-value="${esc(t)}">${esc(t)}</a>`).join("");

function storeBar() {
  const m = (S.arg && S.arg.mode) || (S.view === "store" ? "home" : "");
  const link = (mode, label) => `<a class="${m === mode ? "on" : ""}" data-browse="${mode}">${label}</a>`;
  return `<div class="storebar"><a class="${m === "home" ? "on" : ""}" data-gostore="1">Your Store</a>${link("new", "New &amp; Noteworthy")}${link("cats", "Categories")}
    <a data-golibhome="1">Your Cartridges</a><a data-goview="work">Work in Progress</a><a data-goview="news">News</a>
    <input id="search" placeholder="search the store" value="${esc(S.storeQuery)}"></div>`;
}

function storeHome() {
  const games = S.catalog;
  if (!games.length) return `<div class="store">${storeBar()}<div class="empty">The arcade service has no games yet.</div></div>`;
  const f = games[0];
  const fs = shots(shown(f)).length ? shots(shown(f)) : versions(f).map(shots).find((x) => x.length) || [];
  const dev = [];
  for (const g of games) for (const b of versions(g)) if (b.worktree && (b.newer || g.worktree)) dev.push([g, b]);
  const updated = games.slice().sort((a, b) => ((b.build || {}).created || "").localeCompare((a.build || {}).created || ""));
  return `<div class="store">${storeBar()}
    <h2>Featured &amp; Recommended</h2>
    <div class="featured" data-open="${esc(f.id)}">
      <div class="main" style="background-image:url('${fs[S.shot % Math.max(1, fs.length)] || art(f, "header_460x215")}')"></div>
      <div class="side"><h3>${esc(f.title)}</h3>
        <div class="thumbs">${fs.slice(0, 4).map((s, k) => `<div data-feat="${k}" style="background-image:url('${s}')"></div>`).join("")}</div>
        <div>${esc(f.short_description)}</div>
        <div class="tags">${tagChips(f.tags, "tag")}</div>
        <div class="status">${S.native.library[f.id] ? "In Library" : '<span class="free">Free to Play</span>'}</div>
      </div>
    </div>
    <h2>Built from cards</h2>
    <div class="grid">${games.map((g) => `<div class="capsule" data-open="${esc(g.id)}">
      <div class="art" style="background-image:url('${art(g, "header_460x215")}')"></div>
      <div class="meta"><b>${esc(g.title)}</b><span>${S.native.library[g.id] ? "IN LIBRARY" : g.worktree ? "IN DEVELOPMENT" : "FREE"}</span>
      <div class="tags">${tagChips(g.genre, "genre")}</div></div></div>`).join("")}</div>
    ${dev.length ? `<h2>In development <a class="more" data-goview="work">all work in progress &rsaquo;</a></h2>
    <div class="grid">${dev.map(([g, b]) => `<div class="capsule" data-open="${esc(g.id)}" data-wt="${esc(b.worktree)}">
      <div class="art" style="background-image:url('${media(b, "header_460x215") || art(g, "header_460x215")}')"></div>
      <div class="meta"><b>${esc(g.title)} ${esc(b.version)}</b><span>BRANCH</span>
      <div class="dim">${esc(branchName(b))}</div><div class="dim">${esc(verState(b))}</div></div></div>`).join("")}</div>` : ""}
    ${S.lib.roms.length ? `<h2>Your cartridges</h2>
    <div class="grid">${S.lib.systems.filter((s) => s.playable || S.lib.roms.some((r) => r.system_card === s.id)).map((s) => {
      const n = S.lib.roms.filter((r) => r.system_card === s.id).length;
      const pl = game(s.player || "");
      return `<div class="capsule" ${pl ? `data-open="${esc(pl.id)}"` : `data-lib="home"`}>
        <div class="art" style="background-image:url('${pl ? art(pl, "header_460x215") : ""}')"></div>
        <div class="meta"><b>${esc(s.title)}</b><span>${n} FOUND</span>
        <div class="tags">${(s.systems || []).map((x) => `<a class="tag" data-libgroup="${esc(x.label)}">${esc(x.label)}</a>`).join("")}${s.playable ? "" : `<span class="tag">not playable yet</span>`}</div></div></div>`;
    }).join("")}</div>` : ""}
    <h2>Recently updated</h2>
    ${updated.map((g) => `<div class="card link" data-open="${esc(g.id)}"><b style="color:#fff">${esc(g.title)}</b> &nbsp; v${esc(g.version)}
      ${g.build ? `<span class="dim"> &middot; built ${esc(g.build.created.slice(0, 10))}</span>` : ""}
      ${(g.changelog || []).slice(-1).map((c) => ` &mdash; ${esc(c.title)}<ul>${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`).join("")}</div>`).join("")}
  </div>`;
}

// the store's lists: all games, new and noteworthy, a category, a developer, a search
function browseView(a) {
  if (a.mode === "cats") return categoriesView();
  const q = (a.mode === "search" ? a.value || "" : "").trim().toLowerCase();
  const hit = (...xs) => xs.some((x) => String(x || "").toLowerCase().includes(q));
  const rows = [];
  for (const g of S.catalog) {
    for (const v of versions(g)) {
      const own = wtOf(v) === wtOf(g);
      const keep = a.mode === "all" ? own
        : a.mode === "new" ? own || v.newer
        : a.mode === "tag" ? own && (g.tags || []).includes(a.value)
        : a.mode === "genre" ? own && (g.genre || []).includes(a.value)
        : a.mode === "dev" ? own && g.developer === a.value
        : a.mode === "search" ? q && (own ? hit(g.title, g.short_description, g.developer, ...(g.tags || []), ...(g.genre || [])) : hit(g.title, v.branch, v.version))
        : false;
      if (keep) rows.push([g, v]);
    }
  }
  if (a.mode === "new") rows.sort((x, y) => ((y[1].build || {}).created || "~").localeCompare((x[1].build || {}).created || "~"));
  const carts = a.mode === "search" && q ? S.lib.roms.filter((r) => hit(r.title, r.tags, subLabel(r))).slice(0, 60) : [];
  const title = { all: "All games", new: "New &amp; Noteworthy", tag: "Tagged " + esc(a.value), genre: esc(a.value), dev: "By " + esc(a.value),
    search: q ? `Results for &ldquo;${esc(a.value)}&rdquo;` : "Search" }[a.mode] || "";
  const row = ([g, v]) => `<div class="result" data-open="${esc(g.id)}" data-wt="${esc(wtOf(v))}">
      <div class="art" style="background-image:url('${media(v, "capsule_231x87") || media(v, "header_460x215") || art(g, "header_460x215")}')"></div>
      <div><b>${esc(g.title)}</b> <span class="dim">v${esc(v.version)}${v.worktree ? " &middot; " + esc(branchName(v)) : ""}</span>
        <div class="tags">${tagChips(g.tags, "tag")}</div></div>
      <div class="dim right">${v.build ? esc(v.build.created.slice(0, 10)) : "not built"}<br>${S.native.library[g.id] ? "In Library" : "Free"}</div></div>`;
  return `<div class="store">${storeBar()}
    <div class="crumbs"><a data-gostore="1">Store</a> &gt; <a data-browse="all">All Games</a>${a.mode !== "all" ? " &gt; " + title : ""}</div>
    <h2>${title} <small class="dim">${plural(rows.length + carts.length, "result")}</small></h2>
    ${rows.map(row).join("") || (carts.length ? "" : `<div class="empty">Nothing matches.</div>`)}
    ${carts.length ? `<h2>Your cartridges</h2>${carts.map((r) => `<div class="result" data-lib="${esc(r.id)}">
      <div class="art cart" style="background-image:url('${esc(r.cover || "")}')"></div>
      <div><b>${esc(r.title)}</b> <span class="dim">${esc(subLabel(r))}</span></div><div class="dim right">${esc(r.verdict.level)}</div></div>`).join("")}` : ""}
  </div>`;
}
function categoriesView() {
  const count = (kind) => {
    const c = {};
    for (const g of S.catalog) for (const t of g[kind] || []) c[t] = (c[t] || 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  };
  const devs = {};
  for (const g of S.catalog) if (g.developer) devs[g.developer] = (devs[g.developer] || 0) + 1;
  const tiles = (list, kind) => list.map(([t, n]) => `<a class="cat" data-filter="${kind}" data-value="${esc(t)}"><b>${esc(t)}</b><span>${plural(n, "game")}</span></a>`).join("");
  return `<div class="store">${storeBar()}
    <h2>Genres</h2><div class="cats">${tiles(count("genre"), "genre")}</div>
    <h2>Tags</h2><div class="cats">${tiles(count("tags"), "tag")}</div>
    <h2>Developers</h2><div class="cats">${tiles(Object.entries(devs), "dev")}</div>
    ${S.lib.systems.length ? `<h2>Consoles</h2><div class="cats">${S.lib.systems.flatMap((s) => (s.systems || []).map((x) =>
      `<a class="cat" data-libgroup="${esc(x.label)}"><b>${esc(x.label)}</b><span>${plural(S.lib.roms.filter((r) => r.system_card === s.id && r.system === x.id).length, "cartridge")}</span></a>`)).join("")}</div>` : ""}
  </div>`;
}

function storePage(id) {
  const g = game(id);
  if (!g) return `${storeBar()}<div class="empty">Not found.</div>`;
  const v = shown(g);
  const d = detail(id, wtOf(v)) || v;
  const list = shots(v).length ? shots(v) : versions(g).map(shots).find((x) => x.length) || [];
  const cur = list[S.shot % Math.max(1, list.length)] || "";
  const inst = S.native.library[id];
  const got = inst ? inst.achievements || [] : [];
  const genre = (g.genre || [])[0];
  return `${storeBar()}<div class="crumbs"><a data-browse="all">All Games</a> &gt; ${genre ? `<a data-filter="genre" data-value="${esc(genre)}">${esc(genre)}</a>` : "Games"} &gt; <a data-golib="${esc(id)}">${esc(g.title)}</a></div>
    <div class="page-title">${esc(g.title)} ${v.worktree ? `<span class="tag new" data-ver="${esc(id)}" data-wt="">v${esc(v.version)} on ${esc(branchName(v))}</span>` : ""}</div>
    <div class="storepage">
      <div><div class="stage" style="background-image:url('${cur}')"></div>
        <div class="strip">${list.map((s, k) => `<div class="${k === S.shot % list.length ? "on" : ""}" data-shot="${k}" style="background-image:url('${s}')"></div>`).join("")}</div></div>
      <div class="facts"><img src="${media(v, "header_460x215") || art(g, "header_460x215")}" alt="" data-shot="0">
        <p>${esc(v.short_description)}</p>
        <p><span class="k">Release date</span>${v.build ? `<a data-build="${esc(id)}" data-wt="${esc(wtOf(v))}">${esc(v.build.created.slice(0, 10))}</a>` : "Not built yet"}</p>
        <p><span class="k">Developer</span><a data-filter="dev" data-value="${esc(g.developer)}">${esc(g.developer)}</a></p>
        <p><span class="k">Version</span><a data-scroll="versions">${esc(v.version)}${v.build ? " &middot; build " + esc(v.build.build) : ""}</a></p>
        <p><span class="k">Branch</span><a data-scroll="versions">${esc(branchName(v))}</a>${versions(g).length > 1 ? ` <span class="dim">(${versions(g).length} versions)</span>` : ""}</p>
        <div class="tags">${tagChips(g.tags, "tag")}</div>
      </div>
    </div>
    ${problem(g)}
    <div class="buybox"><h3>Play ${esc(g.title)}${v.worktree ? " " + esc(v.version) : ""}</h3><div class="action"><div class="price">Free to Play</div>${inst && instWt(g) === wtOf(v) ? `<button class="btn play small" data-golib="${esc(id)}">In Library</button>` : inst ? verButton(g, v) : bigButton(g, true)}</div></div>
    <div class="about">
      <div><h4>About this game</h4>${(d.about || []).map((p) => `<p>${esc(p)}</p>`).join("") || `<p>${esc(v.short_description)}</p>`}
        <h4>System requirements</h4><div class="reqs"><p><b>OS:</b> macOS 13 or later &middot; <b>Built for:</b> this Mac (native code from the cards)</p>
        <p><b>Storage:</b> ${v.build ? `<a data-build="${esc(id)}" data-wt="${esc(wtOf(v))}">${mb(v.build.size)}</a>` : "—"} &middot; <b>Controls:</b> ${esc(g.controls || "keyboard or gamepad")}</p></div>
        <h4>What's new</h4><div class="news">${newsEntries(g, v)}</div>
        <div id="versions">${versionsCard(g)}</div></div>
      <div><h4>Achievements</h4>${achList(g, got)}</div>
    </div>`;
}

function newsEntries(g, v) {
  const src = v || g;
  return (src.changelog || []).slice().reverse().map((c, k) => {
    const key = `news:${g.id}:${wtOf(src)}:${c.version}`;
    const shut = k > 0 ? !S.open[key] : S.open[key] === false;
    return `<div class="entry"><a class="eh" data-toggle="${esc(key)}" data-def="${k > 0 ? "0" : "1"}"><b>${esc(g.title)} ${esc(c.version)} &mdash; ${esc(c.title)}</b>
      <small>${shut ? "show" : "hide"}</small></a>${shut ? "" : `<ul>${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`}</div>`;
  }).join("") || `<div class="dim">No notes yet.</div>`;
}
function achList(g, got) {
  return `<div class="achlist">${(g.achievements || []).map((a, k) => `<div class="a ${got[k] ? "got" : ""}" data-ach="${esc(g.id)}" data-k="${k}"><div class="ico">&#9733;</div><div><b>${esc(a.name)}</b><small>${esc(a.description)}</small></div></div>`).join("") || `<div class="dim">No achievements.</div>`}</div>`;
}

function libraryView() {
  const q = S.libQuery.trim().toLowerCase();
  const hit = (t) => !q || String(t).toLowerCase().includes(q);
  const all = S.catalog.slice().sort((a, b) => (!!S.native.library[b.id]) - (!!S.native.library[a.id]) || a.title.localeCompare(b.title));
  const games = all.filter((g) => g.kind !== "system" && hit(g.title));
  const tools = all.filter((g) => g.kind === "system" && hit(g.title));
  const home = S.libSel === "home" || (!S.libSel && S.lib.roms.length);
  const selRom = rom(S.libSel);
  const sel = selRom ? null : game(S.libSel) || (home ? null : all[0]);
  const gameItem = (g) => {
    const inst = S.native.library[g.id];
    const st = status(g);
    const from = inst ? instWt(g) : "";
    const tag = st.kind === "busy" ? st.label : inst && inst.running ? "Running" : st.kind === "update" && inst ? "Update" : from ? "branch" : "";
    return `<div class="item ${inst ? "installed" : ""} ${sel && sel.id === g.id ? "on" : ""}" data-lib="${esc(g.id)}" title="${esc(from ? "installed from " + branchName(sourceOf(g)) : g.title)}">
      <img src="${art(g, "icon")}" alt="">${esc(g.title)}<span class="st">${esc(tag)}</span></div>`;
  };
  const group = (key, label, n, body) => `<a class="group" data-group="${esc(key)}">${S.collapsed[key] ? "&#9656;" : "&#9662;"} ${esc(label)} (${n})</a>${S.collapsed[key] ? "" : body}`;
  const groups = [];
  for (const sy of S.lib.systems) {
    for (const sub of sy.systems || []) {
      const list = S.lib.roms.filter((r) => r.system_card === sy.id && r.system === sub.id && hit(r.title));
      if (!list.length) continue;
      const items = list.map((r) => {
        const played = (S.native.played || {})[r.id];
        const cls = sy.playable ? "installed" : "";
        return `<div class="item ${cls} ${selRom && selRom.id === r.id ? "on" : ""}" data-lib="${esc(r.id)}">
          ${r.cover ? `<img loading="lazy" src="${esc(r.cover)}" alt="">` : `<span class="noimg"></span>`}<span class="t">${esc(r.title)}</span>
          <span class="st">${played && played.running ? "Running" : ""}</span></div>`;
      }).join("");
      groups.push(group(sub.label, sub.label, list.length, items));
    }
  }
  const page = selRom ? romPage(selRom) : sel ? gamePage(sel) : home ? libraryHome() : `<div class="empty">No games.</div>`;
  return `<div class="library"><div class="side"><a class="home ${home && !selRom && !sel ? "on" : ""}" data-lib="home">HOME</a>
      <input id="libsearch" placeholder="Search" value="${esc(S.libQuery)}">
      ${games.length ? group("games", "Games", games.length, games.map(gameItem).join("")) : ""}
      ${tools.length ? group("players", "Players", tools.length, tools.map(gameItem).join("")) : ""}
      ${groups.join("")}</div>
    <div class="gamepage">${page}</div></div>`;
}

// the library's front: what was played lately, then a shelf of title screens per console
function libraryHome() {
  const played = S.native.played || {};
  const recent = S.lib.roms.filter((r) => played[r.id]).sort((a, b) => played[b.id].lastPlayed - played[a.id].lastPlayed).slice(0, 12);
  const tile = (r) => `<div class="cov" data-lib="${esc(r.id)}" title="${esc(r.title)}">
      ${r.cover ? `<img loading="lazy" src="${esc(r.cover)}" alt="">` : `<div class="noart">${esc(r.title)}</div>`}
      <div class="cap">${esc(r.title)}</div><span class="vb ${esc(r.verdict.level)}"></span></div>`;
  const d = S.lib.drawing || {};
  let out = `<div class="libhome">`;
  const mine = S.catalog.filter((g) => S.native.library[g.id]);
  if (mine.length) out += `<h3>Your games</h3><div class="shelf wide">${mine.map((g) => `<div class="cov" data-lib="${esc(g.id)}" title="${esc(g.title)}">
      <img src="${art(g, "header_460x215")}" alt="" style="aspect-ratio:460/215"><div class="cap">${esc(g.title)} <span class="dim">${esc(status(g).label)}</span></div></div>`).join("")}</div>`;
  if (d.busy) out += `<div class="card">Drawing title screens: ${d.drawn || 0} of ${d.of || "?"} (the machine runs each cartridge for ten seconds, headless).</div>`;
  if (recent.length) out += `<h3>Recent</h3><div class="shelf">${recent.map(tile).join("")}</div>`;
  for (const sy of S.lib.systems) {
    for (const sub of sy.systems || []) {
      const list = S.lib.roms.filter((r) => r.system_card === sy.id && r.system === sub.id);
      if (!list.length) continue;
      const key = "shelf:" + sub.label;
      const show = S.open[key] ? list : list.slice(0, 24);
      out += `<h3 id="shelf-${esc(sub.label.replace(/\W+/g, "-"))}"><a data-toggle="${esc(key)}">${esc(sub.label)}</a> <small>${plural(list.length, "cartridge")}</small>
        ${list.length > 24 ? `<a class="more" data-toggle="${esc(key)}">${S.open[key] ? "show fewer" : "show all"}</a>` : ""}</h3><div class="shelf">${show.map(tile).join("")}</div>`;
    }
  }
  if (!S.lib.roms.length) out += `<div class="empty">No cartridges found. <a data-settings="1">Add a folder of cartridges</a> in Settings.</div>`;
  return out + `</div>`;
}

// a cartridge: its title screen, how far the card model gets with it, and the player's big button
function romStatus(r) {
  const sy = sysOf(r);
  if (!sy.playable) return { kind: "na", label: "Not playable yet" };
  const pl = playerOf(r);
  if (!pl) return { kind: "na", label: "No player" };
  const ps = status(pl);
  if (ps.kind === "busy") return { kind: "busy", label: ps.label };
  if (ps.kind === "install") return { kind: "install", label: "Install " + pl.title, player: pl.id };
  const played = (S.native.played || {})[r.id];
  if (played && played.running) return { kind: "stop", label: "Stop" };
  return { kind: "play", label: "Play" };
}
function romButton(r) {
  const st = romStatus(r);
  const cls = st.kind === "na" ? "busy" : st.kind;
  const icon = st.kind === "play" ? "&#9654;&nbsp; " : st.kind === "install" ? "&#11015;&nbsp; " : "";
  return `<button class="btn ${cls}" data-romact="${esc(r.id)}">${icon}${esc(st.label)}</button>`;
}
function romAct(r) {
  const st = romStatus(r);
  if (st.kind === "install") { const pl = game(st.player); send("install", { id: st.player, branch: pl ? wtOf(shown(pl)) : "" }); }
  else if (st.kind === "play") send("play_rom", { id: r.id, player: sysOf(r).player, path: r.path, title: r.title });
  else if (st.kind === "stop") send("stop", { id: r.id });
  else if (st.kind === "na") toast(sysOf(r).playable === false ? `${subLabel(r)} cartridges are listed; the card model does not play them yet.` : "No player for this console.");
}
function romPage(r) {
  const played = (S.native.played || {})[r.id];
  const h = r.header || {};
  const v = r.verdict || {};
  const pl = playerOf(r);
  const vtext = { verified: "Verified", playable: "Playable", unsupported: "Unsupported", unavailable: "Not playable yet", unknown: "Unknown" }[v.level] || v.level;
  const facts = r.system_card === "gameboy" ? [
    ["Cartridge", h.title], ["Bank controller", (h.mbc || "none").toUpperCase() + (h.supported === false ? " (no card yet)" : "")],
    ["RAM", h.ram ? mb(h.ram) + (h.battery ? ", battery" : "") : "none"], ["Clock", h.rtc ? "MBC3 real-time clock" : "none"],
    ["ROM", mb(r.size)], ["Colour", r.system === "gbc" ? (h.cgb_only ? "Game Boy Color only" : "Game Boy Color enhanced") : "Game Boy"],
  ] : [["Cartridge", h.title], ["Game code", h.code], ["Size", mb(r.size)]];
  const ds = v.detail && v.detail.cpus ? Object.entries(v.detail.cpus).map(([k, c]) =>
    `<p><b>${esc(k.toUpperCase())}</b>: ${esc((c.instructions || 0).toLocaleString())} instructions, ${esc((c.distinct || 0).toLocaleString())} distinct;
      not modelled yet: ${esc((c.not_modelled || []).join(", ") || "nothing")}</p>`).join("") : "";
  return `<div class="hero rom" data-romcover="${esc(r.id)}"><div class="blur" style="background-image:url('${esc(r.cover || "")}')"></div>
      ${r.cover ? `<img class="shot" src="${esc(r.cover)}" alt="">` : ""}
      <div class="logo">${esc(r.title)}<small><a data-libgroup="${esc(subLabel(r))}">${esc(subLabel(r))}</a>${r.tags ? " &middot; " + esc(r.tags) : ""}</small></div></div>
    <div class="actionbar">${romButton(r)}
      <a class="stat" data-goview="profile">Last played<b>${played ? when(played.lastPlayed) : "Never"}</b></a>
      <a class="stat" data-goview="profile">Play time<b>${played ? playtime(played.playSeconds) : "None yet"}</b></a>
      <a class="stat" data-scroll="compat">Card model<b><span class="vb ${esc(v.level)}"></span> ${esc(vtext)}</b></a>
      <a class="stat" data-libgroup="${esc(subLabel(r))}">Console<b>${esc(subLabel(r))}</b></a>
      <div class="gear"><button class="iconbtn" data-gear="1" title="Manage">&#9881;</button>
        ${S.gear ? `<div class="menu"><a data-romreveal="${esc(r.path)}">Show the cartridge in Finder</a>
          ${pl ? `<a data-lib="${esc(pl.id)}">${esc(pl.title)}</a><a data-open="${esc(pl.id)}">${esc(pl.title)}: store page</a>` : ""}
          <a data-settings="1">Cartridge folders&hellip;</a></div>` : ""}</div>
    </div>
    ${pl ? `<div id="progress-${esc(pl.id)}" class="progress" style="padding:0 26px"></div>` : ""}
    ${S.lastErr[r.id] ? `<div class="banner"><p class="err">${esc(S.lastErr[r.id])}</p><div class="row"><a data-dismiss="${esc(r.id)}">Dismiss</a></div></div>` : ""}
    <div class="cols"><div>
        <div class="card" id="compat"><h4>Compatibility</h4><p class="verdict"><span class="vb ${esc(v.level)}"></span><b>${esc(vtext)}</b> &mdash; ${esc(v.text || "")}</p>
          ${v.reason ? `<p class="dim">Survey: ${esc(v.reason)}</p>` : ""}${ds}</div>
        ${pl ? `<div class="card"><h4>Controls</h4><p>${esc(pl.controls || "")}</p></div>
          <div class="card link" data-lib="${esc(pl.id)}"><h4>Played by</h4><p>${esc(pl.title)} v${esc(pl.version)} &middot; ${esc(status(pl).label)}</p></div>` : ""}
      </div><div>
        <div class="card"><h4>Cartridge</h4><div class="factlist">${facts.map(([k, x]) => `<div><span>${esc(k)}</span>${esc(x || "—")}</div>`).join("")}</div></div>
        <div class="card"><h4>File</h4><a class="path" data-romreveal="${esc(r.path)}" title="Show in Finder">${esc(r.path)}</a><p class="dim">Played where it is: nothing is copied.</p></div>
      </div></div>`;
}

function gamePage(g) {
  const inst = S.native.library[g.id];
  const got = inst ? inst.achievements || [] : [];
  const nGot = got.slice(0, (g.achievements || []).length).filter(Boolean).length;
  const v = shown(g);
  const src = sourceOf(g);
  return `<div class="hero" data-open="${esc(g.id)}" title="Store page" style="background-image:url('${media(v, "hero_1920x620") || art(g, "hero_1920x620")}')"><div class="logo">${esc(g.title.toUpperCase())}
      <small>${inst ? `installed v${esc(inst.version)} from ${esc(branchName(src || { worktree: inst.source }))}` : `v${esc(v.version)} &middot; ${esc(branchName(v))}`}</small></div></div>
    <div class="actionbar">${bigButton(g)}
      <a class="stat" data-goview="profile">Last played<b>${inst ? when(inst.lastPlayed) : "Never"}</b></a>
      <a class="stat" data-goview="profile">Play time<b>${inst ? playtime(inst.playSeconds) : "None yet"}</b></a>
      <a class="stat" data-scroll="achievements">Achievements<b>${nGot}/${(g.achievements || []).length}</b></a>
      <a class="stat" data-build="${esc(g.id)}" data-wt="${esc(inst ? instWt(g) : wtOf(v))}">Size on disk<b>${inst ? mb(inst.size) : v.build ? mb(v.build.size) : "—"}</b></a>
      <a class="stat" data-scroll="versions">Version<b>${esc(inst ? inst.version : v.version)}${versions(g).length > 1 ? ` <span class="dim">+${versions(g).length - 1}</span>` : ""}</b></a>
      <div class="gear"><button class="iconbtn" data-gear="1" title="Manage">&#9881;</button>
        ${S.gear ? `<div class="menu">${inst ? `<a data-verify="${esc(g.id)}">Verify integrity of game files</a>
          <a data-reveal="${esc(g.id)}">Browse local files</a>` : ""}<a data-open="${esc(g.id)}">Store page</a>
          <a data-build="${esc(g.id)}" data-wt="${esc(wtOf(v))}">Build details</a><a data-scroll="versions">Versions and branches</a>
          ${inst ? `<a data-uninstall="${esc(g.id)}">Uninstall</a>` : ""}</div>` : ""}</div>
    </div>
    <div id="progress-${esc(g.id)}" class="progress" style="padding:0 26px"></div>
    ${problem(g)}
    <div class="cols"><div>
        ${inst && src && src.build && src.build.build !== inst.build ? `<div class="card"><h4>Update available</h4>Version ${esc(src.version)} (build ${esc(src.build.build)}) from ${esc(branchName(src))} is ready.
          <div class="row"><button class="btn small update" data-act="${esc(g.id)}">Update now</button> <a data-build="${esc(g.id)}" data-wt="${esc(wtOf(src))}">what's in it</a></div></div>` : ""}
        ${src && src.build_due && !src.build_error ? `<div class="card"><h4>New build from the cards</h4>The cards of ${esc(branchName(src))} changed since its last build: the next update compiles them first.
          <div class="row"><button class="btn small update" data-act="${esc(g.id)}">Build and update</button></div></div>` : ""}
        <div id="versions">${versionsCard(g)}</div>
        <div class="card news"><h4>What's new</h4>${newsEntries(g, v)}</div>
      </div><div>
        <div class="card" id="achievements"><h4>Achievements</h4>${achList(g, got)}</div>
        <div class="card"><h4>Info</h4><div class="factlist">
          <div><span>Version</span><a data-scroll="versions">${esc(inst ? inst.version : v.version)}</a></div>
          <div><span>Build</span><a data-build="${esc(g.id)}" data-wt="${esc(inst ? instWt(g) : wtOf(v))}">${esc(inst ? inst.build : v.build ? v.build.build : "—")}</a></div>
          <div><span>Branch</span><a data-goview="work">${esc(branchName(src || v))}</a></div>
          <div><span>Developer</span><a data-filter="dev" data-value="${esc(g.developer)}">${esc(g.developer)}</a></div>
          <div><span>Engine</span>card-language logic, native code via the C card</div></div></div>
      </div></div>`;
}

// every session's branch: what it changed, what it has not committed, and the programs it has (a section of IN
// PROGRESS, below the projects)
function workSection() {
  if (!S.work) return `<div class="work"><h2>Every branch</h2><div class="empty">Reading every branch of the repository&hellip;</div></div>`;
  const f = S.workFilter;
  const trees = S.work.worktrees.filter((w) => !f || w.areas.includes(f) || w.programs.some((p) => p.id === f));
  const busy = trees.filter((w) => w.own || w.ahead_count || w.uncommitted);
  const idle = trees.filter((w) => !(w.own || w.ahead_count || w.uncommitted));
  const counts = {};
  for (const w of S.work.worktrees) for (const a of w.areas) counts[a] = (counts[a] || 0) + 1;
  const chips = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 18);
  return `<div class="work">
    <div class="workhead"><h2>Every branch</h2>
      <span class="dim">${plural(S.work.worktrees.length, "branch", "branches")} of this repository &middot; ${plural(S.work.worktrees.filter((w) => w.programs.length).length, "with programs", "with programs")} &middot; read ${since(S.work.time)}</span>
      <button class="btn small ghost" data-workreload="1">Refresh</button></div>
    <div class="chips"><a class="chip ${f ? "" : "on"}" data-area="">everything</a>${chips.map(([a, n]) => `<a class="chip ${f === a ? "on" : ""}" data-area="${esc(a)}">${esc(a)} <span>${n}</span></a>`).join("")}</div>
    ${busy.map(wtCard).join("") || `<div class="empty">No branch matches.</div>`}
    ${idle.length ? `<div class="section-title"><a data-toggle="idle">${S.open.idle ? "&#9662;" : "&#9656;"} ${plural(idle.length, "branch", "branches")} with nothing beyond main</a></div>
      ${S.open.idle ? idle.map(wtCard).join("") : ""}` : ""}
  </div>`;
}
function wtCard(w) {
  const k = (x) => `${x}:${w.name}`;
  const last = w.ahead[0];
  return `<div class="card wt ${w.own ? "own" : ""}">
    <div class="wthead"><a class="bname" data-toggle="${esc(k("commits"))}">${esc(w.branch || "detached at " + w.head)}</a>
      ${w.own ? `<span class="tag">the arcade's own checkout</span>` : ""}<span class="when">${esc(since(Math.max(w.time, last ? last.time : 0)))}</span></div>
    <div class="subject"><a data-commit="${esc(w.name)}" data-hash="${esc(w.head)}">${esc(w.subject || "(no commits)")}</a></div>
    <div class="wtstats"><a data-toggle="${esc(k("commits"))}">${plural(w.ahead_count, "commit")} not on main</a> &middot;
      <a data-toggle="${esc(k("files"))}">${plural(w.uncommitted, "uncommitted change")}</a> &middot;
      <a data-revealpath="${esc(w.path)}" title="${esc(w.path)}">${esc(w.name)}</a></div>
    ${w.areas.length ? `<div class="chips">${w.areas.map((a) => `<a class="chip small ${S.workFilter === a ? "on" : ""}" data-area="${esc(a)}">${esc(a)}</a>`).join("")}</div>` : ""}
    ${S.open[k("commits")] ? `<div class="list">${w.ahead.map((c) => `<a class="li" data-commit="${esc(w.name)}" data-hash="${esc(c.hash)}"><code>${esc(c.hash)}</code> ${esc(c.subject)} <span class="dim">${esc(since(c.time))}</span></a>`).join("")
      || `<div class="dim">Nothing beyond main.</div>`}${w.ahead_count > w.ahead.length ? `<div class="dim">and ${w.ahead_count - w.ahead.length} older</div>` : ""}</div>` : ""}
    ${S.open[k("files")] ? `<div class="list">${w.uncommitted_files.map((p) => `<a class="li" data-revealpath="${esc(w.path + "/" + p)}"><code>${esc(p)}</code></a>`).join("")
      || `<div class="dim">Everything is committed.</div>`}${w.uncommitted > w.uncommitted_files.length ? `<div class="dim">and ${w.uncommitted - w.uncommitted_files.length} more</div>` : ""}</div>` : ""}
    ${w.status_error ? `<p class="err small">This branch could not say whether its programs need a build: ${esc(w.status_error)}</p>` : ""}
    ${w.programs.length ? `<div class="progs">${w.programs.map((p) => progRow(w, p)).join("")}</div>` : ""}
  </div>`;
}
function progRow(w, p) {
  const g = game(p.id);
  const wt = w.own ? "" : w.name;
  const v = g ? versionOf(g, wt) : null;
  const state = p.building ? "building now" : p.build_error ? "the cards in progress don't build yet"
    : p.build_due ? "the cards changed since its last build" : p.build_due === false ? "build current with its cards" : p.build ? "asking the branch" : "not built yet";
  return `<div class="prog"><img src="${g ? media(v || g, "icon") || art(g, "icon") : ""}" alt="">
    <div><a class="t" data-open="${esc(p.id)}" data-wt="${esc(wt)}">${esc(p.title)}</a> <span class="v">v${esc(p.version)}</span>
      <div class="dim">${p.build ? `<a data-build="${esc(p.id)}" data-wt="${esc(wt)}">build ${esc(p.build.build)}</a> of ${esc((p.build.created || "").slice(0, 10))} &middot; ` : ""}${esc(state)}</div></div>
    <div class="ctl">${g && v ? verButton(g, v) : ""}</div></div>`;
}

function downloadsView() {
  const id = S.native.downloading || Object.keys(S.progress)[0];
  const g = id && game(id);
  const p = id && S.progress[id];
  const cur = S.rates.length ? S.rates[S.rates.length - 1] : 0;
  return `<div class="downloads">
    <div class="dlhead"><canvas id="graph" width="760" height="120"></canvas>
      <div class="dlstats">Current<b>${rate(cur)}</b><br>Peak<b>${rate(S.peak)}</b><br>Total<b>${mb(S.totalDown)}</b></div></div>
    <div class="section-title">Downloading</div>
    ${g ? `<div class="dlitem"><div class="art" data-lib="${esc(g.id)}" style="background-image:url('${art(g, "header_460x215")}')"></div>
      <div><a class="name" data-lib="${esc(g.id)}">${esc(g.title)}</a><div class="phase">${esc(p ? phaseLabel(p) : "Queued")}</div>
        <div id="progress-${esc(g.id)}" class="progress"></div></div>
      <div class="ctl">${S.native.paused ? `<button class="btn small install" data-resume="1">Resume</button>` : `<button class="btn small ghost" data-pause="1">Pause</button>`}
        <button class="btn small ghost" data-cancel="1">Cancel</button></div></div>` : `<div class="empty">Nothing is downloading.</div>`}
    <div class="section-title">Completed</div>
    ${S.completed.length ? S.completed.map((c) => { const cg = game(c.id); return cg ? `<div class="dlitem"><div class="art" data-lib="${esc(cg.id)}" style="background-image:url('${art(cg, "header_460x215")}')"></div>
      <div><a class="name" data-lib="${esc(cg.id)}">${esc(cg.title)}</a><div class="phase">Installed ${new Date(c.at).toLocaleTimeString()}</div></div>
      <div class="ctl">${bigButton(cg, true)}</div></div>` : ""; }).join("") : `<div class="empty">Nothing yet.</div>`}
  </div>`;
}

function newsView() {
  return `<div class="store"><h2>News and patch notes</h2>${S.catalog.map((g) => {
    const newer = versions(g).filter((v) => v.worktree && v.newer);
    return `<div class="card news"><h4><a data-open="${esc(g.id)}">${esc(g.title)}</a></h4>${newsEntries(g)}
      ${newer.map((v) => `<div class="entry"><a data-open="${esc(g.id)}" data-wt="${esc(v.worktree)}"><b>In development: ${esc(g.title)} ${esc(v.version)}</b> <small>${esc(branchName(v))}</small></a>
        ${(v.changelog || []).slice(-1).map((c) => `<ul>${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`).join("")}</div>`).join("")}</div>`;
  }).join("")}</div>`;
}

function profileView() {
  const lib = S.native.library;
  const n = Object.keys(lib).length;
  let ach = 0, total = 0, secs = 0;
  for (const g of S.catalog) {
    total += (g.achievements || []).length;
    if (lib[g.id]) { ach += (lib[g.id].achievements || []).slice(0, (g.achievements || []).length).filter(Boolean).length; secs += lib[g.id].playSeconds || 0; }
  }
  const carts = Object.entries(S.native.played || {}).sort((a, b) => b[1].lastPlayed - a[1].lastPlayed);
  for (const [, c] of carts) secs += c.playSeconds || 0;
  const user = S.native.settings.user || "You";
  return `<div class="profile"><div class="head"><div class="avatar">${esc(user[0] || "?")}</div>
    <div><h2>${esc(user)}</h2><a class="stat" data-golibhome="1">Games<b>${n}</b></a></div>
    <a class="stat" style="margin-left:auto" data-scroll="showcase">Achievements<b>${ach} / ${total}</b></a><a class="stat" data-scroll="activity">Play time<b>${playtime(secs)}</b></a></div>
    <h2 class="ph" id="activity">Recent activity</h2>
    ${S.catalog.filter((g) => lib[g.id]).map((g) => `<div class="card link" data-lib="${esc(g.id)}"><b>${esc(g.title)}</b> <span class="dim">&middot; ${playtime(lib[g.id].playSeconds)} &middot; last played ${when(lib[g.id].lastPlayed)}</span></div>`).join("")}
    ${carts.slice(0, 12).map(([id, c]) => { const r = rom(id); return r ? `<div class="card link" data-lib="${esc(id)}"><b>${esc(r.title)}</b> <span class="dim">&middot; ${esc(subLabel(r))} &middot; ${playtime(c.playSeconds)} &middot; last played ${when(c.lastPlayed)}</span></div>` : ""; }).join("")}
    ${!n && !carts.length ? `<div class="empty">Nothing played yet. <a data-gostore="1">Visit the store</a>.</div>` : ""}
    <h2 class="ph" id="showcase">Achievement showcase</h2>
    ${S.catalog.filter((g) => (g.achievements || []).length).map((g) => `<div class="card"><h4><a data-lib="${esc(g.id)}">${esc(g.title)}</a></h4><div class="achlist">${(g.achievements || []).map((a, k) => { const gotIt = lib[g.id] && (lib[g.id].achievements || [])[k];
      return gotIt ? `<div class="a got" data-ach="${esc(g.id)}" data-k="${k}"><div class="ico">&#9733;</div><div><b>${esc(a.name)}</b><small>${esc(a.description)}</small></div></div>` : ""; }).join("") || `<div class="empty">None unlocked yet. <a data-scroll="achievements" data-lib="${esc(g.id)}">See them all</a></div>`}</div></div>`).join("")}
  </div>`;
}

// -- dialogs --------------------------------------------------------------------------------------------------------
function modal(html) {
  $("#modal").innerHTML = html;
  $("#modal").classList.remove("hidden");
  bind();
}
function settingsDialog() {
  const b = S.native.settings.bandwidth || 0;
  const opts = [[0, "No limit"], [262144, "256 KB/s"], [1048576, "1 MB/s"], [4194304, "4 MB/s"], [16777216, "16 MB/s"]];
  $("#modal").innerHTML = `<div class="dialog"><h3>SETTINGS</h3><div class="body">
    <label>Limit bandwidth to</label><select id="bw">${opts.map(([v, t]) => `<option value="${v}" ${v === b ? "selected" : ""}>${t}</option>`).join("")}</select>
    <label>Library folder</label><input value="${esc(S.native.libraryPath || "")}" readonly>
    ${S.lib.systems.map((sy) => `<label>${esc(sy.title)}: cartridge folders</label>
      ${(sy.folders || []).map((f) => `<div class="folder"><span>${esc(f)}</span><a data-unfolder="${esc(sy.id)}" data-path="${esc(f)}">Remove</a></div>`).join("")
        || `<div class="dim">None yet.</div>`}
      <button class="btn small ghost" data-addfolder="${esc(sy.id)}">Add a folder&hellip;</button>`).join("")}
    <label>About</label><div>Cardmodel Arcade. The arcade service builds every game from its cards (card-language logic, compiled to native code) and serves it as a depot of checked chunks. Each program's versions on the repository's other branches are installable from its Versions card or the Work tab.</div>
    </div><div class="foot"><button class="btn small install" id="ok">OK</button></div></div>`;
  $("#modal").classList.remove("hidden");
  $("#ok").onclick = () => { send("settings", { bandwidth: parseInt($("#bw").value, 10) }); $("#modal").classList.add("hidden"); };
  document.querySelectorAll("[data-addfolder]").forEach((el) => (el.onclick = () => send("pick_folder", { system: el.dataset.addfolder })));
  document.querySelectorAll("[data-unfolder]").forEach((el) => (el.onclick = () => folders({ system: el.dataset.unfolder, remove: el.dataset.path })));
}
// the cartridge folders live with the service (library.json beside the saves); after a change, list again
async function folders(change) {
  try {
    await fetch("/api/library/folders", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change) });
    S.libLoaded = 0;
    await refresh();
    if (!$("#modal").classList.contains("hidden")) settingsDialog();
    toast(change.add ? "Looking for cartridges in " + change.add : "Folder removed.");
  } catch (e) { toast("The arcade service did not answer."); }
}
function buildDialog(id, wt) {
  const g = game(id);
  if (!g) return;
  const v = versionOf(g, wt) || shown(g);
  const b = v.build;
  const inst = S.native.library[id];
  const mine = inst && instWt(g) === wtOf(v);
  const row = (k, x) => `<div><span>${esc(k)}</span>${x}</div>`;
  modal(`<div class="dialog"><h3>${esc(g.title)} ${esc(v.version)} &mdash; ${esc(branchName(v))}</h3><div class="body"><div class="factlist">
    ${row("State", esc(verState(v)))}
    ${b ? row("Build", `<code>${esc(b.build)}</code>`) + row("Built", esc(b.created)) + row("Build time", b.seconds != null ? esc(b.seconds) + " s" : "—")
      + row("Size", mb(b.size)) + row("Chunks", esc(b.chunks)) + row("Program", `<code>${esc(b.executable)}</code>`) : ""}
    ${inst ? row("Installed", `v${esc(inst.version)} build <code>${esc(inst.build)}</code> from ${esc(branchName(sourceOf(g) || { worktree: inst.source }))}`) + row("On disk", mb(inst.size)) + row("Installed on", when(inst.installedAt)) : row("Installed", "no")}
    </div>${v.build_error ? `<pre class="err">${esc(v.build_error)}</pre>` : ""}</div>
    <div class="foot">${inst ? `<button class="btn small ghost" data-reveal="${esc(id)}" data-close="1">Browse local files</button> <button class="btn small ghost" data-verify="${esc(id)}" data-close="1">Verify files</button> ` : ""}
      ${!mine ? `<button class="btn small install" data-verinstall="${esc(id)}" data-wt="${esc(wtOf(v))}" data-close="1">${inst ? "Switch to this version" : "Install"}</button> ` : ""}
      <button class="btn small ghost" data-close="1">Close</button></div></div>`);
}
function achDialog(id, k) {
  const g = game(id);
  const a = g && (g.achievements || [])[k];
  if (!a) return;
  const inst = S.native.library[id];
  const got = inst && (inst.achievements || [])[k];
  modal(`<div class="dialog"><h3>${esc(a.name)}</h3><div class="body"><div class="achbig ${got ? "got" : ""}">&#9733;</div>
    <p>${esc(a.description)}</p><p class="dim">${got ? "Unlocked" : "Locked"} &middot; ${esc(g.title)} &middot; ${k + 1} of ${g.achievements.length}</p></div>
    <div class="foot"><button class="btn small ghost" data-lib="${esc(id)}" data-close="1">Library page</button> <button class="btn small ghost" data-close="1">Close</button></div></div>`);
}
async function commitDialog(wt, hash) {
  modal(`<div class="dialog wide"><h3>${esc(hash)}</h3><div class="body"><div class="dim">Reading the commit&hellip;</div></div></div>`);
  try {
    const r = await fetch(`/api/work/${encodeURIComponent(wt)}/commit/${encodeURIComponent(hash)}`);
    const c = await r.json();
    if (c.error) throw new Error(c.error);
    const w = S.work && S.work.worktrees.find((x) => x.name === wt);
    modal(`<div class="dialog wide"><h3>${esc(c.subject)}</h3><div class="body">
      <p class="dim"><code>${esc(c.hash.slice(0, 12))}</code> &middot; ${esc(c.author)} &middot; ${esc(new Date(c.time * 1000).toLocaleString())} &middot; ${esc(w ? w.branch : wt)}</p>
      ${c.body ? `<pre class="msg">${esc(c.body)}</pre>` : ""}
      ${c.areas.length ? `<div class="chips">${c.areas.map((a) => `<a class="chip small" data-area="${esc(a)}" data-close="1">${esc(a)}</a>`).join("")}</div>` : ""}
      <label>${plural(c.files.length, "file")} changed</label><div class="list">${c.files.map((f) => `<a class="li" data-revealpath="${esc((w ? w.path : "") + "/" + f.path)}"><code>${esc(f.path)}</code>
        <span class="plus">${f.added != null ? "+" + f.added : ""}</span> <span class="minus">${f.removed != null ? "-" + f.removed : ""}</span></a>`).join("") || `<div class="dim">No file changes of its own (a merge).</div>`}</div></div>
      <div class="foot"><button class="btn small ghost" data-close="1">Close</button></div></div>`);
  } catch (e) {
    modal(`<div class="dialog"><h3>${esc(hash)}</h3><div class="body">Could not read the commit: ${esc(e.message || e)}</div><div class="foot"><button class="btn small ghost" data-close="1">Close</button></div></div>`);
  }
}
function serviceDialog() {
  const w = S.work ? S.work.worktrees : [];
  const own = w.find((x) => x.own);
  modal(`<div class="dialog"><h3>ARCADE SERVICE</h3><div class="body"><div class="factlist">
    <div><span>State</span>${S.service ? "connected" : S.service === false ? "unreachable" : "connecting"}</div>
    <div><span>Address</span>${esc(location.origin)}</div>
    <div><span>Checkout</span>${own ? `<a data-revealpath="${esc(own.path)}">${esc(own.path)}</a>` : "—"}</div>
    <div><span>Branch</span>${own ? esc(own.branch) : "—"}</div>
    <div><span>Programs</span>${S.catalog.length}</div>
    <div><span>Cartridges</span>${S.lib.roms.length}</div>
    <div><span>Branches</span><a data-goview="work" data-close="1">${w.length}</a></div></div></div>
    <div class="foot"><button class="btn small ghost" data-reloadall="1" data-close="1">Reload</button> <button class="btn small ghost" data-close="1">Close</button></div></div>`);
}
function ask(title, text, yes, then) {
  $("#modal").innerHTML = `<div class="dialog"><h3>${esc(title)}</h3><div class="body">${esc(text)}</div>
    <div class="foot"><button class="btn small ghost" id="no">Cancel</button> <button class="btn small stop" id="yes">${esc(yes)}</button></div></div>`;
  $("#modal").classList.remove("hidden");
  $("#no").onclick = () => $("#modal").classList.add("hidden");
  $("#yes").onclick = () => { $("#modal").classList.add("hidden"); then(); };
}

// -- progress, graph, toast ---------------------------------------------------------------------------------------
function renderProgress() {
  const id = S.native.downloading || Object.keys(S.progress)[0];
  const p = id && S.progress[id];
  const fill = $("#dl-mini-fill");
  if (p && p.total) {
    fill.style.width = Math.floor((100 * p.done) / p.total) + "%";
    $("#dl-mini").textContent = `${(game(id) || {}).title || id}: ${phaseLabel(p)}`;
  } else {
    fill.style.width = "0";
    $("#dl-mini").textContent = "Manage";
  }
  for (const [gid, q] of Object.entries(S.progress)) {
    const el = document.getElementById("progress-" + gid);
    if (!el) continue;
    const pct = q.total ? Math.floor((100 * q.done) / q.total) : 0;
    const extra = q.phase === "downloading" ? ` &middot; ${mb(q.done)} of ${mb(q.total)} &middot; ${rate(q.rate || 0)}` : q.label ? ` &middot; ${esc(q.label)}` : "";
    el.innerHTML = `<div class="bar"><div class="fill" style="width:${pct}%"></div></div><div class="label">${esc(phaseLabel(q))}${extra}</div>`;
  }
  const c = $("#graph");
  if (c) {
    const x = c.getContext("2d"), w = c.width, h = c.height;
    x.clearRect(0, 0, w, h);
    x.strokeStyle = "#1f2c3a";
    for (let k = 1; k < 4; k++) { x.beginPath(); x.moveTo(0, (h * k) / 4); x.lineTo(w, (h * k) / 4); x.stroke(); }
    const max = Math.max(1, ...S.rates);
    x.beginPath(); x.moveTo(0, h);
    S.rates.forEach((r, k) => x.lineTo((k * w) / Math.max(1, 239), h - (r / max) * (h - 8)));
    x.lineTo(((S.rates.length - 1) * w) / 239, h); x.closePath();
    x.fillStyle = "rgba(102,192,244,.35)"; x.fill();
    x.strokeStyle = "#66c0f4"; x.stroke();
  }
}
let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), 3800);
}

// -- events ---------------------------------------------------------------------------------------------------------
function installVersion(id, wt) {
  const g = game(id), v = g && versionOf(g, wt);
  if (!g || !v) return;
  const inst = S.native.library[id];
  const doit = () => send(inst && instWt(g) === (wt || "") ? "update" : "install", { id, branch: wt || "" });
  if (inst && instWt(g) !== (wt || "")) ask(`Switch ${g.title} to ${v.version}?`, `The installed build is replaced by ${g.title} ${v.version} from ${branchName(v)}${v.build_due || !v.build ? ", built from its cards first" : ""}. Saves and achievements stay.`, "Switch", doit);
  else doit();
}
async function retry(id, wt) {
  delete S.lastErr[id]; delete S.notice[id];
  if (bridge) { send("update", { id, branch: wt || "" }); return; }
  try {
    await fetch(`/api/build/${encodeURIComponent(id)}${wt ? "?branch=" + encodeURIComponent(wt) : ""}`, { method: "POST" });
    toast("Building from the cards again; the page shows the result when it is done.");
  } catch (e) { toast("The arcade service did not answer."); }
  setTimeout(refresh, 3000);
}
function scrollTo(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}
function filterTo(kind, value) {
  if (kind === "dev" || kind === "tag" || kind === "genre") go("browse", { mode: kind, value });
}
function bind() {
  // a click on anything that does something also closes the manage menu (the page's own click does not get there)
  const on = (sel, f) => document.querySelectorAll(sel).forEach((el) => (el.onclick = (e) => {
    e.stopPropagation();
    const menu = S.gear && !el.dataset.gear;
    if (menu) S.gear = false;
    f(el, e);
    if (menu && document.querySelector("#view .menu")) render();
  }));
  // an element with several of these keeps the last one bound: data-scroll comes before data-lib on purpose
  on("[data-scroll]", (el) => scrollTo(el.dataset.scroll));
  // a link to a program shows the version it names (a branch), else the installed one, else the program's own
  on("[data-open]", (el) => { S.shot = 0; if (el.dataset.wt != null) S.ver[el.dataset.open] = el.dataset.wt; else delete S.ver[el.dataset.open];
    $("#modal").classList.add("hidden"); go("app", el.dataset.open); });
  on("[data-act]", (el) => { const g = game(el.dataset.act); if (g) act(g); });
  on("[data-golib]", (el) => go("library", el.dataset.golib));
  on("[data-lib]", (el) => { S.libSel = el.dataset.lib; S.gear = false; $("#modal").classList.add("hidden");
    if (S.view !== "library") go("library", el.dataset.lib); else { render(); $("#view").querySelector(".gamepage").scrollTop = 0; }
    if (el.dataset.scroll) setTimeout(() => scrollTo(el.dataset.scroll), 50); });
  on("[data-romact]", (el) => { const r = rom(el.dataset.romact); if (r) romAct(r); });
  on("[data-romreveal]", (el) => { S.gear = false; send("reveal_rom", { path: el.dataset.romreveal }); render(); });
  on("[data-revealpath]", (el) => { if (bridge) send("reveal_path", { path: el.dataset.revealpath }); else toast(el.dataset.revealpath); });
  const ls = $("#libsearch");
  if (ls) ls.oninput = () => { S.libQuery = ls.value; render(); };
  const ss = $("#search");
  if (ss) {
    ss.oninput = () => { S.storeQuery = ss.value; if (S.view === "browse" && S.arg && S.arg.mode === "search") { S.arg = { mode: "search", value: ss.value }; render(); } else if (ss.value.trim()) go("browse", { mode: "search", value: ss.value }); };
    ss.onkeydown = (e) => { if (e.key === "Enter") go("browse", { mode: "search", value: ss.value }); if (e.key === "Escape") { S.storeQuery = ""; go("store"); } };
  }
  on("[data-shot]", (el) => { S.shot = parseInt(el.dataset.shot, 10); render(); });
  on("[data-feat]", (el) => { S.shot = parseInt(el.dataset.feat, 10); render(); });
  on("[data-gear]", () => { S.gear = !S.gear; render(); });
  on("[data-verify]", (el) => { S.gear = false; send("verify", { id: el.dataset.verify }); render(); });
  on("[data-reveal]", (el) => { S.gear = false; send("reveal", { id: el.dataset.reveal }); render(); });
  on("[data-uninstall]", (el) => { S.gear = false; render(); ask(`Uninstall ${(game(el.dataset.uninstall) || {}).title}?`, "Its files are removed from this Mac. Its saves and achievements stay.", "Uninstall", () => send("uninstall", { id: el.dataset.uninstall })); });
  on("[data-pause]", () => send("pause"));
  on("[data-resume]", () => send("resume"));
  on("[data-cancel]", () => send("cancel"));
  on("[data-browse]", (el) => go("browse", { mode: el.dataset.browse }));
  on("[data-gostore]", () => go("store"));
  on("[data-goview]", (el) => { $("#modal").classList.add("hidden"); go(el.dataset.goview); });
  on("[data-golibhome]", () => { S.libSel = "home"; go("library", "home"); });
  on("[data-libgroup]", (el) => { S.libSel = "home"; S.libQuery = ""; go("library", "home"); setTimeout(() => scrollTo("shelf-" + el.dataset.libgroup.replace(/\W+/g, "-")), 60); });
  on("[data-filter]", (el) => { $("#modal").classList.add("hidden"); filterTo(el.dataset.filter, el.dataset.value); });
  on("[data-toggle]", (el) => { const k = el.dataset.toggle; const def = el.dataset.def === "1"; S.open[k] = !(S.open[k] != null ? S.open[k] : def); render(); });
  on("[data-group]", (el) => { const k = el.dataset.group; S.collapsed[k] = !S.collapsed[k]; render(); });
  on("[data-ver]", (el) => { S.ver[el.dataset.ver] = el.dataset.wt; S.shot = 0; render(); });
  on("[data-verinstall]", (el) => { $("#modal").classList.add("hidden"); installVersion(el.dataset.verinstall, el.dataset.wt); });
  on("[data-build]", (el) => buildDialog(el.dataset.build, el.dataset.wt));
  on("[data-ach]", (el) => achDialog(el.dataset.ach, parseInt(el.dataset.k, 10)));
  on("[data-commit]", (el) => commitDialog(el.dataset.commit, el.dataset.hash));
  on("[data-area]", (el) => { S.workFilter = S.workFilter === el.dataset.area ? "" : el.dataset.area; $("#modal").classList.add("hidden"); if (S.view !== "dev") go("work"); else render(); });
  on("[data-workreload]", () => { toast("Reading every branch again…"); loadWork(true); });
  on("[data-retry]", (el) => retry(el.dataset.retry, el.dataset.wt));
  on("[data-dismiss]", (el) => {
    const id = el.dataset.dismiss, g = game(id), v = g && (sourceOf(g) || shown(g));
    delete S.lastErr[id]; delete S.notice[id];
    if (v && v.build_error) S.dismissed[id] = v.build_error;      // until the build fails differently
    render();
  });
  on("[data-settings]", () => settingsDialog());
  on("[data-romcover]", (el, e) => { if (e.target.tagName === "IMG") { const r = rom(el.dataset.romcover); if (r) romAct(r); } });
  on("[data-reloadall]", () => { S.libLoaded = 0; refresh(); loadWork(true); });
  document.querySelectorAll("#modal [data-close]").forEach((el) => {
    const f = el.onclick;
    if (f && f.closes) return;
    const g = (e) => { $("#modal").classList.add("hidden"); if (f) f(e); };
    g.closes = true;
    el.onclick = g;
  });
}
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => go(t.dataset.view, t.dataset.view === "library" ? S.libSel : null)));
$("#dl-link").onclick = () => go("downloads");
$("#settings-btn").onclick = settingsDialog;
$("#username").onclick = () => go("profile");
$("#service").onclick = serviceDialog;
$("#worklink").onclick = () => go("work");
$("#back").onclick = () => { const h = S.history.pop(); if (h) { S.future.push([S.view, S.arg]); go(h[0], h[1], true); } };
$("#fwd").onclick = () => { const f = S.future.pop(); if (f) { S.history.push([S.view, S.arg]); go(f[0], f[1], true); } };
$("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); };
document.addEventListener("click", () => { if (S.gear) { S.gear = false; render(); } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#modal").classList.add("hidden"); });
setInterval(() => { if (S.view === "store") { S.shot++; const st = $(".featured .main"); if (st && !document.activeElement.matches("input")) render(); } }, 6000);
setInterval(refresh, 15000);
refresh();
