import { loadAll } from "./lib/data.js";
import { wireShell } from "./lib/shell.js";
import { fmtDate, fmtDateTime, fmtPct } from "./lib/format.js";

function chgFormatter(cell) {
  const v = cell.getValue();
  if (v === null || v === undefined) return "—";
  cell.getElement().className = v >= 0 ? "cell-up" : "cell-down";
  return (v >= 0 ? "▲ " : "▼ ") + fmtPct(Math.abs(v)).replace("+", "");
}

function boolBadgeFormatter(cell) {
  const v = cell.getValue();
  if (v === 1 || v === true) { cell.getElement().className = "cell-badge-yes"; return "●"; }
  return `<span class="cell-muted">—</span>`;
}

function numFormatter(digits) {
  return (cell) => {
    const v = cell.getValue();
    return v === null || v === undefined ? "—" : Number(v).toFixed(digits);
  };
}

let table;

function buildTable(symbols) {
  table = new Tabulator("#explorer-table", {
    data: symbols,
    layout: "fitColumns",
    height: "calc(100vh - 320px)",
    placeholder: "No symbols match the current filters",
    columns: [
      { title: "Symbol", field: "symbol", frozen: true, headerFilter: "input", width: 90 },
      { title: "Company", field: "company_name", headerFilter: "input", widthGrow: 2,
        formatter: (cell) => cell.getValue() || `<span class="cell-muted">—</span>` },
      { title: "Sector", field: "sector", headerFilter: "input", widthGrow: 1.4 },
      { title: "Close", field: "close", hozAlign: "right", formatter: numFormatter(2), cssClass: "tabular-nums" },
      { title: "Chg %", field: "chg_pct", hozAlign: "right", formatter: chgFormatter, cssClass: "tabular-nums",
        sorter: "number" },
      { title: "RS Rank", field: "rs_rank", hozAlign: "right", sorter: "number", cssClass: "tabular-nums" },
      { title: "Sector RS", field: "sector_rs_rank", hozAlign: "right", sorter: "number", cssClass: "tabular-nums" },
      { title: "RS 20d", field: "rs_score_20", hozAlign: "right", formatter: numFormatter(1), sorter: "number",
        cssClass: "tabular-nums" },
      { title: "Breakout", field: "bos_flag", hozAlign: "center", formatter: boolBadgeFormatter, width: 90 },
      { title: "Stage-2", field: "stage2_bull", hozAlign: "center", formatter: boolBadgeFormatter, width: 90 },
      { title: "Base tight.", field: "base_tightness", hozAlign: "right", formatter: numFormatter(1), sorter: "number",
        cssClass: "tabular-nums" },
      { title: "Pivot dist %", field: "pivot_distance_pct", hozAlign: "right", formatter: numFormatter(1),
        sorter: "number", cssClass: "tabular-nums" },
      { title: "Price basis", field: "price_basis", hozAlign: "center", width: 100,
        formatter: (cell) => `<span class="cell-muted">${cell.getValue() || "—"}</span>` },
    ],
    initialSort: [{ column: "rs_rank", dir: "asc" }],
  });
}

function wireControls(symbols) {
  const search = document.querySelector("[data-search]");
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    table.setFilter((row) =>
      !q || row.symbol.toLowerCase().includes(q) || (row.company_name || "").toLowerCase().includes(q));
  });

  const basisSelect = document.querySelector("[data-basis-select]");
  const bases = [...new Set(symbols.map((s) => s.price_basis).filter(Boolean))];
  basisSelect.innerHTML = `<option value="">All</option>` + bases.map((b) => `<option value="${b}">${b}</option>`).join("");
  basisSelect.addEventListener("change", () => {
    const v = basisSelect.value;
    table.setFilter(v ? [{ field: "price_basis", type: "=", value: v }] : []);
  });

  const chips = document.querySelectorAll("[data-filter]");
  let active = null;
  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      const key = chip.getAttribute("data-filter");
      if (active === key) {
        active = null;
        table.clearFilter();
        chips.forEach((c) => c.classList.remove("is-active"));
        return;
      }
      active = key;
      chips.forEach((c) => c.classList.toggle("is-active", c === chip));
      if (key === "breakout") table.setFilter("bos_flag", "=", 1);
      if (key === "stage2") table.setFilter("stage2_bull", "=", 1);
    });
  });
}

function renderStatStrip(symbols) {
  const breakouts = symbols.filter((s) => s.bos_flag === 1).length;
  const advancing = symbols.filter((s) => s.stage2_bull === 1).length;
  const strip = document.querySelector("[data-stat-strip]");
  strip.innerHTML = `
    <div class="stat-tile"><div class="stat-tile__label">Symbols</div><div class="stat-tile__value">${symbols.length}</div></div>
    <div class="stat-tile"><div class="stat-tile__label">Breakouts today</div><div class="stat-tile__value tone-good">${breakouts}</div></div>
    <div class="stat-tile"><div class="stat-tile__label">Stage-2 bull</div><div class="stat-tile__value tone-good">${advancing}</div></div>
  `;
}

async function main() {
  const { meta, signals } = await loadAll();
  wireShell(meta);
  document.querySelector("[data-as-of]").textContent = `As of ${fmtDate(signals.as_of)}`;
  document.querySelector("[data-footer]").textContent =
    `Kiran — local-first Gold build · generated ${fmtDateTime(meta.generated_at)}`;

  renderStatStrip(signals.symbols);
  buildTable(signals.symbols);
  wireControls(signals.symbols);
}

main().catch((err) => {
  document.querySelector("#explorer-table").innerHTML = `Failed to load data: ${err.message}`;
  console.error(err);
});
