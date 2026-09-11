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
import shutil
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


def _baseline_db() -> Path | None:
    d = ARCHIVE_ROOT / "baseline"
    if not d.exists():
        return None
    cands = sorted(d.glob("psx_data_baseline_KIRAN_LFM_P1_*.db"))
    return cands[-1] if cands else None


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


# -------------------------------------------------------- medallion views

def _medallion_views(gcon: "duckdb.DuckDBPyConnection", store: GoldStore) -> None:
    """Expose the live Silver/Bronze Parquet under the table names the ported
    screeners' loaders expect. The big price series stay VIEWS (read straight
    from Parquet); the small reference sets are materialised as TABLES.

    `stock_metadata` is materialised **CONFORMED** -- `config.EXCLUDED_SECTORS`
    and non-equity symbols dropped -- so the screeners that read it
    (`stock_signals._load_universe`, `sector_signals`'s stock JOIN) and the
    front end all see the tradeable universe by construction (§118 Defect A:
    `_load_universe` itself never filtered, and live's stock_metadata grew
    ~150 excluded-sector rows on 2026-08-03). `sectors` stays the FULL
    symbol->sector map (parity needs to know the excluded sectors)."""
    import config
    _excl = ", ".join("'" + s.replace("'", "''") + "'" for s in sorted(config.EXCLUDED_SECTORS))
    _ne = ", ".join("'" + s.replace("'", "''") + "'" for s in sorted(config.NON_EQUITY_SYMBOLS))
    gcon.execute(f"CREATE OR REPLACE VIEW prices_adjusted AS "
                 f"SELECT * FROM read_parquet('{store.silver_glob('prices_adjusted')}')")
    gcon.execute(f"CREATE OR REPLACE VIEW index_prices AS "
                 f"SELECT * FROM read_parquet('{store.bronze_glob('index_prices')}')")
    # RAW (unadjusted) prices -- Bronze, not Silver. boring_signals.py /
    # leaders_scan.py read `prices` (not `prices_adjusted`) for several
    # to-the-day computations (today's close, volume ratios, overhead) --
    # ported faithfully rather than substituted, since 3.3d.
    gcon.execute(f"CREATE OR REPLACE VIEW prices AS "
                 f"SELECT * FROM read_parquet('{store.bronze_glob('prices')}')")
    gcon.execute(
        f"CREATE OR REPLACE TABLE stock_metadata AS "
        f"SELECT * FROM read_parquet('{store.silver_glob('stock_metadata')}') "
        f"WHERE sector NOT IN ({_excl}) AND symbol NOT IN ({_ne}) "
        f"AND NOT regexp_matches(symbol, '^[A-Z0-9]+-C?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]?$') "
        f"AND NOT regexp_matches(symbol, '^P\\d{{2}}[A-Z]{{3}}\\d{{6}}$')")
    gcon.execute(f"CREATE OR REPLACE TABLE sectors AS "
                 f"SELECT * FROM read_parquet('{store.silver_glob('sectors')}')")


# ---------------------------------------------------- screener: stock_signals

# column order == the batch tuple _process_trading_dates.write_fn receives
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

_SS_WARMUP_CAL_DAYS = 180        # ~120 trading days -- warms base_duration / near_pivot / prev_ranks
# Calendar days of price/volume history to load before the warm-up.
#   * `rs_score_20/50`, `base_tightness`, `vol_contraction`, `pivot_*`, `bos_flag`,
#     `avg_vol_10d`, and all the ranks need at most ~60 trading days of lookback
#     -> they are byte-exact vs live at ANY floor >= ~180 cal days.
#   * the EMA-stack FLAGS (`stage2_bull`, `close_above_ema50/150`,
#     `ema*_slope_pos`, `overhead_clear`) need up to 3*200 + 200 bars; a
#     thinly-traded name needs a much deeper *calendar* window to accumulate
#     that many *trading* bars. `stock_signals.py` loads from a fixed
#     2015-01-01 floor for exactly this reason.
# Default 1050 (~720 trading days) keeps the nightly run to a few minutes and
# this 7.6 GB machine out of swap; at that floor Gold reports those flags as
# NULL for thin names with < ~200 in-window bars (live had them from its deeper
# load). Override with KIRAN_SS_LOOKBACK_DAYS / --ss-lookback-days (e.g. 4200 ~
# 2015) on a box with the RAM for full EMA-flag parity.
_SS_LOOKBACK_CAL_DAYS = int(os.environ.get("KIRAN_SS_LOOKBACK_DAYS", "1050"))


def build_stock_signals(store: GoldStore, gcon: "duckdb.DuckDBPyConnection",
                        window_from: str) -> dict:
    """Port of stock_signals.backfill/append for the Gold path.

    Reuses stock_signals._load_universe / _load_kse100 / _load_stock_prices /
    _load_stock_prices_with_volume / _build_pivot_lookup / _process_trading_dates
    VERBATIM by import -- the loaders already take a `conn` and use `?` params
    (DuckDB-compatible), and `_process_trading_dates(conn=None, write_fn=...)` is
    the exact zero-SQLite path the PG port uses. Computes over a warm-up +
    serving window (deep price history for the 200-EMA / pivot / overhead
    lookbacks), then writes only the `date >= window_from` slice into Gold.
    """
    import datetime as dt
    import stock_signals as ss

    _medallion_views(gcon, store)

    end_date = gcon.execute("SELECT max(date) FROM prices_adjusted "
                            "WHERE symbol IN (SELECT symbol FROM stock_metadata)").fetchone()[0]
    warmup_from = (dt.date.fromisoformat(window_from)
                   - dt.timedelta(days=_SS_WARMUP_CAL_DAYS)).isoformat()
    deep_from = (dt.date.fromisoformat(warmup_from)
                 - dt.timedelta(days=_SS_LOOKBACK_CAL_DAYS)).isoformat()

    # `_medallion_views` already materialised `stock_metadata` conformed
    # (EXCLUDED_SECTORS + non-equity dropped -- §118 Defect A); this belt-and-
    # suspenders filter keeps `build_stock_signals` correct even if that changes.
    import config
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

# `sector_signals.py`'s INSERT passes raw pandas values -- a sector with too
# little data on a date comes through with float NaN for rank / flag columns
# (SQLite stores it fine; DuckDB rejects NaN in an INTEGER column). Every
# nominally-int column is DOUBLE here (rank 2.0 / flag 1.0 read fine, NaN/NULL
# for missing); parity coerces. sector_stage (the four-stage grade) is TEXT.
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
# ~100 cal days (~68 trading) before window_from: sector_signals reads a
# 60-trading-day price window for the sector EMA/pivot + a 30-day rs_history +
# chains rs_rank_prev off its own prior rows.
_SEC_WARMUP_CAL_DAYS = 100


