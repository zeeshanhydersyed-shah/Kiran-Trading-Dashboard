export function fmtNum(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtInt(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Math.round(Number(v)).toLocaleString();
}

export function fmtPct(v, digits = 1) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${Number(v).toFixed(digits)}%`;
}

export function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00Z");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

const STAGE_LABEL = {
  "Stage 1": "Stage 1 · Basing",
  "Stage 2": "Stage 2 · Advancing",
  "Stage 3": "Stage 3 · Topping",
  "Stage 4": "Stage 4 · Declining",
};
export function stageLabel(stage) {
  return STAGE_LABEL[stage] || stage || "Unknown";
}

const STAGE_CLASS = { "Stage 1": "stage-1", "Stage 2": "stage-2", "Stage 3": "stage-3", "Stage 4": "stage-4" };
export function stageClass(stage) {
  return STAGE_CLASS[stage] || "stage-1";
}

const STAGE_NUM = { "Stage 1": 1, "Stage 2": 2, "Stage 3": 3, "Stage 4": 4 };
export function stageNumber(stage) {
  return STAGE_NUM[stage] || 0;
}
