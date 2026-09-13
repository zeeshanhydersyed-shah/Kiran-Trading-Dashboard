r"""
Kiran Local-First Migration -- CA v2 Standalone Prototype (PARKED, not wired into production)

Status: research prototype only. Reads the CA Pipeline's deep-horizon, full-universe
v2 substrate (``full_prices_v2.sqlite`` -- 808 equity symbols, full history back to
2005, 686/808 fully resolved) and runs the existing ``stock_signals``/
``sector_signals`` screeners against it, to prove out "sector grading + stock
grading on properly CA-adjusted prices" ahead of the day this substrate is wired
into production. That wiring is a separate, later step -- the tracker's own Q6 gate
(deferred until after Phase 6 cutover, Trust Register OI-16) -- NOT done here.

Why this exists as a SEPARATE module from ``archive/gold_build.py`` /
``archive/silver_build.py``, not a branch inside them: switching the live Silver
``prices_adjusted`` to CA v2 today would break Phase 5's shadow-diff clean-session
streak -- ``shadow_diff`` compares Gold against live Supabase, which still runs the
legacy (largely unadjusted, per DR-002) CA logic, so every session would show
DISAGREE purely from using better prices, not a bug. This module never touches
Bronze, Silver, Gold, ``psx_serving.duckdb``, ``psx_data.db``, or Supabase -- it is
a fully decoupled, read-only, parked prototype.

Adjustment methodology (verified empirically, not assumed):
  - ``full_prices_v2.sqlite``'s ``prices_v2`` table gives raw OHLCV plus
    ``close_v2`` (split/bonus/rights-adjusted close), ``close_tr`` (also
    dividend-adjusted, total-return), ``volume_v2`` (share-count-adjusted volume),
    and ``cum_price_factor`` / ``cum_tr_factor``. Confirmed ``close_v2 == close *
    cum_price_factor`` exactly (max abs diff 0.0 over a full symbol history).
  - Open/high/low have no adjusted column of their own in the v2 artifact, so this
    module derives them the same way ``apply_price_adjustments.py`` already does
    for the legacy path -- multiply by the same per-row ``cum_price_factor``.
  - Default price field is ``close_v2`` (structural adjustment only), NOT
    ``close_tr``. Screeners here compute pivots / support-resistance / RS off price
    LEVELS a real chart would show; a total-return series synthetically inflates
    historical price levels for cumulative dividends and would distort every pivot
    and resistance level. ``close_tr`` is still selectable (``--price-field
    close_tr``) for a future total-return-style backtest, but is not the charting
    default. Volume defaults to ``volume_v2`` (share-count-adjusted) -- an explicit
    improvement over legacy ``prices_adjusted.volume``, which DR-002 found is never
    adjusted at all.
  - Index prices, ``stock_metadata`` (sector map / universe) and ``sectors`` are
    read from the existing Bronze/Silver archive, read-only -- CA v2 does not cover
    the index or sector reference data, only individual-stock adjustment.

Reuses ``stock_signals.py`` / ``sector_signals.py``'s pure compute cores VERBATIM
by import -- the same "reuse the algorithm, reimplement only the I/O" convention
Task 3.3 established in ``archive/gold_build.py`` -- pointed at a DuckDB
``prices_adjusted`` view built from the v2 SQLite instead of Silver Parquet.

Output store (separate from everything else):
    D:\KIRAN_ARCHIVE\ca_v2_prototype\ca_v2_serving.duckdb
    D:\KIRAN_ARCHIVE\ca_v2_prototype\parquet\<table>.parquet
    D:\KIRAN_ARCHIVE\ca_v2_prototype\_ca_v2_build_log.jsonl

    python -m archive.ca_v2_prototype [--window-days N] [--price-field close_v2|close_tr]

Tracker: docs/KIRAN_LOCAL_FIRST_MIGRATION.md -- "Parallel -- CA v2 Standalone Prototype"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import warnings
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from archive.bronze_ingest import ARCHIVE_ROOT, PARQUET_OPTS, _now

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WINDOW_DAYS = 730

# The CA pipeline's own directory -- a sibling project, not part of psx_pipeline.
# Overridable so tests can point at a synthetic fixture.
CA_V2_DIR = REPO_ROOT.parent / "ZH_Research_PSX" / "trading_edge_program" / "ca_pipeline_kse100_20260907"
CA_V2_DB = CA_V2_DIR / "full_prices_v2.sqlite"

_PRICE_FIELDS = {"close_v2", "close_tr"}


class CaV2Store:
    """Mirrors archive.gold_build.GoldStore's layout, in its own root -- reads the
    SAME Bronze/Silver reference data (read-only), writes to a separate serving
    store so nothing here can collide with psx_serving.duckdb."""

    def __init__(self, root: Path):
        self.root = root
        self.silver = root.parent / "prices_archive" / "silver"
        self.bronze = root.parent / "prices_archive" / "bronze"
        self.db = root / "ca_v2_serving.duckdb"
        self.staging = root / "ca_v2_serving_staging.duckdb"
        self.parquet_dir = root / "parquet"
        self.log_path = root / "_ca_v2_build_log.jsonl"

    def silver_glob(self, name: str) -> str:
        return (self.silver / name / "**" / "*.parquet").as_posix()

    def bronze_glob(self, name: str) -> str:
        return (self.bronze / name / "**" / "*.parquet").as_posix()


def _load_v2_adjusted(v2_db: Path, price_field: str) -> pd.DataFrame:
    """Read-only load of the v2 substrate, deriving adjusted OHLCV.

    ``open_v2``/``high_v2``/``low_v2`` = raw * cum_price_factor (same convention
    apply_price_adjustments.py uses for the legacy path); close = the requested
    price_field (close_v2 or close_tr, already adjusted in the source); volume =
    volume_v2 (share-count-adjusted).
    """
    if not v2_db.exists():
        raise SystemExit(
            f"CA v2 substrate not found at {v2_db} -- build it first "
            "(see ZH_Research_PSX/trading_edge_program/ca_pipeline_kse100_20260907/CA_PIPELINE_PROGRAM.md)")
    if price_field not in _PRICE_FIELDS:
        raise SystemExit(f"--price-field must be one of {sorted(_PRICE_FIELDS)}, got {price_field!r}")

    con = sqlite3.connect(f"file:{v2_db}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(
            f"SELECT symbol, date, open, high, low, volume, {price_field} AS close, "
            "cum_price_factor, volume_v2, status, adjustment_confidence FROM prices_v2",
            con)
    finally:
        con.close()

    for c in ("open", "high", "low"):
        df[c] = df[c] * df["cum_price_factor"]
    df["volume"] = df["volume_v2"].fillna(df["volume"])
    return df[["symbol", "date", "close", "volume", "high", "low", "open",
               "status", "adjustment_confidence"]]


def _ca_v2_medallion_views(gcon: "duckdb.DuckDBPyConnection", store: CaV2Store,
                           v2_db: Path, price_field: str) -> pd.DataFrame:
    """Build the table names stock_signals.py / sector_signals.py expect.

    `prices_adjusted` comes from the v2 substrate (this module's whole reason to
    exist); `index_prices` / `stock_metadata` (conformed) / `sectors` come
    read-only from the existing Bronze/Silver archive -- CA v2 doesn't cover
    either, and this is exactly the reference data the live Gold build already
    trusts, not a fresh assumption made here.
    """
    import config

    v2 = _load_v2_adjusted(v2_db, price_field)
    gcon.register("_v2_df", v2[["symbol", "date", "close", "volume", "high", "low", "open"]])
    gcon.execute("CREATE OR REPLACE TABLE prices_adjusted AS SELECT * FROM _v2_df")
    gcon.unregister("_v2_df")

    gcon.execute(f"CREATE OR REPLACE VIEW index_prices AS "
                f"SELECT * FROM read_parquet('{store.bronze_glob('index_prices')}')")

    _excl = ", ".join("'" + s.replace("'", "''") + "'" for s in sorted(config.EXCLUDED_SECTORS))
    _ne = ", ".join("'" + s.replace("'", "''") + "'" for s in sorted(config.NON_EQUITY_SYMBOLS))
    gcon.execute(
        f"CREATE OR REPLACE TABLE stock_metadata AS "
        f"SELECT * FROM read_parquet('{store.silver_glob('stock_metadata')}') "
        f"WHERE sector NOT IN ({_excl}) AND symbol NOT IN ({_ne}) "
        f"AND NOT regexp_matches(symbol, '^[A-Z0-9]+-C?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]?$') "
        f"AND NOT regexp_matches(symbol, '^P\\d{{2}}[A-Z]{{3}}\\d{{6}}$')")
    gcon.execute(f"CREATE OR REPLACE TABLE sectors AS "
                f"SELECT * FROM read_parquet('{store.silver_glob('sectors')}')")
    return v2


# ---------------------------------------------------------- screener: regime

def build_regime_v2(store: CaV2Store, gcon: "duckdb.DuckDBPyConnection", window_from: str) -> dict:
    """Identical to gold_build.build_regime -- market_regime is computed purely
    from the KSE-100 index (Bronze), which CA v2 does not touch at all. Needed
    here only because sector_signals._compute_and_write_sector_signals_for_date_sqlite
    reads `market_regime` for its composite-score regime context."""
    import pandas as pd
    import regime

    df = gcon.execute(
        f"SELECT date, high, low, close FROM read_parquet('{store.bronze_glob('index_prices')}') "
        "WHERE symbol = 'KSE-100' ORDER BY date"
    ).fetchdf()
    if df.empty:
        raise SystemExit("ca_v2_prototype: no KSE-100 rows in Bronze index_prices")

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
            "range": [sliced["date"].min(), sliced["date"].max()] if len(sliced) else None}


# ---------------------------------------------------- screener: stock_signals

_SS_COLS = [
    "date", "symbol", "rs_score_20", "rs_score_50", "rs_rank", "rs_rank_prev",
    "rank_change", "sector_rs_rank", "base_tightness", "bos_flag", "vol_contraction",
    "avg_vol_10d", "pivot_high", "pivot_distance_pct", "stage2_bull",
    "close_above_ema50", "ema50_slope_pos", "base_duration", "overhead_clear",
    "near_pivot_days", "close_above_ema150", "ema150_slope_pos",
]
_SS_DDL = """CREATE OR REPLACE TABLE stock_signals (
    date TEXT, symbol TEXT, rs_score_20 DOUBLE, rs_score_50 DOUBLE,
    rs_rank INTEGER, rs_rank_prev INTEGER, rank_change INTEGER, sector_rs_rank INTEGER,
    base_tightness DOUBLE, bos_flag INTEGER, vol_contraction DOUBLE, avg_vol_10d DOUBLE,
    pivot_high DOUBLE, pivot_distance_pct DOUBLE, stage2_bull INTEGER,
    close_above_ema50 INTEGER, ema50_slope_pos INTEGER, base_duration INTEGER,
    overhead_clear INTEGER, near_pivot_days INTEGER,
    close_above_ema150 INTEGER, ema150_slope_pos INTEGER)"""
_SS_ARROW_SCHEMA = pa.schema(
    [(c, pa.string()) for c in ("date", "symbol")]
    + [(c, pa.float64()) for c in ("rs_score_20", "rs_score_50", "base_tightness",
                                   "vol_contraction", "avg_vol_10d", "pivot_high",
                                   "pivot_distance_pct")]
    + [(c, pa.int64()) for c in ("rs_rank", "rs_rank_prev", "rank_change",
                                 "sector_rs_rank", "bos_flag", "stage2_bull",
                                 "close_above_ema50", "ema50_slope_pos", "base_duration",
                                 "overhead_clear", "near_pivot_days",
                                 "close_above_ema150", "ema150_slope_pos")]
)
_SS_WARMUP_CAL_DAYS = 180
_SS_LOOKBACK_CAL_DAYS = int(os.environ.get("KIRAN_CA_V2_SS_LOOKBACK_DAYS", "1050"))


def build_stock_signals_v2(store: CaV2Store, gcon: "duckdb.DuckDBPyConnection",
                           window_from: str) -> dict:
    """Same reuse-by-import as gold_build.build_stock_signals, pointed at the v2
    `prices_adjusted` this module builds instead of Silver's."""
    import stock_signals as ss
    import config

    end_date = gcon.execute("SELECT max(date) FROM prices_adjusted "
                            "WHERE symbol IN (SELECT symbol FROM stock_metadata)").fetchone()[0]
    warmup_from = (dt.date.fromisoformat(window_from)
                  - dt.timedelta(days=_SS_WARMUP_CAL_DAYS)).isoformat()
    deep_from = (dt.date.fromisoformat(warmup_from)
                - dt.timedelta(days=_SS_LOOKBACK_CAL_DAYS)).isoformat()

    symbol_sector = {s: sec for s, sec in ss._load_universe(gcon).items()
                     if sec not in config.EXCLUDED_SECTORS
                     and not config.is_non_equity_symbol(s)}
    syms = set(symbol_sector)

    kse_list = ss._load_kse100(gcon, deep_from, end_date)
    kse_date_idx = {row[0]: i for i, row in enumerate(kse_list)}
    stock_prices = ss._load_stock_prices(gcon, syms, deep_from, end_date)
    stock_prices_vol = ss._load_stock_prices_with_volume(gcon, syms, deep_from, end_date)
    pivot_lookup = ss._build_pivot_lookup(stock_prices_vol)

    trading_dates = [row[0] for row in kse_list if warmup_from <= row[0] <= end_date]

    batches: list[tuple] = []
    ss._process_trading_dates(
        None, trading_dates, kse_list, kse_date_idx,
        stock_prices, symbol_sector, {},
        stock_prices_vol=stock_prices_vol, pivot_lookup=pivot_lookup,
        base_duration_seed={}, near_pivot_seed={},
        write_fn=lambda batch: batches.extend(batch),
    )

    served = [row for row in batches if row[0] >= window_from]
    gcon.execute(_SS_DDL)
    if served:
        cols = {c: [row[i] for row in served] for i, c in enumerate(_SS_COLS)}
        tbl = pa.table(cols, schema=_SS_ARROW_SCHEMA)
        gcon.register("_ss_df", tbl)
        gcon.execute(f"INSERT INTO stock_signals SELECT {','.join(_SS_COLS)} FROM _ss_df")
        gcon.unregister("_ss_df")

    dates = sorted({r[0] for r in served})
    return {"rows": len(served), "computed_rows": len(batches),
            "deep_from": deep_from, "warmup_from": warmup_from,
            "window_from": window_from, "end_date": end_date,
            "dates": len(dates), "symbols": len({r[1] for r in served}),
            "range": [dates[0], dates[-1]] if dates else None}


