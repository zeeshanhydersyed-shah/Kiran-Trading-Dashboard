const KEY = "kiran-theme"; // "light" | "dark" | absent (follow OS)

export function initTheme() {
  const saved = safeGet();
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  updateToggleIcon();
}

export function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme")
    || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  safeSet(next);
  updateToggleIcon();
}

function updateToggleIcon() {
  const btn = document.querySelector("[data-theme-toggle]");
  if (!btn) return;
  const current = document.documentElement.getAttribute("data-theme")
    || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  btn.textContent = current === "dark" ? "☀" : "☾";
}

function safeGet() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}
function safeSet(v) {
  try { localStorage.setItem(KEY, v); } catch { /* private mode etc -- non-fatal */ }
}
