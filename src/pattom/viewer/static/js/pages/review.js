// Review and labels (FR-06, FR-07): check flagged frames, correct the boxes, save YOLO-format labels.
import { api, esc, chip, attempt, toast, CLASS_COLORS, $, $$ } from "../api.js";
import { label as drawLabel } from "../framecanvas.js";

let run, info, boxes, sel, frame, reason, k, full, addStart, img, canvas, ctx;

export async function render(root, args) {
  const runs = (await api("/api/runs")).filter(r => r.has_tracks);
  root.innerHTML = `
    <h1>Review and labels</h1>
    <p class="sub">Frames flagged by the review block (low confidence, class changes, vanished tracks, hard zones, a random sample). Correct the boxes and save: each saved frame becomes a training image and label in YOLO format, and a line in the review log. Keep these files on this PC (privacy, O16).</p>
    ${runs.length ? "" : `<div class="notice">No tracked runs yet.</div>`}
    <div class="panel row" style="margin-bottom:12px">
      <label class="f">Run<select id="run">${runs.map(r => `<option value="${r.slot}/${r.video}">${esc(r.slot)} / ${esc(r.video)}</option>`).join("")}</select></label>
      <label class="f">Go to frame<input id="goto" type="number" min="0" style="width:100px"></label><button id="gobtn">Open</button>
      <span id="rinfo" class="small muted"></span>
    </div>
    <div class="split wide">
      <div class="panel">
        <div class="stage crosshair"><img id="rimg" alt="frame"><canvas id="rcanvas"></canvas></div>
        <div class="row" style="margin-top:8px">
          <button id="add">Add a box (2 clicks)</button>
          <label class="f">Class of selected box<select id="cls"></select></label>
          <button id="del" class="danger">Delete selected box</button>
          <span class="spacer"></span>
          <button id="save" class="primary">Save label</button><button id="next">Next flagged frame ▶</button>
        </div>
        <p id="hint" class="small muted"></p>
      </div>
      <div class="panel"><h3>Flagged frames <span id="nq" class="muted"></span></h3><div class="scroll" style="max-height:600px"><table id="queue"></table></div></div>
    </div>`;
  img = $("#rimg"); canvas = $("#rcanvas"); ctx = canvas.getContext("2d");
  canvas.onclick = click;
  img.onload = draw;
  window.onresize = draw;
  $("#run").onchange = e => openRun(e.target.value);
  $("#gobtn").onclick = () => openFrame(+$("#goto").value, "manual");
  $("#add").onclick = () => { addStart = "wait"; hint("Click two opposite corners of the new box."); };
  $("#del").onclick = () => { if (sel != null) { boxes.splice(sel, 1); sel = null; draw(); } };
  $("#cls").onchange = e => { if (sel != null) { boxes[sel].class = e.target.value; draw(); } };
  $("#save").onclick = save;
  $("#next").onclick = next;
  if (runs.length) await openRun(args[0] && args[1] ? `${args[0]}/${args[1]}` : $("#run").value);
}

const hint = t => { $("#hint").textContent = t || ""; };

async function openRun(key) {
  run = key; $("#run").value = key;
  info = await api(`/api/review/${key}`);
  $("#cls").innerHTML = info.classes.map(c => `<option>${esc(c)}</option>`).join("");
  $("#rinfo").textContent = `${info.width}×${info.height} · labels saved to ${info.labels_dir}`;
  $("#nq").textContent = `(${info.queue.length})`;
  $("#queue").innerHTML = info.queue.length ? `<tr><th>Frame</th><th>Time</th><th>Why</th><th></th></tr>` + info.queue.map((q, i) => `
    <tr class="click" data-i="${i}"><td class="mono">${q.frame}</td><td class="small">${(+q.time_s).toFixed(1)} s</td>
      <td class="small">${q.reasons.split(";").map(r => chip(r.replace("_", " "), r === "random_sample" ? "planned" : "warn")).join(" ")}</td>
      <td>${info.reviewed[q.frame] ? chip("done", "ok") : ""}</td></tr>`).join("")
    : `<tr><td class="muted small">No review queue yet: run the review block on the Pipeline page, or open any frame by number.</td></tr>`;
  $("#queue").onclick = e => { const r = e.target.closest("tr[data-i]"); if (r) { const q = info.queue[+r.dataset.i]; openFrame(+q.frame, q.reasons); } };
  const first = info.queue.find(q => !info.reviewed[q.frame]) || info.queue[0];
  if (first) await openFrame(+first.frame, first.reasons);
}

