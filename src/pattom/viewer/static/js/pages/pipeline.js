// Pipeline editor: switch blocks, bind inputs, set parameters, check, save, run with a live log.
import { api, esc, chip, attempt, toast, parseValue, showValue, $, $$ } from "../api.js";

const COMPONENTS = {
  A: "Raw video", B: "Preparation", C: "Detection", D: "Tracking", E: "Review", F: "Calculation layer",
  G: "Index and emissions", H: "Analysis", I: "Alternatives", J: "Pre-SUMO scoring", K: "MCE", L: "SUMO", M: "Comparison",
};
let state = null, dirty = false, pollTimer = null, logSince = 0;

export function leave() { clearTimeout(pollTimer); }

export async function render(root) {
  state = await api("/api/pipeline");
  dirty = false; logSince = 0;
  root.innerHTML = `
    <h1>Pipeline</h1>
    <p class="sub">Each block reads named files and writes new ones. Switch blocks off, feed a block from another file, set its options, then check and run. Saved to <span class="mono">${esc(state.config)}</span>.</p>
    <div class="panel" style="position:sticky;top:0;z-index:5">
      <div class="row">
        <label class="f">Slot<input id="slot" style="width:120px"></label>
        <span class="spacer"></span>
        <span id="dirty" class="muted small"></span>
        <button id="check">Check</button>
        <button id="save">Save</button>
        <button id="runsel" title="run only the ticked blocks; other inputs come from the last run">Run ticked</button>
        <button id="run" class="primary">Run all switched-on blocks</button>
        <button id="stop" class="danger" hidden>Stop</button>
      </div>
      <div id="problems"></div>
    </div>
    <div class="split" style="margin-top:14px">
      <div id="blocks"></div>
      <div style="position:sticky;top:120px" class="grid">
        <div class="panel"><h3>Inputs</h3><p class="muted small">Files that exist before the run.</p><div id="inputs"></div>
          <button id="addin" style="margin-top:6px">Add input</button></div>
        <div class="panel"><h3>Run log</h3><div id="jobstate" class="small muted">No run yet.</div><div class="log" id="log"></div></div>
      </div>
    </div>`;
  $("#slot").value = state.spec.slot || "";
  $("#slot").oninput = e => { state.spec.slot = e.target.value.trim(); touch(); };
  $("#check").onclick = () => attempt(async () => { await refresh("check"); toast(state.problems.length ? "Check found problems" : "Ready to run", state.problems.length ? "bad" : "ok"); });
  $("#save").onclick = () => attempt(() => refresh("save"), "Pipeline saved");
  $("#run").onclick = () => run([]);
  $("#runsel").onclick = () => {
    const only = $$("[data-only]:checked").map(c => c.dataset.only);
    if (!only.length) { toast("Tick the blocks to run first.", "bad"); return; }
    run(only);
  };
  $("#stop").onclick = () => attempt(() => api("/api/jobs/stop", { method: "POST" }), "Stop sent");
  $("#addin").onclick = () => { const k = prompt("Artifact name (e.g. phase_log, video.checkerboard)"); if (k) { state.spec.inputs = { ...(state.spec.inputs || {}), [k.trim()]: "" }; touch(); drawInputs(); } };
  draw();
  pollJob();
}

function entries() {
  state.spec.blocks = (state.spec.blocks || []).map(b => typeof b === "string" ? { use: b } : b);
  return state.spec.blocks;
}

function touch() { dirty = true; $("#dirty").textContent = "unsaved changes"; }

async function refresh(mode) {
  const spec = { ...state.spec, blocks: entries() };
  state = await api(mode === "save" ? "/api/pipeline" : "/api/pipeline/check", { method: mode === "save" ? "PUT" : "POST", body: spec });
  if (mode === "save") { dirty = false; $("#dirty").textContent = ""; }
  draw();
}

