// In progress: everything being built, live. The arcade service's hub (cardmodel/arcade/hub.py) computes every
// project's status from git and from the model's own records and pushes it here as server-sent events
// (/api/events). Early access is a program's version on a branch: it opens the program's store page on that
// branch, where it installs like a beta (one mechanism, app.js). Every branch of the repository is listed below
// the projects (app.js workSection).
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

const earlyButton = (e) => `<a class="btn small install" data-open="${esc(e.game)}" data-wt="${esc(e.worktree)}">See it on its branch</a>`;
const earlyBuilt = (e) => (e.build ? `build ${esc(e.build)}${e.created ? " &middot; built " + ago(tsOf(e.created)) : ""}` : "not built yet: its page builds it from the branch's cards");

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
    : `<div class="build"><span class="chan ea">EARLY ACCESS</span> ${esc(b.version)} <span class="dim">from ${esc(b.branch)} &middot; ${earlyBuilt(b)}</span> ${earlyButton(b)}</div>`)).join("");
  const d = p.detail || {}, card = p.card || {};
  const list = (label, xs, n) => (xs && xs.length ? `<div class="dl"><span>${label}</span><ul>${xs.slice(0, n || 4).map((x) => `<li>${esc(x)}</li>`).join("")}${xs.length > (n || 4) ? `<li class="dim">and ${xs.length - (n || 4)} more</li>` : ""}</ul></div>` : "");
  const det = `<div class="detail">${d.standing ? `<div class="status">${esc(d.standing)}</div>` : ""}
    ${list("In progress", d.in_progress)}${list("Left", d.left)}${list("Blocked by", d.blockers)}${list("Next", d.next_steps, 3)}
    <div class="owner dim">${d.owner ? `owned by ${esc(d.owner.name || d.owner.session)} &middot; ` : ""}card revised ${ago(tsOf(d.updated))}${card.stale ? ' <span class="stale">STALE</span>' : ""}</div></div>`;
  return `<div class="proj ${cls(p.phase)}">
    <div class="ph"><span class="phase ${cls(p.phase)}">${esc(p.phase)}</span><span class="kind">${esc(p.kind)}</span></div>
    <h3>${esc(p.title)}</h3><div class="st">${esc(d.goal || p.statement)}</div>
    ${det}${last}${changes}${branches}
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
    ${(d.waiting_on_you || []).length ? `<h2>Waiting on you</h2><div class="you">${d.waiting_on_you.map((a, i) => `<div class="ask">
      <span class="n">${i + 1}</span><div><b>${esc(a.action)}</b><div class="dim">${esc(a.why)}</div>
      <div class="tags">${a.unblocks.map((u) => `<span class="tag">unblocks: ${esc(u)}</span>`).join("")}</div>
      <div class="dim">${esc(a.title)}${a.owner ? " &middot; " + esc(a.owner) : ""}</div></div></div>`).join("")}</div>` : ""}
    ${(d.card_problems || []).length ? `<div class="cardprobs">${d.card_problems.length} project card problem${d.card_problems.length === 1 ? "" : "s"} (law CM41): ${d.card_problems.slice(0, 3).map(esc).join(" &middot; ")}</div>` : ""}
    ${early.length ? `<h2>Early access</h2><div class="early">${early.map((e) => { const g = game(e.game); return `<div class="eacard">
      <div class="art" style="background-image:url('${g ? art(g, "header_460x215") : ""}')"></div>
      <div class="meta"><span class="chan ea">EARLY ACCESS</span><b>${esc(e.title)} ${esc(e.version)}</b>
        <div class="dim">from ${esc(e.branch)} &middot; ${earlyBuilt(e)}${e.release ? ` &middot; the release is ${esc(e.release)}` : ""}</div>
        ${earlyButton(e)}</div></div>`; }).join("")}</div>` : ""}
    <div class="devcols"><div class="projects">${shown.map(([k, l]) => {
      const ps = d.projects.filter((p) => p.kind === k);
      return ps.length ? `<h2>${l}</h2>${ps.map(projectHTML).join("")}` : "";
    }).join("")}</div>
      <div class="feed"><h2>Activity</h2>${feedHTML(d.activity || []) || '<div class="empty">Nothing this week.</div>'}</div></div>
    <div id="branches">${workSection()}</div>
  </div>`;
}

document.addEventListener("click", (ev) => {
  const f = ev.target.closest && ev.target.closest("[data-devfilter]");
  if (f) { S.devFilter = f.dataset.devfilter; render(); }
}, true);

function devConnect() {
  const take = (d) => {
    S.dev = d;
    const sig = (d.releases || []).map((r) => r.id + r.build).join() + "|" + (d.early || []).map((e) => e.game + e.worktree + e.build).join();
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
