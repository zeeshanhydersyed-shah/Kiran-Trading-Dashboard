r"""
Kiran Local-First Migration -- Phase 1, sub-task 1 (store materialisation).

Materialise the Bronze/Silver Parquet store from a FROZEN baseline .db (never
from live ``psx_data.db``). Parquet is engine-neutral; DuckDB attaches to it in
Phase 3. D7: read-only derived copy -- no historical row is altered,
corrected, or re-scraped.

Layout under KIRAN_ARCHIVE_ROOT (default D:\KIRAN_ARCHIVE):
  bronze/prices/year=YYYY/data.parquet          raw OHLCV  (price source of truth)
  bronze/index_prices/year=YYYY/data.parquet    raw index OHLCV
  silver/prices_adjusted/year=YYYY/data.parquet CA-adjusted prices (as-captured)
  silver/sectors.parquet                        symbol -> sector map (as-captured)
  silver/stock_metadata.parquet                 universe / listing metadata (as-captured)

Rows are sorted deterministically before writing so a re-run is byte-identical.
Indicator tables (stock_signals, sector_signals, market_regime) are NOT exported
here -- they stay in the whole-DB baseline and are rebuilt by the Medallion
pipeline in Phase 3.

    python -m archive.build_store [BASELINE_DB]
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import sys

import pyarrow as pa
import pyarrow.parquet as pq

ARCHIVE_ROOT = os.environ.get("KIRAN_ARCHIVE_ROOT", r"D:\KIRAN_ARCHIVE")

PLAN = {
    "prices":          ("bronze", ["symbol", "date"], "date"),
    "index_prices":    ("bronze", ["symbol", "date"], "date"),
    "prices_adjusted": ("silver", ["symbol", "date"], "date"),
    "sectors":         ("silver", ["symbol"], None),
    "stock_metadata":  ("silver", ["symbol"], None),
}
PARQUET_OPTS = dict(compression="zstd", version="2.6", use_dictionary=True)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _latest_baseline() -> str:
    d = os.path.join(ARCHIVE_ROOT, "baseline")
    cands = sorted(f for f in os.listdir(d)
                   if f.startswith("psx_data_baseline_KIRAN_LFM_P1_") and f.endswith(".db"))
    if not cands:
        raise SystemExit(f"no baseline .db under {d}")
    return os.path.join(d, cands[-1])


def fetch_table(con: sqlite3.Connection, name: str, sort_keys: list[str]):
    cur = con.cursor()
    cols = [r[1] for r in cur.execute(f"PRAGMA table_info('{name}')")]
    order = ", ".join(f'"{k}"' for k in sort_keys)
    sel = ", ".join(f'"{c}"' for c in cols)
    rows = cur.execute(f'SELECT {sel} FROM "{name}" ORDER BY {order}').fetchall()
    return pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)}), len(rows), cols


def main() -> int:
    baseline = sys.argv[1] if len(sys.argv) > 1 else _latest_baseline()
    assert os.path.exists(baseline), baseline
    print(f"source baseline : {baseline}")
    print(f"        sha256  : {sha256(baseline)}")
    con = sqlite3.connect(f"file:{baseline}?mode=ro", uri=True)

    manifest = {"built_at": dt.datetime.now().isoformat(), "source_baseline": baseline,
                "source_baseline_sha256": sha256(baseline),
                "parquet_opts": PARQUET_OPTS, "tables": {}}

    for tbl, (layer, sort_keys, part_col) in PLAN.items():
        table, n, cols = fetch_table(con, tbl, sort_keys)
        base = os.path.join(ARCHIVE_ROOT, layer, tbl)
        files = []
        if part_col:
            by_year: dict[str, list[int]] = {}
            for i, d in enumerate(table.column(part_col).to_pylist()):
                by_year.setdefault((d or "")[:4], []).append(i)
            for yr, idx in sorted(by_year.items()):
                d = os.path.join(base, f"year={yr}")
                os.makedirs(d, exist_ok=True)
                fp = os.path.join(d, "data.parquet")
                pq.write_table(table.take(pa.array(idx)), fp, **PARQUET_OPTS)
                files.append(fp)
        else:
            os.makedirs(base, exist_ok=True)
            fp = os.path.join(base, f"{tbl}.parquet")
            pq.write_table(table, fp, **PARQUET_OPTS)
            files.append(fp)

        manifest["tables"][tbl] = {
            "layer": layer, "rows": n, "columns": cols, "partitioned_by": part_col,
            "files": len(files), "bytes": sum(os.path.getsize(f) for f in files),
            "file_sha256": {os.path.relpath(f, ARCHIVE_ROOT).replace("\\", "/"): sha256(f)
                            for f in files},
        }
        print(f"  {layer}/{tbl:<16} rows={n:>9,} files={len(files):>3} "
              f"bytes={manifest['tables'][tbl]['bytes']:>12,}")

    con.close()
    mp = os.path.join(ARCHIVE_ROOT, "STORE_MANIFEST.json")
    with open(mp, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nstore manifest -> {mp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
