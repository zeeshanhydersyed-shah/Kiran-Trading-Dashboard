r"""
Kiran Local-First Migration -- Phase 3, Task 3.2: Silver build.

Rebuild the Silver layer from the live Bronze store:

    prices_archive/silver/prices_adjusted/year=YYYY/data.parquet
    prices_archive/silver/sectors/sectors.parquet
    prices_archive/silver/stock_metadata/stock_metadata.parquet
    prices_archive/_silver_build_log.jsonl        append-only provenance

Silver is **disposable** -- a full rebuild from Bronze every run, deterministic
(re-run => byte-identical). It never writes to Bronze and never opens
``psx_data.db`` for write.

What it ports (tracker section 5 / docs/KIRAN_LOCAL_FIRST_ARCHIVE/MEDALLION.md):

1. **Corporate-action adjustment** -- a faithful port of ``apply_price_adjustments.py``:
   ``prices_adjusted`` = Bronze ``prices`` with each confirmed backward CA factor
   (``close_after / close_before``) applied to that symbol's pre-ex-date OHLC,
   ``ROUND(_, 4)`` per event, events oldest->newest so they compound. Legacy
   event set = the DROP_50/33/25 auto-confirm rows in
   ``corporate_action_suspects_clean.csv`` + the CONFIRMED rows in the frozen
   baseline's ``corporate_action_suspects`` table (read-only; the live table is
   never touched).
2. **Circuit flags** -- ``hit_circuit_up`` / ``hit_circuit_down`` /
   ``thin_trading_flag`` via the confirmed producer formula
   (``apply_price_adjustments.compute_circuit_flags``), computed on the adjusted
   series, exactly the columns the frozen ``silver/prices_adjusted`` carries.
3. **Universe conforming** -- ``sectors`` with non-equity symbols
   (``config.is_non_equity_symbol``) dropped; ``stock_metadata`` rebuilt from the
   frozen ``silver`` universe inputs + Bronze price ranges + ``config``'s
   ``EXCLUDED_SECTORS`` / ``SECTOR_OVERRIDES`` / ``UNIVERSE_WHITELIST``
   (a port of ``build_stock_metadata.py``'s include-set rule).

**CA source gate** (``--ca-source`` / ``KIRAN_SILVER_CA_SOURCE``, default
``legacy``): ``v2`` makes the CA-pipeline-v2 total-return substrate
(``ca_v2_reader.load_v2_prices``) an *available* Silver input. It is **off by
default** and the dashboard never reads this store yet -- wiring v2 into the
dashboard is a separate, Q6-gated sign-off (tracker section 9 D5 / TR-19). This
switch only lets research/Gold opt in behind an explicit flag.

    python -m archive.silver_build [--store-root DIR] [--ca-source legacy|v2]
                                   [--ca-v2-dir DIR]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from archive.bronze_ingest import ARCHIVE_ROOT, PARQUET_OPTS, _now, _sort

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "corporate_action_suspects_clean.csv"
AUTO_CONFIRM_CATS = {"DROP_50", "DROP_33", "DROP_25"}

PRICES_ADJ_COLUMNS = ["symbol", "date", "close", "volume", "high", "low", "open",
                      "hit_circuit_up", "hit_circuit_down", "thin_trading_flag"]
PRICES_ADJ_SCHEMA = pa.schema([
    ("symbol", pa.string()), ("date", pa.string()),
    ("close", pa.float64()), ("volume", pa.int64()),
    ("high", pa.float64()), ("low", pa.float64()), ("open", pa.float64()),
    ("hit_circuit_up", pa.int64()), ("hit_circuit_down", pa.int64()),
    ("thin_trading_flag", pa.int64()),
])

ACTIVE_CUTOFF = "2024-01-01"  # matches build_stock_metadata.py


def _baseline_db() -> Path | None:
    d = ARCHIVE_ROOT / "baseline"
    if not d.exists():
        return None
    cands = sorted(p for p in d.glob("psx_data_baseline_KIRAN_LFM_P1_*.db"))
    return cands[-1] if cands else None


def _write_partitioned(table: pa.Table, base: Path) -> list[Path]:
    """Write a (symbol,date)-sorted table into year=YYYY/data.parquet partitions,
    deterministically (matches archive/build_store.py)."""
    table = _sort(table)
    years = table.column("date").to_pylist()
    by_year: dict[str, list[int]] = defaultdict(list)
    for i, d in enumerate(years):
        by_year[(d or "")[:4]].append(i)
    out = []
    for yr, idx in sorted(by_year.items()):
        fp = base / f"year={yr}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = fp.with_suffix(".parquet.tmp")
        pq.write_table(table.take(pa.array(idx)), tmp, **PARQUET_OPTS)
        os.replace(tmp, fp)
        out.append(fp)
    return out


def _write_single(table: pa.Table, fp: Path) -> None:
    fp.parent.mkdir(parents=True, exist_ok=True)
    tmp = fp.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp, **PARQUET_OPTS)
    os.replace(tmp, fp)


# --------------------------------------------------------------- CA events

def load_legacy_events(baseline_db: Path | None) -> list[dict]:
    """Port of apply_price_adjustments.load_events(apply_all=True), reading the
    CONFIRMED corporate-action rows from the FROZEN baseline (never the live DB)."""
    events: list[dict] = []
    seen: set[tuple[str, str]] = set()

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat = row["magnitude_category"]
            status = row["review_status"].strip().upper()
            if cat in AUTO_CONFIRM_CATS or status == "CONFIRMED":
                events.append({"symbol": row["symbol"], "date": row["date"],
                               "close_before": row["close_before"],
                               "close_after": row["close_after"],
                               "category": cat, "override": None})
                seen.add((row["symbol"], row["date"]))

    if baseline_db is not None and baseline_db.exists():
        con = sqlite3.connect(f"file:{baseline_db}?mode=ro&immutable=1", uri=True)
        try:
            live = con.execute(
                "SELECT symbol, suspect_date, close_before, close_after, adjustment_factor "
                "FROM corporate_action_suspects WHERE status = 'CONFIRMED'").fetchall()
        finally:
            con.close()
        for sym, d, cb, ca, factor in live:
            if (sym, d) in seen:
                continue
            events.append({"symbol": sym, "date": d, "close_before": str(cb),
                           "close_after": str(ca), "category": "BASELINE_CONFIRMED",
                           "override": factor})
            seen.add((sym, d))

    events.sort(key=lambda r: (r["symbol"], r["date"]))
    return events


def _apply_ca(con: "duckdb.DuckDBPyConnection", events: list[dict]) -> tuple[int, int]:
    """Apply each event's backward factor to the symbol's pre-ex-date OHLC,
    ROUND(_,4) per event, oldest->newest (compounding) -- exactly
    apply_price_adjustments.build_adjusted_prices()'s inner loop. Returns
    (events_applied, events_skipped_zero_close_before)."""
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        by_symbol[ev["symbol"]].append(ev)

    applied, skipped = 0, 0
    for sym, evs in by_symbol.items():
        for ev in sorted(evs, key=lambda r: r["date"]):
            if ev["override"] is not None:
                adj = float(ev["override"])
            else:
                cb, ca = float(ev["close_before"]), float(ev["close_after"])
                if cb == 0:
                    skipped += 1
                    continue
                adj = ca / cb
            con.execute(
                "UPDATE pa SET open=round(open*?,4), high=round(high*?,4), "
                "low=round(low*?,4), close=round(close*?,4) "
                "WHERE symbol=? AND date < ?",
                [adj, adj, adj, adj, sym, ev["date"]])
            applied += 1
    return applied, skipped


# --------------------------------------------------------- universe conforming

def _conform_sectors(frozen_sectors: pa.Table):
    import config
    syms = frozen_sectors.column("symbol").to_pylist()
    secs = frozen_sectors.column("sector").to_pylist()
    keep = [(s, sec) for s, sec in zip(syms, secs) if not config.is_non_equity_symbol(s)]
    keep.sort()
    dropped = sorted(s for s, _ in zip(syms, secs) if config.is_non_equity_symbol(s))
    t = pa.table({"symbol": [k[0] for k in keep], "sector": [k[1] for k in keep]},
                 schema=pa.schema([("symbol", pa.string()), ("sector", pa.string())]))
    return t, dropped


def _build_stock_metadata(sectors_tbl: pa.Table, frozen_meta: pa.Table,
                          bronze_ranges: dict[str, tuple[str, str]]) -> pa.Table:
    """Port of build_stock_metadata.py -- an idempotent UPSERT over the frozen
    stock_metadata, NOT a drop-and-rebuild:

      * every frozen row is preserved (manual / legacy / now-excluded rows are
        never deleted -- build_stock_metadata.py's explicit contract);
      * for symbols in the recomputed include-set (sector not EXCLUDED, + the
        UNIVERSE_WHITELIST, SECTOR_OVERRIDES applied) the source-derived columns
        (sector, company_name, in_kse100, listing_date) are refreshed;
      * is_active / delisting_date / notes are INSERT-only manual-curation
        columns -- kept as the frozen row has them, set only for brand-new rows.
    """
    import config
    sec_map = dict(zip(sectors_tbl.column("symbol").to_pylist(),
                       sectors_tbl.column("sector").to_pylist()))
    frozen_rows = {r["symbol"]: dict(r) for r in frozen_meta.to_pylist()}
    kse100 = {r["symbol"] for r in frozen_meta.to_pylist() if r.get("in_kse100")}

    include: dict[str, str] = {
        s: sec for s, sec in sec_map.items() if sec not in config.EXCLUDED_SECTORS}
    for sym in config.UNIVERSE_WHITELIST:
        if sym in config.SECTOR_OVERRIDES:
            include[sym] = config.SECTOR_OVERRIDES[sym]
    for sym, ov in config.SECTOR_OVERRIDES.items():
        if sym in include:
            include[sym] = ov

    out: dict[str, dict] = {s: dict(r) for s, r in frozen_rows.items()}

    for sym in include:
        rng = bronze_ranges.get(sym)
        fr = frozen_rows.get(sym)
        if fr is None:  # brand-new include-set symbol -> INSERT
            if rng:
                listing_date, last_date = rng
                is_active = 1 if last_date and last_date >= ACTIVE_CUTOFF else 0
                delisting_date = last_date if is_active == 0 else None
            else:
                listing_date = delisting_date = None
                is_active = 0
            out[sym] = {
                "symbol": sym, "company_name": None, "sector": include[sym],
                "listing_date": listing_date, "delisting_date": delisting_date,
                "is_active": is_active, "in_kse100": 1 if sym in kse100 else 0,
                "notes": None,
            }
        else:            # existing row -> refresh source-derived columns only
            row = out[sym]
            row["sector"] = include[sym]
            row["in_kse100"] = 1 if sym in kse100 else 0
            if rng:
                row["listing_date"] = rng[0]

    rows = [out[s] for s in sorted(out)]
    schema = pa.schema([
        ("symbol", pa.string()), ("company_name", pa.string()), ("sector", pa.string()),
        ("listing_date", pa.string()), ("delisting_date", pa.string()),
        ("is_active", pa.int64()), ("in_kse100", pa.int64()), ("notes", pa.string()),
    ])
    return pa.table({k: [r[k] for r in rows] for k in schema.names}, schema=schema)


# ------------------------------------------------------------------ v2 gate

def _load_ca_v2(ca_v2_dir: Path, quiet: bool = True):
    """Import ca_v2_reader from the CA-pipeline directory and return its
    load_v2_prices + provenance. Available-but-not-default (tracker section 9 D5)."""
    if not (ca_v2_dir / "ca_v2_reader.py").exists():
        raise SystemExit(f"--ca-source v2: ca_v2_reader.py not found under {ca_v2_dir}")
    sys.path.insert(0, str(ca_v2_dir))
    import ca_v2_reader  # noqa: E402
    long = ca_v2_reader.load_v2_prices(scope="expanded", field="close_tr", wide=False, quiet=quiet)
    return long, dict(long.attrs.get("ca_v2", {}))


# --------------------------------------------------------------------- build

def build(store_root: Path, ca_source: str = "legacy",
          ca_v2_dir: Path | None = None) -> dict:
    from apply_price_adjustments import compute_circuit_flags

    bronze = store_root / "bronze" / "prices"
    if not bronze.exists():
        raise SystemExit(f"live Bronze not found at {bronze} -- run archive.bronze_ingest first")

    silver = store_root / "silver"
    baseline_db = _baseline_db()

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE pa AS SELECT symbol, date, close, volume, high, low, open "
        f"FROM read_parquet('{(bronze / '**' / '*.parquet').as_posix()}')")
    bronze_rows = con.execute("SELECT count(*) FROM pa").fetchone()[0]
    bmin, bmax = con.execute("SELECT min(date), max(date) FROM pa").fetchone()

    if ca_source not in ("legacy", "v2"):
        raise SystemExit(f"--ca-source must be 'legacy' or 'v2', got {ca_source!r}")

    ca_v2_prov = None
    events = load_legacy_events(baseline_db)
    applied, skipped = _apply_ca(con, events)
    n_events = len(events)
    if ca_source == "v2":
        # v2 total-return series replaces close for the symbols/dates it covers;
        # everything else stays on the legacy-adjusted basis.
        v2_long, ca_v2_prov = _load_ca_v2(ca_v2_dir or (REPO_ROOT.parent /
            "ZH_Research_PSX" / "trading_edge_program" / "ca_pipeline_kse100_20260907"))
        con.register("v2", v2_long.rename(columns={"close_tr": "v2_close"}))
        con.execute("UPDATE pa SET close = v2.v2_close FROM v2 "
                    "WHERE pa.symbol = v2.symbol AND pa.date = v2.date")

    adj = con.execute("SELECT symbol, date, close, volume, high, low, open FROM pa "
                      "ORDER BY symbol, date").fetchdf()
    con.close()

    # universe conforming: non-equity symbols never enter Silver prices_adjusted
    # (config.is_non_equity_symbol -- futures, govt paper, 786/786R). Bronze
    # keeps everything raw; Silver is the conformed layer.
    import config
    non_equity = {s for s in adj["symbol"].unique() if config.is_non_equity_symbol(s)}
    if non_equity:
        adj = adj[~adj["symbol"].isin(non_equity)].reset_index(drop=True)

    flags = compute_circuit_flags(adj)
    for c in ("hit_circuit_up", "hit_circuit_down", "thin_trading_flag"):
        adj[c] = flags[c].astype("int64").values
    adj = adj[PRICES_ADJ_COLUMNS]

    pa_table = pa.Table.from_pandas(adj, schema=PRICES_ADJ_SCHEMA, preserve_index=False)
    pa_files = _write_partitioned(pa_table, silver / "prices_adjusted")

    # universe conforming
    frozen_sectors = pq.read_table(ARCHIVE_ROOT / "silver" / "sectors" / "sectors.parquet")
    frozen_meta = pq.read_table(ARCHIVE_ROOT / "silver" / "stock_metadata" / "stock_metadata.parquet")
    sectors_tbl, dropped_non_equity = _conform_sectors(frozen_sectors)
    _write_single(sectors_tbl, silver / "sectors" / "sectors.parquet")

    ranges: dict[str, tuple[str, str]] = {}
    for sym, lo, hi in _iter_symbol_ranges(bronze):
        ranges[sym] = (lo, hi)
    meta_tbl = _build_stock_metadata(sectors_tbl, frozen_meta, ranges)
    _write_single(meta_tbl, silver / "stock_metadata" / "stock_metadata.parquet")

    parity = _parity_vs_frozen(store_root)

    entry = {
        "ts": _now(), "action": "silver_build", "ca_source": ca_source,
        "bronze_rows": bronze_rows, "bronze_range": [bmin, bmax],
        "baseline_db": baseline_db.name if baseline_db else None,
        "ca_events": n_events, "ca_events_applied": applied, "ca_events_skipped": skipped,
        "prices_adjusted_rows": len(adj),
        "prices_adjusted_files": len(pa_files),
        "circuit_up": int(adj["hit_circuit_up"].sum()),
        "circuit_down": int(adj["hit_circuit_down"].sum()),
        "thin": int(adj["thin_trading_flag"].sum()),
        "sectors_rows": sectors_tbl.num_rows,
        "sectors_dropped_non_equity": dropped_non_equity,
        "stock_metadata_rows": meta_tbl.num_rows,
        "ca_v2_provenance": ca_v2_prov,
        "parity_vs_frozen": parity,
    }
    with open(store_root / "_silver_build_log.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, default=str, sort_keys=True) + "\n")
    (store_root / "_silver_parity.json").write_text(
        json.dumps({"generated": _now(), **parity}, indent=2, default=str) + "\n")

    return {"outcome": "built", **{k: entry[k] for k in
            ("ca_source", "prices_adjusted_rows", "prices_adjusted_files",
             "ca_events", "circuit_up", "circuit_down", "thin",
             "sectors_rows", "stock_metadata_rows")}, "parity_vs_frozen": parity}


def _parity_vs_frozen(store_root: Path) -> dict:
    """Compare the just-built prices_adjusted to the FROZEN silver/prices_adjusted
    over the overlapping date range. A non-zero OHLC residual is expected and is
    a DR-program provenance gap, not a build bug: the frozen prices_adjusted
    carries corporate-action corrections applied via the Data Health page
    (`rebuild_symbol_adjusted`) that leave no recoverable event record in the
    baseline `.db` or `corporate_action_suspects_clean.csv` -- so a pure
    rebuild-from-events cannot reproduce them (see DATA_REHABILITATION_PROGRAM /
    Known_Limitations, and MEDALLION.md). Reported here, decision deferred to the
    owner (carry the frozen delta forward vs. stay rebuild-pure)."""
    frozen = ARCHIVE_ROOT / "silver" / "prices_adjusted"
    new = store_root / "silver" / "prices_adjusted"
    if not frozen.exists() or not new.exists():
        return {"status": "skipped", "reason": "a store is missing"}
    con = duckdb.connect()
    try:
        fg = (frozen / "**" / "*.parquet").as_posix()
        ng = (new / "**" / "*.parquet").as_posix()
        fmax = con.execute(f"SELECT max(date) FROM read_parquet('{fg}')").fetchone()[0]
        row = con.execute(f"""
            WITH f AS (SELECT * FROM read_parquet('{fg}') WHERE date <= '{fmax}'),
                 n AS (SELECT * FROM read_parquet('{ng}') WHERE date <= '{fmax}')
            SELECT
              (SELECT count(*) FROM f) AS frozen_rows,
              (SELECT count(*) FROM (SELECT symbol,date FROM f EXCEPT SELECT symbol,date FROM n)) AS only_frozen,
              (SELECT count(*) FROM (SELECT symbol,date FROM n EXCEPT SELECT symbol,date FROM f)) AS only_new,
              (SELECT count(*) FROM f JOIN n USING(symbol,date)
                 WHERE abs(f.close-n.close)>0.005 OR abs(f.open-n.open)>0.005
                    OR abs(f.high-n.high)>0.005 OR abs(f.low-n.low)>0.005) AS ohlc_diff_rows,
              (SELECT count(*) FROM f JOIN n USING(symbol,date)
                 WHERE f.hit_circuit_up!=n.hit_circuit_up OR f.hit_circuit_down!=n.hit_circuit_down
                    OR f.thin_trading_flag!=n.thin_trading_flag) AS flag_diff_rows
        """).fetchone()
        cols = ["frozen_rows", "only_frozen", "only_new", "ohlc_diff_rows", "flag_diff_rows"]
        res = dict(zip(cols, row))
        res["ohlc_diff_symbols"] = [r[0] for r in con.execute(f"""
            WITH f AS (SELECT * FROM read_parquet('{fg}') WHERE date <= '{fmax}'),
                 n AS (SELECT * FROM read_parquet('{ng}') WHERE date <= '{fmax}')
            SELECT f.symbol FROM f JOIN n USING(symbol,date)
            WHERE abs(f.close-n.close)>0.005 GROUP BY f.symbol ORDER BY count(*) DESC
        """).fetchall()]
        res["overlap_through"] = fmax
        res["status"] = "clean" if res["ohlc_diff_rows"] == 0 and res["only_frozen"] == 0 \
            and res["only_new"] == 0 else "residual"
        return res
    finally:
        con.close()


def _iter_symbol_ranges(bronze_prices: Path):
    con = duckdb.connect()
    try:
        rows = con.execute(
            "SELECT symbol, min(date), max(date) FROM read_parquet("
            f"'{(bronze_prices / '**' / '*.parquet').as_posix()}') GROUP BY symbol").fetchall()
    finally:
        con.close()
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Silver build -- rebuild prices_adjusted + universe from Bronze.")
    ap.add_argument("--store-root", default=str(ARCHIVE_ROOT / "prices_archive"))
    ap.add_argument("--ca-source", default=os.environ.get("KIRAN_SILVER_CA_SOURCE", "legacy"),
                    choices=["legacy", "v2"])
    ap.add_argument("--ca-v2-dir", default=None,
                    help="directory containing ca_v2_reader.py (v2 source only)")
    args = ap.parse_args(argv)

    result = build(Path(args.store_root), ca_source=args.ca_source,
                   ca_v2_dir=Path(args.ca_v2_dir) if args.ca_v2_dir else None)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
