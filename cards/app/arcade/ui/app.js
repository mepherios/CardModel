// Cardmodel Arcade's pages. The arcade service (same origin) gives the catalog, the store pages, the builds;
// the native app (window.webkit.messageHandlers.arcade) installs, verifies, launches and reports back through
// window.arcade.event(...). In a plain browser the store still works and installing says where to go.
"use strict";

const bridge = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.arcade;
const S = {
  catalog: [], details: {}, native: { library: {}, settings: { bandwidth: 0, user: "" }, downloading: null, native: !!bridge },
  progress: {}, rates: [], peak: 0, totalDown: 0, completed: [], view: "store", arg: null, history: [], future: [],
  gear: false, shot: 0, libSel: null, lastErr: {},
  lib: { systems: [], roms: [], drawing: {} }, libQuery: "", libLoaded: 0,
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
      const g = game(e.id); delete S.progress[e.id];
      S.completed.unshift({ id: e.id, at: Date.now() });
      toast(`${g ? g.title : e.id} is ready to play.`); refresh(); return;
    }
    if (e.type === "error") { delete S.progress[e.id]; S.lastErr[e.id] = e.message; toast("Problem: " + e.message); render(); return; }
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

// -- data ------------------------------------------------------------------------------------------------------------
async function refresh() {
  try {
    const r = await fetch("/api/catalog");
    S.catalog = await r.json();
    $("#service").className = "dot ok";
    $("#service").title = "Arcade service: connected";
  } catch (e) {
    $("#service").className = "dot bad";
    $("#service").title = "Arcade service: unreachable";
  }
  if (!S.libLoaded || (S.lib.drawing && S.lib.drawing.busy)) {
    try {
      const r = await fetch("/api/library");
      S.lib = await r.json();
      S.libLoaded = Date.now();
    } catch (e) { /* the service is older or down: no cartridges */ }
  }
  if (bridge) send("state");
  render();
}
async function details(id) {
  if (!S.details[id]) {
    const r = await fetch("/api/game/" + encodeURIComponent(id));
    S.details[id] = await r.json();
  }
  return S.details[id];
}

// -- what the big button says -------------------------------------------------------------------------------------
function status(g) {
  const inst = S.native.library[g.id];
  const p = S.progress[g.id];
  if (S.native.downloading === g.id || p) return { kind: "busy", label: p ? phaseLabel(p) : "Queued" };
  if (!inst) return { kind: "install", label: "Install" };
  if (inst.running) return { kind: "stop", label: "Stop" };
  if (g.build_due || !g.build || g.build.build !== inst.build) return { kind: "update", label: "Update" };
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
  if (st.kind === "install" || st.kind === "update") send(st.kind, { id: g.id });
  else if (st.kind === "play") send("play", { id: g.id });
  else if (st.kind === "stop") send("stop", { id: g.id });
}
function bigButton(g, small) {
  const st = status(g);
  const cls = st.kind === "busy" ? "busy" : st.kind;
  const icon = st.kind === "play" ? "&#9654;&nbsp; " : st.kind === "install" || st.kind === "update" ? "&#11015;&nbsp; " : "";
  return `<button class="btn ${cls}${small ? " small" : ""}" data-act="${esc(g.id)}">${icon}${esc(st.label)}</button>`;
}

// -- views ----------------------------------------------------------------------------------------------------------
function go(view, arg, noHistory) {
  if (!noHistory) { S.history.push([S.view, S.arg]); S.future = []; }
  S.view = view; S.arg = arg; S.gear = false;
  if (view === "library" && arg) S.libSel = arg;
  render();
  $("#view").scrollTop = 0;
}
function render() {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.dataset.view === (S.view === "app" ? "store" : S.view)));
  $("#username").textContent = S.native.settings.user || "";
  $("#usertab").textContent = (S.native.settings.user || "YOU").split(" ")[0].toUpperCase();
  const v = $("#view");
  // a re-render keeps where the library's lists were scrolled (selecting something scrolls its page itself)
  const kept = S.view === "library" ? [...v.querySelectorAll(".side, .gamepage")].map((el) => el.scrollTop) : [];
  if (S.view === "store") v.innerHTML = storeHome();
  else if (S.view === "app") { v.innerHTML = `<div class="store">${storePage(S.arg)}</div>`; details(S.arg).then(() => { if (S.view === "app") v.innerHTML = `<div class="store">${storePage(S.arg)}</div>`; bind(); }); }
  else if (S.view === "library") v.innerHTML = libraryView();
  else if (S.view === "downloads") v.innerHTML = downloadsView();
  else if (S.view === "news") v.innerHTML = newsView();
  else if (S.view === "profile") v.innerHTML = profileView();
  if (S.view === "library") v.querySelectorAll(".side, .gamepage").forEach((el, k) => { if (kept[k] != null) el.scrollTop = kept[k]; });
  bind();
  renderProgress();
}

