// Manual counts from playback (FR-08, T17): one person counts sampled windows; the count-validation block compares.
import { api, esc, attempt, toast, fmtTime, CLASS_COLORS, $, $$ } from "../api.js";

let key, data, windows, cur, video, alive;

export function leave() {
  alive = false; document.onkeydown = null;
  if (video) { video.ontimeupdate = video.onseeked = null; video.pause(); video.removeAttribute("src"); video.load(); }
}

export async function render(root, args) {
  alive = true;
  const runs = (await api("/api/runs")).filter(r => r.has_tracks);
  root.innerHTML = `
    <h1>Manual counts</h1>
    <p class="sub">Count vehicles yourself on short sampled windows, one line at a time, to measure the counting error per approach and class (including the west). Times are video time, the same clock as the automatic crossings.</p>
    ${runs.length ? "" : `<div class="notice">No tracked runs yet.</div>`}
    <div class="split wide">
      <div class="panel">
        <div class="row" style="margin-bottom:8px">
          <label class="f">Run<select id="run">${runs.map(r => `<option value="${r.slot}/${r.video}">${esc(r.slot)} / ${esc(r.video)}</option>`).join("")}</select></label>
          <label class="f">Counting line<select id="line"></select></label>
          <label class="f">Speed<select id="rate"><option>0.5</option><option selected>1</option><option>2</option></select></label>
        </div>
        <div class="stage"><video id="video" controls muted preload="auto"></video></div>
        <div class="row" style="margin-top:8px">
          <button id="start" class="primary">Start window here</button><button id="end">End window here</button>
          <span id="state" class="small muted"></span><span class="spacer"></span><span id="now" class="mono small"></span>
        </div>
        <div class="row" id="classes" style="margin-top:8px"></div>
        <p class="small muted">Keys: <kbd>1</kbd>–<kbd>9</kbd> add one vehicle of that class · <kbd>Backspace</kbd> undo the last · <kbd>space</kbd> play/pause</p>
      </div>
      <div class="panel">
        <div class="row"><h3 style="margin:0">Windows</h3><span class="spacer"></span><button id="save" class="primary">Save</button></div>
        <p id="path" class="mono small muted"></p>
        <div id="wins"></div>
        <a href="#/pipeline" class="small">Then set manual_counts as a pipeline input and run count-validation</a>
      </div>
    </div>`;
  video = $("#video");
  video.ontimeupdate = () => { if (alive && $("#now")) $("#now").textContent = fmtTime(video.currentTime); };
  video.onseeked = video.ontimeupdate;
  $("#rate").onchange = e => { video.playbackRate = +e.target.value; };
  $("#run").onchange = e => open(e.target.value);
  $("#start").onclick = () => { cur = { window_start_s: round(video.currentTime), line_name: $("#line").value, counts: {}, log: [] }; drawCur(); };
  $("#end").onclick = finish;
  $("#save").onclick = save;
  document.onkeydown = keys;
  if (runs.length) await open(args[0] && args[1] ? `${args[0]}/${args[1]}` : $("#run").value);
}

const round = t => Math.round(t * 100) / 100;

async function open(k) {
  key = k; $("#run").value = k;
  data = await api(`/api/manual/${k}`);
  $("#line").innerHTML = data.lines.filter(l => l.type !== "exit").map(l => `<option value="${esc(l.name)}">${esc(l.name)} (${esc(l.approach)}, ${esc(l.type)})</option>`).join("")
    || `<option value="">no counting lines yet</option>`;
  $("#path").textContent = data.path;
  video.src = `/api/videos/stream?path=${encodeURIComponent(data.video_file)}`;
  const by = {};
  for (const r of data.rows) {
    const id = `${r.window_start_s}|${r.window_end_s}|${r.line_name}`;
    (by[id] ||= { window_start_s: +r.window_start_s, window_end_s: +r.window_end_s, line_name: r.line_name, counts: {} }).counts[r.class] = +r.count;
  }
  windows = Object.values(by); cur = null;
  drawCur(); drawWindows();
}

function drawCur() {
  $("#classes").innerHTML = data.classes.map((c, i) => `<button data-c="${esc(c)}"><i class="sw" style="background:${CLASS_COLORS[c] || "#ccc"}"></i>${i + 1}. ${esc(c)} <b>${cur?.counts[c] || 0}</b></button>`).join("");
  $$("[data-c]").forEach(b => b.onclick = () => add(b.dataset.c));
  $("#state").textContent = cur ? `counting ${cur.line_name} from ${fmtTime(cur.window_start_s)}` : "Start a window to count.";
}

function add(c) {
  if (!cur) { toast("Start a window first.", "bad"); return; }
  cur.counts[c] = (cur.counts[c] || 0) + 1; cur.log.push(c); drawCur();
}

function finish() {
  if (!cur) { toast("Start a window first.", "bad"); return; }
  const end = round(video.currentTime);
  if (end <= cur.window_start_s) { toast("The end must be after the start.", "bad"); return; }
  cur.window_end_s = end;
  for (const c of data.classes) cur.counts[c] ||= 0;  // a class not seen is a count of 0, not missing
  delete cur.log; windows.push(cur); cur = null; drawCur(); drawWindows();
}

function drawWindows() {
  $("#wins").innerHTML = windows.length ? `<table><tr><th>Line</th><th>From</th><th>To</th><th>Counts</th><th></th></tr>${windows.map((w, i) => `
    <tr><td>${esc(w.line_name)}</td><td class="mono small">${fmtTime(w.window_start_s)}</td><td class="mono small">${fmtTime(w.window_end_s)}</td>
      <td class="small">${Object.entries(w.counts).map(([c, n]) => `${esc(c)} ${n}`).join(", ")}</td><td><button data-wdel="${i}" class="danger">✕</button></td></tr>`).join("")}</table>`
    : `<p class="small muted">No windows yet.</p>`;
  $$("[data-wdel]").forEach(b => b.onclick = () => { windows.splice(+b.dataset.wdel, 1); drawWindows(); });
}

async function save() {
  if (cur) { toast("End the open window first.", "bad"); return; }
  const r = await attempt(() => api(`/api/manual/${key}`, { method: "PUT", body: { windows } }), "Manual counts saved");
  if (r) data = r;
}

function keys(e) {
  if (!alive || ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (e.key === " ") { e.preventDefault(); video.paused ? video.play() : video.pause(); }
  else if (/^[1-9]$/.test(e.key) && data.classes[+e.key - 1]) add(data.classes[+e.key - 1]);
  else if (e.key === "Backspace" && cur?.log.length) { const c = cur.log.pop(); cur.counts[c]--; drawCur(); }
}
