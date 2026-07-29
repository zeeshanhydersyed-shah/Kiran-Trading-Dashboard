import json

with open('equity_curve_export.json') as f:
    data = json.load(f)

data_json = json.dumps(data, separators=(',', ':'))

html = r"""<style>
.viz-root {
  color-scheme: light;
  --surface-1:      #fcfcfb;
  --page:           #f9f9f7;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --muted:          #898781;
  --grid:           #e1e0d9;
  --baseline:       #c3c2b7;
  --series-1:       #2a78d6;
  --critical:       #d03b3b;
  --critical-fill:  rgba(208,59,59,0.10);
  --good:           #0ca30c;
  --border:         rgba(11,11,11,0.10);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --muted:          #898781;
    --grid:           #2c2c2a;
    --baseline:       #383835;
    --series-1:       #3987e5;
    --critical:       #e66767;
    --critical-fill:  rgba(230,103,103,0.14);
    --good:           #0ca30c;
    --border:         rgba(255,255,255,0.10);
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --surface-1:      #1a1a19;
  --page:           #0d0d0d;
  --text-primary:   #ffffff;
  --text-secondary: #c3c2b7;
  --muted:          #898781;
  --grid:           #2c2c2a;
  --baseline:       #383835;
  --series-1:       #3987e5;
  --critical:       #e66767;
  --critical-fill:  rgba(230,103,103,0.14);
  --good:           #0ca30c;
  --border:         rgba(255,255,255,0.10);
}
.viz-root { background: var(--page); padding: 24px; box-sizing: border-box; }
.viz-card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 20px 20px 12px; max-width: 980px; margin: 0 auto; }
.viz-title { color: var(--text-primary); font-size: 15px; font-weight: 600; margin: 0 0 2px; }
.viz-sub { color: var(--text-secondary); font-size: 12.5px; margin: 0 0 14px; }
.viz-chart-wrap { position: relative; width: 100%; }
svg { display: block; width: 100%; height: auto; overflow: visible; }
.axis-label { fill: var(--muted); font-size: 10.5px; }
.gridline { stroke: var(--grid); stroke-width: 1; }
.baseline { stroke: var(--baseline); stroke-width: 1; }
.equity-line { fill: none; stroke: var(--series-1); stroke-width: 2; }
.dd-fill { fill: var(--critical-fill); }
.zero-line { stroke: var(--baseline); stroke-width: 1; stroke-dasharray: 2 3; }
.marker-dot { fill: var(--critical); stroke: var(--surface-1); stroke-width: 1.5; }
.marker-label { fill: var(--text-secondary); font-size: 10.5px; }
.hover-crosshair { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 2 3; pointer-events: none; opacity: 0; }
.hover-dot { fill: var(--series-1); stroke: var(--surface-1); stroke-width: 2; pointer-events: none; opacity: 0; }
.tooltip { position: absolute; pointer-events: none; background: var(--text-primary); color: var(--surface-1); font-size: 11.5px; padding: 6px 9px; border-radius: 6px; opacity: 0; transform: translate(-50%, -100%); white-space: nowrap; z-index: 10; line-height: 1.5; }
.legend-row { display:flex; gap:16px; align-items:center; margin: 6px 0 14px; font-size: 11.5px; color: var(--text-secondary); }
.legend-item { display:flex; align-items:center; gap:6px; }
.legend-swatch { width: 14px; height: 2px; border-radius: 1px; }
.legend-swatch.line { background: var(--series-1); }
.legend-swatch.fill { width: 12px; height: 10px; background: var(--critical-fill); border: 1px solid var(--critical); border-radius: 2px; }
</style>

<div class="viz-root">
  <div class="viz-card">
    <p class="viz-title">Cumulative realized R, chronological order (518 trades, 2005-07-11 to 2026-07-10)</p>
    <p class="viz-sub">Sum of gap-adjusted, floored realized_R per trade, ordered by breakout date across the whole universe. Simplification, not a portfolio simulation -- does not model concurrent positions.</p>
    <div class="legend-row">
      <div class="legend-item"><span class="legend-swatch line"></span>Cumulative R</div>
      <div class="legend-item"><span class="legend-swatch fill"></span>Drawdown from running peak</div>
    </div>
    <div class="viz-chart-wrap" id="chartWrap">
      <svg id="chartSvg" viewBox="0 0 920 420" preserveAspectRatio="xMidYMid meet"></svg>
      <div class="tooltip" id="tooltip"></div>
    </div>
  </div>
</div>

<script>
const data = __DATA_JSON__;

const svg = document.getElementById('chartSvg');
const tooltip = document.getElementById('tooltip');
const wrap = document.getElementById('chartWrap');

const W = 920, H = 420;
const marginL = 46, marginR = 16, marginT = 16, marginB = 32;
const plotW = W - marginL - marginR;
const plotH = H - marginT - marginB;

const n = data.length;
const cums = data.map(function(d){ return d.cum; });
const yMax = Math.max.apply(null, cums) * 1.08;
const yMin = Math.min(Math.min.apply(null, cums), 0) * 1.15;

function xScale(i) { return marginL + (i / (n - 1)) * plotW; }
function yScale(v) { return marginT + plotH - ((v - yMin) / (yMax - yMin)) * plotH; }

const ns = "http://www.w3.org/2000/svg";
function el(tag, attrs) {
  const e = document.createElementNS(ns, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

const yTicks = 6;
for (let t = 0; t <= yTicks; t++) {
  const v = yMin + (yMax - yMin) * (t / yTicks);
  const y = yScale(v);
  svg.appendChild(el('line', { x1: marginL, x2: W - marginR, y1: y, y2: y, class: 'gridline' }));
  const lbl = el('text', { x: marginL - 8, y: y + 3.5, class: 'axis-label', 'text-anchor': 'end' });
  lbl.textContent = v.toFixed(0) + 'R';
  svg.appendChild(lbl);
}

svg.appendChild(el('line', { x1: marginL, x2: W - marginR, y1: yScale(0), y2: yScale(0), class: 'zero-line' }));

const yearsShown = new Set();
data.forEach(function(d, i) {
  const yr = d.d.slice(0, 4);
  if (i === 0 || yr !== data[i-1].d.slice(0,4)) {
    if (parseInt(yr) % 3 === 0 || i === 0) {
      if (!yearsShown.has(yr)) {
        yearsShown.add(yr);
        const x = xScale(i);
        const lbl = el('text', { x: x, y: H - marginB + 16, class: 'axis-label', 'text-anchor': 'middle' });
        lbl.textContent = yr;
        svg.appendChild(lbl);
      }
    }
  }
});
svg.appendChild(el('line', { x1: marginL, x2: W - marginR, y1: H - marginB, y2: H - marginB, class: 'baseline' }));

let ddPath = 'M ' + xScale(0) + ' ' + yScale(cums[0]);
data.forEach(function(d, i){ ddPath += ' L ' + xScale(i) + ' ' + yScale(d.cum); });
let peak = cums[0];
const peakVals = cums.map(function(v){ peak = Math.max(peak, v); return peak; });
for (let i = n - 1; i >= 0; i--) { ddPath += ' L ' + xScale(i) + ' ' + yScale(peakVals[i]); }
ddPath += ' Z';
svg.appendChild(el('path', { d: ddPath, class: 'dd-fill' }));

let linePath = 'M ' + xScale(0) + ' ' + yScale(cums[0]);
data.forEach(function(d, i){ if (i > 0) linePath += ' L ' + xScale(i) + ' ' + yScale(d.cum); });
svg.appendChild(el('path', { d: linePath, class: 'equity-line' }));

let minDdIdx = 0;
data.forEach(function(d, i){ if (d.dd < data[minDdIdx].dd) minDdIdx = i; });
const mdX = xScale(minDdIdx), mdY = yScale(cums[minDdIdx]);
svg.appendChild(el('circle', { cx: mdX, cy: mdY, r: 4, class: 'marker-dot' }));
const mdLabel = el('text', { x: mdX, y: mdY + 18, class: 'marker-label', 'text-anchor': 'middle' });
mdLabel.textContent = 'max drawdown ' + data[minDdIdx].dd + 'R';
svg.appendChild(mdLabel);

let maxRIdx = 0;
data.forEach(function(d, i){ if (d.R > data[maxRIdx].R) maxRIdx = i; });
const crX = xScale(maxRIdx), crY = yScale(cums[maxRIdx]);
svg.appendChild(el('circle', { cx: crX, cy: crY, r: 4, fill: 'var(--good)', stroke: 'var(--surface-1)', 'stroke-width': 1.5 }));
const crLabel = el('text', { x: crX, y: crY - 12, class: 'marker-label', 'text-anchor': 'middle' });
crLabel.textContent = data[maxRIdx].sym + ' +' + data[maxRIdx].R + 'R';
svg.appendChild(crLabel);

const crosshair = el('line', { class: 'hover-crosshair', y1: marginT, y2: H - marginB });
svg.appendChild(crosshair);
const hoverDot = el('circle', { class: 'hover-dot', r: 4 });
svg.appendChild(hoverDot);

const hitRect = el('rect', { x: marginL, y: marginT, width: plotW, height: plotH, fill: 'transparent' });
svg.appendChild(hitRect);

hitRect.addEventListener('mousemove', function(ev) {
  const rect = svg.getBoundingClientRect();
  const scaleX = W / rect.width;
  const mx = (ev.clientX - rect.left) * scaleX;
  let i = Math.round(((mx - marginL) / plotW) * (n - 1));
  i = Math.max(0, Math.min(n - 1, i));
  const d = data[i];
  const x = xScale(i), y = yScale(d.cum);
  crosshair.setAttribute('x1', x); crosshair.setAttribute('x2', x);
  crosshair.style.opacity = 1;
  hoverDot.setAttribute('cx', x); hoverDot.setAttribute('cy', y);
  hoverDot.style.opacity = 1;
  const wrapRect = wrap.getBoundingClientRect();
  const px = (x / W) * wrapRect.width;
  const py = (y / H) * wrapRect.height;
  tooltip.style.left = px + 'px';
  tooltip.style.top = (py - 10) + 'px';
  tooltip.style.opacity = 1;
  tooltip.innerHTML = '<b>' + d.sym + '</b> · ' + d.d + '<br>trade R: ' + (d.R >= 0 ? '+' : '') + d.R + 'R &nbsp; cum: ' + (d.cum >= 0 ? '+' : '') + d.cum + 'R<br>drawdown: ' + d.dd + 'R';
});
hitRect.addEventListener('mouseleave', function() {
  crosshair.style.opacity = 0; hoverDot.style.opacity = 0; tooltip.style.opacity = 0;
});
</script>
"""

html = html.replace('__DATA_JSON__', data_json)

out_path = r"C:\Users\Lenovo\AppData\Local\Temp\claude\C--Users-Lenovo\da218be5-10e6-4c1c-adaf-0ea46a26d154\scratchpad\triangle_equity_curve.html"
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(html)
print("wrote", out_path, len(html), "bytes")