function storeHome() {
  const games = S.catalog;
  if (!games.length) return `<div class="store"><div class="empty">The arcade service has no games yet.</div></div>`;
  const f = games[0];
  const shots = ["screenshot_1", "screenshot_2", "screenshot_3", "screenshot_4"].map((k) => media(f, k)).filter(Boolean);
  return `<div class="store">
    <div class="storebar"><a>Your Store</a><a>New &amp; Noteworthy</a><a>Categories</a><a>Points Shop</a><a>News</a>
      <input id="search" placeholder="search"></div>
    <h2>Featured &amp; Recommended</h2>
    <div class="featured" data-open="${esc(f.id)}">
      <div class="main" style="background-image:url('${shots[S.shot % Math.max(1, shots.length)] || media(f, "header_460x215")}')"></div>
      <div class="side"><h3>${esc(f.title)}</h3>
        <div class="thumbs">${shots.map((s) => `<div style="background-image:url('${s}')"></div>`).join("")}</div>
        <div>${esc(f.short_description)}</div>
        <div class="tags">${(f.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
        <div class="status">${S.native.library[f.id] ? "In Library" : '<span class="free">Free to Play</span>'}</div>
      </div>
    </div>
    <h2>Built from cards</h2>
    <div class="grid">${games.map((g) => `<div class="capsule" data-open="${esc(g.id)}">
      <div class="art" style="background-image:url('${media(g, "header_460x215")}')"></div>
      <div class="meta"><b>${esc(g.title)}</b><span>${S.native.library[g.id] ? "IN LIBRARY" : "FREE"}</span>
      <div class="tags">${(g.genre || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div></div></div>`).join("")}</div>
    ${S.lib.roms.length ? `<h2>Your cartridges</h2>
    <div class="grid">${S.lib.systems.filter((s) => s.playable || S.lib.roms.some((r) => r.system_card === s.id)).map((s) => {
      const n = S.lib.roms.filter((r) => r.system_card === s.id).length;
      const pl = game(s.player || "");
      return `<div class="capsule" ${pl ? `data-open="${esc(pl.id)}"` : `data-lib="home"`}>
        <div class="art" style="background-image:url('${pl ? media(pl, "header_460x215") : ""}')"></div>
        <div class="meta"><b>${esc(s.title)}</b><span>${n} FOUND</span>
        <div class="tags">${(s.systems || []).map((x) => `<span class="tag">${esc(x.label)}</span>`).join("")}${s.playable ? "" : `<span class="tag">not playable yet</span>`}</div></div></div>`;
    }).join("")}</div>` : ""}
    <h2>Recently updated</h2>
    ${games.map((g) => `<div class="card"><b style="color:#fff">${esc(g.title)}</b> &nbsp; v${esc(g.version)}
      ${(g.changelog || []).slice(-1).map((c) => ` &mdash; ${esc(c.title)}<ul>${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`).join("")}</div>`).join("")}
  </div>`;
}

function storePage(id) {
  const g = game(id);
  if (!g) return `<div class="empty">Not found.</div>`;
  const d = S.details[id] || g;
  const shots = ["screenshot_1", "screenshot_2", "screenshot_3", "screenshot_4", "screenshot_5"].map((k) => media(g, k)).filter(Boolean);
  const cur = shots[S.shot % Math.max(1, shots.length)] || "";
  const inst = S.native.library[id];
  const got = inst ? inst.achievements || [] : [];
  return `<div class="crumbs">All Games &gt; ${esc((g.genre || [])[0] || "Games")} &gt; ${esc(g.title)}</div>
    <div class="page-title">${esc(g.title)}</div>
    <div class="storepage">
      <div><div class="stage" style="background-image:url('${cur}')"></div>
        <div class="strip">${shots.map((s, k) => `<div class="${k === S.shot % shots.length ? "on" : ""}" data-shot="${k}" style="background-image:url('${s}')"></div>`).join("")}</div></div>
      <div class="facts"><img src="${media(g, "header_460x215")}" alt="">
        <p>${esc(g.short_description)}</p>
        <p><span class="k">Release date</span>${g.build ? esc(g.build.created.slice(0, 10)) : "Not built yet"}</p>
        <p><span class="k">Developer</span><a>${esc(g.developer)}</a></p>
        <p><span class="k">Version</span>${esc(g.version)}${g.build ? " &middot; build " + esc(g.build.build) : ""}</p>
        <div class="tags">${(g.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>
      </div>
    </div>
    <div class="buybox"><h3>Play ${esc(g.title)}</h3><div class="action"><div class="price">Free to Play</div>${inst ? `<button class="btn play small" data-golib="${esc(id)}">In Library</button>` : bigButton(g, true)}</div></div>
    <div class="about">
      <div><h4>About this game</h4>${(d.about || []).map((p) => `<p>${esc(p)}</p>`).join("")}
        <h4>System requirements</h4><div class="reqs"><p><b>OS:</b> macOS 13 or later &middot; <b>Built for:</b> this Mac (native code from the cards)</p>
        <p><b>Storage:</b> ${g.build ? mb(g.build.size) : "—"} &middot; <b>Controls:</b> keyboard or gamepad</p></div>
        <h4>What's new</h4><div class="news">${newsEntries(g)}</div></div>
      <div><h4>Achievements</h4><div class="achlist">${(g.achievements || []).map((a, k) => `<div class="a ${got[k] ? "got" : ""}"><div class="ico">&#9733;</div><div><b>${esc(a.name)}</b><small>${esc(a.description)}</small></div></div>`).join("")}</div></div>
    </div>`;
}

function newsEntries(g) {
  return (g.changelog || []).slice().reverse().map((c) => `<div class="entry"><b>${esc(g.title)} ${esc(c.version)} &mdash; ${esc(c.title)}</b>
    <ul>${c.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`).join("");
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
    const tag = st.kind === "busy" ? st.label : inst && inst.running ? "Running" : st.kind === "update" && inst ? "Update" : "";
    return `<div class="item ${inst ? "installed" : ""} ${sel && sel.id === g.id ? "on" : ""}" data-lib="${esc(g.id)}">
      <img src="${media(g, "icon")}" alt="">${esc(g.title)}<span class="st">${esc(tag)}</span></div>`;
  };
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
      groups.push(`<div class="group">${esc(sub.label)} (${list.length})</div>${items}`);
    }
  }
  const page = selRom ? romPage(selRom) : sel ? gamePage(sel) : home ? libraryHome() : `<div class="empty">No games.</div>`;
  return `<div class="library"><div class="side"><a class="home ${home && !selRom && !sel ? "on" : ""}" data-lib="home">HOME</a>
      <input id="libsearch" placeholder="Search" value="${esc(S.libQuery)}">
      ${games.length ? `<div class="group">Games (${games.length})</div>${games.map(gameItem).join("")}` : ""}
      ${tools.length ? `<div class="group">Players (${tools.length})</div>${tools.map(gameItem).join("")}` : ""}
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
  if (d.busy) out += `<div class="card">Drawing title screens: ${d.drawn || 0} of ${d.of || "?"} (the machine runs each cartridge for ten seconds, headless).</div>`;
  if (recent.length) out += `<h3>Recent</h3><div class="shelf">${recent.map(tile).join("")}</div>`;
  for (const sy of S.lib.systems) {
    for (const sub of sy.systems || []) {
      const list = S.lib.roms.filter((r) => r.system_card === sy.id && r.system === sub.id);
      if (!list.length) continue;
      out += `<h3>${esc(sub.label)} <small>${list.length} cartridge${list.length === 1 ? "" : "s"}</small></h3><div class="shelf">${list.map(tile).join("")}</div>`;
    }
  }
  if (!S.lib.roms.length) out += `<div class="empty">No cartridges found. The player's card lists the folders it looks in.</div>`;
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
  if (st.kind === "install") send("install", { id: st.player });
  else if (st.kind === "play") send("play_rom", { id: r.id, player: sysOf(r).player, path: r.path, title: r.title });
  else if (st.kind === "stop") send("stop", { id: r.id });
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
  return `<div class="hero rom"><div class="blur" style="background-image:url('${esc(r.cover || "")}')"></div>
      ${r.cover ? `<img class="shot" src="${esc(r.cover)}" alt="">` : ""}
      <div class="logo">${esc(r.title)}<small>${esc(subLabel(r))}${r.tags ? " &middot; " + esc(r.tags) : ""}</small></div></div>
    <div class="actionbar">${romButton(r)}
      <div class="stat">Last played<b>${played ? when(played.lastPlayed) : "Never"}</b></div>
      <div class="stat">Play time<b>${played ? playtime(played.playSeconds) : "None yet"}</b></div>
      <div class="stat">Card model<b><span class="vb ${esc(v.level)}"></span> ${esc(vtext)}</b></div>
      <div class="stat">Console<b>${esc(subLabel(r))}</b></div>
      <div class="gear"><button class="iconbtn" data-gear="1" title="Manage">&#9881;</button>
        ${S.gear ? `<div class="menu"><a data-romreveal="${esc(r.path)}">Show the cartridge in Finder</a>
          ${pl ? `<a data-lib="${esc(pl.id)}">${esc(pl.title)}</a>` : ""}</div>` : ""}</div>
    </div>
    ${pl ? `<div id="progress-${esc(pl.id)}" class="progress" style="padding:0 26px"></div>` : ""}
    ${S.lastErr[r.id] ? `<div class="card" style="margin:14px 26px 0;color:#e88">${esc(S.lastErr[r.id])}</div>` : ""}
    <div class="cols"><div>
        <div class="card"><h4>Compatibility</h4><p class="verdict"><span class="vb ${esc(v.level)}"></span><b>${esc(vtext)}</b> &mdash; ${esc(v.text || "")}</p>
          ${v.reason ? `<p class="dim">Survey: ${esc(v.reason)}</p>` : ""}${ds}</div>
        ${pl ? `<div class="card"><h4>Controls</h4><p>${esc(pl.controls || "")}</p></div>` : ""}
      </div><div>
        <div class="card"><h4>Cartridge</h4><div class="factlist">${facts.map(([k, x]) => `<div><span>${esc(k)}</span>${esc(x || "—")}</div>`).join("")}</div></div>
        <div class="card"><h4>File</h4><div class="path">${esc(r.path)}</div><p class="dim">Played where it is: nothing is copied.</p></div>
      </div></div>`;
}

function gamePage(g) {
  const inst = S.native.library[g.id];
  const got = inst ? inst.achievements || [] : [];
  const nGot = got.slice(0, (g.achievements || []).length).filter(Boolean).length;
  const err = S.lastErr[g.id];
  return `<div class="hero" style="background-image:url('${media(g, "hero_1920x620")}')"><div class="logo">${esc(g.title.toUpperCase())}</div></div>
    <div class="actionbar">${bigButton(g)}
      <div class="stat">Last played<b>${inst ? when(inst.lastPlayed) : "Never"}</b></div>
      <div class="stat">Play time<b>${inst ? playtime(inst.playSeconds) : "None yet"}</b></div>
      <div class="stat">Achievements<b>${nGot}/${(g.achievements || []).length}</b></div>
      <div class="stat">Size on disk<b>${inst ? mb(inst.size) : g.build ? mb(g.build.size) : "—"}</b></div>
      <div class="gear">${inst ? `<button class="iconbtn" data-gear="1" title="Manage">&#9881;</button>` : ""}
        ${S.gear && inst ? `<div class="menu"><a data-verify="${esc(g.id)}">Verify integrity of game files</a>
          <a data-reveal="${esc(g.id)}">Browse local files</a><a data-open="${esc(g.id)}">Store page</a>
          <a data-uninstall="${esc(g.id)}">Uninstall</a></div>` : ""}</div>
    </div>
    <div id="progress-${esc(g.id)}" class="progress" style="padding:0 26px"></div>
    ${err ? `<div class="card" style="margin:14px 26px 0;color:#e88">${esc(err)}</div>` : ""}
    <div class="cols"><div>
        ${inst && g.build && g.build.build !== inst.build ? `<div class="card"><h4>Update available</h4>Version ${esc(g.version)} (build ${esc(g.build.build)}) is ready.</div>` : ""}
        ${g.build_due ? `<div class="card"><h4>New build from the cards</h4>The game's cards changed since the last build: the next update compiles them first.</div>` : ""}
        <div class="card news"><h4>What's new</h4>${newsEntries(g)}</div>
      </div><div>
        <div class="card"><h4>Achievements</h4><div class="achlist">${(g.achievements || []).map((a, k) => `<div class="a ${got[k] ? "got" : ""}"><div class="ico">&#9733;</div><div><b>${esc(a.name)}</b><small>${esc(a.description)}</small></div></div>`).join("")}</div></div>
        <div class="card"><h4>Info</h4><div style="font-size:13px">Version ${esc(inst ? inst.version : g.version)}<br>Build ${esc(inst ? inst.build : g.build ? g.build.build : "—")}<br>
          Developer: ${esc(g.developer)}<br>Engine: card-language logic, native code via the C card</div></div>
      </div></div>`;
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
    ${g ? `<div class="dlitem"><div class="art" style="background-image:url('${media(g, "header_460x215")}')"></div>
      <div><div class="name">${esc(g.title)}</div><div class="phase">${esc(p ? phaseLabel(p) : "Queued")}</div>
        <div id="progress-${esc(g.id)}" class="progress"></div></div>
      <div class="ctl">${S.native.paused ? `<button class="btn small install" data-resume="1">Resume</button>` : `<button class="btn small ghost" data-pause="1">Pause</button>`}
        <button class="btn small ghost" data-cancel="1">Cancel</button></div></div>` : `<div class="empty">Nothing is downloading.</div>`}
    <div class="section-title">Completed</div>
    ${S.completed.length ? S.completed.map((c) => { const cg = game(c.id); return cg ? `<div class="dlitem"><div class="art" style="background-image:url('${media(cg, "header_460x215")}')"></div>
      <div><div class="name">${esc(cg.title)}</div><div class="phase">Installed ${new Date(c.at).toLocaleTimeString()}</div></div>
      <div class="ctl">${bigButton(cg, true)}</div></div>` : ""; }).join("") : `<div class="empty">Nothing yet.</div>`}
  </div>`;
}

function newsView() {
  return `<div class="store"><h2>News and patch notes</h2>${S.catalog.map((g) => `<div class="card news">
    <h4>${esc(g.title)}</h4>${newsEntries(g)}</div>`).join("")}</div>`;
}

function profileView() {
  const lib = S.native.library;
  const n = Object.keys(lib).length;
  let ach = 0, total = 0, secs = 0;
  for (const g of S.catalog) {
    total += (g.achievements || []).length;
    if (lib[g.id]) { ach += (lib[g.id].achievements || []).slice(0, (g.achievements || []).length).filter(Boolean).length; secs += lib[g.id].playSeconds || 0; }
  }
  const user = S.native.settings.user || "You";
  return `<div class="profile"><div class="head"><div class="avatar">${esc(user[0] || "?")}</div>
    <div><h2>${esc(user)}</h2><div class="stat">Games<b>${n}</b></div></div>
    <div class="stat" style="margin-left:auto">Achievements<b>${ach} / ${total}</b></div><div class="stat">Play time<b>${playtime(secs)}</b></div></div>
    <h2 style="color:#fff;font-weight:400;font-size:16px;margin-top:26px">Achievement showcase</h2>
    ${S.catalog.map((g) => `<div class="card"><h4>${esc(g.title)}</h4><div class="achlist">${(g.achievements || []).map((a, k) => { const gotIt = lib[g.id] && (lib[g.id].achievements || [])[k];
      return gotIt ? `<div class="a got"><div class="ico">&#9733;</div><div><b>${esc(a.name)}</b><small>${esc(a.description)}</small></div></div>` : ""; }).join("") || `<div class="empty">None unlocked yet.</div>`}</div></div>`).join("")}
  </div>`;
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
    <label>About</label><div>Cardmodel Arcade. The arcade service builds every game from its cards (card-language logic, compiled to native code) and serves it as a depot of checked chunks.</div>
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
function ask(title, text, yes, then) {
  $("#modal").innerHTML = `<div class="dialog"><h3>${esc(title)}</h3><div class="body">${esc(text)}</div>
    <div class="foot"><button class="btn small ghost" id="no">Cancel</button> <button class="btn small stop" id="yes">${esc(yes)}</button></div></div>`;
  $("#modal").classList.remove("hidden");
  $("#no").onclick = () => $("#modal").classList.add("hidden");
  $("#yes").onclick = () => { $("#modal").classList.add("hidden"); then(); };
}
let toastTimer = null;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add("hidden"), 3800);
}

// -- events ---------------------------------------------------------------------------------------------------------
function bind() {
  document.querySelectorAll("[data-open]").forEach((el) => (el.onclick = (e) => { e.stopPropagation(); S.shot = 0; go("app", el.dataset.open); }));
  document.querySelectorAll("[data-act]").forEach((el) => (el.onclick = (e) => { e.stopPropagation(); const g = game(el.dataset.act); if (g) act(g); }));
  document.querySelectorAll("[data-golib]").forEach((el) => (el.onclick = () => go("library", el.dataset.golib)));
  document.querySelectorAll("[data-lib]").forEach((el) => (el.onclick = (e) => { e.stopPropagation(); S.libSel = el.dataset.lib; S.gear = false;
    if (S.view !== "library") go("library", el.dataset.lib); else { render(); $("#view").querySelector(".gamepage").scrollTop = 0; } }));
  document.querySelectorAll("[data-romact]").forEach((el) => (el.onclick = (e) => { e.stopPropagation(); const r = rom(el.dataset.romact); if (r) romAct(r); }));
  document.querySelectorAll("[data-romreveal]").forEach((el) => (el.onclick = () => { S.gear = false; send("reveal_rom", { path: el.dataset.romreveal }); render(); }));
  const ls = $("#libsearch");
  if (ls) ls.oninput = () => { S.libQuery = ls.value; const pos = ls.selectionStart; render(); const n = $("#libsearch"); if (n) { n.focus(); n.setSelectionRange(pos, pos); } };
  document.querySelectorAll("[data-shot]").forEach((el) => (el.onclick = () => { S.shot = parseInt(el.dataset.shot, 10); render(); }));
  document.querySelectorAll("[data-gear]").forEach((el) => (el.onclick = (e) => { e.stopPropagation(); S.gear = !S.gear; render(); }));
  document.querySelectorAll("[data-verify]").forEach((el) => (el.onclick = () => { S.gear = false; send("verify", { id: el.dataset.verify }); render(); }));
  document.querySelectorAll("[data-reveal]").forEach((el) => (el.onclick = () => { S.gear = false; send("reveal", { id: el.dataset.reveal }); render(); }));
  document.querySelectorAll("[data-uninstall]").forEach((el) => (el.onclick = (e) => { e.stopPropagation(); S.gear = false; render(); ask(`Uninstall ${(game(el.dataset.uninstall) || {}).title}?`, "Its files are removed from this Mac. Its saves and achievements stay.", "Uninstall", () => send("uninstall", { id: el.dataset.uninstall })); }));
  document.querySelectorAll("[data-pause]").forEach((el) => (el.onclick = () => send("pause")));
  document.querySelectorAll("[data-resume]").forEach((el) => (el.onclick = () => send("resume")));
  document.querySelectorAll("[data-cancel]").forEach((el) => (el.onclick = () => send("cancel")));
}
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => go(t.dataset.view, t.dataset.view === "library" ? S.libSel : null)));
$("#dl-link").onclick = () => go("downloads");
$("#settings-btn").onclick = settingsDialog;
$("#back").onclick = () => { const h = S.history.pop(); if (h) { S.future.push([S.view, S.arg]); go(h[0], h[1], true); } };
$("#fwd").onclick = () => { const f = S.future.pop(); if (f) { S.history.push([S.view, S.arg]); go(f[0], f[1], true); } };
$("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); };
document.addEventListener("click", () => { if (S.gear) { S.gear = false; render(); } });
setInterval(() => { if (S.view === "store" || S.view === "app") { S.shot++; const st = $(".featured .main"); if (st) render(); } }, 6000);
setInterval(refresh, 15000);
refresh();
