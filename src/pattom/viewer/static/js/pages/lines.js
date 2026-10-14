// Counting lines and movements (T18): click two points on a frame to add a line.
import { api, esc, attempt, toast, $, $$ } from "../api.js";
import { FrameCanvas, line, label, arrow, dot } from "../framecanvas.js";

const TYPES = ["stop_line", "arrival", "exit"];
const DIRS = ["left", "right", "both"];
const APPROACHES = ["north", "south", "east", "west"];
const MOVES = ["through", "left", "right", "free_left"];
const COLOR = { stop_line: "#ff5a4f", arrival: "#4fa3ff", exit: "#3fd17a" };
let spec, fc, pending = null, mode = null, hover = null, selected = null, dirty = false;

export async function render(root, args) {
  const data = await api("/api/lines");
  spec = data.spec; pending = null; mode = null; selected = null; dirty = false;
  root.innerHTML = `
    <h1>Counting lines</h1>
    <p class="sub">Where vehicles are counted (FR-09). A line counts one direction: the arrow shows the side a counted vehicle comes from. Draw on the prepared (undistorted) video, the same pixels the tracker uses. Saved to <span class="mono">${esc(data.path)}</span>.</p>
    ${data.from_example ? `<div class="notice info">No lines saved yet. The final positions follow the written definitions (T46) and decisions O9 (free lefts) and O10 (west).</div>` : ""}
    <div class="split wide">
      <div class="panel"><div id="fc"></div></div>
      <div class="grid">
        <div class="panel">
          <div class="row"><button id="add" class="primary">Add line (click 2 points)</button><span class="spacer"></span><span id="dirty" class="small muted"></span><button id="save">Save</button></div>
          <p id="hint" class="small muted"></p>
          <div id="list"></div>
        </div>
        <div class="panel"><h3>Movements</h3><p class="small muted">A track that crosses the entry line and later the exit line gets this movement.</p>
          <div id="moves"></div><button id="addmove" style="margin-top:6px">Add movement</button></div>
      </div>
    </div>`;
  fc = new FrameCanvas($("#fc"), { onClick: click, onMove: p => { hover = p; if (pending) fc.redraw(); }, draw, video: args[0] });
  await fc.init();
  $("#add").onclick = () => { mode = "add"; pending = null; hint("Click the first end of the new line."); };
  $("#save").onclick = save;
  $("#addmove").onclick = () => { spec.movements.push({ approach: "north", movement: "through", entry_line: spec.lines[0]?.name || "", exit_line: spec.lines[1]?.name || "" }); touch(); drawMoves(); };
  drawList(); drawMoves();
}

const hint = t => { $("#hint").textContent = t || ""; };
function touch() { dirty = true; $("#dirty").textContent = "unsaved"; fc.redraw(); }

function click(p) {
  if (!mode) return;
  if (!pending) { pending = p; hint("Now click the second end."); fc.redraw(); return; }
  if (mode === "add") {
    let n = spec.lines.length + 1, name; do { name = `L${n++}`; } while (spec.lines.some(l => l.name === name));
    spec.lines.push({ name, type: "stop_line", approach: "north", endpoints_px: [pending, p], direction: "left" });
    selected = name;
  } else {
    spec.lines.find(l => l.name === mode.slice(7)).endpoints_px = [pending, p];
  }
  pending = null; mode = null; hint("Set the name, type, approach and direction below."); touch(); drawList();
}

function draw(ctx, k) {
  for (const l of spec.lines) {
    const [a, b] = l.endpoints_px, col = COLOR[l.type] || "#fff", sel = l.name === selected;
    line(ctx, k, a, b, col, sel ? 5 : 3);
    dot(ctx, k, a, col, 4); dot(ctx, k, b, col, 4);
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    const n = [-(b[1] - a[1]) / len, (b[0] - a[0]) / len];  // points to the right of a -> b (y down)
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], L = 28 / k;
    const across = s => arrow(ctx, k, [mid[0] - s * n[0] * L, mid[1] - s * n[1] * L], [mid[0] + s * n[0] * L, mid[1] + s * n[1] * L], col);
    if (l.direction === "left" || l.direction === "both") across(1);
    if (l.direction === "right" || l.direction === "both") across(-1);
    label(ctx, k, a, `${l.name} · ${l.type}`, col);
  }
  if (pending) { dot(ctx, k, pending, "#ffd400", 5); if (hover) line(ctx, k, pending, hover, "#ffd400", 2); }
}

