r"""
Kiran Local-First Migration -- Phase 3, Task 3.3: Gold build.

Rebuild the Gold serving store from the live Medallion Silver/Bronze store, on
**DuckDB** (owner decision 2026-09-10 -- full DuckDB port, no SQLite compute
scratchpad). Each screener's *pure compute core* (DB-agnostic pandas / plain
Python) is reused by import; only the I/O is reimplemented against DuckDB.

    D:\KIRAN_ARCHIVE\psx_serving\psx_serving.duckdb     the serving DB (read-only for the front end)
    D:\KIRAN_ARCHIVE\psx_serving\parquet\<table>.parquet deterministic export (idempotency + JSON feed)
    D:\KIRAN_ARCHIVE\psx_serving\_gold_build_log.jsonl  append-only provenance
    D:\KIRAN_ARCHIVE\psx_serving\_gold_parity.json      vs the live psx_data.db, each run

Full replace every run: built into ``psx_serving_staging.duckdb``, then atomically
renamed over ``psx_serving.duckdb``. Never writes to Bronze/Silver, never opens
``psx_data.db`` for write (the parity check opens it ``mode=ro&immutable=1``).

Screeners are registered in ``SCREENERS``; 3.3a ships the scaffold + ``regime``.
Later sub-tasks (3.3b..e) add ``stock_signals`` / ``sector_signals`` / etc.

    python -m archive.gold_build [--store-root DIR] [--window-days N] [--no-parity]

Tracker: docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 3 (section 5, tasks 3.3a-f).
Design:  docs/KIRAN_LOCAL_FIRST_ARCHIVE/MEDALLION.md
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from archive.bronze_ingest import ARCHIVE_ROOT, PARQUET_OPTS, _now

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_DB = REPO_ROOT / "psx_data.db"           # parity reference only, opened read-only
DEFAULT_WINDOW_DAYS = 730  # ~2 trading years -- the Gold serving window


# --------------------------------------------------------------------- layout

class GoldStore:
    def __init__(self, root: Path):
        self.root = root
        self.silver = root.parent / "prices_archive" / "silver"
        self.bronze = root.parent / "prices_archive" / "bronze"
        self.db = root / "psx_serving.duckdb"
        self.staging = root / "psx_serving_staging.duckdb"
        self.parquet_dir = root / "parquet"
        self.log_path = root / "_gold_build_log.jsonl"
        self.parity_path = root / "_gold_parity.json"

    def silver_glob(self, name: str) -> str:
        return (self.silver / name / "**" / "*.parquet").as_posix()

    def bronze_glob(self, name: str) -> str:
        return (self.bronze / name / "**" / "*.parquet").as_posix()


# --------------------------------------------------------- screener: regime

def build_regime(store: GoldStore, gcon: "duckdb.DuckDBPyConnection", window_from: str) -> dict:
    """Port of regime.append_latest_regime for the Gold path.

    Reuses regime._compute_indicators / _pending_regime_rows / _classify verbatim
    (they are pure -- no DB I/O). Reads KSE-100 from Bronze index_prices via
    DuckDB, writes the 2-yr `market_regime` slice into the Gold DB. regime_days is
    chained across the FULL history first, then the slice is taken, so the
    boundary row's count is correct.
    """
    import pandas as pd
    import regime

    df = gcon.execute(
        f"SELECT date, high, low, close FROM read_parquet('{store.bronze_glob('index_prices')}') "
        "WHERE symbol = 'KSE-100' ORDER BY date"
    ).fetchdf()
    if df.empty:
        raise SystemExit("gold_build: no KSE-100 rows in Bronze index_prices")

    df["date"] = pd.to_datetime(df["date"])
    df = regime._compute_indicators(df)
    total = len(df)

    recs = []
    for ds, row, reg, days in regime._pending_regime_rows(df, total, None, None, 0):
        recs.append({
            "date": ds,
            "close": float(row["close"]),
            "ema_20": float(row["ema_20"]), "ema_50": float(row["ema_50"]),
            "ema_200": float(row["ema_200"]),
            "atr_20": float(row["atr_20"]) if pd.notna(row["atr_20"]) else None,
            "atr_pct": float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
            "return_20d": float(row["return_20d"]) if pd.notna(row["return_20d"]) else None,
            "regime": reg, "regime_days": int(days), "notes": None,
        })
    full = pd.DataFrame.from_records(recs)
    sliced = full[full["date"] >= window_from].reset_index(drop=True)

    gcon.register("_regime_df", sliced)
    gcon.execute("CREATE OR REPLACE TABLE market_regime AS SELECT * FROM _regime_df")
    gcon.unregister("_regime_df")

    return {"rows": len(sliced), "full_rows": len(full),
            "range": [sliced["date"].min(), sliced["date"].max()],
            "latest": [sliced["date"].iloc[-1], sliced["regime"].iloc[-1],
                       int(sliced["regime_days"].iloc[-1])] if len(sliced) else None}


# regime first; 3.3b..e append here.
SCREENERS = {
    "market_regime": build_regime,
}


# ------------------------------------------------------------------- parity

def _parity_market_regime(gcon: "duckdb.DuckDBPyConnection", live_db: Path) -> dict:
    """Compare Gold `market_regime` to the live `psx_data.db` over the overlap.

    Gold recomputes over the COMPLETE KSE-100 series; the live pipeline is
    incremental and has documented gaps (`market_regime` missing 2026-04-27 +
    the 2026-07 Postgres-dispatch outage dates -- CLAUDE.md "Known Gaps"). So
    Gold is a superset on dates, and its EMA/`regime_days` chain diverges from
    the live one for every date at or after the first live gap -- an EXPECTED
    consequence of computing on the complete series, not a port bug.

    Parity is `clean` iff (a) Gold's dates are a superset of live's, and (b)
    every shared date BEFORE the first live-only gap agrees exactly. A
    disagreement on a pre-gap date is a genuine `residual`.
    """
    if not live_db.exists():
        return {"status": "skipped", "reason": f"{live_db} not found"}
    lcon = sqlite3.connect(f"file:{live_db}?mode=ro&immutable=1", uri=True)
    try:
        gmin, gmax = gcon.execute("SELECT min(date), max(date) FROM market_regime").fetchone()
        live = {r[0]: r for r in lcon.execute(
            "SELECT date, regime, regime_days, ema_20, atr_pct FROM market_regime "
            "WHERE date >= ? ORDER BY date", (gmin,))}
        gold = {r[0]: r for r in gcon.execute(
            "SELECT date, regime, regime_days, ema_20, atr_pct FROM market_regime ORDER BY date").fetchall()}

        only_gold = sorted(set(gold) - set(live))     # live-pipeline gaps Gold fills
        only_live = sorted(set(live) - set(gold))     # should be empty
        first_gap = only_gold[0] if only_gold else None

        shared = sorted(set(live) & set(gold))
        def _diffs(pred):
            return [d for d in shared if pred(d)]
        regime_diff = _diffs(lambda d: live[d][1] != gold[d][1])
        days_diff = _diffs(lambda d: live[d][2] != gold[d][2])
        ema_diff = _diffs(lambda d: live[d][3] is not None and gold[d][3] is not None
                          and abs(live[d][3] - gold[d][3]) > max(1e-6, 1e-4 * abs(live[d][3])))

        def _pre_gap(ds):
            return [d for d in ds if first_gap is None or d < first_gap]
        pre_gap_residual = sorted(set(_pre_gap(regime_diff)) | set(_pre_gap(days_diff))
                                  | set(_pre_gap(ema_diff)))

        clean = not only_live and not pre_gap_residual
        return {
            "status": "clean" if clean else "residual",
            "overlap_from": gmin, "overlap_through": gmax, "shared_dates": len(shared),
            "gold_fills_live_gaps": only_gold, "first_live_gap": first_gap,
            "only_live": only_live[:20],
            "pre_gap_residual": pre_gap_residual,
            "post_gap_expected_divergence": {
                "regime_label_diff_n": len(regime_diff),
                "regime_days_diff_n": len(days_diff),
                "ema20_diff_n": len(ema_diff),
            },
            "note": ("post-gap divergence is expected: Gold chains EMAs / regime_days "
                     "across the complete series; the live pipeline chained across its gaps."),
        }
    finally:
        lcon.close()


PARITY = {
    "market_regime": _parity_market_regime,
}


# --------------------------------------------------------------------- build

def build(store_root: Path, window_days: int = DEFAULT_WINDOW_DAYS,
          run_parity: bool = True) -> dict:
    import datetime as dt

    store = GoldStore(store_root)
    store.root.mkdir(parents=True, exist_ok=True)
    store.parquet_dir.mkdir(parents=True, exist_ok=True)
    if store.staging.exists():
        store.staging.unlink()

    # window anchor = latest Bronze price date minus the window
    con0 = duckdb.connect()
    bmax = con0.execute(
        f"SELECT max(date) FROM read_parquet('{store.bronze_glob('prices')}')"
    ).fetchone()[0]
    con0.close()
    window_from = (dt.date.fromisoformat(bmax) - dt.timedelta(days=window_days)).isoformat()

    gcon = duckdb.connect(str(store.staging))
    built: dict[str, dict] = {}
    try:
        for table, fn in SCREENERS.items():
            built[table] = fn(store, gcon, window_from)
        gcon.close()
    except Exception:
        gcon.close()
        if store.staging.exists():
            store.staging.unlink()
        raise

    # atomic swap
    if store.db.exists():
        store.db.unlink()
    os.replace(store.staging, store.db)

    # deterministic parquet export (idempotency + the JSON feed later)
    gcon = duckdb.connect(str(store.db), read_only=True)
    exported = {}
    for table in SCREENERS:
        t = gcon.execute(f"SELECT * FROM {table} ORDER BY ALL").to_arrow_table()
        fp = store.parquet_dir / f"{table}.parquet"
        tmp = fp.with_suffix(".parquet.tmp")
        pq.write_table(t, tmp, **PARQUET_OPTS)
        os.replace(tmp, fp)
        exported[table] = t.num_rows
    gcon.close()

    parity = {}
    if run_parity:
        gcon = duckdb.connect(str(store.db), read_only=True)
        try:
            for table, pfn in PARITY.items():
                parity[table] = pfn(gcon, LIVE_DB)
        finally:
            gcon.close()
        store.parity_path.write_text(json.dumps({"generated": _now(), **parity}, indent=2, default=str) + "\n")

    entry = {
        "ts": _now(), "action": "gold_build",
        "window_days": window_days, "window_from": window_from, "bronze_max": bmax,
        "screeners": built, "exported_rows": exported, "parity": parity,
    }
    with open(store.log_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, default=str, sort_keys=True) + "\n")

    return {"outcome": "built", "window_from": window_from, "screeners": list(SCREENERS),
            "rows": exported, "parity": {k: v.get("status") for k, v in parity.items()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gold build -- rebuild the DuckDB serving store from Silver.")
    ap.add_argument("--store-root", default=str(ARCHIVE_ROOT / "psx_serving"))
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    ap.add_argument("--no-parity", action="store_true")
    args = ap.parse_args(argv)
    result = build(Path(args.store_root), window_days=args.window_days,
                   run_parity=not args.no_parity)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
