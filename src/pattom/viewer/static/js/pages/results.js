// Results: the prepared video with boxes drawn over it, the track list, and the run's tables.
import { api, esc, chip, fmtTime, CLASS_COLORS, $ } from "../api.js";

const WINDOW = 600;  // processed frames per fetch
let run, cache, loading, selected, video, canvas, ctx, alive;

export function leave() {
  alive = false; document.onkeydown = null; window.onresize = null;
  if (video) { video.onseeked = video.onloadeddata = video.onplay = video.onpause = null; video.pause(); video.removeAttribute("src"); video.load(); }
}

export async function render(root, args) {
  alive = true;
  const runs = await api("/api/runs");
  root.innerHTML = `
    <h1>Results</h1>
    <p class="sub">Display only. Boxes are detections, not counts; a vehicle can be split into several tracks.</p>
    <div class="panel row" style="margin-bottom:12px">
      <label class="f">Run<select id="run">${runs.map(r => `<option value="${r.slot}/${r.video}">${esc(r.slot)} / ${esc(r.video)}${r.has_tracks ? "" : " (no tracks)"}</option>`).join("")}</select></label>
      <label class="f">Boxes<select id="source"><option value="tracks">tracks</option><option value="detections">detections</option></select></label>
      <label class="f">Min confidence <span><input id="conf" type="range" min="0" max="1" step="0.05" value="0"> <span id="confv">0.00</span></span></label>
      <span id="info" class="muted small"></span>
    </div>
    ${runs.length ? "" : `<div class="notice">No runs yet. Run detect and track on the Pipeline page.</div>`}
    <div class="split">
      <div>
        <div class="panel">
          <div id="notice" class="notice" hidden></div>
          <div class="stage" id="stage"><video id="video" muted playsinline preload="auto"></video><canvas id="overlay" class="passive"></canvas></div>
          <div class="row" style="margin-top:8px">
            <button id="back" title="previous processed frame (←)">◀</button>
            <button id="play" title="play / pause (space)">Play</button>
            <button id="fwd" title="next processed frame (→)">▶</button>
            <input id="seek" type="range" min="0" max="1" step="0.001" value="0" style="flex:1">
            <span id="clock" class="mono small" style="min-width:170px">–</span>
          </div>
          <div class="legend" style="margin-top:6px">${Object.entries(CLASS_COLORS).map(([c, v]) => `<span><i class="sw" style="background:${v}"></i>${c}</span>`).join("")}</div>
        </div>
        <div class="panel" style="margin-top:12px"><h3>Output tables</h3><div class="row" id="files"></div><div id="table" class="scroll" style="margin-top:8px"></div></div>
      </div>
      <div class="panel"><h3>Tracks <span id="ntracks" class="muted"></span></h3>
        <div class="scroll" style="max-height:640px"><table id="tracks"></table></div></div>
    </div>`;
  video = $("#video"); canvas = $("#overlay"); ctx = canvas.getContext("2d");
  wire();
  if (!runs.length) return;
  const want = args[0] && args[1] ? `${args[0]}/${args[1]}` : null;
  if (want && runs.some(r => `${r.slot}/${r.video}` === want)) $("#run").value = want;
  await openRun($("#run").value);
  loop();
}

function notice(text) { $("#notice").hidden = !text; $("#notice").textContent = text || ""; $("#stage").hidden = !!text; }

async function openRun(key) {
  run = await api(`/api/runs/${key}`);
  run.key = key; cache = new Map(); loading = new Set(); selected = null;
  $("#source").value = run.has_tracks ? "tracks" : "detections";
  $("#info").textContent = `${run.width}×${run.height} · ${run.fps} fps · every ${run.frame_stride} frame(s) · ${run.model || ""} ${run.tracker || ""}`;
  if (run.notes) $("#info").textContent += ` · ${run.notes}`;
  if (run.video_playable) { notice(""); video.src = `/api/runs/${key}/video`; }
  else { notice(`${run.video_file} cannot be played in the browser (use the CFR .mp4 copy).`); video.removeAttribute("src"); }
  const rows = await api(`/api/runs/${key}/tracks`);
  $("#ntracks").textContent = `(${rows.length})`;
  $("#tracks").innerHTML = `<tr><th>ID</th><th>Class</th><th>Seen</th><th>From</th></tr>` + rows.map(r => `
    <tr class="click" data-id="${r.track_id}" data-t="${r.first_time_s}"><td class="mono">#${r.track_id}</td>
      <td><i class="sw" style="background:${CLASS_COLORS[r.majority_class] || "#ccc"}"></i>${esc(r.majority_class)}${+r.class_changes ? ` ${chip("±" + r.class_changes, "warn")}` : ""}</td>
      <td class="small">${(r.last_time_s - r.first_time_s).toFixed(1)} s</td><td class="small mono">${fmtTime(+r.first_time_s)}</td></tr>`).join("");
  const csvs = run.files.filter(f => f.endsWith(".csv"));
  $("#files").innerHTML = csvs.map(f => `<button data-file="${esc(f)}">${esc(f)}</button>`).join("") || `<span class="muted">No tables.</span>`;
  $("#table").innerHTML = "";
}

