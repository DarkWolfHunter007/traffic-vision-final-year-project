// Signal phase log (T19): play the video and press G / A / R when a signal head changes.
import { api, esc, chip, attempt, toast, fmtTime, $, $$ } from "../api.js";

let slot, rows, heads, sel, video, dirty, alive;

const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } },
};

export function leave() {
  alive = false; document.onkeydown = null;
  if (video) { video.ontimeupdate = video.onseeked = null; video.pause(); video.removeAttribute("src"); video.load(); }
}

export async function render(root, args) {
  alive = true;
  const pipe = await api("/api/pipeline").catch(() => null);
  slot = args[0] || pipe?.spec?.slot || "test";
  const [data, vids] = await Promise.all([api(`/api/phases/${encodeURIComponent(slot)}`), api("/api/videos")]);
  rows = data.rows.map(r => ({ ...r, time_s: +r.time_s }));
  const known = rows.map(r => ({ name: r.signal_head, group: r.phase_group }));
  heads = dedupe([...(store.get(`pattom.heads.${slot}`) || []), ...known]);
  sel = 0; dirty = false;
  const playable = vids.filter(v => v.playable);
  root.innerHTML = `
    <h1>Signal phases</h1>
    <p class="sub">Measured from the footage (FR-10). Play the prepared video; each time a signal head changes, press its colour. The time is the video time. Saved to <span class="mono">${esc(data.path)}</span>; a cycle runs from one green to the next, and part-cycles at the ends are left out.</p>
    <div class="split wide">
      <div class="panel">
        <div class="row" style="margin-bottom:8px">
          <label class="f">Slot<input id="slot" value="${esc(slot)}" style="width:110px"></label>
          <label class="f">Video<select id="vid">${playable.map(v => `<option value="${esc(v.path)}">${esc(v.path)}</option>`).join("")}</select></label>
          <label class="f">Speed<select id="rate"><option>0.5</option><option selected>1</option><option>2</option><option>4</option></select></label>
        </div>
        ${playable.length ? "" : `<div class="notice">No browser-playable video. Make the CFR .mp4 copy first (Pipeline → cfr).</div>`}
        <div class="stage"><video id="video" controls muted preload="auto"></video></div>
        <div class="row small muted" style="margin-top:6px"><span id="now" class="mono">0:00.00</span><span class="spacer"></span>
          Keys: <kbd>1</kbd>–<kbd>9</kbd> pick head · <kbd>G</kbd> <kbd>A</kbd> <kbd>R</kbd> mark · <kbd>space</kbd> play · <kbd>,</kbd> <kbd>.</kbd> step 0.1 s</div>
      </div>
      <div class="grid">
        <div class="panel"><h3>Signal heads</h3><div class="heads" id="heads"></div>
          <div class="row" style="margin-top:8px"><input id="hname" placeholder="head, e.g. N_main" style="width:120px"><input id="hgroup" placeholder="phase group, e.g. NS" style="width:120px"><button id="hadd">Add</button></div></div>
        <div class="panel">
          <div class="row"><h3 style="margin:0">Changes <span id="nrows" class="muted"></span></h3><span class="spacer"></span><span id="dirty" class="small muted"></span>
            <button id="save" class="primary">Save and check</button></div>
          <div class="scroll" style="max-height:300px;margin-top:6px"><table id="rows"></table></div>
          <button id="useinput" style="margin-top:8px">Use as pipeline input (phase_log)</button>
        </div>
        <div class="panel"><h3>Cycles</h3><div id="cycles" class="small muted">Save to see the cycles.</div></div>
      </div>
    </div>`;
  video = $("#video");
  if (playable.length) video.src = `/api/videos/stream?path=${encodeURIComponent($("#vid").value)}`;
  $("#vid").onchange = e => { video.src = `/api/videos/stream?path=${encodeURIComponent(e.target.value)}`; };
  $("#rate").onchange = e => { video.playbackRate = +e.target.value; };
  $("#slot").onchange = e => { location.hash = `#/phases/${encodeURIComponent(e.target.value.trim())}`; };
  video.ontimeupdate = () => { const now = $("#now"); if (alive && now) now.textContent = fmtTime(video.currentTime); };
  video.onseeked = video.ontimeupdate;
  $("#hadd").onclick = () => {
    const name = $("#hname").value.trim(), group = $("#hgroup").value.trim();
    if (!name) { toast("Type a head name.", "bad"); return; }
    heads = dedupe([...heads, { name, group }]); sel = heads.length - 1; saveHeads(); drawHeads();
    $("#hname").value = ""; $("#hgroup").value = "";
  };
  $("#save").onclick = save;
  $("#useinput").onclick = () => attempt(async () => {
    const p = await api("/api/pipeline");
    p.spec.inputs = { ...(p.spec.inputs || {}), phase_log: data.path };
    await api("/api/pipeline", { method: "PUT", body: p.spec });
  }, `Pipeline input phase_log set to ${data.path}`);
  document.onkeydown = keys;
  drawHeads(); drawRows();
  if (rows.length) api(`/api/phases/${encodeURIComponent(slot)}/check`, { method: "POST" }).then(r => showCycles(r.cycles)).catch(e => toast(e.message, "bad"));
}

