import { loadOverview } from "./lib/data.js";
import { wireShell } from "./lib/shell.js";
import { fmtNum, fmtPct, fmtDate, fmtDateTime, stageLabel, stageClass, stageNumber } from "./lib/format.js";
import { radialGaugeSVG } from "./lib/chart.js";

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

const REGIME_LABEL = {
  TRENDING_UP: "Trending up", TRENDING_DOWN: "Trending down", RANGING: "Ranging",
};
const REGIME_TONE = {
  TRENDING_UP: "tone-good", TRENDING_DOWN: "tone-critical", RANGING: "tone-warning",
};
const STAGE_VAR = { 1: "--status-neutral", 2: "--status-good", 3: "--status-warning", 4: "--status-critical" };

// ---------------------------------------------------------- candlestick chart

function candlestickPaths(u, seriesIdx, idx0, idx1) {
  const { ctx } = u;
  const xs = u.data[0], opens = u.data[1], highs = u.data[2], lows = u.data[3], closes = u.data[4];
  const upColor = cssVar("--delta-up") || "#0ca30c";
  const downColor = cssVar("--delta-down") || "#d03b3b";

  ctx.save();
  ctx.beginPath();
  ctx.rect(u.bbox.left, u.bbox.top, u.bbox.width, u.bbox.height);
  ctx.clip();

  let colPx = 6;
  if (idx1 > idx0) {
    const x0 = u.valToPos(xs[idx0], "x", true);
    const x1 = u.valToPos(xs[Math.min(idx0 + 1, idx1)], "x", true);
    colPx = Math.max(2, Math.abs(x1 - x0));
  }
  const bodyW = Math.max(1, colPx * 0.62);

  for (let i = idx0; i <= idx1; i++) {
    const o = opens[i], h = highs[i], l = lows[i], c = closes[i];
    if (o == null || h == null || l == null || c == null) continue;
    const x = u.valToPos(xs[i], "x", true);
    const yO = u.valToPos(o, "y", true);
    const yH = u.valToPos(h, "y", true);
    const yL = u.valToPos(l, "y", true);
    const yC = u.valToPos(c, "y", true);
    const up = c >= o;
    ctx.strokeStyle = up ? upColor : downColor;
    ctx.fillStyle = up ? upColor : downColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + 0.5, yH);
    ctx.lineTo(Math.round(x) + 0.5, yL);
    ctx.stroke();
    const yTop = Math.min(yO, yC);
    const bodyH = Math.max(1, Math.abs(yC - yO));
    ctx.fillRect(x - bodyW / 2, yTop, bodyW, bodyH);
  }
  ctx.restore();
  return null;
}

function fmtCompactPrice(v) {
  if (v == null || Number.isNaN(v)) return "";
  if (Math.abs(v) >= 1000) return (v / 1000).toFixed(0) + "k";
  return v.toFixed(0);
}

