// The De Marzi sigma/Neo4j "hairball" palette: a few bright saturated hues
// (magenta, green, cyan, pink, violet, lime) cycled across communities on a
// near-black field.
const PALETTE = [
  "#c04ad6", // magenta
  "#8ed11f", // green
  "#33e0cf", // cyan
  "#f0a6e0", // pink
  "#a85bff", // violet
  "#b6f04a", // lime
  "#5be0a0", // teal
  "#e06ab0", // rose
];
const colorFor = (community) =>
  community == null ? "#3a3f4b" : PALETTE[community % PALETTE.length];

const el = (id) => document.getElementById(id);
const api = (path) => fetch(path).then((r) => r.json());

const PROJECT_PREFIX = /^[^.]+__[0-9a-f]{8}\./;
const shortName = (qn) => (qn || "").replace(PROJECT_PREFIX, "");

function hexAlpha(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

let orb = null;
let nodesById = new Map();
let adjacency = new Map();
let hoveredNode = null;
const positions = new Map();
let currentOrbNodes = [];
let currentOrbEdges = [];

function neighborsOf(id) {
  return new Set((adjacency.get(id) || []).map((e) => (e.start === id ? e.end : e.start)));
}

function nodeStyle(n) {
  const active = hoveredNode && (n.id === hoveredNode || neighborsOf(hoveredNode).has(n.id));
  const base = colorFor(n.community);
  const fontColor = "#e4e6eb";
  const fontBackgroundColor = "rgba(8,8,11,0.72)";
  if (hoveredNode && !active) {
    const faded = "rgba(136,136,136,0.1)";
    return {
      color: faded, colorHover: faded, colorSelected: faded,
      borderColor: faded, borderColorHover: faded, borderColorSelected: faded,
      size: n.size, label: undefined, fontColor, fontBackgroundColor,
      shadowColor: "transparent", shadowSize: 0, zIndex: 0,
    };
  }
  if (n.id === hoveredNode) {
    const full = hexAlpha(base, 1);
    return {
      color: full, colorHover: full, colorSelected: full,
      size: n.size, label: n.name, fontColor, fontBackgroundColor,
      borderColor: "#ffffff", borderColorHover: "#ffffff", borderColorSelected: "#ffffff",
      borderWidth: 1, shadowColor: base, shadowSize: 26, zIndex: 2,
    };
  }
  const normal = hexAlpha(base, 0.8);
  return {
    color: normal, colorHover: normal, colorSelected: normal,
    borderColor: normal, borderColorHover: normal, borderColorSelected: normal,
    size: n.size, label: hoveredNode ? n.name : undefined, fontColor, fontBackgroundColor,
    shadowColor: hoveredNode ? base : "transparent", shadowSize: hoveredNode ? 12 : 0,
    zIndex: 1,
  };
}

function edgeStyle(e) {
  const tint = colorFor(nodesById.get(e.start)?.community);
  if (hoveredNode) {
    const touches = e.start === hoveredNode || e.end === hoveredNode;
    const color = touches ? "rgba(255,255,255,0.67)" : "rgba(255,255,255,0.03)";
    return {
      color, colorHover: color, colorSelected: color,
      width: touches ? (e.resolution === "heuristic" ? 0.6 : 1) : 0.3,
      zIndex: touches ? 1 : 0,
    };
  }
  const color = hexAlpha(tint, e.resolution === "heuristic" ? 0.27 : 0.47);
  return {
    color, colorHover: color, colorSelected: color,
    width: e.resolution === "heuristic" ? 0.4 : 0.7,
    zIndex: 0,
  };
}

function applyStyles() {
  orb.data.getNodes().forEach((n) => n.setStyle(nodeStyle(n.getData()), { isNotifySkipped: true }));
  orb.data.getEdges().forEach((e) => e.setStyle(edgeStyle(e.getData()), { isNotifySkipped: true }));
}

function restyle() {
  applyStyles();
  orb.render();
}

// Like ALL NODES's select(): re-feeding the same data on every click nudges
// Orb's force simulation awake again for a brief resettle, instead of a
// static restyle — same selection "comes alive" feel on a smaller graph.
function rebump() {
  orb.data.getNodePositions().forEach((p) => {
    if (p.x != null) positions.set(p.id, { x: p.x, y: p.y });
  });
  orb.data.setup({ nodes: currentOrbNodes, edges: currentOrbEdges });
  applyStyles();
  orb.render();
}

function renderGraph({ nodes, edges }) {
  const orbNodes = nodes.map((n) => ({
    id: n.id,
    name: shortName(n.qualified_name) || n.name || n.id,
    community: n.community,
    size: 2 + Math.sqrt(n.pagerank || 0) * 16,
  }));
  nodesById = new Map(orbNodes.map((n) => [n.id, n]));

  const ids = new Set(orbNodes.map((n) => n.id));
  const seen = new Set();
  const orbEdges = [];
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    const key = `${e.source}->${e.target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    orbEdges.push({ id: key, start: e.source, end: e.target, resolution: e.resolution });
  }
  adjacency = new Map(orbNodes.map((n) => [n.id, []]));
  orbEdges.forEach((e) => {
    adjacency.get(e.start).push(e);
    if (e.start !== e.end) adjacency.get(e.end).push(e);
  });
  currentOrbNodes = orbNodes;
  currentOrbEdges = orbEdges;

  positions.clear();
  hoveredNode = null;

  if (!orb) {
    orb = new window.Orb.OrbView(el("graph-container"), {
      getPosition: (node) => positions.get(node.id),
      render: {
        backgroundColor: null,
        labelsIsEnabled: true,
        labelsOnEventIsEnabled: true,
        shadowIsEnabled: true,
        shadowOnEventIsEnabled: true,
        fontColor: "#e4e6eb",
        fontBackgroundColor: "rgba(8,8,11,0.72)",
        fontSize: 7,
      },
      strategy: { isDefaultSelectEnabled: false, isDefaultHoverEnabled: false },
      layout: {
        type: "force",
        options: {
          collision: { radius: 9, strength: 0.8, iterations: 1 },
          links: { distance: 30, strength: 0.5, iterations: 1 },
          manyBody: { strength: -140, theta: 0.9, distanceMin: 1, distanceMax: 400 },
          positioning: { forceX: { x: 0, strength: 0.06 }, forceY: { y: 0, strength: 0.06 } },
        },
      },
      zoomFitTransitionMs: 400,
    });
    orb.events.on(window.Orb.OrbEventType.NODE_CLICK, (e) => showDetail(e.node.getData().id));
    orb.events.on(window.Orb.OrbEventType.MOUSE_CLICK, (e) => {
      if (!e.subject) el("detail").classList.add("hidden");
    });
    orb.events.on(window.Orb.OrbEventType.MOUSE_MOVE, (e) => {
      const s = e.subject;
      const id = s && s.getData && s.getData().id !== undefined ? s.getData().id : null;
      if (id === hoveredNode) return;
      hoveredNode = id;
      restyle();
    });
  }

  orb.data.setup({ nodes: orbNodes, edges: orbEdges });
  applyStyles();
  orb.render(() => orb.recenter());
}

function badge(cls, text) {
  return `<span class="badge ${cls}">${text}</span>`;
}

function nodeRowHtml(n) {
  return `<div class="list-item" data-id="${n.id}">
    ${shortName(n.qualified_name) || n.name || n.id}
    <span class="path">${n.path || ""}:${n.start_line || ""}</span>
  </div>`;
}

function bindNodeRows(container) {
  container.querySelectorAll(".list-item[data-id]").forEach((row) => {
    row.addEventListener("click", () => {
      focusNode(row.dataset.id);
      showDetail(row.dataset.id);
    });
  });
}

function focusNode(id) {
  if (!orb || !nodesById.has(id)) return;
  hoveredNode = id;
  rebump();
}

async function showDetail(id) {
  const n = await api(`/api/node/${id}`);
  const badges = [
    n.dead_code ? badge("dead", "dead code") : "",
    n.duplicate ? badge("dup", `duplicate #${n.duplicate.group}`) : "",
    ...n.security_issues.map(() => badge("sec", "security")),
    ...n.code_smells.map(() => badge("smell", "smell")),
  ].join(" ");

  const relGroup = (title, items, color) =>
    `<div class="rel-group">
      <h4><span class="line" style="--c:${color}"></span>${title} · ${items.length}</h4>
      ${
        items.length
          ? items
              .map(
                (c) =>
                  `<div class="list-item" data-id="${c.id}">${shortName(c.qualified_name)}${
                    c.resolution === "heuristic" ? " <em>(heuristic)</em>" : ""
                  }</div>`
              )
              .join("")
          : `<p class="empty">none</p>`
      }
    </div>`;

  el("detail-header").innerHTML = `
    <span class="badge community" style="--c:${colorFor(n.community)}">community ${n.community}</span>
    <h3>${shortName(n.qualified_name) || n.name}</h3>
    <div class="path">${n.path}:${n.start_line}-${n.end_line} · ${n.label}</div>
    <div>${badges}</div>
    <div>PageRank ${(n.pagerank || 0).toFixed(5)}</div>
    <div class="actions">
      <button class="btn primary" id="d-focus" type="button">Show neighbourhood</button>
      <button class="btn" id="d-copy" type="button">Copy name</button>
    </div>
  `;
  el("detail-content").innerHTML = `
    ${n.source ? `<h4>Source</h4><pre>${escapeHtml(n.source)}</pre>` : ""}
    ${relGroup("Callers", n.callers, "#22d3ee")}
    ${relGroup("Callees", n.callees, "#7c5cff")}
  `;
  bindNodeRows(el("detail-content"));
  showAllPanels();
  rebump();

  el("d-focus").addEventListener("click", () => focusNode(id));
  el("d-copy").addEventListener("click", () => {
    const text = shortName(n.qualified_name) || n.name;
    const btn = el("d-copy");
    (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
      () => {
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = "Copy name"; }, 1200);
      },
      () => {}
    );
  });
}

