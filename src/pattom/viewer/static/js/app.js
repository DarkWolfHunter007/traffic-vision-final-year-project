// Hash router: each page module exports render(root) and may export leave().
import { api, esc } from "./api.js";

const PAGES = ["home", "videos", "pipeline", "results", "review", "lines", "ground", "phases", "manual", "alternatives",
  "settings", "files", "sources"];
let current = null;

async function route() {
  const [name, ...rest] = (location.hash.replace(/^#\//, "") || "home").split("/");
  const page = PAGES.includes(name) ? name : "home";
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.page === page));
  if (current?.leave) current.leave();
  // A fresh element per page, so listeners from the previous page do not carry over.
  const old = document.getElementById("view"), root = old.cloneNode(false);
  old.replaceWith(root);
  root.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    current = await import(`./pages/${page}.js`);
    await current.render(root, rest.map(decodeURIComponent));
  } catch (e) {
    root.innerHTML = `<div class="notice bad">Could not open this page: ${esc(e.message)}</div>`;
    console.error(e);
  }
}

// Small "run going" chip in the sidebar, on every page.
async function pollJob() {
  try {
    const j = await api("/api/jobs/current");
    const c = document.getElementById("jobchip");
    c.className = `chip ${j.state === "idle" ? "off" : j.state}`;
    c.textContent = j.state === "idle" ? "no run" : `run ${j.state}`;
  } catch { /* server stopped */ }
  setTimeout(pollJob, 3000);
}

window.addEventListener("hashchange", route);
route();
pollJob();