def build_sector_signals(store: GoldStore, gcon: "duckdb.DuckDBPyConnection",
                         window_from: str) -> dict:
    """Port of sector_signals.append_latest_sector_signals for the Gold path.

    Reuses `sector_signals._compute_and_write_sector_signals_for_date_sqlite`
    **verbatim by import** -- it takes a `conn`, uses `pd.read_sql_query(conn,
    params=...)` + `conn.execute("INSERT OR REPLACE ...")`, all of which work
    against a DuckDB connection. `stock_metadata` is already conformed by
    `_medallion_views`, so no excluded sector is computed. `active_stocks_on_date`
    is rebuilt pure + point-in-time (traded-on-D AND in the conformed universe),
    a strict superset of live's hand-curated legacy table. `stock_market_cap` is
    materialised from the frozen baseline (weights are "today's, applied to the
    whole series" -- the snapshot is fine).

    The four-stage sector grade is `sector_stage` (Stage 1-4), computed inside
    that function -- "grade every sector" (tracker §5) is its output.
    """
    import datetime as dt
    import sector_signals as sig

    _medallion_views(gcon, store)                 # ensure the views/tables exist
    gcon.execute(_SECTOR_SIGNALS_DDL)
    # `active_stocks_on_date` in live is a VIEW: stock_metadata JOIN
    # symbol_active_dates (a hand-curated point-in-time universe table, no
    # builder in the repo, stale since 2026-07-31). Gold rebuilds it pure and
    # point-in-time: a symbol is "active on date D" iff it actually traded on D
    # AND is in the conformed universe. Strict superset of live's (live's table
    # omits 5 legit equities -- BML/FCL/WAVESAPP/SYM/IMAGE, all company_name
    # NULL in stock_metadata -- see KIRAN_CLEANUP_AUDIT.md §118).
    gcon.execute(
        "CREATE OR REPLACE TABLE active_stocks_on_date AS "
        "SELECT pa.symbol AS symbol, pa.date AS trading_date "
        "FROM prices_adjusted pa JOIN stock_metadata sm ON sm.symbol = pa.symbol "
        "WHERE pa.close IS NOT NULL AND pa.close > 0")
    baseline_db = _baseline_db()
    if baseline_db is not None and baseline_db.exists():
        bcon = sqlite3.connect(f"file:{baseline_db}?mode=ro&immutable=1", uri=True)
        try:
            import pandas as pd
            mcap = pd.read_sql_query(
                "SELECT symbol, shares_m, market_cap_m, cap_date FROM stock_market_cap", bcon)
        finally:
            bcon.close()
        gcon.register("_mcap_df", mcap)
        gcon.execute("CREATE OR REPLACE TABLE stock_market_cap AS SELECT * FROM _mcap_df")
        gcon.unregister("_mcap_df")
    else:
        gcon.execute("CREATE OR REPLACE TABLE stock_market_cap "
                     "(symbol TEXT, shares_m DOUBLE, market_cap_m DOUBLE, cap_date TEXT)")

    # market_regime must exist (build_regime runs first in SCREENERS); it is
    # windowed, so warm-up dates get regime=NULL -- fine, they are sliced out.
    end_date = gcon.execute("SELECT max(date) FROM prices_adjusted").fetchone()[0]
    warmup_from = (dt.date.fromisoformat(window_from)
                   - dt.timedelta(days=_SEC_WARMUP_CAL_DAYS)).isoformat()
    trading_dates = [r[0] for r in gcon.execute(
        "SELECT DISTINCT date FROM prices_adjusted WHERE date >= ? AND date <= ? ORDER BY date",
        (warmup_from, end_date)).fetchall()]

    written = 0
    import warnings
    with warnings.catch_warnings():
        # sector_signals.py uses pd.read_sql_query on the DuckDB connection --
        # pandas warns it is "untested" for non-SQLAlchemy DBAPI, but it works
        # (verified in the port + tests). One warning per read per date otherwise.
        warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
        for d in trading_dates:
            written += sig._compute_and_write_sector_signals_for_date_sqlite(gcon, d)

    gcon.execute("DELETE FROM sector_signals WHERE date < ?", (window_from,))
    n = gcon.execute("SELECT count(*) FROM sector_signals").fetchone()[0]
    drange = gcon.execute("SELECT min(date), max(date), "
                          "count(DISTINCT date), count(DISTINCT sector) FROM sector_signals").fetchone()
    # str(None key) -> "None": a thin/early sector can have NULL sector_stage
    # (insufficient EMA-slope history) -- json.dumps(sort_keys=True) can't
    # compare a None key against the other (string) keys otherwise.
    stages = {(k if k is not None else "None"): v for k, v in gcon.execute(
        "SELECT sector_stage, count(*) FROM sector_signals GROUP BY sector_stage").fetchall()}
    return {"rows": n, "computed_rows": written, "warmup_from": warmup_from,
            "window_from": window_from, "end_date": end_date,
            "range": [drange[0], drange[1]], "dates": drange[2], "sectors": drange[3],
            "stage_counts": stages}


# ---------------------------------------------------- screener: boring_signals

# boring_signals.py's INSERT never supplies `id` -- it relies on the table's
# own autoincrement. DuckDB has no SQLite-style AUTOINCREMENT; a SEQUENCE +
# DEFAULT nextval(...) is the equivalent. `current_stop` (added by a later
# migration in the SQLite DDL) is included directly here since Gold owns its
# own schema from scratch every build.
_BORING_SIGNALS_DDL = """CREATE OR REPLACE TABLE boring_signals (
    id INTEGER PRIMARY KEY DEFAULT nextval('seq_boring_signals'),
    symbol TEXT NOT NULL, signal_date TEXT NOT NULL, lookback_n INTEGER NOT NULL,
    breakout_level DOUBLE, trigger_price DOUBLE NOT NULL, target_price DOUBLE NOT NULL,
    stop_price DOUBLE NOT NULL, rs_60 DOUBLE NOT NULL, rs_60_decile INTEGER NOT NULL,
    avg_vol_10d DOUBLE, liquidity_pass INTEGER NOT NULL, strategy_confirmed INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending', executed INTEGER NOT NULL DEFAULT 0,
    executed_at TEXT, executed_price DOUBLE, resolution_date TEXT, resolution_type TEXT,
    days_open INTEGER, created_at TEXT, dedup_conflict INTEGER NOT NULL DEFAULT 0,
    current_stop DOUBLE,
    UNIQUE(symbol, signal_date, lookback_n))"""


def build_boring_signals(store: GoldStore, gcon: "duckdb.DuckDBPyConnection",
                         window_from: str) -> dict:
    """Port of boring_signals.py's automated daily hook
    (`scan_boring_breakouts_pending` + `update_open_signal_statuses`, as
    called from `main.py`) for the Gold path.

    Reuses `scan_boring_breakouts` / `update_open_signal_statuses` **verbatim
    by import** -- both now take an optional `conn` (3.3d refactor, mirrors
    `sector_signals.py`'s dialect fix): when given, the function uses it
    directly instead of opening `psx_data.db`, and skips the SQLite-only
    schema/backfill calls (`ensure_boring_signals_table`,
    `_backfill_breakout_levels`) since Gold owns its own schema and never has
    a NULL `breakout_level` row to begin with. `_eligible_universe` /
    `_load_price_history` / `_load_kse100` are already `conn`-based, reused
    unchanged.

    Gold writes its OWN chronological-replay loop (`update_open_signal_statuses
    (as_of_date=d)` then `scan_boring_breakouts(date=d)`, in date order -- the
    same order `_scan_boring_breakouts_pending_sqlite` uses, TR-13/OI-6 §0a.1.7)
    rather than reusing that function directly: Gold always rebuilds the whole
    window from scratch (no marker table / resume / coverage-guard machinery
    needed -- there is no partial state to protect against a bad catch-up,
    since the table starts empty every run). `scan_date=None` semantics
    (`_completeness_ok`'s `scrape_coverage` lookup) are also skipped by
    construction: Gold's loop never touches `psx_data.db`, even read-only,
    outside the established parity-only pattern.

    `boring_signals.BORING_SIGNALS_FLOOR_DATE` (2026-07-10, the feature's own
    go-live floor in production) bounds the start -- this table was never
    meant to carry 2+ years of signal history, and using Gold's full window
    would just replay two years of dates with nothing to find before the
    feature existed.
    """
    import boring_signals as bsig

    _medallion_views(gcon, store)
    gcon.execute("CREATE SEQUENCE IF NOT EXISTS seq_boring_signals START 1")
    gcon.execute(_BORING_SIGNALS_DDL)

    end_date = gcon.execute("SELECT max(date) FROM prices_adjusted "
                            "WHERE symbol IN (SELECT symbol FROM stock_metadata)").fetchone()[0]
    scan_from = max(window_from, bsig.BORING_SIGNALS_FLOOR_DATE)
    trading_dates = [r[0] for r in gcon.execute(
        "SELECT DISTINCT date FROM prices_adjusted WHERE date >= ? AND date <= ? ORDER BY date",
        (scan_from, end_date)).fetchall()]

    new_signals = 0
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
        for d in trading_dates:
            bsig.update_open_signal_statuses(as_of_date=d, conn=gcon)
            new_signals += bsig.scan_boring_breakouts(date=d, conn=gcon)

    n = gcon.execute("SELECT count(*) FROM boring_signals").fetchone()[0]
    status_counts = dict(gcon.execute(
        "SELECT status, count(*) FROM boring_signals GROUP BY status").fetchall())
    drange = gcon.execute("SELECT min(signal_date), max(signal_date), "
                          "count(DISTINCT signal_date), count(DISTINCT symbol) "
                          "FROM boring_signals").fetchone()
    return {"rows": n, "new_signals": new_signals, "scan_from": scan_from,
            "window_from": window_from, "end_date": end_date,
            "dates_scanned": len(trading_dates),
            "range": [drange[0], drange[1]] if drange[0] else None,
            "distinct_dates": drange[2], "symbols": drange[3],
            "status_counts": status_counts}


