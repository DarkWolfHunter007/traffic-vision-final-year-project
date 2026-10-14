// Settings: detection tiles with a preview on a real frame, then the raw YAML of both settings files.
import { api, esc, attempt, toast, chip, CLASS_COLORS, $, $$ } from "../api.js";
import { FrameCanvas, label } from "../framecanvas.js";

const KINDS = { detection: "Detection (YOLO)", tracker: "Tracker (ByteTrack)" };
let fc, tiling, preview, show;

function readTiling(text) {
  // The tiling keys from the detection YAML text (the server checks the file on save).
  const grab = key => { const m = text.match(new RegExp(`^${key}\\s*:\\s*(.+?)\\s*(#.*)?$`, "m")); return m ? m[1] : null; };
  const parse = v => { if (v === null || v === "null" || v === "~") return null; try { return JSON.parse(v.replace(/(\w+)\s*:/g, '"$1":')); } catch { return v; } };
  return { tiles: parse(grab("tiles")) || [], tile_grid: parse(grab("tile_grid")), tile_imgsz: +(grab("tile_imgsz") || 1280),
           merge_inside: parse(grab("merge_inside")), imgsz: +(grab("imgsz") || 1280) };
}

export async function render(root) {
  const data = await Promise.all(Object.keys(KINDS).map(k => api(`/api/settings/${k}`)));
  tiling = readTiling(data[0].text); preview = null; show = "with_tiles";
  root.innerHTML = `
    <h1>Settings</h1>
    <p class="sub">Tool settings for detection and tracking, tuned on the test clip. Whether tiling is used is a project decision (O7): compare on your own frames here first.</p>
    <div class="panel">
      <h3>Detection tiles for 4K video</h3>
      <p class="small muted">YOLO sees the whole frame shrunk to <b>imgsz</b> pixels wide, so far vehicles become a few pixels and are missed. Tiles are extra passes on parts of the frame at full resolution, merged with the whole-frame pass. More tiles see more but take longer per frame.</p>
      <div class="split wide">
        <div id="fc"></div>
        <div class="grid">
          <div class="row">
            <button data-preset="none">No tiles</button>
            <button data-preset="far">Far half (top)</button>
            <button data-preset="grid">Whole-frame grid</button>
            <button data-preset="draw">Draw a tile</button>
          </div>
          <div class="row">
            <label class="f">Grid tile size (px)<input id="gsize" type="number" value="${tiling.tile_grid?.size || 1280}" style="width:90px"></label>
            <label class="f">Overlap (px)<input id="gover" type="number" value="${tiling.tile_grid?.overlap ?? 256}" style="width:80px"></label>
            <label class="f">Tile imgsz<input id="timg" type="number" value="${tiling.tile_imgsz}" style="width:80px"></label>
          </div>
          <label class="small"><input type="checkbox" id="minside" ${tiling.merge_inside ? "checked" : ""}> Remove a box lying mostly inside a stronger one (tile-edge halves), share <input id="minv" type="number" step="0.05" min="0.5" max="1" value="${tiling.merge_inside || 0.85}" style="width:64px"></label>
          <div id="tiledesc" class="small"></div>
          <div class="row"><button id="prev" class="primary">Preview detection on this frame</button><button id="apply">Save tiles to detection settings</button></div>
          <div id="pres" class="small"></div>
        </div>
      </div>
    </div>
    <div class="grid cols-2" style="margin-top:12px">${data.map(d => `
      <div class="panel">
        <div class="row"><h3 style="margin:0">${esc(KINDS[d.kind])}</h3><span class="spacer"></span><span class="mono small muted">${esc(d.path)}</span></div>
        ${d.from_example ? `<div class="notice info">Not created yet: showing the example. Save to create it.</div>` : ""}
        <textarea id="t-${d.kind}" rows="24" spellcheck="false">${esc(d.text)}</textarea>
        <div class="row end" style="margin-top:8px"><span id="m-${d.kind}" class="small muted"></span><button class="primary" data-save="${d.kind}">Save</button></div>
      </div>`).join("")}</div>
    <div class="notice info" style="margin-top:12px">Detection uses the GPU only when PyTorch is the CUDA build. Start the app with <span class="mono">uv run --no-sync pattom view</span> so uv does not swap it back.</div>`;

  let drawStart = null;
  fc = new FrameCanvas($("#fc"), {
    draw: drawFrame,
    onClick: p => {
      if (!drawStart && $('[data-preset="draw"]').classList.contains("on")) { drawStart = p; return; }
      if (drawStart) {
        const t = [Math.min(drawStart[0], p[0]), Math.min(drawStart[1], p[1]), Math.max(drawStart[0], p[0]), Math.max(drawStart[1], p[1])];
        if (t[2] - t[0] > 32 && t[3] - t[1] > 32) tiling.tiles = [...tiling.tiles, t];
        drawStart = null; preview = null; describe(); fc.redraw();
      }
    },
  });
  await fc.init();
  $$("[data-preset]").forEach(b => b.onclick = () => preset(b.dataset.preset));
  ["gsize", "gover"].forEach(id => $(`#${id}`).onchange = () => { if (tiling.tile_grid) { tiling.tile_grid = gridSpec(tiling.tile_grid.region); preview = null; describe(); fc.redraw(); } });
  $("#timg").onchange = e => { tiling.tile_imgsz = +e.target.value; };
  $("#minside").onchange = $("#minv").onchange = () => { tiling.merge_inside = $("#minside").checked ? +$("#minv").value : null; };
  $("#prev").onclick = runPreview;
  $("#apply").onclick = () => attempt(async () => {
    await api("/api/settings/detection/tiling", { method: "PUT", body: { tiles: tiling.tiles, tile_grid: tiling.tile_grid, tile_imgsz: tiling.tile_imgsz, merge_inside: tiling.merge_inside } });
    $("#t-detection").value = (await api("/api/settings/detection")).text;
  }, "Tiles saved to the detection settings");
  root.addEventListener("click", async e => {
    const b = e.target.closest("[data-save]"); if (!b) return;
    const k = b.dataset.save;
    const r = await attempt(() => api(`/api/settings/${k}`, { method: "PUT", body: { text: $(`#t-${k}`).value } }), `${KINDS[k]} settings saved`);
    if (r) { $(`#m-${k}`).textContent = "saved"; if (k === "detection") { tiling = readTiling(r.text); describe(); fc.redraw(); } }
  });
  describe();
}

