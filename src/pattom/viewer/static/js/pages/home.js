// Home: what is set up and what to do next, from the app's own files.
import { api, esc, chip, $ } from "../api.js";

export async function render(root) {
  const s = await api("/api/status");
  const g = s.ground ? Object.values(s.ground) : [];
  const groundOk = g.length && g.every(m => m.ok);
  const p = s.pipeline;
  const steps = [
    { ok: s.videos.originals + s.videos.prepared > 0, title: "Add a video",
      detail: `${s.videos.originals} original(s), ${s.videos.prepared} prepared copy(ies). Copy originals into data/raw/.`, href: "#/videos" },
    { ok: s.weights.length > 0, title: "YOLO weights in models/",
      detail: s.weights.length ? s.weights.join(", ") : "Put the .pt file in models/ and name it in the detection settings.", href: "#/settings" },
    { ok: s.settings.detection && s.settings.tracker, title: "Detection and tracker settings",
      detail: `detection ${s.settings.detection ? "saved" : "not saved"} · tracker ${s.settings.tracker ? "saved" : "not saved"}`, href: "#/settings" },
    { ok: p.saved && !(p.problems || []).length && !p.error, title: "Pipeline saved and checked",
      detail: !p.saved ? "Not saved yet." : p.error ? p.error : p.problems.length ? `${p.problems.length} problem(s): ${p.problems[0]}` : `Slot ${p.slot}: ${p.enabled.join(", ")}`, href: "#/pipeline" },
    { ok: s.runs.some(r => r.tracks), title: "Detection and tracking run",
      detail: s.runs.length ? s.runs.map(r => `${r.slot}/${r.video}${r.tracks ? "" : " (no tracks)"}`).join(", ") : "No runs yet.", href: "#/results" },
    { ok: s.lens, title: "Lens calibration", detail: s.lens ? "calibration/lens.json" : "Optional until the checkerboard clip is recorded.", href: "#/pipeline", optional: true },
    { ok: s.lines > 0, title: "Counting lines", detail: s.lines ? `${s.lines} line(s)` : "Draw them on a prepared frame.", href: "#/lines" },
    { ok: !!groundOk, title: "Ground points",
      detail: !s.ground ? "Click points and type the site measurements." : g.map(m => m.ok ? `largest check error ${m.max_check_error_m.toFixed(3)} m` : m.error).join(" · "), href: "#/ground" },
    { ok: Object.keys(s.phase_logs).length > 0, title: "Signal phase log",
      detail: Object.keys(s.phase_logs).length ? Object.entries(s.phase_logs).map(([k, n]) => `${k}: ${n} changes`).join(", ") : "Mark the signal changes while playing the video.", href: "#/phases" },
  ];
  const next = steps.find(x => !x.ok && !x.optional);
  root.innerHTML = `
    <h1>Pattom workbench</h1>
    <p class="sub">Video → YOLO detection → tracking → counts, signal phases and ground positions. YOLO only detects vehicles; every traffic number comes from the calculation blocks.</p>
    ${next ? `<div class="notice info">Next: <a href="${next.href}"><b>${esc(next.title)}</b></a> — ${esc(next.detail)}</div>` : `<div class="notice ok">Everything set up. Run the pipeline and check the results.</div>`}
    <div class="split" style="margin-top:12px">
      <div class="panel"><h3>Setup</h3><table>
        ${steps.map(x => `<tr class="click" data-href="${x.href}"><td style="width:28px">${x.ok ? chip("✓", "ok") : x.optional ? chip("–", "planned") : chip("✗", "bad")}</td>
          <td><b>${esc(x.title)}</b>${x.optional ? ` <span class="muted small">(optional for now)</span>` : ""}<div class="small muted">${esc(x.detail)}</div></td></tr>`).join("")}
      </table></div>
      <div class="grid">
        <div class="panel"><h3>GPU</h3><div id="gpu" class="small muted">Checking PyTorch…</div></div>
        <div class="panel"><h3>Last pipeline run</h3>${p.last_run?.date ? `<p class="small muted">${esc(p.last_run.date)}</p>${p.last_run.steps.map(([id, st]) => `<div class="row small">${chip(st)} ${esc(id)}</div>`).join("")}` : `<p class="small muted">None yet.</p>`}</div>
      </div>
    </div>`;
  root.addEventListener("click", e => { const r = e.target.closest("tr[data-href]"); if (r) location.hash = r.dataset.href; });
  api("/api/status/gpu").then(gpu => {
    const el = $("#gpu"); if (!el) return;
    el.innerHTML = gpu.cuda ? `${chip("CUDA", "ok")} ${esc(gpu.device)} · PyTorch ${esc(gpu.torch)}`
      : `${chip("CPU only", "warn")} PyTorch ${esc(gpu.torch || "not installed")}. ${esc(gpu.note || "Start the app with uv run --no-sync pattom view so the GPU build is kept.")}`;
  }).catch(() => {});
}
