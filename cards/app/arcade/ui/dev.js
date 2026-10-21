// In progress: everything being built, live. The arcade service's hub (cardmodel/arcade/hub.py) computes every
// project's status from git and from the model's own records and pushes it here as server-sent events
// (/api/events). Early-access builds install beside the release, under their own library id.
"use strict";

S.dev = null; S.devLive = false; S.devBuilds = ""; S.devFilter = "all";

function ago(t) {
  if (!t) return "never";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  return Math.floor(s / 86400) + " d ago";
}
const tsOf = (v) => (typeof v === "number" ? v : v ? Date.parse(String(v).replace(/([+-]\d\d)(\d\d)$/, "$1:$2")) / 1000 : 0);
const cls = (s) => String(s || "").replace(/[^a-z]+/g, "-");

function earlyStatus(e) {
  const inst = S.native.library[e.id];
  const p = S.progress[e.id];
  if (S.native.downloading === e.id || p) return { kind: "busy", label: p ? phaseLabel(p) : "Queued" };
  if (!inst) return { kind: "install", label: "Install early access" };
  if (inst.running) return { kind: "stop", label: "Stop" };
  if (inst.build !== e.build) return { kind: "update", label: "Update" };
  return { kind: "play", label: "Play" };
}
const earlyButton = (e) => { const st = earlyStatus(e); return `<button class="btn small ${st.kind}" data-early="${esc(e.id)}">${esc(st.label)}</button>`; };

function metricHTML(m) {
  let v = m.value == null ? m.note || "—" : m.value;
  if (typeof v === "number" && !Number.isInteger(v)) v = v.toFixed(3);
  const tgt = m.target != null ? ` <span class="tgt">${m.direction === "lower" ? "&le;" : "&ge;"} ${esc(m.target)}</span>` : "";
  const mark = m.met === true ? "ok" : m.met === false ? "no" : "na";
  const where = m.where && m.where !== "main" ? ` <span class="where">measured in ${esc(m.where)}</span>` : "";
  return `<div class="metric ${mark}"><span class="ml">${esc(m.label)}</span><span class="mv">${esc(v)}${tgt}${where}</span></div>`;
}

function projectHTML(p) {
  const last = p.last
    ? `<div class="last"><b>${esc(p.last.title)}</b> <span class="dim">${esc(p.last.who)} &middot; ${ago(p.last.t)}</span></div>`
    : `<div class="last dim">${p.phase === "not on this machine" ? "the repository is not on this machine" : "no commit touches it yet"}</div>`;
  const changes = (p.changes || []).map((c) => `<div class="change"><span class="pulse"></span>${c.files} file${c.files === 1 ? "" : "s"}
    changing in <b>${esc(c.worktree)}</b> <span class="dim">(${esc(c.branch)}) &middot; ${ago(c.newest)}</span>
    <div class="files">${c.sample.map(esc).join(" &middot; ")}</div></div>`).join("");
  const branches = (p.branches || []).map((b) => `<div class="branch"><span class="bn">${esc(b.branch)}</span>
    <span class="ab">${b.ahead} ahead &middot; ${b.behind} behind main</span>${b.worktree ? ` <span class="wt">${esc(b.worktree)}</span>` : ""}
    <div class="bl">${esc(b.last.title)} &middot; ${ago(b.last.t)}</div></div>`).join("");
  const builds = (p.builds || []).map((b) => (b.channel === "release"
    ? `<div class="build"><span class="chan">RELEASE</span> ${esc(b.version)} <span class="dim">build ${esc(b.build)}</span></div>`
    : `<div class="build"><span class="chan ea">EARLY ACCESS</span> ${esc(b.version)} <span class="dim">from ${esc(b.branch)}</span> ${earlyButton(b)}</div>`)).join("");
  return `<div class="proj ${cls(p.phase)}">
    <div class="ph"><span class="phase ${cls(p.phase)}">${esc(p.phase)}</span><span class="kind">${esc(p.kind)}</span></div>
    <h3>${esc(p.title)}</h3><div class="st">${esc(p.statement)}</div>
    ${last}${changes}${branches}
    ${p.metrics && p.metrics.length ? `<div class="metrics">${p.metrics.map(metricHTML).join("")}</div>` : ""}
    ${builds ? `<div class="builds">${builds}</div>` : ""}
    <div class="foot">${p.recent || 0} commit${p.recent === 1 ? "" : "s"} this week${p.repo && p.repo !== "cardmodel" ? ` &middot; ${esc(p.repo)}` : ""}${(p.docs || []).length ? ` &middot; ${p.docs.map(esc).join(", ")}` : ""}</div>
  </div>`;
}

