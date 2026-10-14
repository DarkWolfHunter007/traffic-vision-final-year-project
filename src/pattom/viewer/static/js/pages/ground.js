// Ground points (T04, T48): click pixels on a frame, type the site measurements in metres.
import { api, esc, attempt, toast, $, $$ } from "../api.js";
import { FrameCanvas, line, dot, label } from "../framecanvas.js";

const ROLE_COLOR = { fit: "#3fd17a", check: "#ffb020" };
let spec, fc, mapping = null, mode = null, pending = null, report = {};

export async function render(root, args) {
  const data = await api("/api/ground");
  spec = data.spec; spec.mappings ||= {}; spec.landmarks ||= []; report = data.report || {};
  mapping = Object.keys(spec.mappings)[0] || null; mode = null; pending = null;
  root.innerHTML = `
    <h1>Ground points</h1>
    <p class="sub">Pixel-to-ground mapping (FR-24). Click a point on the frame, then type its position in metres from your site measurements. At least 4 <b>fit</b> points per mapping, plus <b>check</b> points or check distances that are never used to fit: they give the error in metres. Saved to <span class="mono">${esc(data.path)}</span>.</p>
    ${data.from_example ? `<div class="notice info">No ground points saved yet (T04 site measurements).</div>` : ""}
    <div class="split wide">
      <div class="panel"><div id="fc"></div></div>
      <div class="grid">
        <div class="panel">
          <div class="row"><label class="f">Mapping<select id="mapsel"></select></label><button id="addmap">New mapping</button><span class="spacer"></span><button id="fit">Fit and check</button><button id="save" class="primary">Save</button></div>
          <div class="row" style="margin-top:8px">
            <button data-mode="point">Add point</button><button data-mode="zone">Zone corners</button>
            <button data-mode="distance">Check distance</button><button data-mode="landmark">Drift landmark</button>
            <button data-mode="">Stop clicking</button>
          </div>
          <p id="hint" class="small muted"></p>
          <div id="report"></div>
        </div>
        <div class="panel"><h3>Points</h3><div id="points"></div></div>
        <div class="panel"><h3>Check distances</h3><div id="dists"></div></div>
        <div class="panel"><h3>Zone and landmarks</h3><div id="zone"></div></div>
      </div>
    </div>`;
  fc = new FrameCanvas($("#fc"), { onClick: click, draw, video: args[0] });
  await fc.init();
  $("#addmap").onclick = () => {
    const n = prompt("Mapping name (e.g. all, north, south)"); if (!n) return;
    spec.mappings[n.trim()] ||= { zone_px: [], points: [], check_distances: [] }; mapping = n.trim(); drawAll();
  };
  $("#mapsel").onchange = e => { mapping = e.target.value; drawAll(); };
  $$("[data-mode]").forEach(b => b.onclick = () => setMode(b.dataset.mode || null));
  $("#fit").onclick = fit;
  $("#save").onclick = save;
  drawAll();
}

const m = () => spec.mappings[mapping];
const hint = t => { $("#hint").textContent = t || ""; };
const HINTS = { point: "Click a measured point (e.g. a zebra corner).", zone: "Click the corners of the area this mapping covers, in order.",
  distance: "Click both ends of a taped distance.", landmark: "Click two corners of a box around a fixed feature (pole, kerb corner)." };

function setMode(md) {
  if (md && md !== "landmark" && !mapping) { toast("Create a mapping first.", "bad"); return; }
  mode = md; pending = null; hint(HINTS[md] || "");
  $$("[data-mode]").forEach(b => b.classList.toggle("on", (b.dataset.mode || null) === md && !!md));
}

function click(p) {
  if (mode === "point") {
    const ids = new Set(m().points.map(x => x.id)); let n = m().points.length + 1, id; do { id = `P${n++}`; } while (ids.has(id));
    m().points.push({ id, px: p, m: [null, null], role: m().points.filter(x => x.role === "fit").length < 4 ? "fit" : "check" });
    hint(`${id} placed. Type its metres in the table.`);
  } else if (mode === "zone") {
    m().zone_px.push(p);
  } else if (mode === "distance" || mode === "landmark") {
    if (!pending) { pending = p; hint("Now the second point."); fc.redraw(); return; }
    if (mode === "distance") {
      const d = parseFloat(prompt("Measured distance between the two points, in metres:") || "");
      if (Number.isFinite(d) && d > 0) (m().check_distances ||= []).push({ a_px: pending, b_px: p, distance_m: d });
    } else {
      const id = prompt("Landmark name (e.g. pole_ne):");
      if (id) spec.landmarks.push({ id: id.trim(), box_px: [Math.min(pending[0], p[0]), Math.min(pending[1], p[1]), Math.max(pending[0], p[0]), Math.max(pending[1], p[1])] });
    }
    pending = null; hint(HINTS[mode]);
  } else return;
  drawAll();
}

