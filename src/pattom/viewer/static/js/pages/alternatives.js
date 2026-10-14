// Alternatives (FR-17): write the signal-timing alternatives; optional SP 41 fixed-time suggestion from the observed flows.
import { api, esc, attempt, toast, $, $$ } from "../api.js";

let state;
const NOTES = ["expected_effect", "safety_note", "cost_note", "land_note", "feasibility_note"];

export async function render(root) {
  state = await api("/api/alternatives");
  root.innerHTML = `
    <h1>Alternatives</h1>
    <p class="sub">Signal-timing alternatives, written after the problems are known (D4). The existing plan is taken from the observed cycles. Keep at least two alternatives besides it. Saved to <span class="mono">${esc(state.path)}</span>.</p>
    <div class="split wide">
      <div>
        <div class="row" style="margin-bottom:8px"><button id="add">Add alternative</button><span class="spacer"></span><button id="save" class="primary">Save</button></div>
        <div id="list"></div>
      </div>
      <div class="panel">
        <h3>SP 41 fixed-time suggestion</h3>
        <p class="small muted">Co = (1.5 L + 5) / (1 − Y), greens split by y = q / s (IRC SP 41 p. 78), from a capacity-vc result. A starting point only: it gives effective greens.</p>
        <label class="f">Capacity result<select id="capf">${state.capacity_files.map(f => `<option>${esc(f)}</option>`).join("") || "<option value=''>none yet: run capacity-vc</option>"}</select></label>
        <label class="f" style="margin-top:6px">Approach → phase group (JSON)<input id="groups" placeholder='{"north": "NS", "south": "NS", "east": "EW"}'></label>
        <label class="f" style="margin-top:6px">All-red per cycle, s (measured)<input id="allred" type="number" step="0.5"></label>
        <button id="sp41" style="margin-top:8px">Suggest</button>
        <div id="sugg" class="small" style="margin-top:8px"></div>
      </div>
    </div>`;
  $("#add").onclick = () => { state.alternatives.push({ id: `A${state.alternatives.length + 1}`, description: "", control: "fixed",
    problem_addressed: state.problems[0] || "", plan: { cycle_s: "", groups: {} } }); draw(); };
  $("#save").onclick = save;
  $("#sp41").onclick = suggest;
  draw();
}

function draw() {
  const probs = state.problems;
  $("#list").innerHTML = state.alternatives.length ? state.alternatives.map((a, i) => `
    <div class="block" data-a="${i}">
      <div class="row">
        <label class="f">Id<input data-f="id" value="${esc(a.id)}" style="width:70px"></label>
        <label class="f" style="flex:1">Description<input data-f="description" value="${esc(a.description)}"></label>
        <label class="f">Control<select data-f="control">${["fixed", "actuated", "adaptive"].map(c => `<option ${c === a.control ? "selected" : ""}>${c}</option>`).join("")}</select></label>
        <button data-del="${i}" class="danger">Delete</button>
      </div>
      <label class="f" style="margin-top:6px">Problem addressed
        ${probs.length ? `<select data-f="problem_addressed">${[...new Set([a.problem_addressed, ...probs])].filter(Boolean).map(p => `<option ${p === a.problem_addressed ? "selected" : ""}>${esc(p)}</option>`).join("")}</select>`
          : `<input data-f="problem_addressed" value="${esc(a.problem_addressed)}" placeholder="no problems.csv yet: run the analysis block first">`}</label>
      ${a.control === "fixed" ? planEditor(a, i) : a.control === "actuated" ? actuatedEditor(a) : `<p class="small muted">Adaptive control needs external control in SUMO (TraCI) and cannot be scored by a fixed-time formula; it is kept as documented only.</p>`}
      <div class="params" style="margin-top:6px">${NOTES.map(n => `<label class="f">${n.replace("_", " ")}<input data-f="${n}" value="${esc(a[n] || "")}"></label>`).join("")}</div>
    </div>`).join("") : `<p class="muted">No alternatives yet.</p>`;
  $$("[data-f]").forEach(inp => inp.onchange = () => {
    const a = state.alternatives[+inp.closest("[data-a]").dataset.a];
    a[inp.dataset.f] = inp.value.trim();
    if (inp.dataset.f === "control") draw();
  });
  $$("[data-del]").forEach(b => b.onclick = () => { state.alternatives.splice(+b.dataset.del, 1); draw(); });
  $$("[data-g]").forEach(inp => inp.onchange = () => {
    const a = state.alternatives[+inp.closest("[data-a]").dataset.a], [grp, f] = inp.dataset.g.split("|");
    const target = a.control === "actuated" ? (a.actuated ||= {}) : (a.plan ||= { groups: {} }).groups;
    target[grp] ||= {}; target[grp][f] = inp.value === "" ? undefined : +inp.value;
  });
  $$("[data-cycle]").forEach(inp => inp.onchange = () => { state.alternatives[+inp.dataset.cycle].plan.cycle_s = +inp.value; });
  $$("[data-addgroup]").forEach(b => b.onclick = () => {
    const name = prompt("Phase group name (e.g. NS, EW)"); if (!name) return;
    const a = state.alternatives[+b.dataset.addgroup];
    const target = a.control === "actuated" ? (a.actuated ||= {}) : (a.plan ||= { groups: {} }).groups;
    target[name.trim()] = {}; draw();
  });
}

