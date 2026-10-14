// A video frame with a drawing layer. Clicks are reported in full-resolution
// pixels of the video, the same pixels the pipeline uses.
import { api, esc, $ } from "./api.js";

export class FrameCanvas {
  constructor(root, { onClick, onMove, draw, video }) {
    this.root = root; this.onClick = onClick; this.onMove = onMove; this.drawFn = draw;
    this.full = null; this.path = video || ""; this.t = 1;
    root.innerHTML = `
      <div class="row" style="margin-bottom:8px">
        <label class="f">Video (use the prepared copy the pipeline detects on)<select class="fc-video" style="max-width:420px"></select></label>
        <label class="f">Time (s)<input class="fc-time" type="number" min="0" step="0.5" value="1" style="width:90px"></label>
        <button class="fc-load">Show frame</button>
        <span class="fc-info small muted"></span>
      </div>
      <div class="stage crosshair"><img class="fc-img" alt="frame"><canvas class="fc-canvas"></canvas></div>
      <div class="small muted fc-pos" style="margin-top:4px">&nbsp;</div>`;
    this.img = $(".fc-img", root); this.canvas = $(".fc-canvas", root); this.ctx = this.canvas.getContext("2d");
    this.canvas.addEventListener("click", e => { if (this.full) this.onClick?.(this.toFull(e), e); });
    this.canvas.addEventListener("mousemove", e => {
      if (!this.full) return;
      const p = this.toFull(e); $(".fc-pos", root).textContent = `pixel (${p[0]}, ${p[1]})`;
      this.onMove?.(p, e);
    });
    $(".fc-load", root).onclick = () => this.load($(".fc-video", root).value, +$(".fc-time", root).value);
    this.img.onload = () => this.redraw();
    window.addEventListener("resize", () => this.redraw());
  }

  async init() {
    const vids = await api("/api/videos");
    const prepared = vids.filter(v => !v.original), originals = vids.filter(v => v.original);
    const opt = v => `<option value="${esc(v.path)}">${esc(v.path)}</option>`;
    $(".fc-video", this.root).innerHTML = (prepared.length ? `<optgroup label="Prepared copies">${prepared.map(opt).join("")}</optgroup>` : "")
      + (originals.length ? `<optgroup label="Originals (not undistorted)">${originals.map(opt).join("")}</optgroup>` : "");
    if (this.path && vids.some(v => v.path === this.path)) $(".fc-video", this.root).value = this.path;
    if (vids.length) await this.load($(".fc-video", this.root).value, this.t);
    else $(".fc-info", this.root).textContent = "No videos found.";
  }

  async load(path, t) {
    this.path = path; this.t = t;
    const r = await fetch(`/api/videos/frame?path=${encodeURIComponent(path)}&t=${t}&w=1920`);
    if (!r.ok) { $(".fc-info", this.root).textContent = (await r.json()).detail; return; }
    this.full = [+r.headers.get("X-Frame-Width"), +r.headers.get("X-Frame-Height")];
    this.img.src = URL.createObjectURL(await r.blob());
    $(".fc-info", this.root).textContent = `${this.full[0]}×${this.full[1]} px · ${t} s`;
  }

  get k() { return this.img.clientWidth / (this.full?.[0] || 1); }

  toFull(e) {
    const b = this.canvas.getBoundingClientRect();
    return [Math.round((e.clientX - b.left) / this.k), Math.round((e.clientY - b.top) / this.k)];
  }

  redraw() {
    const w = this.img.clientWidth, h = this.img.clientHeight;
    if (this.canvas.width !== w || this.canvas.height !== h) { this.canvas.width = w; this.canvas.height = h; }
    this.ctx.clearRect(0, 0, w, h);
    if (this.full) this.drawFn?.(this.ctx, this.k);
  }
}

// Drawing helpers in full-resolution pixels (k scales to the screen).
export function line(ctx, k, a, b, color, width = 3) {
  ctx.strokeStyle = color; ctx.lineWidth = width;
  ctx.beginPath(); ctx.moveTo(a[0] * k, a[1] * k); ctx.lineTo(b[0] * k, b[1] * k); ctx.stroke();
}

export function dot(ctx, k, p, color, r = 5) {
  ctx.fillStyle = color; ctx.strokeStyle = "#000"; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(p[0] * k, p[1] * k, r, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
}

export function label(ctx, k, p, text, color = "#fff", dy = -10) {
  ctx.font = "bold 12px system-ui, sans-serif";
  const w = ctx.measureText(text).width + 6;
  ctx.fillStyle = "rgba(0,0,0,.65)"; ctx.fillRect(p[0] * k + 6, p[1] * k + dy - 12, w, 16);
  ctx.fillStyle = color; ctx.fillText(text, p[0] * k + 9, p[1] * k + dy);
}

export function arrow(ctx, k, from, to, color) {
  const [x1, y1, x2, y2] = [from[0] * k, from[1] * k, to[0] * k, to[1] * k];
  const ang = Math.atan2(y2 - y1, x2 - x1);
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - 10 * Math.cos(ang - 0.45), y2 - 10 * Math.sin(ang - 0.45));
  ctx.lineTo(x2 - 10 * Math.cos(ang + 0.45), y2 - 10 * Math.sin(ang + 0.45));
  ctx.closePath(); ctx.fill();
}
