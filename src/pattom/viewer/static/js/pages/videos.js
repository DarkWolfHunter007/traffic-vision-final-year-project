// Videos on disk: originals and prepared copies. Probe, preview, set as pipeline input.
import { api, esc, chip, attempt, $ } from "../api.js";

export async function render(root) {
  const videos = await api("/api/videos");
  root.innerHTML = `
    <h1>Videos</h1>
    <p class="sub">Originals in <span class="mono">data/raw</span> and <span class="mono">raw-video</span> are never written to. Prepared copies (constant frame rate, undistorted) are made by the pipeline.</p>
    <div class="split">
      <div class="panel">
        ${videos.length ? `<table id="vt"><tr><th>File</th><th>Folder</th><th>Size</th><th>Kind</th><th></th></tr>
          ${videos.map((v, i) => `<tr class="click" data-i="${i}"><td>${esc(v.name)}</td><td class="mono small">${esc(v.folder)}</td>
            <td class="small">${v.size_mb} MB</td>
            <td>${v.original ? chip("original", "warn") : chip(v.prepared_by || "copy", "built")} ${v.playable ? "" : `<span class="muted small" title="HEVC .MOV does not play in a browser">no preview</span>`}</td>
            <td><button data-probe="${i}">Probe</button></td></tr>`).join("")}</table>`
          : `<div class="notice">No videos yet. Copy an original into <span class="mono">data/raw/</span>, then reload.</div>`}
      </div>
      <div class="panel" id="detail"><p class="muted">Select a video.</p></div>
    </div>`;

  const show = async i => {
    const v = videos[i];
    document.querySelectorAll("#vt tr").forEach(r => r.classList.toggle("sel", r.dataset.i == i));
    const d = $("#detail");
    d.innerHTML = `<h3>${esc(v.name)}</h3><p class="mono small muted">${esc(v.path)}</p>
      <div class="stage">${v.playable ? `<video src="/api/videos/stream?path=${encodeURIComponent(v.path)}" controls muted preload="metadata"></video>`
        : `<img alt="frame" src="/api/videos/frame?path=${encodeURIComponent(v.path)}&t=1&w=900">`}</div>
      <div id="probe" class="small" style="margin-top:8px"></div>
      <div class="row" style="margin-top:10px">
        ${v.original ? `<button class="primary" id="use">Use as pipeline input (video.raw)</button>` : ""}
        <a href="#/lines/${encodeURIComponent(v.path)}">Draw counting lines on it</a>
      </div>`;
    const use = $("#use");
    if (use) use.onclick = () => attempt(async () => {
      const p = await api("/api/pipeline");
      p.spec.inputs = { ...(p.spec.inputs || {}), "video.raw": v.path };
      await api("/api/pipeline", { method: "PUT", body: p.spec });
    }, `Pipeline input set to ${v.path}`);
  };

  const probe = async i => {
    await show(i);
    $("#probe").innerHTML = `<span class="muted">Probing…</span>`;
    const info = await attempt(() => api(`/api/videos/probe?path=${encodeURIComponent(videos[i].path)}`));
    if (!info) { $("#probe").innerHTML = ""; return; }
    const rows = Object.entries(info).map(([k, v]) => `<tr><td class="muted">${esc(k)}</td><td class="mono">${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("");
    $("#probe").innerHTML = `${info.is_vfr ? `<div class="notice">Variable frame rate: make a constant-frame-rate copy (cfr block) before detection.</div>` : `<div class="notice ok">Constant frame rate.</div>`}<table>${rows}</table>`;
  };

  root.addEventListener("click", e => {
    const b = e.target.closest("[data-probe]");
    if (b) { e.stopPropagation(); probe(+b.dataset.probe); return; }
    const row = e.target.closest("tr.click");
    if (row) show(+row.dataset.i);
  });
}