function dedupe(list) {
  const seen = new Map();
  for (const h of list) if (h.name && !seen.has(h.name)) seen.set(h.name, h);
  return [...seen.values()];
}
const saveHeads = () => store.set(`pattom.heads.${slot}`, heads);
function touch() { dirty = true; $("#dirty").textContent = "unsaved"; }

function lastState(name) { const r = rows.filter(x => x.signal_head === name).sort((a, b) => a.time_s - b.time_s).pop(); return r?.state; }

function drawHeads() {
  $("#heads").innerHTML = heads.length ? heads.map((h, i) => `
    <div class="head-row ${i === sel ? "sel" : ""}" data-h="${i}"><div><b>${i + 1}. ${esc(h.name)}</b> <span class="muted small">${esc(h.group || "no group")}</span>
      ${lastState(h.name) ? chip(lastState(h.name), { green: "ok", amber: "warn", red: "bad" }[lastState(h.name)]) : ""}</div>
      <div class="row"><button class="state-btn g" data-mark="${i}|green" title="green (G)">G</button><button class="state-btn a" data-mark="${i}|amber" title="amber (A)">A</button><button class="state-btn r" data-mark="${i}|red" title="red (R)">R</button></div></div>`).join("")
    : `<p class="muted small">Add each signal head you can see (for example N_main, E_main) with its phase group.</p>`;
  $$("[data-h]").forEach(d => d.onclick = e => { if (!e.target.closest("button")) { sel = +d.dataset.h; drawHeads(); } });
  $$("[data-mark]").forEach(b => b.onclick = () => { const [i, s] = b.dataset.mark.split("|"); sel = +i; mark(s); });
}

function mark(state) {
  const h = heads[sel];
  if (!h) { toast("Add a signal head first.", "bad"); return; }
  const t = Math.round(video.currentTime * 100) / 100;
  if (lastState(h.name) === state) { toast(`${h.name} is already ${state}; not added.`, "bad"); return; }
  rows.push({ slot, time_s: t, signal_head: h.name, state, phase_group: h.group || "" });
  touch(); drawRows(); drawHeads();
}

function drawRows() {
  rows.sort((a, b) => a.time_s - b.time_s || a.signal_head.localeCompare(b.signal_head));
  $("#nrows").textContent = `(${rows.length})`;
  $("#rows").innerHTML = `<tr><th>Time (s)</th><th>Head</th><th>State</th><th>Group</th><th></th></tr>` + rows.map((r, i) => `
    <tr data-r="${i}"><td><input type="number" step="0.01" value="${r.time_s}" data-rt style="width:90px"></td><td>${esc(r.signal_head)}</td>
      <td>${chip(r.state, { green: "ok", amber: "warn", red: "bad" }[r.state])}</td><td class="small">${esc(r.phase_group)}</td>
      <td class="nw"><button data-seek="${i}" title="go to this time">▶</button><button data-rdel="${i}" class="danger">✕</button></td></tr>`).join("");
  $$("[data-rt]").forEach(inp => inp.onchange = () => { rows[+inp.closest("[data-r]").dataset.r].time_s = +inp.value; touch(); drawRows(); });
  $$("[data-rdel]").forEach(b => b.onclick = () => { rows.splice(+b.dataset.rdel, 1); touch(); drawRows(); drawHeads(); });
  $$("[data-seek]").forEach(b => b.onclick = () => { video.pause(); video.currentTime = rows[+b.dataset.seek].time_s; });
}

async function save() {
  const r = await attempt(() => api(`/api/phases/${encodeURIComponent(slot)}`, { method: "PUT", body: { rows } }), "Phase log saved");
  if (!r) return;
  dirty = false; $("#dirty").textContent = "";
  showCycles(r.cycles);
}

function showCycles(cyc) {
  $("#cycles").innerHTML = cyc.length ? `<table><tr><th>Head</th><th>Start</th><th>Green</th><th>Amber</th><th>Red</th><th>Cycle</th><th></th></tr>
    ${cyc.map(c => `<tr><td>${esc(c.signal_head)}</td><td class="mono">${fmtTime(+c.cycle_start_s)}</td><td>${(+c.green_s).toFixed(1)}</td><td>${(+c.amber_s).toFixed(1)}</td>
      <td>${(+c.red_s).toFixed(1)}</td><td><b>${(+c.cycle_s).toFixed(1)} s</b></td><td>${c.regular ? "" : chip(c.sequence, "warn")}</td></tr>`).join("")}</table>
    <p class="small muted">Seconds, measured from the footage. Run the signal-phases block to write the cycles file for the pipeline.</p>`
    : `<p class="small muted">No complete cycle yet: a cycle needs two green marks on the same head.</p>`;
}

function keys(e) {
  if (!alive || ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  const k = e.key.toLowerCase();
  if (k === " ") { e.preventDefault(); video.paused ? video.play() : video.pause(); }
  else if (k >= "1" && k <= "9" && heads[+k - 1]) { sel = +k - 1; drawHeads(); }
  else if (k === "g") mark("green"); else if (k === "a") mark("amber"); else if (k === "r") mark("red");
  else if (k === ",") video.currentTime = Math.max(0, video.currentTime - 0.1);
  else if (k === ".") video.currentTime += 0.1;
}