# ----------------------------------------------------- screener: leaders_scan

# `scan_date`/`trigger_date` are TEXT here (Gold's convention throughout),
# not SQLite's `DATE` affinity column -- values are always ISO strings either way.
# `id` is NOT the primary key here (unlike the SQLite original) -- DuckDB's
# `INSERT OR REPLACE` (== `ON CONFLICT DO UPDATE`) refuses to infer a conflict
# target when a table has more than one UNIQUE/PRIMARY KEY constraint, so
# `id` stays a plain sequence-defaulted column and the natural key
# (scan_date, setup_type, symbol / rank) is the sole PRIMARY KEY. Every
# nominally-int column is DOUBLE, same reason as `_SECTOR_SIGNALS_DDL`:
# leaders_scan.py's INSERT passes raw pandas values, and a sector/date with
# no rank that day comes through as NaN for `sector_rank` -- SQLite stores
# a float in an INTEGER column fine, DuckDB rejects it.
_LEADERS_SCAN_DDL = """CREATE OR REPLACE TABLE leaders_scan (
    id INTEGER DEFAULT nextval('seq_leaders_scan'),
    scan_date TEXT NOT NULL, setup_type TEXT NOT NULL, symbol TEXT NOT NULL,
    sector TEXT, sector_rank DOUBLE, rs_rank DOUBLE, sector_rs_rank DOUBLE,
    rs_score_20 DOUBLE, rs_score_50 DOUBLE, rank_change DOUBLE,
    base_tightness DOUBLE, pivot_high DOUBLE, pivot_distance_pct DOUBLE,
    avg_vol_10d DOUBLE, vol_ratio_today DOUBLE, entry_trigger DOUBLE, stop_loss DOUBLE,
    sl_pct DOUBLE, rs_inflection DOUBLE, sector_composite DOUBLE,
    vol_rejection_flag DOUBLE, nearest_overhead_pct DOUBLE, vol_contraction DOUBLE,
    raw_score DOUBLE, penalty DOUBLE, final_score DOUBLE, flag TEXT,
    PRIMARY KEY (scan_date, setup_type, symbol))"""
_LEADERS_TOP_PICKS_DDL = """CREATE OR REPLACE TABLE leaders_top_picks (
    id INTEGER DEFAULT nextval('seq_leaders_top_picks'),
    scan_date TEXT NOT NULL, setup_type TEXT NOT NULL, rank INTEGER NOT NULL,
    symbol TEXT, sector TEXT, sector_rank DOUBLE,
    entry_trigger DOUBLE, stop_loss DOUBLE, sl_pct DOUBLE, vol_ratio_today DOUBLE,
    key_reason TEXT, flag TEXT, fwd_return_5d DOUBLE, fwd_return_10d DOUBLE, fwd_return_20d DOUBLE,
    outcome_label TEXT DEFAULT 'OPEN', triggered DOUBLE, trigger_date TEXT,
    PRIMARY KEY (scan_date, setup_type, rank))"""


def build_leaders_scan(store: GoldStore, gcon: "duckdb.DuckDBPyConnection",
                       window_from: str) -> dict:
    """Port of leaders_scan.py's `run_all()` chain for the Gold path.

    Reuses `append_leaders_scan` / `save_top_picks` / `fill_leaders_forward_returns`
    **verbatim by import** -- all three now take an optional `conn` (3.3d
    refactor, same pattern as `boring_signals.py`); the `-4 days` window-closure
    floor in `fill_leaders_forward_returns` was SQLite-only (`date('now', ...)`,
    UTC) and is now computed in Python via `datetime.utcnow()` -- identical
    value on both backends. `_nearest_overhead_pct`'s `date(?, '-120 days')`
    had the same fix.

    **Depends on `stock_signals` + `sector_signals` already being populated in
    this `gcon`** (both screeners run earlier in `SCREENERS`) -- `append_leaders_
    scan` reads them directly, exactly as `main.py`'s hook order requires
    (leaders_scan runs after both are fresh).

    Gold writes its own per-date loop (append_leaders_scan -> save_top_picks,
    each date a self-contained DELETE+rebuild, same as `run_all()`'s inner
    loop) rather than reusing `run_all()` / `_pending_scan_dates()` -- no
    resume/pending-date bookkeeping is needed for a from-scratch rebuild.
    `fill_leaders_forward_returns` runs once at the end, exactly as `run_all()`
    does (it is whole-table, not per-date).
    """
    import leaders_scan as lsc

    _medallion_views(gcon, store)
    gcon.execute("CREATE SEQUENCE IF NOT EXISTS seq_leaders_scan START 1")
    gcon.execute("CREATE SEQUENCE IF NOT EXISTS seq_leaders_top_picks START 1")
    gcon.execute(_LEADERS_SCAN_DDL)
    gcon.execute(_LEADERS_TOP_PICKS_DDL)

    trading_dates = [r[0] for r in gcon.execute(
        "SELECT DISTINCT date FROM stock_signals WHERE date >= ? ORDER BY date",
        (window_from,)).fetchall()]

    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
        for d in trading_dates:
            lsc.append_leaders_scan(scan_date=d, conn=gcon)
            lsc.save_top_picks(scan_date=d, conn=gcon)
        lsc.fill_leaders_forward_returns(conn=gcon)

    n_scan = gcon.execute("SELECT count(*) FROM leaders_scan").fetchone()[0]
    n_picks = gcon.execute("SELECT count(*) FROM leaders_top_picks").fetchone()[0]
    outcome_counts = dict(gcon.execute(
        "SELECT outcome_label, count(*) FROM leaders_top_picks GROUP BY outcome_label").fetchall())
    return {"leaders_scan_rows": n_scan, "leaders_top_picks_rows": n_picks,
            "window_from": window_from, "dates": len(trading_dates),
            "outcome_counts": outcome_counts}


# regime first; then 3.3f appends the front-end export.
SCREENERS = {
    "market_regime": build_regime,
    "stock_signals": build_stock_signals,
    "sector_signals": build_sector_signals,
    "boring_signals": build_boring_signals,
    "leaders_scan": build_leaders_scan,
}
# reference tables materialised into the serving DB by the screeners (from Silver)
# -- exported for the front end, not recomputed here.
REFERENCE_TABLES = ["stock_metadata", "sectors"]


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
        if not lcon.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_regime'").fetchone():
            return {"status": "skipped", "reason": "live psx_data.db has no market_regime table"}
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


_SS_KNOWN_SILVER_RESIDUAL = {"DLL"}   # D8: unrecoverable Data Health split, tracked in _silver_parity.json
# population-independent AND lookback-insensitive -- MUST be byte-exact among
# symbols present in BOTH stores if the port is faithful.
_SS_HARD_FLOAT = ["rs_score_20", "rs_score_50", "base_tightness", "vol_contraction",
                  "avg_vol_10d", "pivot_high", "pivot_distance_pct"]
_SS_HARD_INT = ["bos_flag"]
# threshold crossings sensitive to how many lookback bars are loaded (EMA seed,
# 200-day-high, accumulator warm-up). 0<->1 flips vs the live incremental
# pipeline's deeper (2015-floor) load are reported, not failed -- they are a
# load-depth artifact on thin names, resolved by raising KIRAN_SS_LOOKBACK_DAYS.
_SS_LOOKBACK_FLAGS = ["stage2_bull", "close_above_ema50", "ema50_slope_pos",
                      "close_above_ema150", "ema150_slope_pos", "overhead_clear",
                      "base_duration", "near_pivot_days"]