function frameAt(t) { const s = run.frame_stride; return Math.round(Math.round(t * run.fps) / s) * s; }

function boxesFor(frame) {
  const src = $("#source").value, chunk = Math.floor(frame / run.frame_stride / WINDOW), key = `${src}:${chunk}`;
  if (!cache.has(key) && !loading.has(key)) {
    loading.add(key);
    const start = chunk * WINDOW * run.frame_stride, end = start + WINDOW * run.frame_stride - 1;
    api(`/api/runs/${run.key}/boxes?source=${src}&start=${start}&end=${end}`).then(d => { cache.set(key, d); draw(); }).finally(() => loading.delete(key));
  }
  return (cache.get(key) || {})[frame] || [];
}

function draw(t = video.currentTime) {
  if (!run || !alive) return;
  const w = video.clientWidth, h = video.clientHeight;
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  ctx.clearRect(0, 0, w, h);
  const frame = frameAt(t), k = w / run.width, min = +$("#conf").value;
  ctx.font = "12px system-ui, sans-serif";
  for (const [id, cls, conf, x1, y1, x2, y2] of boxesFor(frame)) {
    if (conf < min) continue;
    const col = CLASS_COLORS[cls] || "#fff";
    ctx.strokeStyle = col; ctx.lineWidth = selected !== null && id === selected ? 4 : 2;
    ctx.strokeRect(x1 * k, y1 * k, (x2 - x1) * k, (y2 - y1) * k);
    const label = `${id !== null ? "#" + id + " " : ""}${cls} ${conf.toFixed(2)}`, tw = ctx.measureText(label).width + 6;
    ctx.fillStyle = col; ctx.fillRect(x1 * k, y1 * k - 16, tw, 16);
    ctx.fillStyle = "#000"; ctx.fillText(label, x1 * k + 3, y1 * k - 4);
  }
  $("#clock").textContent = `${fmtTime(t)} · frame ${frame}`;
  if (video.duration) $("#seek").value = t / video.duration;
}

function loop() {
  if ("requestVideoFrameCallback" in video) {
    const tick = (_, m) => { if (!alive) return; draw(m.mediaTime); video.requestVideoFrameCallback(tick); };
    video.requestVideoFrameCallback(tick);
  }
}

function step(dir) {
  video.pause();
  const target = (frameAt(video.currentTime) + dir * run.frame_stride) / run.fps;
  video.currentTime = Math.max(0, Math.min(video.duration || 0, target + 0.001));
}

async function showTable(name) {
  const t = await api(`/api/runs/${run.key}/table/${encodeURIComponent(name)}?limit=500`);
  $("#table").innerHTML = `<p class="small muted">${esc(name)} · first ${t.rows.length} rows</p><table><tr>${t.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr>
    ${t.rows.map(r => `<tr>${t.columns.map(c => `<td class="small">${esc(r[c])}</td>`).join("")}</tr>`).join("")}</table>`;
}

function wire() {
  $("#run").onchange = e => { location.hash = `#/results/${e.target.value}`; };
  $("#source").onchange = () => draw();
  $("#conf").oninput = e => { $("#confv").textContent = (+e.target.value).toFixed(2); draw(); };
  $("#play").onclick = () => video.paused ? video.play() : video.pause();
  $("#back").onclick = () => step(-1);
  $("#fwd").onclick = () => step(1);
  $("#seek").oninput = e => { if (video.duration) video.currentTime = e.target.value * video.duration; };
  video.onplay = () => $("#play").textContent = "Pause";
  video.onpause = () => $("#play").textContent = "Play";
  video.onseeked = () => draw();
  video.onloadeddata = () => draw();
  window.onresize = () => draw();
  $("#files").onclick = e => { const b = e.target.closest("[data-file]"); if (b) showTable(b.dataset.file); };
  $("#tracks").onclick = e => {
    const row = e.target.closest("tr[data-id]"); if (!row) return;
    $("#tracks").querySelectorAll(".sel").forEach(r => r.classList.remove("sel"));
    row.classList.add("sel"); selected = +row.dataset.id;
    video.pause(); video.currentTime = +row.dataset.t + 0.001;
  };
  document.onkeydown = e => {
    if (!alive || ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.key === " ") { e.preventDefault(); $("#play").click(); }
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  };
}