function artifactKeys() {
  const keys = new Set(Object.keys(state.spec.inputs || {}));
  for (const s of state.steps) s.outputs.forEach(k => keys.add(k));
  return [...keys].sort();
}

function draw() {
  drawProblems(); drawInputs(); drawBlocks();
}

function drawProblems() {
  const p = state.problems || [];
  $("#problems").innerHTML = state.from_example ? `<div class="notice info">No <span class="mono">configs/pipeline.yaml</span> yet: showing the example. Save to create it.</div>` : "";
  $("#problems").innerHTML += p.length ? `<div class="notice bad"><b>${p.length} problem(s) before this can run:</b><ul style="margin:4px 0 0 18px;padding:0">${p.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`
    : `<div class="notice ok">Check passed: the switched-on blocks can run.</div>`;
}

function drawInputs() {
  const ins = state.spec.inputs || {};
  $("#inputs").innerHTML = Object.keys(ins).length ? Object.entries(ins).map(([k, v]) => `
    <div class="row" style="margin-bottom:6px"><span class="mono small" style="min-width:110px">${esc(k)}</span>
      <input data-in="${esc(k)}" value="${esc(v)}" style="flex:1" list="videolist" placeholder="path inside the repository">
      <button data-delin="${esc(k)}" title="remove">✕</button></div>`).join("") : `<p class="muted small">None.</p>`;
  $$("[data-in]").forEach(i => i.oninput = e => { state.spec.inputs[i.dataset.in] = e.target.value.trim(); touch(); });
  $$("[data-delin]").forEach(b => b.onclick = () => { delete state.spec.inputs[b.dataset.delin]; touch(); drawInputs(); });
  if (!$("#videolist")) {
    api("/api/videos").then(v => {
      const dl = document.createElement("datalist"); dl.id = "videolist";
      dl.innerHTML = v.map(x => `<option value="${esc(x.path)}">`).join("");
      document.body.appendChild(dl);
    });
  }
}

function drawBlocks() {
  const keys = artifactKeys();
  const byComp = {};
  state.steps.forEach((s, i) => (byComp[s.component] ||= []).push([s, entries()[i]]));
  $("#blocks").innerHTML = Object.entries(byComp).map(([c, list]) => `
    <div class="comp"><div class="letter" title="${esc(COMPONENTS[c] || "")}">${esc(c)}</div><div>
      <div class="small muted" style="margin:6px 0">${esc(COMPONENTS[c] || "")}</div>
      ${list.map(([s, e]) => blockCard(s, e, keys)).join("")}</div></div>`).join("");

  $$("[data-toggle]").forEach(t => t.onchange = () => {
    const e = entries().find(x => (x.id || x.use) === t.dataset.toggle);
    e.enabled = t.checked; touch(); refresh("check");
  });
  $$("[data-bind]").forEach(sel => sel.onchange = () => {
    const [id, port] = sel.dataset.bind.split("|");
    const e = entries().find(x => (x.id || x.use) === id);
    const step = state.steps.find(s => s.id === id);
    e.bind = { ...(e.bind || {}) };
    if (sel.value === step.inputs[port]) delete e.bind[port]; else e.bind[port] = sel.value;
    if (!Object.keys(e.bind).length) delete e.bind;
    touch(); refresh("check");
  });
  $$("[data-param]").forEach(inp => inp.onchange = () => {
    const [id, name] = inp.dataset.param.split("|");
    const e = entries().find(x => (x.id || x.use) === id);
    const v = parseValue(inp.value);
    e.params = { ...(e.params || {}) };
    if (v === undefined) delete e.params[name]; else e.params[name] = v;
    if (!Object.keys(e.params).length) delete e.params;
    touch(); refresh("check");
  });
}