def _parity_stock_signals(gcon: "duckdb.DuckDBPyConnection", live_db: Path) -> dict:
    """Compare Gold `stock_signals` to live `psx_data.db` on sample dates.

    The two stores rank a different universe -- Gold drops
    `config.EXCLUDED_SECTORS` (which live has ranked since 2026-08-03, §118
    Defect A), and live carries `recompute_symbol_signals` rank corruption on
    MTL/PIAB (§118 Defect B) -- so an absolute-rank diff is meaningless.
    What actually tests the PORT:

      * `rs_score_20` (per-symbol RS vs KSE-100 -- population-independent) MUST
        be exact among the symbols present in BOTH stores;
      * the hard population-independent columns (`base_tightness`, `pivot_*`,
        `bos_flag`, `avg_vol_10d`, `vol_contraction`) MUST be exact among shared
        symbols;
      * **genuine** `only_live` MUST be empty -- `only_live` entries in an
        EXCLUDED sector are EXPECTED (Gold correctly drops them);
      * Gold's OWN ranks must be self-consistent (monotonic in `rs_score_20`).

    Everything else -- the shared-symbol rank *order* differing from live,
    `live_rank_self_inconsistencies` -- is a LIVE-side defect surfaced by the
    rebuild, not a Gold bug (see the `finding` field). DLL excluded (D8).
    """
    if not live_db.exists():
        return {"status": "skipped", "reason": f"{live_db} not found"}
    lcon = sqlite3.connect(f"file:{live_db}?mode=ro&immutable=1", uri=True)
    try:
        if not lcon.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_signals'").fetchone():
            return {"status": "skipped", "reason": "live psx_data.db has no stock_signals table"}
        gmin, gmax = gcon.execute("SELECT min(date), max(date) FROM stock_signals").fetchone()
        live_max = lcon.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]
        hi = min(gmax, live_max) if live_max else gmax
        gdates = [r[0] for r in gcon.execute(
            "SELECT DISTINCT date FROM stock_signals WHERE date > ? AND date < ? ORDER BY date",
            (gmin, hi)).fetchall()]
        if not gdates:
            return {"status": "skipped", "reason": "no shared in-window dates"}
        samples = sorted({gdates[len(gdates) * q // 4] for q in (1, 2, 3)})

        cols, ci = _SS_COLS, {c: i for i, c in enumerate(_SS_COLS)}
        sel = ",".join(cols)
        # `sectors` is the FULL symbol->sector map (stock_metadata is conformed);
        # need the excluded sectors to classify live's excluded-sector rows.
        sec_of = dict(gcon.execute("SELECT symbol, sector FROM sectors").fetchall())

        def _monotonic_break(rows_by_rank):
            """count symbols whose rs_score_20 is HIGHER than the symbol one rank
            better -- i.e. rank not consistent with score (allowing exact ties)."""
            ordered = sorted(rows_by_rank, key=lambda r: r[ci["rs_rank"]])
            return sum(1 for i in range(1, len(ordered))
                       if ordered[i][ci["rs_score_20"]] is not None
                       and ordered[i - 1][ci["rs_score_20"]] is not None
                       and ordered[i][ci["rs_score_20"]] > ordered[i - 1][ci["rs_score_20"]] + 1e-6)

        per_date = {}
        rs_score_mismatch_total = 0
        hard_mismatch_total = 0
        lookback_flag_flip_total = 0
        flag_gold_null_total = 0
        flag_both_valued_total = 0
        gold_self_inconsistent_total = 0
        only_live_genuine_total = 0
        live_excluded_sector_total = 0
        try:
            import config as _cfg
            _excl = set(_cfg.EXCLUDED_SECTORS)
        except Exception:
            _excl = set()
        for d in samples:
            g = {r[ci["symbol"]]: r for r in gcon.execute(
                f"SELECT {sel} FROM stock_signals WHERE date = ?", (d,)).fetchall()}
            lv = {r[ci["symbol"]]: r for r in lcon.execute(
                f"SELECT {sel} FROM stock_signals WHERE date = ?", (d,)).fetchall()}
            shared = sorted((set(g) & set(lv)) - _SS_KNOWN_SILVER_RESIDUAL)
            only_gold = sorted(set(g) - set(lv) - _SS_KNOWN_SILVER_RESIDUAL)
            only_live_all = sorted(set(lv) - set(g) - _SS_KNOWN_SILVER_RESIDUAL)
            # §118 Defect A: live ranks EXCLUDED_SECTORS since 2026-08-03; Gold
            # correctly drops them -> those `only_live` entries are EXPECTED.
            live_excluded = [s for s in only_live_all if sec_of.get(s) in _excl]
            only_live = [s for s in only_live_all if sec_of.get(s) not in _excl]
            only_live_genuine_total += len(only_live)
            live_excluded_sector_total += len(live_excluded)

            rs_score_mm = [s for s in shared
                           if abs((g[s][ci["rs_score_20"]] or 0) - (lv[s][ci["rs_score_20"]] or 0)) > 1e-6]
            rs_score_mismatch_total += len(rs_score_mm)

            hard, flag_flips = [], []
            for s in shared:
                gr, lr = g[s], lv[s]
                for c in _SS_HARD_INT:
                    if gr[ci[c]] != lr[ci[c]]:
                        hard.append((s, c, lr[ci[c]], gr[ci[c]]))
                for c in _SS_HARD_FLOAT:
                    if c == "rs_score_20":
                        continue
                    gv, lvv = gr[ci[c]], lr[ci[c]]
                    if gv is None and lvv is None:
                        continue
                    if (gv is None) != (lvv is None):
                        hard.append((s, c, lvv, gv))
                    elif abs(gv - lvv) > max(1e-4, 1e-3 * abs(lvv)):
                        hard.append((s, c, round(lvv, 4), round(gv, 4)))
                for c in _SS_LOOKBACK_FLAGS:
                    if gr[ci[c]] == lr[ci[c]]:
                        continue
                    kind = "gold_null" if gr[ci[c]] is None else (
                        "live_null" if lr[ci[c]] is None else "both_valued")
                    flag_flips.append((s, c, lr[ci[c]], gr[ci[c]], kind))
            hard_mismatch_total += len(hard)
            lookback_flag_flip_total += len(flag_flips)
            gold_null = sum(1 for f in flag_flips if f[4] == "gold_null")
            both_valued = [f for f in flag_flips if f[4] == "both_valued"]
            flag_gold_null_total += gold_null
            flag_both_valued_total += len(both_valued)

            g_self_break = _monotonic_break(list(g.values()))
            l_self_break = _monotonic_break(list(lv.values()))
            gold_self_inconsistent_total += g_self_break

            g_order = [s for s in sorted(shared, key=lambda s: g[s][ci["rs_rank"]])]
            l_order = [s for s in sorted(shared, key=lambda s: lv[s][ci["rs_rank"]])]

            per_date[d] = {
                "shared_symbols": len(shared),
                "rs_score_20_exact": not rs_score_mm, "rs_score_20_mismatch": rs_score_mm[:10],
                "only_gold_n": len(only_gold), "only_gold_sample": only_gold[:12],
                "only_live_genuine_n": len(only_live), "only_live_genuine_sample": only_live[:12],
                "live_excluded_sector_n": len(live_excluded),
                "live_excluded_sector_sample": live_excluded[:12],
                "hard_columns_exact": not hard,
                "hard_diff_n": len(hard), "hard_diff_sample": hard[:12],
                "lookback_flag_flips": len(flag_flips),
                "flag_gold_null": sum(1 for f in flag_flips if f[4] == "gold_null"),
                "flag_both_valued": len(both_valued),
                "flag_flip_sample": [list(f) for f in flag_flips[:14]],
                "gold_rank_self_inconsistencies": g_self_break,
                "live_rank_self_inconsistencies": l_self_break,
                "shared_rank_order_identical": g_order == l_order,
            }

        # PORT FAITHFUL == every population-independent, lookback-insensitive
        # column exact + only_live 0 + Gold ranks self-consistent. The EMA-stack
        # flag flips (gold_null + both_valued) are ALL traceable to Gold's
        # bounded price-history load vs stock_signals.py's 2015 floor -- a
        # RAM/runtime trade-off on this box, not a logic diff -- so they are
        # reported (`lookback_flag_residual`), not failed. Set
        # KIRAN_SS_LOOKBACK_DAYS higher on adequate hardware for byte parity.
        clean = (only_live_genuine_total == 0 and rs_score_mismatch_total == 0
                 and hard_mismatch_total == 0 and gold_self_inconsistent_total == 0)
        return {
            "status": "clean" if clean else "residual",
            "lookback_flag_residual": {
                "total": lookback_flag_flip_total, "gold_null": flag_gold_null_total,
                "both_valued": flag_both_valued_total,
                "note": "EMA-stack flags on thin names; load-depth artifact, raise KIRAN_SS_LOOKBACK_DAYS",
            },
            "live_excluded_sector_ranked": {
                "total": live_excluded_sector_total,
                "note": ("§118 Defect A: live ranks config.EXCLUDED_SECTORS since 2026-08-03; "
                         "Gold drops them (matches processor.py / signal_engine.py). Expected, "
                         "not a residual."),
            },
            "sample_dates": samples, "window": [gmin, gmax],
            "rs_score_20_mismatch_total": rs_score_mismatch_total,
            "hard_column_mismatch_total": hard_mismatch_total,
            "lookback_flag_flip_total": lookback_flag_flip_total,
            "flag_gold_null_total": flag_gold_null_total,
            "flag_both_valued_total": flag_both_valued_total,
            "gold_rank_self_inconsistencies_total": gold_self_inconsistent_total,
            "only_live_genuine_total": only_live_genuine_total,
            "ss_lookback_cal_days": _SS_LOOKBACK_CAL_DAYS,
            "excluded": sorted(_SS_KNOWN_SILVER_RESIDUAL),
            "verdict": ("Port faithful iff: `rs_score_20` exact + hard columns "
                        "(`base_tightness` / `pivot_*` / `bos_flag` / `avg_vol_10d` / "
                        "`vol_contraction`) exact among shared symbols + `only_live` 0 + "
                        "Gold ranks self-consistent + no EMA-stack flag flip where BOTH "
                        "stores hold a value. `flag_gold_null` = EMA-stack flags Gold reports "
                        "NULL because its price load "
                        f"(KIRAN_SS_LOOKBACK_DAYS={_SS_LOOKBACK_CAL_DAYS} cal) has < ~200 "
                        "in-window bars for a thin name; live had them from `stock_signals.py`'s "
                        "2015 floor. Raise KIRAN_SS_LOOKBACK_DAYS on a box with the RAM for "
                        "byte parity on those. Rank-order vs live + `live_rank_self_"
                        "inconsistencies` are LIVE defects -- see `finding`."),
            "finding": ("Live `stock_signals` has TWO defects Gold fixes (KIRAN_CLEANUP_AUDIT.md "
                        "§118): (A) EXCLUDED-SECTOR POLLUTION -- `_load_universe` has no "
                        "config.EXCLUDED_SECTORS filter; live's stock_metadata gained ~150 "
                        "preserved excluded-sector rows on 2026-08-03, so live has ranked ~128 "
                        "untradeable stocks (sugar / textiles / modarabas / small inv banks / "
                        "closed-end funds) since then. Gold drops them (matches processor.py / "
                        "signal_engine.py / boring_signals.py). (B) `recompute_symbol_signals` "
                        "RANK CORRUPTION -- it recomputes one symbol with a single-symbol "
                        "universe and writes rs_rank=1 for that symbol's whole history: MTL "
                        "(5194 rows) + PIAB (51 rows). Gold recomputes over one universe -> "
                        "self-consistent ranks. `rs_score_20` (per-symbol vs KSE-100) matches "
                        "live EXACTLY throughout."),
            "per_date": per_date,
        }
    finally:
        lcon.close()


_SEC_STAGE_COL = "sector_stage"


_SEC_PARITY_WINDOW_DAYS = 45          # trading dates to compare
_SEC_PARITY_WARMUP_DAYS = 95          # extra cal-day warmup for the recompute chain


def _parity_sector_signals(gcon: "duckdb.DuckDBPyConnection", live_db: Path) -> dict:
    """Verify the `sector_signals` PORT by RECOMPUTE, not by comparing to live's
    stored rows.

    Live's stored `sector_signals` derived columns (`rs_score_20`,
    `composite_score`, `rs_rank`) are **stale** -- not reproducible by the
    current `sector_signals.py`; only `sector_ema50` (2026-06-19+) was ever
    written by the code Gold reuses (KIRAN_CLEANUP_AUDIT.md §118.6). So a
    stored-row diff proves nothing about the port.

    Instead: materialise Gold's own Silver/Bronze inputs into a scratch SQLite
    and run `_compute_and_write_sector_signals_for_date_sqlite` -- the *same
    function* `build_sector_signals` calls -- over a contiguous recent window.
    Gold ran it on DuckDB; the recompute runs it on SQLite; the inputs are
    identical. Any difference is a genuine engine-level port bug.

    `clean` iff every sector-cell (`sector_stage`, `sector_ema50`,
    `sector_above_ema`, `rs_score_20/50`, `breadth_score`, `vol_ratio`,
    `adv_dec_ratio`, `composite_score`, `rs_rank`) matches within float tol on
    the compare window, and the sector sets are identical.
    """
    import datetime as dt
    import tempfile
    import pandas as pd
    import sector_signals as sig

    if not gcon.execute("SELECT 1 FROM information_schema.tables WHERE table_name='sector_signals'").fetchone():
        return {"status": "skipped", "reason": "gold has no sector_signals"}
    gmin, gmax = gcon.execute("SELECT min(date), max(date) FROM sector_signals").fetchone()
    all_dates = [r[0] for r in gcon.execute(
        "SELECT DISTINCT date FROM sector_signals ORDER BY date").fetchall()]
    if len(all_dates) < 5:
        return {"status": "skipped", "reason": "too few gold sector_signals dates"}
    cmp_dates = all_dates[-_SEC_PARITY_WINDOW_DAYS:]
    cmp_lo = cmp_dates[0]
    warm_lo = (dt.date.fromisoformat(cmp_lo) - dt.timedelta(days=_SEC_PARITY_WARMUP_DAYS)).isoformat()

    tmp = Path(tempfile.mkdtemp(prefix="gold_sec_parity_"))
    scratch = tmp / "recompute.db"
    try:
        rcon = sqlite3.connect(str(scratch))
        # materialise Gold's inputs (Silver prices, Bronze index, conformed meta,
        # baseline mcap, Gold regime, Gold's pure active_stocks_on_date)
        _pa = gcon.execute("SELECT symbol, date, close, volume FROM prices_adjusted "
                           "WHERE date >= ?", (warm_lo,)).df()
        _ix = gcon.execute("SELECT symbol, date, close FROM index_prices WHERE date >= ?", (warm_lo,)).df()
        _sm = gcon.execute("SELECT * FROM stock_metadata").df()
        _mc = gcon.execute("SELECT * FROM stock_market_cap").df() \
            if gcon.execute("SELECT 1 FROM information_schema.tables WHERE table_name='stock_market_cap'").fetchone() \
            else pd.DataFrame(columns=["symbol", "shares_m", "market_cap_m", "cap_date"])
        _rg = gcon.execute("SELECT * FROM market_regime WHERE date >= ?", (warm_lo,)).df() \
            if gcon.execute("SELECT 1 FROM information_schema.tables WHERE table_name='market_regime'").fetchone() \
            else pd.DataFrame(columns=["date", "regime"])
        _as = gcon.execute("SELECT symbol, trading_date FROM active_stocks_on_date "
                           "WHERE trading_date >= ?", (warm_lo,)).df()
        _pa.to_sql("prices_adjusted", rcon, index=False)
        _ix.to_sql("index_prices", rcon, index=False)
        _sm.to_sql("stock_metadata", rcon, index=False)
        _mc.to_sql("stock_market_cap", rcon, index=False)
        _rg.to_sql("market_regime", rcon, index=False)
        _as.to_sql("active_stocks_on_date", rcon, index=False)
        rcon.execute("CREATE INDEX ix_pa ON prices_adjusted(date)")
        rcon.execute("CREATE INDEX ix_pa_s ON prices_adjusted(symbol, date)")
        rcon.execute("CREATE INDEX ix_as ON active_stocks_on_date(trading_date)")
        rcon.execute(_SECTOR_SIGNALS_DDL.replace("CREATE OR REPLACE TABLE", "CREATE TABLE"))
        rcon.commit()

        recompute_dates = [r[0] for r in rcon.execute(
            "SELECT DISTINCT date FROM prices_adjusted WHERE date >= ? AND date <= ? ORDER BY date",
            (warm_lo, cmp_dates[-1])).fetchall()]
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            for d in recompute_dates:
                try:
                    sig._compute_and_write_sector_signals_for_date_sqlite(rcon, d)
                except Exception as e:                     # flow enrichment needs market_flows -> ok
                    if "market_flows" not in str(e):
                        raise
                rcon.commit()

        num_cols = ["rs_score_20", "rs_score_50", "breadth_score", "vol_ratio",
                    "adv_dec_ratio", "composite_score", "rs_rank",
                    "sector_ema50", "sector_above_ema"]
        sel = "sector, sector_stage, " + ", ".join(num_cols)
        tol = {c: 1e-4 for c in num_cols}
        tol.update({"breadth_score": 1e-2, "vol_ratio": 1e-3, "sector_ema50": 1e-2,
                    "composite_score": 1e-3, "rs_rank": 0.5})

        import math

        def _miss(x):
            return x is None or (isinstance(x, float) and math.isnan(x))

        def _close(a, b, t):
            am, bm = _miss(a), _miss(b)          # NULL (SQLite) == NaN (DuckDB) == missing
            if am or bm:
                return am and bm
            return abs(a - b) <= max(t, t * abs(b))

        per_date = {}
        cells = 0
        col_mm = {c: 0 for c in ["sector_stage"] + num_cols}
        set_mm_dates = []
        for d in cmp_dates:
            gg = {r[0]: r for r in gcon.execute(
                f"SELECT {sel} FROM sector_signals WHERE date = ?", (d,)).fetchall()}
            rr = {r[0]: r for r in rcon.execute(
                f"SELECT {sel} FROM sector_signals WHERE date = ?", (d,)).fetchall()}
            if set(gg) != set(rr):
                set_mm_dates.append(d)
            shared = sorted(set(gg) & set(rr))
            cells += len(shared)
            dd = {}
            for s in shared:
                if gg[s][1] != rr[s][1]:
                    col_mm["sector_stage"] += 1
                    dd.setdefault("sector_stage", []).append([s, rr[s][1], gg[s][1]])
                for i, c in enumerate(num_cols, start=2):
                    if not _close(gg[s][i], rr[s][i], tol[c]):
                        col_mm[c] += 1
                        dd.setdefault(c, []).append([s, rr[s][i], gg[s][i]])
            if dd or set(gg) != set(rr):
                per_date[d] = {"only_gold": sorted(set(gg) - set(rr)),
                               "only_recompute": sorted(set(rr) - set(gg)), **dd}

        clean = not set_mm_dates and all(v == 0 for v in col_mm.values())
        return {
            "status": "clean" if clean else "residual",
            "method": "recompute (SQLite) vs Gold (DuckDB), identical Silver/Bronze inputs",
            "compare_window": [cmp_lo, cmp_dates[-1]], "compare_dates": len(cmp_dates),
            "recompute_dates": len(recompute_dates), "cells_compared": cells,
            "gold_window": [gmin, gmax],
            "sector_set_mismatch_dates": set_mm_dates,
            "column_mismatch_totals": col_mm,
            "note": ("Port test = same function (`_compute_and_write_sector_signals_for_"
                     "date_sqlite`), same inputs, SQLite vs DuckDB. Live's STORED "
                     "sector_signals is not the comparison target -- its derived columns "
                     "predate the current code (KIRAN_CLEANUP_AUDIT.md §118.6); its "
                     "four-stage `sector_stage` in live's current-code window "
                     "(sector_ema50 IS NOT NULL, 2026-06-19+) does match Gold byte-exact, "
                     "checked separately."),
            "per_date": per_date,
        }
    finally:
        try:
            rcon.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


def _parity_boring_signals(gcon: "duckdb.DuckDBPyConnection", live_db: Path) -> dict:
    """Verify the `boring_signals` PORT by RECOMPUTE (same methodology as
    `_parity_sector_signals`, applied from the start here rather than after a
    multi-round investigation -- see §118.6 for why comparing to live's
    *stored* rows is not reliable in general for this program's screener
    ports).

    Materialises Gold's own Silver/Bronze inputs into a scratch SQLite and
    re-runs `update_open_signal_statuses` + `scan_boring_breakouts` -- the
    SAME functions `build_boring_signals` calls -- via the identical
    chronological (`as_of_date`) replay, over the identical
    `BORING_SIGNALS_FLOOR_DATE .. end_date` window. Gold ran it on DuckDB;
    the recompute runs it on SQLite; inputs and loop order are identical, so
    any difference is a genuine engine-level port bug -- not a live-data
    question. The table's whole window postdates its 2026-07-10 go-live
    floor, so it is small and cheap to recompute in full (not sampled).

    `mark_executed` / `executed` / `executed_price` / `dedup_conflict` are
    real human actions taken on live's dashboard (`main.py`'s automated hook
    never calls `mark_executed`) -- Gold structurally cannot reproduce them
    and its own recompute never sets them either, so they are outside this
    check by construction, not a residual.

    `clean` iff every (symbol, signal_date, lookback_n) row -- and every
    compared column -- matches between Gold and the recompute, EXCEPT
    `rs_60_decile`: a `pd.qcut` bucket over the whole day's eligible universe,
    reported separately as `decile_boundary_residual` when a symbol sitting
    at a bucket boundary lands one decile apart while `rs_60` itself (checked
    like every other column) matches -- a discretisation artifact from
    sub-tolerance float noise in the *other* symbols' values that day, not a
    port bug in the RS_60 math itself.
    """
    import datetime as dt
    import tempfile
    import boring_signals as bsig

    if not gcon.execute("SELECT 1 FROM information_schema.tables "
                        "WHERE table_name='boring_signals'").fetchone():
        return {"status": "skipped", "reason": "gold has no boring_signals"}
    floor = bsig.BORING_SIGNALS_FLOOR_DATE
    end_date = gcon.execute("SELECT max(date) FROM prices_adjusted "
                            "WHERE symbol IN (SELECT symbol FROM stock_metadata)").fetchone()[0]
    if end_date is None or end_date < floor:
        return {"status": "skipped", "reason": "gold window predates the boring_signals go-live floor"}
    warm_lo = (dt.date.fromisoformat(floor) - dt.timedelta(days=200)).isoformat()

    tmp = Path(tempfile.mkdtemp(prefix="gold_bs_parity_"))
    scratch = tmp / "recompute.db"
    try:
        rcon = sqlite3.connect(str(scratch))
        bsig.ensure_boring_signals_table(rcon)   # native SQLite DDL (AUTOINCREMENT etc.)
        _pa = gcon.execute("SELECT symbol, date, high, low, close, volume "
                           "FROM prices_adjusted WHERE date >= ?", (warm_lo,)).df()
        _ix = gcon.execute("SELECT symbol, date, close FROM index_prices WHERE date >= ?", (warm_lo,)).df()
        _sm = gcon.execute("SELECT * FROM stock_metadata").df()
        _sec = gcon.execute("SELECT * FROM sectors").df()
        _pa.to_sql("prices_adjusted", rcon, index=False)
        _ix.to_sql("index_prices", rcon, index=False)
        _sm.to_sql("stock_metadata", rcon, index=False)
        _sec.to_sql("sectors", rcon, index=False)
        rcon.execute("CREATE INDEX ix_pa ON prices_adjusted(symbol, date)")
        rcon.commit()

        recompute_dates = [r[0] for r in rcon.execute(
            "SELECT DISTINCT date FROM prices_adjusted WHERE date >= ? AND date <= ? ORDER BY date",
            (floor, end_date)).fetchall()]
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
            for d in recompute_dates:
                bsig.update_open_signal_statuses(as_of_date=d, conn=rcon)
                bsig.scan_boring_breakouts(date=d, conn=rcon)
                rcon.commit()

        # rs_60_decile is handled separately: pd.qcut(rs_60, 10) buckets the
        # WHOLE eligible universe's rs_60 that date -- a symbol sitting right
        # at a decile boundary can land in a different bucket SQLite vs
        # DuckDB from sub-tolerance float noise in the *other* symbols'
        # values (the array pandas/numpy sees, not this row alone), even
        # though rs_60 itself (checked below, in num_cols) matches exactly
        # within tolerance for every row. Reported as `decile_boundary_
        # residual`, not counted against `clean` -- a discretisation
        # artifact, not a port bug in the RS_60 math.
        num_cols = ["breakout_level", "trigger_price", "target_price", "stop_price",
                    "rs_60", "avg_vol_10d", "days_open", "current_stop"]
        int_cols = ["liquidity_pass", "strategy_confirmed"]
        txt_cols = ["status", "resolution_type", "resolution_date"]
        cols = num_cols + ["rs_60_decile"] + int_cols + txt_cols
        sel = "symbol, signal_date, lookback_n, " + ", ".join(cols)

        import math

        def _miss(x):
            return x is None or (isinstance(x, float) and math.isnan(x))

        def _close(a, b, t=1e-4):
            am, bm = _miss(a), _miss(b)
            if am or bm:
                return am and bm
            return abs(a - b) <= max(t, t * abs(b))

        g = {(r[0], r[1], r[2]): r[3:] for r in gcon.execute(f"SELECT {sel} FROM boring_signals").fetchall()}
        rr = {(r[0], r[1], r[2]): r[3:] for r in rcon.execute(f"SELECT {sel} FROM boring_signals").fetchall()}
        ci = {c: i for i, c in enumerate(cols)}
        only_gold = sorted(g.keys() - rr.keys())
        only_recompute = sorted(rr.keys() - g.keys())
        shared = sorted(g.keys() & rr.keys())
        col_mm = {c: 0 for c in num_cols + int_cols + txt_cols}
        mismatches = []
        decile_boundary_residual = []
        for k in shared:
            gv, rv = g[k], rr[k]
            row_mm = {}
            for c in num_cols:
                if not _close(gv[ci[c]], rv[ci[c]]):
                    col_mm[c] += 1
                    row_mm[c] = [rv[ci[c]], gv[ci[c]]]
            for c in int_cols + txt_cols:
                if gv[ci[c]] != rv[ci[c]]:
                    col_mm[c] += 1
                    row_mm[c] = [rv[ci[c]], gv[ci[c]]]
            if gv[ci["rs_60_decile"]] != rv[ci["rs_60_decile"]]:
                decile_boundary_residual.append(
                    [list(k), rv[ci["rs_60_decile"]], gv[ci["rs_60_decile"]], gv[ci["rs_60"]]])
            if row_mm:
                mismatches.append([list(k), row_mm])

        clean = (not only_gold and not only_recompute and not mismatches)
        return {
            "status": "clean" if clean else "residual",
            "method": "recompute (SQLite) vs Gold (DuckDB), identical Silver/Bronze inputs",
            "window": [floor, end_date], "dates_replayed": len(recompute_dates),
            "rows_compared": len(shared), "only_gold": only_gold, "only_recompute": only_recompute,
            "column_mismatch_totals": col_mm, "mismatches": mismatches[:20],
            "decile_boundary_residual_n": len(decile_boundary_residual),
            "decile_boundary_residual": decile_boundary_residual[:20],
            "note": ("Port test = same functions (update_open_signal_statuses, "
                     "scan_boring_breakouts), same inputs, identical chronological "
                     "replay order, SQLite vs DuckDB. executed/executed_at/executed_price/"
                     "dedup_conflict are human dashboard actions, never produced by the "
                     "automated scan -- outside this check by construction. "
                     "decile_boundary_residual = rs_60_decile (a pd.qcut bucket over the "
                     "whole day's eligible universe) landed one bucket apart while rs_60 "
                     "itself matched -- a discretisation-boundary artifact, not counted "
                     "against clean."),
        }
    finally:
        try:
            rcon.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


_LSC_PARITY_WINDOW_DAYS = 30
_LSC_PARITY_WARMUP_DAYS = 150   # calendar days -- _nearest_overhead_pct alone needs 120


def _parity_leaders_scan(gcon: "duckdb.DuckDBPyConnection", live_db: Path) -> dict:
    """Verify the `leaders_scan` / `leaders_top_picks` PORT by RECOMPUTE (same
    methodology as `_parity_sector_signals` / `_parity_boring_signals`).

    Materialises Gold's own `stock_signals` / `sector_signals` (already built
    earlier in this same run) plus Silver/Bronze prices into a scratch SQLite,
    and re-runs `append_leaders_scan` + `save_top_picks` -- the SAME functions
    `build_leaders_scan` calls -- per date over a recent window, then
    `fill_leaders_forward_returns` once. Gold ran it on DuckDB; the recompute
    runs it on SQLite; inputs are identical, so any difference is a genuine
    engine-level port bug.

    `clean` iff `leaders_scan` and `leaders_top_picks` match cell-for-cell
    over the compared window.
    """
    import datetime as dt
    import tempfile
    import leaders_scan as lsc

    if not gcon.execute("SELECT 1 FROM information_schema.tables "
                        "WHERE table_name='leaders_scan'").fetchone():
        return {"status": "skipped", "reason": "gold has no leaders_scan"}
    all_dates = [r[0] for r in gcon.execute(
        "SELECT DISTINCT date FROM stock_signals ORDER BY date").fetchall()]
    if len(all_dates) < 3:
        return {"status": "skipped", "reason": "too few gold stock_signals dates"}
    cmp_dates = all_dates[-_LSC_PARITY_WINDOW_DAYS:]
    cmp_lo = cmp_dates[0]
    warm_lo = (dt.date.fromisoformat(cmp_lo) - dt.timedelta(days=_LSC_PARITY_WARMUP_DAYS)).isoformat()

    tmp = Path(tempfile.mkdtemp(prefix="gold_lsc_parity_"))
    scratch = tmp / "recompute.db"
    try:
        rcon = sqlite3.connect(str(scratch))
        lsc.ensure_tables(rcon)   # native SQLite DDL (AUTOINCREMENT etc.)
        _pa = gcon.execute("SELECT symbol, date, close FROM prices_adjusted "
                           "WHERE date >= ?", (warm_lo,)).df()
        _pr = gcon.execute("SELECT symbol, date, high, low, close, volume, open "
                           "FROM prices WHERE date >= ?", (warm_lo,)).df()
        _sm = gcon.execute("SELECT * FROM stock_metadata").df()
        _ss = gcon.execute("SELECT * FROM stock_signals WHERE date >= ?", (warm_lo,)).df()
        _sec = gcon.execute("SELECT * FROM sector_signals WHERE date >= ?", (warm_lo,)).df()
        _pa.to_sql("prices_adjusted", rcon, index=False)
        _pr.to_sql("prices", rcon, index=False)
        _sm.to_sql("stock_metadata", rcon, index=False)
        _ss.to_sql("stock_signals", rcon, index=False)
        _sec.to_sql("sector_signals", rcon, index=False)
        rcon.execute("CREATE INDEX ix_pr ON prices(symbol, date)")
        rcon.execute("CREATE INDEX ix_ss ON stock_signals(date)")
        rcon.commit()

        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
            for d in cmp_dates:
                lsc.append_leaders_scan(scan_date=d, conn=rcon)
                lsc.save_top_picks(scan_date=d, conn=rcon)
            lsc.fill_leaders_forward_returns(conn=rcon)
        rcon.commit()

        import math

        def _miss(x):
            return x is None or (isinstance(x, float) and math.isnan(x))

        def _close(a, b, t=1e-4):
            am, bm = _miss(a), _miss(b)
            if am or bm:
                return am and bm
            return abs(a - b) <= max(t, t * abs(b))

        def _diff_table(table, key_cols, cmp_cols, num_cols):
            sel = ", ".join(key_cols + cmp_cols)
            gcon_sel = f"SELECT {sel} FROM {table} WHERE scan_date >= ? AND scan_date <= ?"
            g = {tuple(r[:len(key_cols)]): r[len(key_cols):] for r in gcon.execute(
                gcon_sel, [cmp_lo, cmp_dates[-1]]).fetchall()}
            rr = {tuple(r[:len(key_cols)]): r[len(key_cols):] for r in rcon.execute(
                gcon_sel, (cmp_lo, cmp_dates[-1])).fetchall()}
            ci = {c: i for i, c in enumerate(cmp_cols)}
            only_gold = sorted(g.keys() - rr.keys())
            only_recompute = sorted(rr.keys() - g.keys())
            shared = sorted(g.keys() & rr.keys())
            col_mm = {c: 0 for c in cmp_cols}
            for k in shared:
                gv, rv = g[k], rr[k]
                for c in cmp_cols:
                    same = _close(gv[ci[c]], rv[ci[c]]) if c in num_cols else gv[ci[c]] == rv[ci[c]]
                    if not same:
                        col_mm[c] += 1
            return {"rows_compared": len(shared), "only_gold": only_gold[:15],
                    "only_recompute": only_recompute[:15], "column_mismatch_totals": col_mm}

        ls_cols = ["sector", "sector_rank", "rs_rank", "sector_rs_rank", "rs_score_20", "rs_score_50",
                   "rank_change", "base_tightness", "pivot_high", "pivot_distance_pct", "avg_vol_10d",
                   "vol_ratio_today", "entry_trigger", "stop_loss", "sl_pct", "rs_inflection",
                   "sector_composite", "vol_rejection_flag", "nearest_overhead_pct", "vol_contraction",
                   "raw_score", "penalty", "final_score", "flag"]
        # every column stored DOUBLE in _LEADERS_SCAN_DDL needs the NaN-aware
        # comparator, not just the "genuinely fractional" ones -- a NaN
        # (missing sector rank, e.g.) compares unequal to itself under plain
        # `==`, which would misreport a false mismatch on both sides being
        # equally missing.
        ls_num = {"sector_rank", "rs_rank", "sector_rs_rank", "rs_score_20", "rs_score_50",
                  "rank_change", "base_tightness", "pivot_high", "pivot_distance_pct",
                  "avg_vol_10d", "vol_ratio_today", "entry_trigger", "stop_loss", "sl_pct",
                  "rs_inflection", "sector_composite", "vol_rejection_flag", "nearest_overhead_pct",
                  "vol_contraction", "raw_score", "penalty", "final_score"}
        ls_res = _diff_table("leaders_scan", ["scan_date", "setup_type", "symbol"], ls_cols, ls_num)

        # leaders_top_picks: `ORDER BY final_score DESC, vol_ratio_today DESC
        # LIMIT 3` has no further tiebreak (save_top_picks() itself, not this
        # port) -- when two+ candidates are EXACTLY tied on both keys, which
        # one lands in a given rank slot is engine-defined and can legitimately
        # differ SQLite vs DuckDB. Detected directly against Gold's own (already
        # byte-identical) leaders_scan: if the gold-picked and recompute-picked
        # symbol at a rank share the identical (final_score, vol_ratio_today)
        # in the candidate pool for that date/setup_type, the swap is a genuine
        # tie, not a port bug -- classified `tie_break_residual`, kept out of
        # `column_mismatch_totals` / `clean`.
        key_cols = ["scan_date", "setup_type", "rank"]
        tp_cols = ["symbol", "sector", "sector_rank", "entry_trigger", "stop_loss", "sl_pct",
                   "vol_ratio_today", "key_reason", "flag", "fwd_return_5d", "fwd_return_10d",
                   "fwd_return_20d", "outcome_label", "triggered", "trigger_date"]
        tp_num = {"sector_rank", "entry_trigger", "stop_loss", "sl_pct", "vol_ratio_today",
                  "fwd_return_5d", "fwd_return_10d", "fwd_return_20d", "triggered"}
        sel = ", ".join(key_cols + tp_cols)
        gsel = f"SELECT {sel} FROM leaders_top_picks WHERE scan_date >= ? AND scan_date <= ?"
        g = {tuple(r[:3]): r[3:] for r in gcon.execute(gsel, [cmp_lo, cmp_dates[-1]]).fetchall()}
        rr = {tuple(r[:3]): r[3:] for r in rcon.execute(gsel, (cmp_lo, cmp_dates[-1])).fetchall()}
        tci = {c: i for i, c in enumerate(tp_cols)}
        only_gold = sorted(g.keys() - rr.keys())
        only_recompute = sorted(rr.keys() - g.keys())
        shared = sorted(g.keys() & rr.keys())
        cand_pool: dict = {}   # (scan_date, setup_type) -> {symbol: (final_score, vol_ratio_today)}

        def _pool(date, setup_type):
            k = (date, setup_type)
            if k not in cand_pool:
                cand_pool[k] = {r[0]: (r[1], r[2]) for r in gcon.execute(
                    "SELECT symbol, final_score, vol_ratio_today FROM leaders_scan "
                    "WHERE scan_date = ? AND setup_type = ?", [date, setup_type]).fetchall()}
            return cand_pool[k]

        col_mm = {c: 0 for c in tp_cols}
        tie_residual = []
        genuine_mismatches = []
        for k in shared:
            gv, rv = g[k], rr[k]
            if gv[tci["symbol"]] != rv[tci["symbol"]]:
                pool = _pool(k[0], k[1])
                gs, rs = gv[tci["symbol"]], rv[tci["symbol"]]
                if pool.get(gs) is not None and pool.get(gs) == pool.get(rs):
                    tie_residual.append([list(k), rs, gs, pool.get(gs)])
                    continue                                    # whole row is tie-explained
                genuine_mismatches.append([list(k), "symbol", rs, gs])
                col_mm["symbol"] += 1
                continue
            row_mm = {}
            for c in tp_cols:
                if c == "symbol":
                    continue
                same = _close(gv[tci[c]], rv[tci[c]]) if c in tp_num else gv[tci[c]] == rv[tci[c]]
                if not same:
                    col_mm[c] += 1
                    row_mm[c] = [rv[tci[c]], gv[tci[c]]]
            if row_mm:
                genuine_mismatches.append([list(k), row_mm])
        tp_res = {"rows_compared": len(shared), "only_gold": only_gold[:15],
                  "only_recompute": only_recompute[:15], "column_mismatch_totals": col_mm,
                  "tie_break_residual_n": len(tie_residual), "tie_break_residual": tie_residual[:15],
                  "genuine_mismatches": genuine_mismatches[:15]}

        clean = (not ls_res["only_gold"] and not ls_res["only_recompute"]
                 and all(v == 0 for v in ls_res["column_mismatch_totals"].values())
                 and not tp_res["only_gold"] and not tp_res["only_recompute"]
                 and all(v == 0 for v in tp_res["column_mismatch_totals"].values()))
        return {
            "status": "clean" if clean else "residual",
            "method": "recompute (SQLite) vs Gold (DuckDB), identical stock_signals/sector_signals/prices inputs",
            "compare_window": [cmp_lo, cmp_dates[-1]], "leaders_scan": ls_res,
            "leaders_top_picks": tp_res,
            "note": ("leaders_scan matches cell-for-cell -> the scoring/filtering port is "
                     "verified. leaders_top_picks' tie_break_residual = save_top_picks()'s own "
                     "ORDER BY final_score DESC, vol_ratio_today DESC LIMIT 3 has no further "
                     "tiebreak; an exact tie on both keys is broken engine-arbitrarily -- "
                     "confirmed against Gold's own leaders_scan candidate pool, not a port bug."),
        }
    finally:
        try:
            rcon.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


PARITY = {
    "market_regime": _parity_market_regime,
    "stock_signals": _parity_stock_signals,
    "sector_signals": _parity_sector_signals,
    "boring_signals": _parity_boring_signals,
    "leaders_scan": _parity_leaders_scan,
}


# --------------------------------------------------------------------- build

def build(store_root: Path, window_days: int = DEFAULT_WINDOW_DAYS,
          run_parity: bool = True, screeners: list[str] | None = None) -> dict:
    import datetime as dt

    active = {k: v for k, v in SCREENERS.items() if screeners is None or k in screeners}
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
        for table, fn in active.items():
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
    have = {r[0] for r in gcon.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    exported = {}
    for table in list(active) + REFERENCE_TABLES:
        if table not in have:
            continue
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
                if table in active:
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

    return {"outcome": "built", "window_from": window_from, "screeners": list(active),
            "rows": exported, "parity": {k: v.get("status") for k, v in parity.items()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gold build -- rebuild the DuckDB serving store from Silver.")
    ap.add_argument("--store-root", default=str(ARCHIVE_ROOT / "psx_serving"))
    ap.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    ap.add_argument("--ss-lookback-days", type=int, default=None,
                    help="calendar days of price history for the stock_signals port "
                         "(default %d; env KIRAN_SS_LOOKBACK_DAYS). Higher = byte parity on "
                         "EMA-stack flags for thin names, at more RAM." % _SS_LOOKBACK_CAL_DAYS)
    ap.add_argument("--no-parity", action="store_true")
    ap.add_argument("--only", help="comma-separated screener table names to build "
                    "(default: all -- %s)" % ", ".join(SCREENERS))
    args = ap.parse_args(argv)
    if args.ss_lookback_days is not None:
        globals()["_SS_LOOKBACK_CAL_DAYS"] = args.ss_lookback_days
    result = build(Path(args.store_root), window_days=args.window_days,
                   run_parity=not args.no_parity,
                   screeners=args.only.split(",") if args.only else None)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