function buildChart(container, overview) {
  const k = overview.kse100;
  const b = overview.breadth_above_sma50;
  const dates = k.dates;
  const xs = dates.map((_, i) => i);

  const breadthByDate = new Map(b.dates.map((d, i) => [d, b.pct[i]]));
  const breadthAligned = dates.map((d) => breadthByDate.has(d) ? breadthByDate.get(d) : null);

  const data = [xs, k.open, k.high, k.low, k.close, k.sma50, breadthAligned];

  const gridColor = cssVar("--gridline");
  const axisColor = cssVar("--ink-muted");
  const smaColor = cssVar("--seq-500");
  const breadthColor = cssVar("--accent-breadth");

  const opts = {
    width: container.clientWidth || 900,
    height: 420,
    padding: [8, 8, 0, 0],
    cursor: { drag: { x: true, y: false }, points: { show: false } },
    legend: { show: true },
    scales: {
      x: { time: false },
      y: { range: (u, min, max) => { const p = (max - min) * 0.08 || 1; return [min - p, max + p]; } },
      breadth: { range: [0, 100] },
    },
    axes: [
      {
        stroke: axisColor, grid: { stroke: gridColor, width: 1 }, ticks: { stroke: gridColor },
        values: (u, splits) => splits.map((s) => {
          const i = Math.round(s);
          return dates[i] ? fmtDate(dates[i]).replace(/, \d{4}$/, "") : "";
        }),
      },
      {
        scale: "y", side: 3, stroke: axisColor, grid: { stroke: gridColor, width: 1 },
        values: (u, vals) => vals.map(fmtCompactPrice), size: 56,
      },
      {
        scale: "breadth", side: 1, stroke: axisColor, grid: { show: false },
        values: (u, vals) => vals.map((v) => v + "%"), size: 40,
      },
    ],
    series: [
      {},
      { scale: "y", show: false },
      { scale: "y", show: false },
      { scale: "y", show: false },
      {
        scale: "y", label: "KSE-100", paths: candlestickPaths, points: { show: false },
        value: (u, v) => fmtNum(v, 0),
      },
      {
        scale: "y", label: "50-session SMA", stroke: smaColor, width: 1.5,
        points: { show: false }, value: (u, v) => fmtNum(v, 0),
      },
      {
        scale: "breadth", label: "% above own SMA50", stroke: breadthColor, width: 1.5,
        points: { show: false }, value: (u, v) => (v == null ? "—" : fmtNum(v, 0) + "%"),
        fill: `color-mix(in srgb, ${breadthColor} 7%, transparent)`,
      },
    ],
  };

  container.innerHTML = "";
  const plot = new uPlot(opts, data, container);

  window.addEventListener("resize", () => {
    plot.setSize({ width: container.clientWidth || 900, height: 420 });
  });

  // Direct series.show + redraw, not the public setSeries() -- uPlot's own
  // setSeries() (and, it turns out, redraw() after a direct .show mutation)
  // syncs a legend DOM row; with legend:{show:false} that row never exists
  // and it throws. The legend is kept alive but hidden in CSS (.u-legend)
  // instead, so the built-in bookkeeping has something real to touch.
  const SERIES_IDX = { sma50: 5, breadth: 6 };
  document.querySelectorAll("[data-series-toggle]").forEach((box) => {
    box.addEventListener("change", () => {
      const idx = SERIES_IDX[box.getAttribute("data-series-toggle")];
      plot.series[idx].show = box.checked;
      plot.redraw();
    });
  });

  return plot;
}

// ------------------------------------------------------------------- render

function renderRegime(regime) {
  const valueEl = document.querySelector("[data-regime-value]");
  const sinceEl = document.querySelector("[data-regime-since]");
  const card = document.querySelector("[data-regime-card]");
  if (!regime) {
    valueEl.textContent = "Unknown";
    valueEl.className = "regime-card__value";
    sinceEl.textContent = "";
    return;
  }
  const label = REGIME_LABEL[regime.regime] || regime.regime || "Unknown";
  const tone = REGIME_TONE[regime.regime] || "tone-neutral";
  valueEl.textContent = label;
  valueEl.className = `regime-card__value ${tone}`;
  card.className = `bento-tile bento-tile--regime ${tone}`;
  const days = regime.regime_days;
  sinceEl.textContent = regime.since_date
    ? `${days} session${days === 1 ? "" : "s"} · since ${fmtDate(regime.since_date)}`
    : "";
}

function renderBreadthGauge(overview) {
  const pct = overview.breadth_above_sma50.pct.at(-1);
  document.querySelector("[data-breadth-gauge]").innerHTML =
    radialGaugeSVG(pct, { size: 104, color: "var(--accent-breadth)", label: "of universe" });
}

function renderPerformance(performance) {
  const strip = document.querySelector("[data-perf-strip]");
  const rows = [["1M", performance["1m"]], ["3M", performance["3m"]], ["6M", performance["6m"]], ["1Y", performance["1y"]]];
  strip.innerHTML = rows.map(([label, v]) => {
    const tone = v == null ? "tone-neutral" : v > 0 ? "tone-good" : v < 0 ? "tone-critical" : "tone-neutral";
    return `<div class="mini-stat">
      <div class="mini-stat__label">${label}</div>
      <div class="mini-stat__value ${tone} tabular-nums">${v == null ? "—" : fmtPct(v)}</div>
    </div>`;
  }).join("");
}