# ---------------------------------------------------- screener: sector_signals

_SECTOR_SIGNALS_DDL = """CREATE OR REPLACE TABLE sector_signals (
    date TEXT, sector TEXT, rs_score_20 DOUBLE, rs_score_50 DOUBLE,
    rs_rank DOUBLE, rs_rank_prev DOUBLE, breadth_score DOUBLE,
    adv_dec_ratio DOUBLE, vol_ratio DOUBLE, rs_inflection DOUBLE,
    regime TEXT, composite_score DOUBLE,
    flow_smart_net_5d DOUBLE, flow_smart_net_20d DOUBLE,
    flow_retail_net_5d DOUBLE, flow_retail_net_20d DOUBLE, flow_direction TEXT,
    sector_ema50 DOUBLE, sector_above_ema DOUBLE, sector_ema_slope DOUBLE,
    sector_stage TEXT, sector_pivot_dist_pct DOUBLE, sector_rs_new_high DOUBLE,
    PRIMARY KEY (date, sector))"""
_SEC_WARMUP_CAL_DAYS = 100


def build_sector_signals_v2(store: CaV2Store, gcon: "duckdb.DuckDBPyConnection",
                            window_from: str) -> dict:
    """Same reuse-by-import as gold_build.build_sector_signals (four-stage
    sector_stage grade included), pointed at the v2 `prices_adjusted`."""
    import sector_signals as sig

    gcon.execute(_SECTOR_SIGNALS_DDL)
    gcon.execute(
        "CREATE OR REPLACE TABLE active_stocks_on_date AS "
        "SELECT pa.symbol AS symbol, pa.date AS trading_date "
        "FROM prices_adjusted pa JOIN stock_metadata sm ON sm.symbol = pa.symbol "
        "WHERE pa.close IS NOT NULL AND pa.close > 0")
    # market_market_cap isn't part of the v2 substrate or this prototype's scope
    # (weights would come from the same frozen baseline Gold uses -- deliberately
    # left NULL here rather than silently reusing another store's snapshot).
    gcon.execute("CREATE OR REPLACE TABLE stock_market_cap "
                "(symbol TEXT, shares_m DOUBLE, market_cap_m DOUBLE, cap_date TEXT)")

    end_date = gcon.execute("SELECT max(date) FROM prices_adjusted").fetchone()[0]
    warmup_from = (dt.date.fromisoformat(window_from)
                  - dt.timedelta(days=_SEC_WARMUP_CAL_DAYS)).isoformat()
    trading_dates = [r[0] for r in gcon.execute(
        "SELECT DISTINCT date FROM prices_adjusted WHERE date >= ? AND date <= ? ORDER BY date",
        (warmup_from, end_date)).fetchall()]

    written = 0
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
        for d in trading_dates:
            written += sig._compute_and_write_sector_signals_for_date_sqlite(gcon, d)

    gcon.execute("DELETE FROM sector_signals WHERE date < ?", (window_from,))
    n = gcon.execute("SELECT count(*) FROM sector_signals").fetchone()[0]
    drange = gcon.execute("SELECT min(date), max(date), "
                          "count(DISTINCT date), count(DISTINCT sector) FROM sector_signals").fetchone()
    stages = {(k if k is not None else "None"): v for k, v in gcon.execute(
        "SELECT sector_stage, count(*) FROM sector_signals GROUP BY sector_stage").fetchall()}
    return {"rows": n, "computed_rows": written, "warmup_from": warmup_from,
            "window_from": window_from, "end_date": end_date,
            "range": [drange[0], drange[1]], "dates": drange[2], "sectors": drange[3],
            "stage_counts": stages}