function planEditor(a, i) {
  a.plan ||= { groups: {} };
  const groups = Object.entries(a.plan.groups || {});
  return `<div class="row" style="margin-top:6px"><label class="f">Cycle (s)<input data-cycle="${i}" type="number" value="${a.plan.cycle_s ?? ""}" style="width:80px"></label>
    ${groups.map(([g, v]) => `<label class="f">${esc(g)} green (s)<input data-g="${esc(g)}|green_s" type="number" value="${v.green_s ?? ""}" style="width:70px"></label>
      <label class="f">${esc(g)} amber (s)<input data-g="${esc(g)}|amber_s" type="number" value="${v.amber_s ?? ""}" style="width:70px"></label>`).join("")}
    <button data-addgroup="${i}">Add phase group</button></div>`;
}

function actuatedEditor(a) {
  const i = state.alternatives.indexOf(a);
  const groups = Object.entries(a.actuated || {});
  return `<div class="row" style="margin-top:6px">${groups.map(([g, v]) => ["min_green_s", "max_green_s", "amber_s"].map(f =>
    `<label class="f">${esc(g)} ${f.replace(/_/g, " ")}<input data-g="${esc(g)}|${f}" type="number" value="${v[f] ?? ""}" style="width:70px"></label>`).join("")).join("")}
    <button data-addgroup="${i}">Add phase group</button></div>
    <p class="small muted">SUMO's gap-based actuated control with these minimum and maximum greens. Not scorable by the fixed-time formula before SUMO.</p>`;
}

async function save() {
  const r = await attempt(() => api("/api/alternatives", { method: "PUT", body: { alternatives: JSON.parse(JSON.stringify(state.alternatives)) } }), "Alternatives saved");
  if (r) { state = r; draw(); }
}

async function suggest() {
  let groups;
  try { groups = JSON.parse($("#groups").value || "{}"); } catch { toast("Approach groups must be JSON, e.g. {\"north\": \"NS\"}", "bad"); return; }
  const r = await attempt(() => api("/api/alternatives/sp41", { method: "POST", body: { capacity_file: $("#capf").value, approach_groups: groups, all_red_s: $("#allred").value } }));
  if (!r) return;
  $("#sugg").innerHTML = `<div class="notice info">Cycle <b>${r.cycle_s} s</b> · lost time ${r.lost_time_s} s · effective greens ${Object.entries(r.effective_green_s).map(([g, v]) => `${esc(g)} ${v} s`).join(", ")}
    <div class="muted">y: ${Object.entries(r.y).map(([g, v]) => `${esc(g)} ${v}`).join(", ")} · ${esc(r.sources.join("; "))} · ${esc(r.note)}</div></div>`;
}
