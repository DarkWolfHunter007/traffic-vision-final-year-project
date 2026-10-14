// The source register (D15), read-only: every constant the code may use.
import { api, esc, chip } from "../api.js";

const show = v => typeof v === "object" && v !== null
  ? Object.entries(v).map(([k, x]) => `${esc(k)}: ${esc(x)}`).join("<br>") : esc(v);

export async function render(root) {
  const r = await api("/api/register");
  root.innerHTML = `
    <h1>Source register</h1>
    <p class="sub">Input values come only from the footage or this register (<span class="mono">sources/register.yaml</span>, D15). A value that is not here is a gap to report, not a number to fill in. "Reported" values are unchecked and are labelled "source not checked" until T50.</p>
    <h2>Values</h2>
    <div class="panel"><table><tr><th>Key</th><th>Value</th><th>Unit</th><th>Source</th><th>Status</th></tr>
      ${r.values.map(v => `<tr><td class="mono small">${esc(v.key)}</td><td class="small">${show(v.value)}</td><td class="small">${esc(v.unit)}</td>
        <td class="small">${esc(v.source)}, ${esc(v.ref)}${v.note ? `<div class="muted">${esc(v.note)}</div>` : ""}</td>
        <td>${chip(v.status === "reported" ? "reported · not checked" : v.status, v.status)}</td></tr>`).join("")}</table></div>
    <h2>Sources</h2>
    <div class="grid cols-2">${Object.entries(r.sources).map(([id, s]) => `
      <div class="panel"><div class="mono small muted">${esc(id)} · added ${esc(s.date_added)}</div><div>${esc(s.citation)}</div>
        <div class="small muted" style="margin-top:4px">Covers: ${esc(s.covers)}${s.notes ? ` · ${esc(s.notes)}` : ""}</div></div>`).join("")}</div>`;
}
