// Minimal inline-SVG sparkline for the sector cards -- a single series needs
// no legend/axis (dataviz skill: "a single series needs no legend box - the
// title names it"). Thin 2px line, rounded data-end anchored at the last
// point, per mark spec. Kept deliberately simple (no uPlot instance per
// card) -- ~24 tiny multiples render faster and stay crisp at any DPI as SVG.
export function sparklineSVG(values, { width = 220, height = 40, color = "currentColor" } = {}) {
  const nums = (values || []).filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
  if (nums.length < 2) {
    return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" preserveAspectRatio="none"></svg>`;
  }
  const min = Math.min(...nums), max = Math.max(...nums);
  const span = max - min || 1;
  const pad = 3;
  const n = values.length;
  const points = values.map((v, i) => {
    const x = (i / (n - 1)) * (width - pad * 2) + pad;
    const val = v === null || v === undefined || Number.isNaN(v) ? null : v;
    const y = val === null ? null : height - pad - ((val - min) / span) * (height - pad * 2);
    return [x, y];
  });
  // build a path, skipping gaps (nulls) rather than interpolating through them
  let d = "";
  let drawing = false;
  for (const [x, y] of points) {
    if (y === null) { drawing = false; continue; }
    d += (drawing ? " L " : "M ") + x.toFixed(1) + " " + y.toFixed(1);
    drawing = true;
  }
  const [lastX, lastY] = [...points].reverse().find((p) => p[1] !== null) || [null, null];
  const dot = lastX !== null
    ? `<circle cx="${lastX.toFixed(1)}" cy="${lastY.toFixed(1)}" r="2.5" fill="${color}"/>`
    : "";
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" preserveAspectRatio="none">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    ${dot}
  </svg>`;
}