const MARK = { commit: "&#9675;", merge: "&#10551;", verify: "&#10003;", build: "&#9635;", "self-run": "&#8635;" };
const feedHTML = (a) => a.map((e) => `<div class="ev ${cls(e.kind)}"><span class="ek">${MARK[e.kind] || "&middot;"}</span>
  <div><div class="et">${esc(e.title)}</div><div class="em">${esc(e.kind)} &middot; ${esc(e.repo)}${e.branch ? " &middot; " + esc(e.branch) : ""}${e.who ? " &middot; " + esc(e.who) : ""} &middot; ${ago(e.t)}</div></div></div>`).join("");

function devView() {
  const d = S.dev;
  const live = `<span class="live ${S.devLive ? "on" : ""}" title="${S.devLive ? "Changes arrive as they happen" : "Not connected to the arcade service"}">${S.devLive ? "LIVE" : "OFFLINE"}</span>`;
  if (!d || !d.projects) return `<div class="store dev"><h2>In progress ${live}</h2><div class="empty">Asking the arcade service what is being built&hellip;</div></div>`;
  const groups = [["game", "Games"], ["program", "Programs"], ["research", "Research"]];
  const shown = groups.filter(([k]) => S.devFilter === "all" || S.devFilter === k);
  const early = d.early || [];
  return `<div class="store dev">
    <div class="devhead"><h2>In progress ${live}</h2>
      <span class="dim">updated ${ago(d.generated)} &middot; ${d.projects.length} projects &middot; ${(d.repos || []).length} repositories watched</span>
      <span class="filters">${[["all", "All"], ...groups].map(([k, l]) => `<a data-devfilter="${k}" class="${S.devFilter === k ? "on" : ""}">${l}</a>`).join("")}</span></div>
    ${early.length ? `<h2>Early access</h2><div class="early">${early.map((e) => `<div class="eacard">
      <div class="art" style="background-image:url('${esc(e.media.header_460x215 || e.media.capsule_231x87 || "")}')"></div>
      <div class="meta"><span class="chan ea">EARLY ACCESS</span><b>${esc(e.title)} ${esc(e.version)}</b>
        <div class="dim">from ${esc(e.branch)} &middot; built ${ago(tsOf(e.created))}${e.release ? ` &middot; the release is ${esc(e.release)}` : ""}</div>
        ${earlyButton(e)}</div></div>`).join("")}</div>` : ""}
    <div class="devcols"><div class="projects">${shown.map(([k, l]) => {
      const ps = d.projects.filter((p) => p.kind === k);
      return ps.length ? `<h2>${l}</h2>${ps.map(projectHTML).join("")}` : "";
    }).join("")}</div>
      <div class="feed"><h2>Activity</h2>${feedHTML(d.activity || []) || '<div class="empty">Nothing this week.</div>'}</div></div>
  </div>`;
}

document.addEventListener("click", (ev) => {
  const b = ev.target.closest && ev.target.closest("[data-early]");
  if (b) {
    ev.stopPropagation();
    const e = ((S.dev && S.dev.early) || []).find((x) => x.id === b.dataset.early);
    if (!e) return;
    const st = earlyStatus(e);
    if (st.kind === "install" || st.kind === "update") send(st.kind, { id: e.id });
    else if (st.kind === "play" || st.kind === "stop") send(st.kind, { id: e.id });
    return;
  }
  const f = ev.target.closest && ev.target.closest("[data-devfilter]");
  if (f) { S.devFilter = f.dataset.devfilter; render(); }
}, true);

function devConnect() {
  const take = (d) => {
    S.dev = d;
    const sig = (d.releases || []).map((r) => r.id + r.build).join() + "|" + (d.early || []).map((e) => e.id + e.build).join();
    if (S.devBuilds && sig !== S.devBuilds) refresh();          // a new build: the store and library see it at once
    S.devBuilds = sig;
    if (S.view === "dev") render();
  };
  if (!window.EventSource) {
    const poll = () => fetch("/api/dev").then((r) => r.json()).then(take).catch(() => {});
    poll(); setInterval(poll, 10000); return;
  }
  const es = new EventSource("/api/events");
  es.addEventListener("hub", (msg) => { S.devLive = true; take(JSON.parse(msg.data)); });
  es.onopen = () => { S.devLive = true; };
  es.onerror = () => { S.devLive = false; if (S.view === "dev") render(); };
}
devConnect();
setInterval(() => { if (S.view === "dev") render(); }, 30000);   // keeps "n min ago" true between events