function renderHealth(meta) {
  const valueEl = document.querySelector("[data-health-value]");
  const metaEl = document.querySelector("[data-health-meta]");
  const card = document.querySelector("[data-health-card]");
  if (meta.verified) {
    valueEl.textContent = "Up to date";
    card.className = "bento-tile bento-tile--health is-good";
    metaEl.textContent = `Latest data ${fmtDate(meta.bronze_max)}`;
  } else {
    valueEl.textContent = "Not verified";
    card.className = "bento-tile bento-tile--health is-critical";
    metaEl.textContent = meta.withheld_reason || meta.reason || "reason unknown";
  }
}

function renderSectorHeatmap(sectorPayload) {
  const wrap = document.querySelector("[data-sector-heatmap]");
  const sectors = (sectorPayload?.sectors || []).slice()
    .sort((a, b) => (b.composite_score ?? -Infinity) - (a.composite_score ?? -Infinity));
  if (!sectors.length) {
    wrap.innerHTML = `<div class="tile-empty">No sector data.</div>`;
    return;
  }
  wrap.innerHTML = sectors.map((s) => {
    const n = stageNumber(s.sector_stage);
    const v = STAGE_VAR[n] || "--status-neutral";
    const title = `${s.sector} — ${stageLabel(s.sector_stage)} · composite ${fmtNum(s.composite_score, 2)}`;
    return `<div class="heat-cell" style="background:color-mix(in srgb, var(${v}) 22%, var(--surface)); border-color:color-mix(in srgb, var(${v}) 55%, transparent)" title="${title}">
      <span class="heat-cell__label">${s.sector}</span>
    </div>`;
  }).join("");
}

function renderTopMovers(signalsPayload) {
  const wrap = document.querySelector("[data-top-movers]");
  const withChg = (signalsPayload?.symbols || []).filter((s) => s.chg_pct !== null && s.chg_pct !== undefined);
  if (!withChg.length) {
    wrap.innerHTML = `<div class="tile-empty">No price-change data.</div>`;
    return;
  }
  const gainers = [...withChg].sort((a, b) => b.chg_pct - a.chg_pct).slice(0, 3);
  const losers = [...withChg].sort((a, b) => a.chg_pct - b.chg_pct).slice(0, 3);
  const row = (s) => `<div class="mover-row">
      <span class="mover-row__symbol">${s.symbol}</span>
      <span class="${s.chg_pct >= 0 ? "cell-up" : "cell-down"} tabular-nums">${fmtPct(s.chg_pct)}</span>
    </div>`;
  wrap.innerHTML = `
    <div class="movers-group">
      <div class="movers-group__label">Gainers</div>
      ${gainers.map(row).join("")}
    </div>
    <div class="movers-group">
      <div class="movers-group__label">Losers</div>
      ${losers.map(row).join("")}
    </div>`;
}

async function main() {
  const { meta, overview, sectors, signals } = await loadOverview();
  wireShell(meta);
  document.querySelector("[data-as-of]").textContent = `As of ${fmtDate(overview.as_of)}`;
  document.querySelector("[data-footer]").textContent =
    `Kiran — local-first Gold build · generated ${fmtDateTime(meta.generated_at)}`;

  renderRegime(overview.regime);
  renderBreadthGauge(overview);
  renderPerformance(overview.performance);
  renderHealth(meta);
  renderSectorHeatmap(sectors);
  renderTopMovers(signals);

  const chartContainer = document.querySelector("[data-kse-chart]");
  if (overview.kse100.dates.length) {
    buildChart(chartContainer, overview);
    const lastPct = overview.kse100.pct_from_sma50.at(-1);
    const foot = document.querySelector("[data-sma-diff]");
    if (lastPct != null) {
      const tone = lastPct >= 0 ? "cell-up" : "cell-down";
      foot.innerHTML = `Close is <span class="${tone} tabular-nums">${fmtPct(lastPct)}</span> from its 50-session SMA`;
    }
  } else {
    chartContainer.innerHTML = `<div class="chart-empty">No KSE-100 price history available.</div>`;
  }
}

main().catch((err) => {
  document.querySelector("[data-kse-chart]").innerHTML = `<div class="chart-empty">Failed to load data: ${err.message}</div>`;
  console.error(err);
});
