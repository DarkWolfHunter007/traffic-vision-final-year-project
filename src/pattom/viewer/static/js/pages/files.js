// Settings files: the YAML files in configs/ and calibration/ (block settings, SUMO network, ...).
import { api, esc, attempt, chip, $, $$ } from "../api.js";

export async function render(root, args) {
  const files = await api("/api/configs");
  root.innerHTML = `
    <h1>Settings files</h1>
    <p class="sub">Long block settings live in YAML files that a block reads through its <span class="mono">settings_file</span> option (Pipeline page). A file that does not exist yet opens from its example; values left empty are open decisions and the pipeline check names them.</p>
    <div class="split wide">
      <div class="panel"><div class="row"><b id="fname" class="mono"></b><span id="fstate"></span><span class="spacer"></span><button id="save" class="primary">Save</button></div>
        <textarea id="text" rows="32" spellcheck="false" style="margin-top:8px"></textarea></div>
      <div class="panel"><h3>Files</h3><table id="list">${files.map(f => `<tr class="click" data-p="${esc(f.path)}"><td class="mono small">${esc(f.path)}</td><td>${f.exists ? "" : chip("from example", "planned")}</td></tr>`).join("")}</table>
        <div class="row" style="margin-top:8px"><input id="newname" placeholder="configs/new_settings.yaml" style="flex:1"><button id="new">New file</button></div></div>
    </div>`;
  let current = null;
  const open = async path => {
    const f = await attempt(() => api(`/api/configs/file?path=${encodeURIComponent(path)}`));
    if (!f) return;
    current = f.path; $("#fname").textContent = f.path; $("#text").value = f.text;
    $("#fstate").innerHTML = f.from_example ? chip("not saved yet: example shown", "warn") : "";
    $$("#list tr").forEach(r => r.classList.toggle("sel", r.dataset.p === f.path));
  };
  $("#list").onclick = e => { const r = e.target.closest("tr[data-p]"); if (r) open(r.dataset.p); };
  $("#new").onclick = () => { const p = $("#newname").value.trim(); if (p) open(p); };
  $("#save").onclick = async () => {
    if (!current) return;
    const r = await attempt(() => api("/api/configs/file", { method: "PUT", body: { path: current, text: $("#text").value } }), `${current} saved`);
    if (r) $("#fstate").innerHTML = "";
  };
  if (args[0] || files[0]) await open(args[0] || files[0].path);
}