function escapeHtml(s) {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

async function loadStats() {
  const s = await api("/api/stats");
  const chips = [
    [s.functions, "functions"],
    [s.call_edges, `call edges (${s.exact_edges} exact, ${s.heuristic_edges} heuristic)`],
    [s.communities, "communities"],
    [s.modularity, "modularity"],
  ];
  el("stats").innerHTML = chips
    .map(([v, label]) => `<div class="stat"><b>${v}</b><span>${label}</span></div>`)
    .join("");
}

async function loadCommunities() {
  const list = await api("/api/communities");
  el("communities").innerHTML = list
    .slice(0, 25)
    .map(
      (c) =>
        `<div class="list-item" data-community="${c.id}">
          <span style="color:${colorFor(c.id)}">●</span>
          community ${c.id} — ${c.size} fns
          <span class="path">${c.top_folder} (${c.folder_match_pct}%)</span>
        </div>`
    )
    .join("");
  el("communities").querySelectorAll(".list-item").forEach((row) => {
    row.addEventListener("click", () => load({ community: row.dataset.community }));
  });
}

async function loadIssues() {
  const { dead_code, duplicates } = await api("/api/issues");
  const deadHtml = dead_code
    .slice(0, 100)
    .map((d) => `<div class="list-item">${badge("dead", d.label)} ${shortName(d.qualified_name)}</div>`)
    .join("");
  const dupHtml = duplicates
    .slice(0, 50)
    .map(
      (g, i) =>
        `<div class="list-item">${badge("dup", g.kind)} group ${i} — ${
          (g.members || []).length
        } members</div>`
    )
    .join("");
  el("issues").innerHTML = deadHtml + dupHtml || `<p class="empty">none found</p>`;
}

async function runSearch(q) {
  if (!q) {
    el("search-results").innerHTML = "";
    return;
  }
  const hits = await api(`/api/search?q=${encodeURIComponent(q)}`);
  el("search-results").innerHTML = hits.map(nodeRowHtml).join("");
  bindNodeRows(el("search-results"));
}

async function load(params = {}) {
  const query = new URLSearchParams({
    show_heuristic: el("show-heuristic").checked,
    min_pagerank: el("min-pagerank").value,
    limit: el("limit").value,
    ...params,
  });
  const data = await api(`/api/graph?${query.toString()}`);
  renderGraph(data);
}

el("apply").addEventListener("click", () => load());
el("search").addEventListener("input", (e) => runSearch(e.target.value));

el("min-pagerank").addEventListener("input", (e) => {
  el("min-pagerank-value").textContent = Number(e.target.value).toFixed(4);
});

function fixupEmbeddedTopbar() {
  const doc = el("static-view").contentDocument;
  const style = doc.createElement("style");
  style.textContent = `
    #topbar #brand { display: none; }
    #topbar { top: 82px; }
    #search-box { position: absolute; left: 50%; transform: translateX(-50%); margin: 0; flex: none; width: min(520px, 90vw); }
  `;
  doc.head.append(style);
}

function moveSwitchThumb() {
  const active = document.querySelector("#view-switch button.active");
  const thumb = document.querySelector("#view-switch .switch-thumb");
  thumb.style.left = `${active.offsetLeft}px`;
  thumb.style.width = `${active.offsetWidth}px`;
}

function showView(view) {
  const live = view === "live";
  el("view-live").classList.toggle("active", live);
  el("view-static").classList.toggle("active", !live);
  el("layout").classList.toggle("hidden", !live);
  el("static-view").classList.toggle("hidden", live);
  if (!live && !el("static-view").src) {
    el("static-view").addEventListener("load", fixupEmbeddedTopbar, { once: true });
    el("static-view").src = "graph.html";
  }
  moveSwitchThumb();
}
el("view-live").addEventListener("click", () => showView("live"));
el("view-static").addEventListener("click", () => showView("static"));
moveSwitchThumb();

el("t-zoom-in").addEventListener("click", () => orb && orb.zoomIn());
el("t-zoom-out").addEventListener("click", () => orb && orb.zoomOut());
el("t-fit").addEventListener("click", () => orb && orb.recenter());
el("t-reset").addEventListener("click", () => {
  el("show-heuristic").checked = false;
  el("min-pagerank").value = 0;
  el("min-pagerank-value").textContent = "0.0000";
  el("limit").value = 800;
  hoveredNode = null;
  load();
});

const PANELS = ["sidebar", "detail", "toolbar"];
function panelEl(id) {
  return id === "header" ? document.querySelector("header") : el(id);
}
function toggleAllPanels() {
  const hidden = !panelEl("header").classList.contains("hidden");
  ["header", ...PANELS].forEach((id) => panelEl(id).classList.toggle("hidden", hidden));
  el("t-panels").setAttribute("aria-pressed", String(!hidden));
}
function showAllPanels() {
  ["header", ...PANELS].forEach((id) => panelEl(id).classList.remove("hidden"));
  el("t-panels").setAttribute("aria-pressed", "true");
}

document.addEventListener("keydown", (e) => {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
  if (e.key.toLowerCase() !== "f") return;
  e.preventDefault();
  toggleAllPanels();
});

el("t-panels").addEventListener("click", toggleAllPanels);
el("d-close").addEventListener("click", () => el("detail").classList.add("hidden"));

let knownVersion = null;
async function pollVersion() {
  try {
    const { version } = await api("/api/version");
    if (knownVersion === null) knownVersion = version;
    else if (version !== knownVersion) location.reload();
  } catch (e) {
    // server mid-reindex or unreachable; try again next tick
  }
}
setInterval(pollVersion, 5000);

loadStats();
loadCommunities();
loadIssues();
load();
