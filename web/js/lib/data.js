// Fetch helpers -- static JSON only, no compute, cache-busted so a fresh
// export is picked up without a hard refresh (design: "computes nothing on load").
export async function fetchJSON(path) {
  const url = `${path}?t=${Date.now()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

export async function loadAll() {
  const [meta, sectors, signals] = await Promise.all([
    fetchJSON("data/meta.json"),
    fetchJSON("data/sector_grades.json"),
    fetchJSON("data/signals.json"),
  ]);
  return { meta, sectors, signals };
}
