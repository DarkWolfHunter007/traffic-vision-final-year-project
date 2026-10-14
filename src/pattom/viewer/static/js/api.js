// Shared helpers: API calls with the app token, toasts, small DOM helpers.
const TOKEN = document.querySelector('meta[name="pattom-token"]').content;

export async function api(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (method !== "GET") opts.headers["X-Pattom-Token"] = TOKEN;
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  const isJson = (r.headers.get("content-type") || "").includes("json");
  const data = isJson ? await r.json() : await r.text();
  if (!r.ok) {
    const msg = isJson ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : data;
    const err = new Error(msg || `HTTP ${r.status}`); err.status = r.status; throw err;
  }
  return data;
}

export function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`; t.textContent = msg;
  document.getElementById("toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "bad" ? 9000 : 3500);
}

export const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export const chip = (text, cls = text) => `<span class="chip ${esc(cls)}">${esc(text)}</span>`;
export const fmtTime = s => { const m = Math.floor(s / 60); return `${m}:${(s - 60 * m).toFixed(2).padStart(5, "0")}`; };

// Run an async action with a toast on failure; returns its result or undefined.
export async function attempt(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg, "ok"); return r; }
  catch (e) { toast(e.message, "bad"); }
}

// Parse a typed parameter: numbers and true/false become values, empty means "not set".
export function parseValue(text) {
  const t = String(text).trim();
  if (t === "") return undefined;
  if (t === "true" || t === "false") return t === "true";
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  if (/^[\[{]/.test(t)) { try { return JSON.parse(t); } catch { /* keep text */ } }
  return t;
}
export const showValue = v => v === undefined || v === null ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);

export const CLASS_COLORS = { car: "#2f9bff", two_wheeler: "#ffb020", auto_rickshaw: "#2ecc71", bus: "#e74c3c", truck: "#a66bff" };