function gridSpec(region) {
  const g = { size: +$("#gsize").value, overlap: +$("#gover").value };
  if (region) g.region = region;
  return g;
}

function preset(name) {
  $$("[data-preset]").forEach(b => b.classList.toggle("on", b.dataset.preset === name));
  const [w, h] = fc.full || [3840, 2160];
  if (name === "none") { tiling.tiles = []; tiling.tile_grid = null; }
  if (name === "far") { tiling.tiles = []; tiling.tile_grid = gridSpec([0, 0, w, Math.round(h / 2)]); }
  if (name === "grid") { tiling.tiles = []; tiling.tile_grid = gridSpec(null); }
  if (name === "draw") { toast("Click two opposite corners of the tile on the frame."); return; }
  preview = null; describe(); fc.redraw();
}

// Same rule as pattom.detection.grid_tiles, for drawing before a preview.
function starts(lo, hi, size, overlap) {
  if (hi - lo <= size) return [lo];
  const out = []; let s = lo;
  while (s + size < hi) { out.push(s); s += size - overlap; }
  out.push(hi - size); return out;
}
function allTiles() {
  if (preview) return preview.tiles;
  const [w, h] = fc?.full || [3840, 2160], g = tiling.tile_grid, t = [...tiling.tiles];
  if (g) {
    const [x1, y1, x2, y2] = g.region || [0, 0, w, h];
    for (const y of starts(y1, Math.min(h, y2), g.size, g.overlap || 0)) for (const x of starts(x1, Math.min(w, x2), g.size, g.overlap || 0))
      t.push([x, y, Math.min(x + g.size, x2), Math.min(y + g.size, y2)]);
  }
  return t;
}

function describe() {
  const n = allTiles().length;
  $("#tiledesc").innerHTML = n ? `${n} tile(s) plus the whole-frame pass: about ${n + 1}× the work per frame.` : "No tiles: one whole-frame pass per frame.";
}

function drawFrame(ctx, k) {
  ctx.setLineDash([8, 5]);
  allTiles().forEach(([x1, y1, x2, y2], i) => {
    ctx.strokeStyle = "rgba(255,255,255,.85)"; ctx.lineWidth = 1.5; ctx.strokeRect(x1 * k, y1 * k, (x2 - x1) * k, (y2 - y1) * k);
    label(ctx, k, [x1, y1 + 30 / k], `tile${i}`, "#fff");
  });
  ctx.setLineDash([]);
  const res = preview?.[show];
  for (const b of res?.boxes || []) {
    const [x1, y1, x2, y2] = b.xyxy, col = CLASS_COLORS[b.class] || "#fff";
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.strokeRect(x1 * k, y1 * k, (x2 - x1) * k, (y2 - y1) * k);
  }
}

async function runPreview() {
  $("#pres").innerHTML = `<span class="muted">Running YOLO on this frame twice (whole frame, then with tiles)… the first run loads the model.</span>`;
  const r = await attempt(() => api("/api/detect/preview", { method: "POST", body: {
    path: fc.path, t: fc.t, tiles: tiling.tiles, tile_grid: tiling.tile_grid, tile_imgsz: tiling.tile_imgsz, merge_inside: tiling.merge_inside } }));
  if (!r) { $("#pres").innerHTML = ""; return; }
  preview = r; show = "with_tiles";
  const sum = res => { const c = {}; res.boxes.filter(b => b.confidence >= 0.5).forEach(b => c[b.class] = (c[b.class] || 0) + 1); return c; };
  const row = (name, res) => { const c = sum(res); const n = Object.values(c).reduce((a, b) => a + b, 0);
    return `<tr class="click ${show === name ? "sel" : ""}" data-show="${name}"><td>${name === "whole_frame" ? "Whole frame only" : `With ${r.tiles.length} tile(s)`}</td><td><b>${n}</b></td>
      <td>${Object.entries(c).map(([k, v]) => `<i class="sw" style="background:${CLASS_COLORS[k] || "#ccc"}"></i>${esc(k)} ${v}`).join(" ")}</td><td>${res.seconds.toFixed(2)} s</td></tr>`; };
  const draw = () => {
    $("#pres").innerHTML = `<table><tr><th>Pass</th><th>Boxes ≥ 0.5</th><th>By class</th><th>Time</th></tr>${row("whole_frame", r.whole_frame)}${row("with_tiles", r.with_tiles)}</table>
      <p class="muted">Click a row to show its boxes. All boxes are drawn, including weak ones the tracker uses. Check by eye for missed vehicles and doubles at tile edges. Time includes the model's first load on the first preview.</p>`;
    $$("#pres [data-show]").forEach(t => t.onclick = () => { show = t.dataset.show; draw(); fc.redraw(); });
  };
  draw(); describe(); fc.redraw();
}
