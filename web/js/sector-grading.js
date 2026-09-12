import { loadAll } from "./lib/data.js";
import { wireShell } from "./lib/shell.js";
import { fmtNum, fmtDate, fmtDateTime, stageLabel, stageClass, stageNumber } from "./lib/format.js";
import { sparklineSVG } from "./lib/chart.js";

const STAGE_COLOR_VAR = { 1: "--status-neutral", 2: "--status-good", 3: "--status-warning", 4: "--status-critical" };

let state = { sectors: [], stageFilter: null, sort: "composite_desc" };

function render() {
  const grid = document.querySelector("[data-sector-grid]");
  let rows = state.sectors.slice();
  if (state.stageFilter) rows = rows.filter((s) => stageNumber(s.sector_stage) === state.stageFilter);

  const sorters = {
    composite_desc: (a, b) => (b.composite_score ?? -Infinity) - (a.composite_score ?? -Infinity),
    rs_rank_asc: (a, b) => (a.rs_rank ?? Infinity) - (b.rs_rank ?? Infinity),
    breadth_desc: (a, b) => (b.breadth_score ?? -Infinity) - (a.breadth_score ?? -Infinity),
    name_asc: (a, b) => a.sector.localeCompare(b.sector),
  };
  rows.sort(sorters[state.sort] || sorters.composite_desc);

  grid.innerHTML = rows.map((s) => {
    const n = stageNumber(s.sector_stage);
    const colorVar = STAGE_COLOR_VAR[n] || "--status-neutral";
    return `
    <div class="sector-card">
      <div class="sector-card__head">
        <div class="sector-card__name">${s.sector}</div>
        <span class="stage-badge ${stageClass(s.sector_stage)}"><span class="dot"></span>${stageLabel(s.sector_stage)}</span>
      </div>
      <div class="sector-card__metrics">
        <div>
          <div class="metric-label">Composite</div>
          <div class="metric-value tabular-nums">${fmtNum(s.composite_score, 2)}</div>
        </div>
        <div>
          <div class="metric-label">RS rank</div>
          <div class="metric-value tabular-nums">#${s.rs_rank ?? "—"}</div>
        </div>
        <div>
          <div class="metric-label">Breadth</div>
          <div class="metric-value tabular-nums">${fmtNum(s.breadth_score, 0)}%</div>
        </div>
      </div>
      <div class="sector-card__chart" style="color:var(${colorVar})">
        ${sparklineSVG(s.history, { color: "currentColor" })}
      </div>
      <div class="sector-card__foot">
        <span>RS 20d ${fmtNum(s.rs_score_20, 1)}</span>
        <span>${s.regime || ""}</span>
      </div>
    </div>`;
  }).join("");
}

function renderStatStrip(sectors) {
  const counts = { 1: 0, 2: 0, 3: 0, 4: 0 };
  for (const s of sectors) counts[stageNumber(s.sector_stage)] = (counts[stageNumber(s.sector_stage)] || 0) + 1;
  const strip = document.querySelector("[data-stat-strip]");
  strip.innerHTML = `
    <div class="stat-tile"><div class="stat-tile__label">Sectors</div><div class="stat-tile__value">${sectors.length}</div></div>
    <div class="stat-tile"><div class="stat-tile__label">Advancing</div><div class="stat-tile__value tone-good">${counts[2]}</div></div>
    <div class="stat-tile"><div class="stat-tile__label">Topping</div><div class="stat-tile__value tone-warning">${counts[3]}</div></div>
    <div class="stat-tile"><div class="stat-tile__label">Declining</div><div class="stat-tile__value tone-critical">${counts[4]}</div></div>
    <div class="stat-tile"><div class="stat-tile__label">Basing</div><div class="stat-tile__value tone-neutral">${counts[1]}</div></div>
  `;
}

function renderStageFilters() {
  const wrap = document.querySelector("[data-stage-filters]");
  const chips = [
    { n: null, label: "All sectors" },
    { n: 2, label: "Advancing", color: "--status-good" },
    { n: 3, label: "Topping", color: "--status-warning" },
    { n: 4, label: "Declining", color: "--status-critical" },
    { n: 1, label: "Basing", color: "--status-neutral" },
  ];
  wrap.innerHTML = chips.map((c) => `
    <button class="filter-chip ${state.stageFilter === c.n ? "is-active" : ""}" data-stage="${c.n ?? ""}">
      ${c.color ? `<span class="filter-chip__swatch" style="background:var(${c.color})"></span>` : ""}${c.label}
    </button>`).join("");
  wrap.querySelectorAll("[data-stage]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const v = btn.getAttribute("data-stage");
      state.stageFilter = v === "" ? null : Number(v);
      renderStageFilters();
      render();
    });
  });
}

async function main() {
  const { meta, sectors } = await loadAll();
  wireShell(meta);
  document.querySelector("[data-as-of]").textContent = `As of ${fmtDate(sectors.as_of)}`;
  document.querySelector("[data-footer]").textContent =
    `Kiran — local-first Gold build · generated ${fmtDateTime(meta.generated_at)}`;

  state.sectors = sectors.sectors;
  renderStatStrip(state.sectors);
  renderStageFilters();
  render();

  document.querySelector("[data-sort-select]").addEventListener("change", (e) => {
    state.sort = e.target.value;
    render();
  });
}

main().catch((err) => {
  document.querySelector("[data-sector-grid]").innerHTML =
    `<div class="sector-card">Failed to load data: ${err.message}</div>`;
  console.error(err);
});