function blockCard(s, e, keys) {
  const last = s.last_run;
  const runCls = last ? last.status : "";
  const planned = s.status === "planned";
  const waits = [...s.tasks, ...s.waits_on].join(", ");
  const ports = Object.entries(s.ports).map(([port, key]) => {
    const opts = [...new Set([s.inputs[port], ...keys])];
    return `<label>${esc(port)} ← <select data-bind="${esc(s.id)}|${esc(port)}" ${planned ? "disabled" : ""}>
      ${opts.map(k => `<option ${k === key ? "selected" : ""} value="${esc(k)}">${esc(k)}${k === s.inputs[port] ? " (default)" : ""}</option>`).join("")}</select></label>`;
  }).join("");
  const params = Object.entries(s.params).map(([name, help]) => `
    <label class="f">${esc(name)}${s.required_params.includes(name) ? " *" : ""}
      <input data-param="${esc(s.id)}|${esc(name)}" value="${esc(showValue((e.params || {})[name]))}" placeholder="${esc(help)}" title="${esc(help)}"></label>`).join("");
  return `<div class="block ${s.enabled ? "" : "off"} ${planned ? "planned" : ""} ${runCls}" data-block="${esc(s.id)}">
    <div class="head">
      <label class="switch" title="${planned ? `planned: waits on ${esc(waits)}` : "switch on or off"}"><input type="checkbox" data-toggle="${esc(s.id)}" ${s.enabled ? "checked" : ""} ${planned && !s.enabled ? "disabled" : ""}><span></span></label>
      <b>${esc(s.id)}</b> ${chip(s.status)} <span class="muted">${esc(s.title)}</span>
      <span class="spacer"></span>
      ${last ? `${chip(last.status)} <span class="small muted">${esc((last.finished || last.started || "").replace("T", " ").slice(0, 19))}</span>` : ""}
      ${!planned && s.enabled ? `<label class="small muted" title="tick to include in 'Run ticked'"><input type="checkbox" data-only="${esc(s.id)}"> run</label>` : ""}
    </div>
    <div class="ports">${ports || "<span>no inputs</span>"}<span>→ ${s.outputs.map(esc).join(", ")}</span></div>
    ${planned ? `<div class="small muted" style="margin-top:6px">Waits on ${esc(waits)}. ${esc(s.note)}</div>` : s.note ? `<div class="small muted" style="margin-top:4px">${esc(s.note)}</div>` : ""}
    ${!planned && params ? `<div class="params">${params}</div>` : ""}
    ${last?.error ? `<div class="notice bad small">${esc(last.error)}</div>` : ""}
    ${last?.outputs ? `<div class="small mono muted" style="margin-top:4px">${Object.entries(last.outputs).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ")}</div>` : ""}
  </div>`;
}

async function run(only) {
  if (dirty) { toast("Save the pipeline before running.", "bad"); return; }
  const j = await attempt(() => api("/api/pipeline/run", { method: "POST", body: { only } }));
  if (j) { logSince = 0; $("#log").textContent = ""; toast("Run started", "ok"); pollJob(); }
}

async function pollJob() {
  clearTimeout(pollTimer);
  let j;
  try { j = await api(`/api/jobs/current?since=${logSince}`); } catch { return; }
  if (!$("#log")) return;
  if (j.lines.length) {
    const log = $("#log");
    log.textContent += j.lines.join("\n") + "\n";
    log.scrollTop = log.scrollHeight;
  }
  logSince = j.n_lines;
  $("#jobstate").innerHTML = j.state === "idle" ? "No run since the app started." : `${chip(j.state)} <span class="mono">${esc(j.command)}</span> · started ${esc(j.started)}`;
  $("#stop").hidden = j.state !== "running";
  $("#run").disabled = $("#runsel").disabled = j.state === "running";
  if (j.state === "running") pollTimer = setTimeout(pollJob, 1000);
  else if (j.state !== "idle" && $("#log").dataset.finished !== j.started) {
    $("#log").dataset.finished = j.started;
    state = await api("/api/pipeline"); dirty = false; draw();
  }
}