# --------------------------------------------------------------------- build

def build(store_root: Path, window_days: int = DEFAULT_WINDOW_DAYS,
         price_field: str = "close_v2", v2_db: Path | None = None) -> dict:
    store = CaV2Store(store_root)
    store.root.mkdir(parents=True, exist_ok=True)
    v2_path = v2_db or CA_V2_DB

    gcon = duckdb.connect()
    v2 = _ca_v2_medallion_views(gcon, store, v2_path, price_field)

    end_date = gcon.execute("SELECT max(date) FROM prices_adjusted").fetchone()[0]
    window_from = (dt.date.fromisoformat(end_date) - dt.timedelta(days=window_days)).isoformat()

    active = {}
    active["market_regime"] = build_regime_v2(store, gcon, window_from)
    active["stock_signals"] = build_stock_signals_v2(store, gcon, window_from)
    active["sector_signals"] = build_sector_signals_v2(store, gcon, window_from)

    _ORDER_BY = {"market_regime": "date", "stock_signals": "date, symbol",
                "sector_signals": "date, sector"}
    store.parquet_dir.mkdir(parents=True, exist_ok=True)
    for table, order in _ORDER_BY.items():
        df = gcon.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchdf()
        tmp = store.parquet_dir / f"{table}.parquet.tmp"
        fp = store.parquet_dir / f"{table}.parquet"
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), tmp, **PARQUET_OPTS)
        os.replace(tmp, fp)

    tmp_db = store.staging
    if tmp_db.exists():
        tmp_db.unlink()
    gcon.execute(f"ATTACH '{tmp_db.as_posix()}' AS out")
    for table in _ORDER_BY:
        gcon.execute(f"CREATE OR REPLACE TABLE out.{table} AS SELECT * FROM {table}")
    gcon.execute("DETACH out")
    gcon.close()
    os.replace(tmp_db, store.db)

    confidence_counts = v2[["status", "adjustment_confidence"]].value_counts().to_dict()
    result = {
        "outcome": "built", "run_at": _now(), "price_field": price_field,
        "v2_db": str(v2_path), "window_from": window_from, "end_date": end_date,
        "v2_symbols": int(v2["symbol"].nunique()),
        "v2_date_range": [str(v2["date"].min()), str(v2["date"].max())],
        "v2_confidence_counts": {str(k): int(v) for k, v in confidence_counts.items()},
        "screeners": active,
    }
    store.log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(store.log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, default=str) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--store-root", type=Path,
                    default=ARCHIVE_ROOT / "ca_v2_prototype")
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    ap.add_argument("--price-field", choices=sorted(_PRICE_FIELDS), default="close_v2")
    args = ap.parse_args(argv)

    result = build(args.store_root, window_days=args.window_days, price_field=args.price_field)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