function draw(ctx, k) {
  const cur = m();
  if (cur?.zone_px?.length) {
    ctx.fillStyle = "rgba(47,111,219,.15)"; ctx.strokeStyle = "#4fa3ff"; ctx.lineWidth = 2;
    ctx.beginPath(); cur.zone_px.forEach(([x, y], i) => i ? ctx.lineTo(x * k, y * k) : ctx.moveTo(x * k, y * k)); ctx.closePath(); ctx.fill(); ctx.stroke();
  }
  for (const d of cur?.check_distances || []) { line(ctx, k, d.a_px, d.b_px, "#ff7ad9", 2); label(ctx, k, d.b_px, `${d.distance_m} m`, "#ff7ad9"); }
  for (const pt of cur?.points || []) {
    dot(ctx, k, pt.px, ROLE_COLOR[pt.role] || "#fff", 6);
    label(ctx, k, pt.px, `${pt.id}${pt.m?.every(v => v !== null && v !== "") ? ` (${pt.m.join(", ")} m)` : " (no metres)"}`, ROLE_COLOR[pt.role]);
  }
  for (const lm of spec.landmarks) {
    const [x1, y1, x2, y2] = lm.box_px; ctx.strokeStyle = "#00e5ff"; ctx.lineWidth = 2; ctx.strokeRect(x1 * k, y1 * k, (x2 - x1) * k, (y2 - y1) * k);
    label(ctx, k, [x1, y1], lm.id, "#00e5ff");
  }
  if (pending) dot(ctx, k, pending, "#ffd400", 5);
}

function drawAll() {
  $("#mapsel").innerHTML = Object.keys(spec.mappings).map(n => `<option ${n === mapping ? "selected" : ""}>${esc(n)}</option>`).join("") || `<option value="">none</option>`;
  const cur = m();
  $("#points").innerHTML = cur?.points?.length ? `<table><tr><th>Id</th><th>Pixel</th><th>x (m)</th><th>y (m)</th><th>Role</th><th></th></tr>
    ${cur.points.map((p, i) => `<tr data-p="${i}"><td><input data-pf="id" value="${esc(p.id)}" style="width:52px"></td><td class="mono small nw">${p.px.join(", ")}</td>
      <td><input data-pf="mx" type="number" step="0.01" value="${p.m?.[0] ?? ""}" style="width:66px"></td>
      <td><input data-pf="my" type="number" step="0.01" value="${p.m?.[1] ?? ""}" style="width:66px"></td>
      <td><select data-pf="role"><option ${p.role === "fit" ? "selected" : ""}>fit</option><option ${p.role === "check" ? "selected" : ""}>check</option></select></td>
      <td><button data-pdel="${i}" class="danger">✕</button></td></tr>`).join("")}</table>` : `<p class="muted small">${mapping ? "No points yet." : "Create a mapping first."}</p>`;
  $$("[data-pf]").forEach(inp => inp.onchange = () => {
    const p = cur.points[+inp.closest("[data-p]").dataset.p], f = inp.dataset.pf;
    if (f === "mx" || f === "my") { p.m ||= [null, null]; p.m[f === "mx" ? 0 : 1] = inp.value === "" ? null : +inp.value; }
    else p[f] = inp.value.trim();
    fc.redraw();
  });
  $$("[data-pdel]").forEach(b => b.onclick = () => { cur.points.splice(+b.dataset.pdel, 1); drawAll(); });
  $("#dists").innerHTML = cur?.check_distances?.length ? `<table><tr><th>From</th><th>To</th><th>Metres</th><th></th></tr>${cur.check_distances.map((d, i) => `
    <tr><td class="mono small">${d.a_px.join(", ")}</td><td class="mono small">${d.b_px.join(", ")}</td><td>${d.distance_m}</td><td><button data-ddel="${i}" class="danger">✕</button></td></tr>`).join("")}</table>` : `<p class="muted small">None.</p>`;
  $$("[data-ddel]").forEach(b => b.onclick = () => { cur.check_distances.splice(+b.dataset.ddel, 1); drawAll(); });
  $("#zone").innerHTML = `<p class="small">Zone: ${cur?.zone_px?.length ? `${cur.zone_px.length} corners <button id="zclear">Clear</button>` : "<span class='muted'>not set</span>"}</p>
    <p class="small">Landmarks: ${spec.landmarks.map((l, i) => `<span class="chip">${esc(l.id)} <a href="#" data-ldel="${i}">✕</a></span>`).join(" ") || "<span class='muted'>none</span>"}</p>`;
  const zc = $("#zclear"); if (zc) zc.onclick = () => { cur.zone_px = []; drawAll(); };
  $$("[data-ldel]").forEach(a => a.onclick = e => { e.preventDefault(); spec.landmarks.splice(+a.dataset.ldel, 1); drawAll(); });
  drawReport();
  fc?.redraw();
}

function drawReport() {
  const r = report[mapping];
  $("#report").innerHTML = !r ? "" : r.ok
    ? `<div class="notice ok">Fitted on ${r.fit_points} points · largest check error <b>${r.max_check_error_m.toFixed(3)} m</b> · fit residual (RMS) ${r.rms_fit_residual_m.toFixed(3)} m
       <div class="small">${Object.entries(r.check_point_errors_m).map(([k, v]) => `${esc(k)}: ${v.toFixed(3)} m`).join(" · ")}${r.check_distance_errors_m.length ? ` · distances: ${r.check_distance_errors_m.map(v => v.toFixed(3) + " m").join(", ")}` : ""}</div></div>`
    : `<div class="notice bad">${esc(r.error)}</div>`;
}

function cleaned() {
  for (const mp of Object.values(spec.mappings)) for (const p of mp.points) if (p.m?.some(v => v === null || v === "")) throw new Error(`${p.id}: type both metre values`);
  return spec;
}

async function fit() {
  const s = await attempt(async () => cleaned());
  if (!s) return;
  report = await attempt(() => api("/api/ground/fit", { method: "POST", body: s })) || report;
  drawReport();
}

async function save() {
  const s = await attempt(async () => cleaned());
  if (!s) return;
  const r = await attempt(() => api("/api/ground", { method: "PUT", body: s }), "Ground points saved");
  if (r) { report = r.report; drawReport(); }
}