async function openFrame(n, why) {
  frame = n; reason = why; sel = null; addStart = null; hint("");
  $$("#queue tr").forEach(r => r.classList.toggle("sel", r.dataset.i !== undefined && +info.queue[+r.dataset.i].frame === n));
  boxes = (await api(`/api/review/${run}/boxes/${n}`)).map(b => ({ class: b.class, xyxy: b.xyxy, confidence: b.confidence, track_id: b.track_id }));
  const r = await fetch(`/api/videos/frame?path=${encodeURIComponent(info.video_file)}&n=${n}&w=1920`);
  if (!r.ok) { toast((await r.json()).detail, "bad"); return; }
  full = [+r.headers.get("X-Frame-Width"), +r.headers.get("X-Frame-Height")];
  img.src = URL.createObjectURL(await r.blob());
}

function toFull(e) { const b = canvas.getBoundingClientRect(); return [(e.clientX - b.left) / k, (e.clientY - b.top) / k]; }

function click(e) {
  const p = toFull(e);
  if (addStart === "wait") { addStart = p; hint("Now the opposite corner."); return; }
  if (Array.isArray(addStart)) {
    const b = [Math.min(addStart[0], p[0]), Math.min(addStart[1], p[1]), Math.max(addStart[0], p[0]), Math.max(addStart[1], p[1])];
    addStart = null;
    if (b[2] - b[0] > 4 && b[3] - b[1] > 4) { boxes.push({ class: $("#cls").value, xyxy: b, confidence: null }); sel = boxes.length - 1; }
    hint("Box added. Choose its class above."); draw(); return;
  }
  const hits = boxes.map((b, i) => [b, i]).filter(([b]) => p[0] >= b.xyxy[0] && p[0] <= b.xyxy[2] && p[1] >= b.xyxy[1] && p[1] <= b.xyxy[3]);
  hits.sort((a, b) => (a[0].xyxy[2] - a[0].xyxy[0]) * (a[0].xyxy[3] - a[0].xyxy[1]) - (b[0].xyxy[2] - b[0].xyxy[0]) * (b[0].xyxy[3] - b[0].xyxy[1]));
  sel = hits.length ? hits[0][1] : null;
  if (sel != null) $("#cls").value = boxes[sel].class;
  draw();
}

function draw() {
  if (!full) return;
  const w = img.clientWidth, h = img.clientHeight;
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  k = w / full[0];
  ctx.clearRect(0, 0, w, h);
  boxes.forEach((b, i) => {
    const [x1, y1, x2, y2] = b.xyxy, col = CLASS_COLORS[b.class] || "#fff";
    ctx.strokeStyle = col; ctx.lineWidth = i === sel ? 4 : 2; ctx.setLineDash(b.confidence === null ? [6, 4] : []);
    ctx.strokeRect(x1 * k, y1 * k, (x2 - x1) * k, (y2 - y1) * k); ctx.setLineDash([]);
    drawLabel(ctx, k, [x1, y1], `${b.class}${b.confidence != null ? " " + b.confidence.toFixed(2) : " (added)"}`, col, -4);
  });
}

async function save() {
  const r = await attempt(() => api(`/api/review/${run}/label`, { method: "POST",
    body: { frame, boxes: boxes.map(b => ({ class: b.class, xyxy: b.xyxy })), reason, action: "corrected" } }), `Frame ${frame} saved as a label`);
  if (r) { info.reviewed[String(frame)] = "corrected"; await openRun(run); }
}

function next() {
  const i = info.queue.findIndex(q => +q.frame === frame);
  const q = info.queue.slice(i + 1).find(x => !info.reviewed[x.frame]) || info.queue[i + 1];
  if (q) openFrame(+q.frame, q.reasons); else toast("No more flagged frames.");
}

export function leave() { window.onresize = null; }
