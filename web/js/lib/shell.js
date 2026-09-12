import { initTheme, toggleTheme } from "./theme.js";
import { fmtDate } from "./format.js";

export function wireShell(meta) {
  initTheme();
  const toggleBtn = document.querySelector("[data-theme-toggle]");
  if (toggleBtn) toggleBtn.addEventListener("click", toggleTheme);

  const pill = document.querySelector("[data-freshness-pill]");
  if (pill && meta) {
    if (meta.verified) {
      pill.className = "freshness-pill is-verified";
      pill.innerHTML = `<span class="freshness-pill__dot"></span> Verified as of ${fmtDate(meta.bronze_max)}`;
    } else {
      pill.className = "freshness-pill is-unverified";
      const reason = meta.withheld_reason || meta.reason || "unknown";
      pill.innerHTML = `<span class="freshness-pill__dot"></span> NOT VERIFIED — ${reason}`;
    }
  }

  const banner = document.querySelector("[data-withheld-banner]");
  if (banner && meta && !meta.verified) {
    banner.classList.add("is-shown");
    const reason = meta.withheld_reason || meta.reason || "unknown";
    banner.textContent = `⚠ Data not verified — ${reason}. Showing the last known-good build.`;
  }
}