function drawList() {
  $("#list").innerHTML = spec.lines.length ? spec.lines.map((l, i) => `
    <div class="block ${l.name === selected ? "" : "off"}" style="border-left-color:${COLOR[l.type]};opacity:1" data-i="${i}">
      <div class="row">
        <input data-f="name" value="${esc(l.name)}" style="width:110px">
        <select data-f="type">${TYPES.map(t => `<option ${t === l.type ? "selected" : ""}>${t}</option>`).join("")}</select>
        <select data-f="approach">${APPROACHES.map(t => `<option ${t === l.approach ? "selected" : ""}>${t}</option>`).join("")}</select>
        <select data-f="direction" title="side a counted vehicle comes from">${DIRS.map(t => `<option ${t === l.direction ? "selected" : ""}>${t}</option>`).join("")}</select>
      </div>
      <div class="row small muted" style="margin-top:4px"><span class="mono">${l.endpoints_px.map(p => `(${p})`).join(" → ")}</span><span class="spacer"></span>
        <button data-redraw="${i}">Redraw</button><button data-del="${i}" class="danger">Delete</button></div>
    </div>`).join("") : `<p class="muted small">No lines yet.</p>`;
  $$("#list [data-f]").forEach(inp => inp.onchange = () => {
    const i = +inp.closest("[data-i]").dataset.i, f = inp.dataset.f, old = spec.lines[i].name;
    spec.lines[i][f] = inp.value.trim();
    if (f === "name") spec.movements.forEach(m => { if (m.entry_line === old) m.entry_line = inp.value.trim(); if (m.exit_line === old) m.exit_line = inp.value.trim(); });
    touch(); drawMoves();
  });
  $$("#list [data-del]").forEach(b => b.onclick = () => { spec.lines.splice(+b.dataset.del, 1); touch(); drawList(); drawMoves(); });
  $$("#list [data-redraw]").forEach(b => b.onclick = () => { mode = `redraw:${spec.lines[+b.dataset.redraw].name}`; pending = null; hint("Click the first end."); });
  $$("#list [data-i]").forEach(d => d.onclick = e => { if (e.target.closest("input,select,button")) return; selected = spec.lines[+d.dataset.i].name; drawList(); fc.redraw(); });
}

function drawMoves() {
  const names = spec.lines.map(l => l.name);
  const sel = (f, v, opts) => `<select data-mf="${f}">${opts.map(o => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  $("#moves").innerHTML = spec.movements.length ? `<table><tr><th>Approach</th><th>Movement</th><th>Entry</th><th>Exit</th><th></th></tr>
    ${spec.movements.map((m, i) => `<tr data-m="${i}"><td>${sel("approach", m.approach, APPROACHES)}</td><td>${sel("movement", m.movement, MOVES)}</td>
      <td>${sel("entry_line", m.entry_line, names)}</td><td>${sel("exit_line", m.exit_line, names)}</td><td><button data-mdel="${i}" class="danger">✕</button></td></tr>`).join("")}</table>`
    : `<p class="muted small">No movements. Line counts still work without them.</p>`;
  $$("[data-mf]").forEach(s => s.onchange = () => { spec.movements[+s.closest("[data-m]").dataset.m][s.dataset.mf] = s.value; touch(); });
  $$("[data-mdel]").forEach(b => b.onclick = () => { spec.movements.splice(+b.dataset.mdel, 1); touch(); drawMoves(); });
}

async function save() {
  if (!spec.lines.length) { toast("Add at least one line first.", "bad"); return; }
  const r = await attempt(() => api("/api/lines", { method: "PUT", body: spec }), "Counting lines saved");
  if (r) { spec = r.spec; dirty = false; $("#dirty").textContent = ""; drawList(); drawMoves(); fc.redraw(); }
}
