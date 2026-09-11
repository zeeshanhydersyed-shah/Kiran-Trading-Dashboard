"""Phase 3, Task 3.3a -- Gold build scaffold + regime port (archive/gold_build.py).

Contract (docs/KIRAN_LOCAL_FIRST_MIGRATION.md Phase 3 §5 / MEDALLION.md):
rebuild the DuckDB serving store from the Medallion Silver/Bronze store, full
replace + staging + atomic swap, deterministic re-run, parity vs the live
psx_data.db; never opens psx_data.db for write. Screener compute is a full
DuckDB port -- the pure core (regime._compute_indicators / _classify /
_pending_regime_rows) is reused by import.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import sqlite3

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive import bronze_ingest, gold_build


def _bars(start="2024-01-01", n=320, base=70000.0, drift=60.0):
    """A synthetic KSE-100 uptrend, weekdays only."""
    rows, d, px = [], dt.date.fromisoformat(start), base
    while len(rows) < n:
        if d.weekday() < 5:
            px += drift + 40 * math.sin(len(rows) / 9)
            rows.append((d.isoformat(), px + 30, px - 30, px, px))
        d += dt.timedelta(days=1)
    return rows


def _write_index(root, bars):
    by_year = {}
    for ds, hi, lo, cl, op in bars:
        by_year.setdefault(ds[:4], []).append(("KSE-100", ds, hi, lo, cl, op))
    for year, rs in by_year.items():
        t = pa.table({"symbol": [r[0] for r in rs], "date": [r[1] for r in rs],
                      "high": [r[2] for r in rs], "low": [r[3] for r in rs],
                      "close": [r[4] for r in rs], "open": [r[5] for r in rs]},
                     schema=bronze_ingest.INDEX_SCHEMA)
        fp = root / "prices_archive" / "bronze" / "index_prices" / f"year={year}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, fp, **bronze_ingest.PARQUET_OPTS)


_SYMS = [("HBL", "COMMERCIAL BANKS"), ("OGDC", "OIL & GAS"),
         ("LUCK", "CEMENT"), ("ENGRO", "FERTILIZER"), ("PSO", "OIL & GAS")]


def _write_prices_anchor(root, bars):
    """Bronze `prices` (RAW, unadjusted) for every _SYMS symbol across the full
    bar series -- same per-symbol multiple as _write_silver's prices_adjusted
    (no synthetic CA event, so raw == adjusted here). gold_build reads this for
    the window anchor (max date) AND, since 3.3d, for boring_signals/
    leaders_scan's raw-price reads (today's close, volume ratios, overhead)."""
    rows_by_year: dict[str, list] = {}
    for si, (sym, _sec) in enumerate(_SYMS):
        mult = 0.001 * (1 + si)
        for bi, (ds, hi, lo, cl, op) in enumerate(bars):
            c = cl * mult + 3 * math.sin((bi + si) / 7)
            rows_by_year.setdefault(ds[:4], []).append(
                (sym, ds, round(c, 4), 500_000 + (bi * 37 + si * 991) % 300_000,
                 round(c * 1.01, 4), round(c * 0.99, 4), round(c, 4)))
    for year, rs in rows_by_year.items():
        t = pa.table({k: [r[i] for r in rs] for i, k in enumerate(bronze_ingest.PRICES_COLUMNS)},
                     schema=bronze_ingest.PRICES_SCHEMA)
        fp = root / "prices_archive" / "bronze" / "prices" / f"year={year}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, fp, **bronze_ingest.PARQUET_OPTS)


def _write_silver(root, bars, extra_syms=()):
    """Per-symbol prices_adjusted derived from the KSE bars (each symbol a
    slightly different multiple), plus sectors + stock_metadata. `extra_syms` =
    list of (symbol, sector) to add on top of _SYMS (e.g. an excluded sector)."""
    syms = list(_SYMS) + list(extra_syms)
    rows_by_year: dict[str, list] = {}
    for si, (sym, sec) in enumerate(syms):
        mult = 0.001 * (1 + si)          # HBL ~70, OGDC ~140, ...
        for bi, (ds, hi, lo, cl, op) in enumerate(bars):
            c = cl * mult + 3 * math.sin((bi + si) / 7)
            rows_by_year.setdefault(ds[:4], []).append(
                (sym, ds, round(c, 4), 500_000 + (bi * 37 + si * 991) % 300_000,
                 round(c * 1.01, 4), round(c * 0.99, 4), round(c, 4), 0, 0, 0))
    from archive import silver_build
    for year, rs in rows_by_year.items():
        t = pa.table({k: [r[i] for r in rs] for i, k in enumerate(silver_build.PRICES_ADJ_COLUMNS)},
                     schema=silver_build.PRICES_ADJ_SCHEMA)
        fp = root / "prices_archive" / "silver" / "prices_adjusted" / f"year={year}" / "data.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, fp, **bronze_ingest.PARQUET_OPTS)

    sct = pa.table({"symbol": [s for s, _ in syms], "sector": [x for _, x in syms]},
                   schema=pa.schema([("symbol", pa.string()), ("sector", pa.string())]))
    (root / "prices_archive" / "silver" / "sectors").mkdir(parents=True, exist_ok=True)
    pq.write_table(sct, root / "prices_archive" / "silver" / "sectors" / "sectors.parquet",
                   **bronze_ingest.PARQUET_OPTS)

    n = len(syms)
    mt = pa.table({"symbol": [s for s, _ in syms], "company_name": [s for s, _ in syms],
                   "sector": [x for _, x in syms], "listing_date": [bars[0][0]] * n,
                   "delisting_date": [None] * n, "is_active": [1] * n,
                   "in_kse100": [1] * n, "notes": [None] * n},
                  schema=pa.schema([
                      ("symbol", pa.string()), ("company_name", pa.string()),
                      ("sector", pa.string()), ("listing_date", pa.string()),
                      ("delisting_date", pa.string()), ("is_active", pa.int64()),
                      ("in_kse100", pa.int64()), ("notes", pa.string())]))
    (root / "prices_archive" / "silver" / "stock_metadata").mkdir(parents=True, exist_ok=True)
    pq.write_table(mt, root / "prices_archive" / "silver" / "stock_metadata" / "stock_metadata.parquet",
                   **bronze_ingest.PARQUET_OPTS)


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    (root / "psx_serving").mkdir(parents=True)
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(gold_build, "ARCHIVE_ROOT", root)

    bars = _bars()
    _write_index(root, bars)
    _write_prices_anchor(root, bars)
    _write_silver(root, bars)

    live = tmp_path / "psx_data.db"
    monkeypatch.setattr(gold_build, "LIVE_DB", live)
    return root, live, bars


def _gold_regime(root):
    import duckdb
    c = duckdb.connect(str(root / "psx_serving" / "psx_serving.duckdb"), read_only=True)
    try:
        return c.execute("SELECT date, regime, regime_days FROM market_regime ORDER BY date").fetchall()
    finally:
        c.close()


def test_build_produces_regime_and_export(env):
    root, live, bars = env
    res = gold_build.build(root / "psx_serving", window_days=730, run_parity=False, screeners=["market_regime"])
    assert res["outcome"] == "built"
    assert (root / "psx_serving" / "psx_serving.duckdb").exists()
    assert not (root / "psx_serving" / "psx_serving_staging.duckdb").exists()  # swapped
    exp = root / "psx_serving" / "parquet" / "market_regime.parquet"
    assert exp.exists()
    rows = _gold_regime(root)
    assert rows and rows[-1][1] == "TRENDING_UP"          # synthetic uptrend
    assert rows[-1][0] == bars[-1][0]


def test_window_slice(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=90, run_parity=False, screeners=["market_regime"])
    rows = _gold_regime(root)
    anchor = dt.date.fromisoformat(bars[-1][0])
    assert all(dt.date.fromisoformat(d) >= anchor - dt.timedelta(days=90) for d, _, _ in rows)
    # regime_days still chained from full history -> boundary count > 1 possible
    assert rows[0][2] >= 1


def test_idempotent(env):
    root, live, bars = env
    import hashlib
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False, screeners=["market_regime"])
    h1 = hashlib.sha256((root / "psx_serving" / "parquet" / "market_regime.parquet").read_bytes()).hexdigest()
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False, screeners=["market_regime"])
    h2 = hashlib.sha256((root / "psx_serving" / "parquet" / "market_regime.parquet").read_bytes()).hexdigest()
    assert h1 == h2


def test_parity_clean_when_live_is_a_gapless_subset(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False, screeners=["market_regime"])
    gold = _gold_regime(root)
    # seed a live market_regime with the same rows minus the last 3 (a trailing
    # gap, not an interior one) -> Gold is a clean superset
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE market_regime (date TEXT PRIMARY KEY, regime TEXT, "
                "regime_days INT, ema_20 REAL, atr_pct REAL)")
    con.executemany("INSERT INTO market_regime VALUES (?,?,?,?,?)",
                    [(d, r, dd, None, None) for d, r, dd in gold[:-3]])
    con.commit(); con.close()

    res = gold_build.build(root / "psx_serving", window_days=730, run_parity=True, screeners=["market_regime"])
    rep = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())
    assert rep["market_regime"]["status"] == "clean"
    assert rep["market_regime"]["only_live"] == []
    assert rep["market_regime"]["pre_gap_residual"] == []


def test_interior_disagreement_is_residual(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False, screeners=["market_regime"])
    gold = _gold_regime(root)
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE market_regime (date TEXT PRIMARY KEY, regime TEXT, "
                "regime_days INT, ema_20 REAL, atr_pct REAL)")
    # same dates, but flip one interior regime label -> genuine pre-gap residual
    rows = [(d, ("RANGING" if i == 50 else r), dd, None, None)
            for i, (d, r, dd) in enumerate(gold)]
    con.executemany("INSERT INTO market_regime VALUES (?,?,?,?,?)", rows)
    con.commit(); con.close()

    gold_build.build(root / "psx_serving", window_days=730, run_parity=True, screeners=["market_regime"])
    rep = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())
    assert rep["market_regime"]["status"] == "residual"
    assert rep["market_regime"]["pre_gap_residual"] == [gold[50][0]]


def test_never_writes_psx_data_db(env):
    root, live, bars = env
    before = live.read_bytes() if live.exists() else None
    gold_build.build(root / "psx_serving", window_days=730, run_parity=True, screeners=["market_regime"])
    assert (live.read_bytes() if live.exists() else None) == before
    text = open(gold_build.__file__).read()
    # every sqlite3.connect that touches a REAL db (live psx_data.db for parity,
    # frozen baseline for stock_market_cap) opens it strictly read-only; the only
    # writable connect is the throwaway recompute scratch under tempfile.mkdtemp.
    n = text.count("sqlite3.connect")
    assert n >= 1
    ro = (text.count('sqlite3.connect(f"file:{live_db}?mode=ro&immutable=1"')
          + text.count('sqlite3.connect(f"file:{baseline_db}?mode=ro&immutable=1"'))
    scratch = text.count("sqlite3.connect(str(scratch))")
    assert ro + scratch == n, f"{n - ro - scratch} sqlite3.connect call(s) touch a real db writable"
    assert "tempfile.mkdtemp" in text and 'scratch = tmp / "recompute.db"' in text


# ------------------------------------------------------- stock_signals (3.3b)

def _gold_ss(root, cols="date, symbol, rs_rank, rs_score_20, bos_flag"):
    import duckdb
    c = duckdb.connect(str(root / "psx_serving" / "psx_serving.duckdb"), read_only=True)
    try:
        return c.execute(f"SELECT {cols} FROM stock_signals ORDER BY date, rs_rank").fetchall()
    finally:
        c.close()


_SS_LIVE_DDL = """CREATE TABLE stock_signals (
    date TEXT, symbol TEXT, rs_score_20 REAL, rs_score_50 REAL,
    rs_rank INTEGER, rs_rank_prev INTEGER, rank_change INTEGER, sector_rs_rank INTEGER,
    base_tightness REAL, bos_flag INTEGER, vol_contraction REAL, avg_vol_10d REAL,
    pivot_high REAL, pivot_distance_pct REAL, stage2_bull INTEGER,
    close_above_ema50 INTEGER, ema50_slope_pos INTEGER, base_duration INTEGER,
    overhead_clear INTEGER, near_pivot_days INTEGER,
    close_above_ema150 INTEGER, ema150_slope_pos INTEGER)"""


def test_stock_signals_built_and_windowed(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False, screeners=["market_regime", "stock_signals"])
    rows = _gold_ss(root)
    assert rows
    anchor = dt.date.fromisoformat(bars[-1][0])
    assert all(dt.date.fromisoformat(d) >= anchor - dt.timedelta(days=200) for d, *_ in rows)
    # rs_rank is a dense 1..N cross-section per date
    from collections import defaultdict
    by_date = defaultdict(list)
    for d, sym, rank, *_ in rows:
        by_date[d].append(rank)
    for d, ranks in by_date.items():
        assert sorted(ranks) == list(range(1, len(ranks) + 1))
    assert (root / "psx_serving" / "parquet" / "stock_signals.parquet").exists()


def test_stock_signals_idempotent(env):
    root, live, bars = env
    import hashlib
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False, screeners=["market_regime", "stock_signals"])
    h1 = hashlib.sha256((root / "psx_serving" / "parquet" / "stock_signals.parquet").read_bytes()).hexdigest()
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False, screeners=["market_regime", "stock_signals"])
    h2 = hashlib.sha256((root / "psx_serving" / "parquet" / "stock_signals.parquet").read_bytes()).hexdigest()
    assert h1 == h2


def _seed_live_ss_from_gold(root, live, mutate=None):
    import duckdb
    c = duckdb.connect(str(root / "psx_serving" / "psx_serving.duckdb"), read_only=True)
    cols = [d[0] for d in c.execute("SELECT * FROM stock_signals LIMIT 0").description]
    g = c.execute(f"SELECT {','.join(cols)} FROM stock_signals").fetchall()
    c.close()
    rows = [list(r) for r in g]
    if mutate:
        mutate(rows, cols)
    con = sqlite3.connect(live)
    con.execute(_SS_LIVE_DDL)
    con.executemany(f"INSERT INTO stock_signals ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})", rows)
    con.commit(); con.close()


def test_stock_signals_parity_clean_when_live_matches(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False, screeners=["market_regime", "stock_signals"])
    _seed_live_ss_from_gold(root, live)
    gold_build.build(root / "psx_serving", window_days=200, run_parity=True, screeners=["market_regime", "stock_signals"])
    ss = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())["stock_signals"]
    assert ss["status"] == "clean", ss
    assert ss["rs_score_20_mismatch_total"] == 0
    assert ss["hard_column_mismatch_total"] == 0
    assert ss["lookback_flag_flip_total"] == 0
    assert ss["only_live_genuine_total"] == 0
    assert ss["live_excluded_sector_ranked"]["total"] == 0
    assert ss["gold_rank_self_inconsistencies_total"] == 0


def test_stock_signals_parity_flags_rs_score_diff(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False, screeners=["market_regime", "stock_signals"])

    def _bump_one_score(rows, cols):
        si, ci = cols.index("symbol"), cols.index("rs_score_20")
        target = rows[0][si]
        for r in rows:
            if r[si] == target and r[ci] is not None:
                r[ci] = r[ci] + 5.0        # shared symbol, now disagrees with Gold

    _seed_live_ss_from_gold(root, live, mutate=_bump_one_score)
    gold_build.build(root / "psx_serving", window_days=200, run_parity=True, screeners=["market_regime", "stock_signals"])
    ss = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())["stock_signals"]
    assert ss["status"] == "residual"
    assert ss["rs_score_20_mismatch_total"] >= 1


def test_stock_signals_excludes_excluded_sectors(tmp_path, monkeypatch):
    """§118 Defect A: Gold's build_stock_signals must drop config.EXCLUDED_SECTORS
    (which live's _load_universe does not filter). An excluded-sector symbol in
    Silver stock_metadata + prices must NOT get a stock_signals row, and the
    parity check must classify a live-ranked excluded symbol as
    `live_excluded_sector`, not a genuine `only_live`."""
    import config
    root = tmp_path / "KIRAN_ARCHIVE"
    (root / "psx_serving").mkdir(parents=True)
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(gold_build, "ARCHIVE_ROOT", root)
    live = tmp_path / "psx_data.db"
    monkeypatch.setattr(gold_build, "LIVE_DB", live)

    bars = _bars()
    excl_sector = sorted(config.EXCLUDED_SECTORS)[0]
    _write_index(root, bars)
    _write_prices_anchor(root, bars)
    _write_silver(root, bars, extra_syms=[("ZEXC", excl_sector)])

    gold_build.build(root / "psx_serving", window_days=200, run_parity=False, screeners=["market_regime", "stock_signals"])
    import duckdb
    c = duckdb.connect(str(root / "psx_serving" / "psx_serving.duckdb"), read_only=True)
    zexc = c.execute("SELECT count(*) FROM stock_signals WHERE symbol = 'ZEXC'").fetchone()[0]
    c.close()
    assert zexc == 0, "excluded-sector symbol must not be ranked in Gold"

    # live has ZEXC ranked (like live post-2026-08-03) -> parity: excluded, not genuine
    def _add_zexc(rows, cols):
        di, si = cols.index("date"), cols.index("symbol")
        seen = {}
        for r in list(rows):
            d = r[di]
            if d not in seen:
                seen[d] = list(r)
                seen[d][si] = "ZEXC"
                rows.append(seen[d])

    _seed_live_ss_from_gold(root, live, mutate=_add_zexc)
    gold_build.build(root / "psx_serving", window_days=200, run_parity=True, screeners=["market_regime", "stock_signals"])
    ss = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())["stock_signals"]
    assert ss["status"] == "clean", ss
    assert ss["only_live_genuine_total"] == 0
    assert ss["live_excluded_sector_ranked"]["total"] >= 1


# ------------------------------------------------------- sector_signals (3.3c)

def test_sector_signals_built_stages_windowed_and_parity(env):
    """3.3c: build_sector_signals reuses sector_signals._compute_and_write_
    sector_signals_for_date_sqlite verbatim, produces the four-stage `sector_stage`
    grade per sector, drops EXCLUDED_SECTORS, windows the output, and passes
    RECOMPUTE parity (same function, same inputs, SQLite vs DuckDB)."""
    import config
    root, live, bars = env
    scr = ["market_regime", "stock_signals", "sector_signals"]

    r = gold_build.build(root / "psx_serving", window_days=15, run_parity=True, screeners=scr)
    assert "sector_signals" in r["rows"]

    import duckdb
    c = duckdb.connect(str(root / "psx_serving" / "psx_serving.duckdb"), read_only=True)
    rows = c.execute("SELECT date, sector, rs_rank, sector_stage, composite_score "
                     "FROM sector_signals ORDER BY date, rs_rank").fetchall()
    sectors = {s for _, s, *_ in rows}
    stages = {st for *_, st, _ in rows if st is not None}
    c.close()

    assert rows
    anchor = dt.date.fromisoformat(bars[-1][0])
    assert all(dt.date.fromisoformat(d) >= anchor - dt.timedelta(days=15) for d, *_ in rows)
    # only tradeable sectors (env's _SYMS sectors), none excluded
    assert sectors <= {s for _, s in _SYMS}
    assert not (sectors & config.EXCLUDED_SECTORS)
    # the four-stage grade is populated (>=200 synthetic bars -> real stages)
    assert stages and stages <= {"Stage 1", "Stage 2", "Stage 3", "Stage 4"}
    assert (root / "psx_serving" / "parquet" / "sector_signals.parquet").exists()

    rep = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())["sector_signals"]
    assert rep["status"] == "clean", rep
    assert rep["sector_set_mismatch_dates"] == []
    assert all(v == 0 for v in rep["column_mismatch_totals"].values()), rep["column_mismatch_totals"]
    assert rep["cells_compared"] > 0


# ---------------------------------------- boring_signals + leaders_scan (3.3d)

def _jump_bars(start="2025-01-01", n=450, jump_from="2026-07-17", factor=1.08):
    """Like _bars(), but with a sustained multiplicative jump from `jump_from`
    onward -- boring_signals' RS_60-conditioned Donchian breakout needs a
    genuine >1% break above the rolling N-day high to fire at all; a smooth
    drift+sine series alone (as used by every earlier 3.3x test) never
    produces one once the trend has been running a while."""
    bars = _bars(start=start, n=n)
    out = []
    for ds, hi, lo, cl, op in bars:
        f = factor if ds >= jump_from else 1.0
        out.append((ds, hi * f, lo * f, cl * f, op * f))
    return out


def test_boring_signals_and_leaders_scan_built_and_parity(tmp_path, monkeypatch):
    """3.3d: build_boring_signals / build_leaders_scan reuse boring_signals.py's
    / leaders_scan.py's compute verbatim by import (both now take an optional
    `conn`, mirroring sector_signals.py's dialect fix). Parity is
    recompute-based from the start (the 3.3c lesson -- live's stored rows are
    not a reliable comparison target in general for this program)."""
    import config
    import leaders_scan as lsc

    root = tmp_path / "KIRAN_ARCHIVE"
    (root / "psx_serving").mkdir(parents=True)
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(gold_build, "ARCHIVE_ROOT", root)
    live = tmp_path / "psx_data.db"
    monkeypatch.setattr(gold_build, "LIVE_DB", live)
    # the 5-symbol synthetic universe rarely reaches leaders_scan's real
    # MIN_PICK_SCORE (tuned for a 300+ stock population) -- lower it so
    # save_top_picks()'s selection path is actually exercised, not just a
    # documented-empty "nothing qualified" no-op.
    monkeypatch.setattr(lsc, "MIN_PICK_SCORE", 1)

    bars = _jump_bars()
    _write_index(root, bars)
    _write_prices_anchor(root, bars)
    _write_silver(root, bars)

    scr = ["market_regime", "stock_signals", "sector_signals", "boring_signals", "leaders_scan"]
    r = gold_build.build(root / "psx_serving", window_days=730, run_parity=True, screeners=scr)
    assert "boring_signals" in r["rows"] and "leaders_scan" in r["rows"]

    import duckdb
    c = duckdb.connect(str(root / "psx_serving" / "psx_serving.duckdb"), read_only=True)
    try:
        bs_rows = c.execute(
            "SELECT symbol, signal_date, lookback_n, status, resolution_type, strategy_confirmed "
            "FROM boring_signals ORDER BY signal_date, symbol, lookback_n").fetchall()
        ls_rows = c.execute("SELECT scan_date, setup_type, symbol FROM leaders_scan").fetchall()
        floor_min = c.execute("SELECT min(signal_date) FROM boring_signals").fetchone()[0]
    finally:
        c.close()

    # the injected jump fires at least one breakout, on/after the go-live floor
    assert bs_rows, "expected at least one boring_signals row from the injected jump"
    assert floor_min >= "2026-07-10"
    assert {r[3] for r in bs_rows} <= {"Pending", "Stopped"}     # never "Executed" -- no mark_executed in Gold
    assert ls_rows
    assert (root / "psx_serving" / "parquet" / "boring_signals.parquet").exists()
    assert (root / "psx_serving" / "parquet" / "leaders_scan.parquet").exists()

    parity = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())

    bsp = parity["boring_signals"]
    assert bsp["status"] == "clean", bsp
    assert bsp["only_gold"] == [] and bsp["only_recompute"] == []
    assert all(v == 0 for v in bsp["column_mismatch_totals"].values()), bsp["column_mismatch_totals"]
    assert bsp["rows_compared"] > 0

    lsp = parity["leaders_scan"]
    assert lsp["status"] == "clean", lsp
    ls_rep = lsp["leaders_scan"]
    assert ls_rep["only_gold"] == [] and ls_rep["only_recompute"] == []
    assert all(v == 0 for v in ls_rep["column_mismatch_totals"].values()), ls_rep["column_mismatch_totals"]
    assert ls_rep["rows_compared"] > 0
    tp_rep = lsp["leaders_top_picks"]
    assert tp_rep["only_gold"] == [] and tp_rep["only_recompute"] == []
    assert all(v == 0 for v in tp_rep["column_mismatch_totals"].values()), tp_rep["column_mismatch_totals"]
    # the tiny synthetic universe produces exact-tie candidates (final_score,
    # vol_ratio_today) that save_top_picks()'s own ORDER BY has no further
    # tiebreak for -- confirmed engine-arbitrary against Gold's own
    # leaders_scan pool, not counted against `clean`. Just confirm the
    # classifier actually ran (a non-negative count), not a specific number.
    assert tp_rep["tie_break_residual_n"] >= 0


# --------------------------- recovery_signals + portfolio_signals + setup_log (3.3e)

def _recovery_symbol_rows(symbol="RCVSYM", n=320, start="2024-01-01"):
    """One extra symbol shaped to trigger `signal_engine._scan_recovery_
    candidates`'s WATCHLIST gates: a long flat pre-history (pre_high=100), a
    sharp >=30% decline, then a short flat base with a volume-contraction-
    then-surge shape (Gates 8/9). The shared `_bars()`/`_write_prices_
    anchor()` fixtures never decline this much and keep volume under the
    800k avg_vol_20d floor (500k-799k range), so recovery_signals never
    fires on them. The base is kept well under `_base_scan`'s own `max_lb=90`
    lookback cap (a longer flat base gets silently truncated to the last 90
    bars by that cap, regardless of price flatness beyond it, which pushes a
    surge/contraction shape placed further back out of the detected window --
    found by a failed first attempt at a 110-day base). Uses the SAME
    (start, n) as `_bars()` so the weekday-skipped dates line up exactly with
    the rest of the synthetic universe.
    """
    rows, d, day = [], dt.date.fromisoformat(start), 0
    decline_from = n - 40   # 5-session decline + 35-session base at the end
    base_from = decline_from + 5
    while len(rows) < n:
        if d.weekday() < 5:
            if day < decline_from:
                price, vol = 100.0, 900_000
            elif day < base_from:
                price = 100.0 - (day - decline_from) * 8.0     # 100 -> 60 over 5 sessions
                vol = 900_000
            else:
                bd = day - base_from
                base_len = n - base_from
                price = 60.0 + 0.2 * math.sin(bd)
                if bd >= base_len - 5:
                    vol = 350_000            # Gate 8: contraction in the last 5 base bars
                elif 10 <= bd < 15:
                    vol = 2_000_000          # Gate 9: a prior surge within the base
                else:
                    vol = 1_000_000
            rows.append((symbol, d.isoformat(), round(price, 4), vol,
                        round(price + 0.5, 4), round(price - 0.5, 4), round(price, 4)))
            day += 1
        d += dt.timedelta(days=1)
    return rows


def _write_recovery_symbol(root, symbol="RCVSYM", sector="COMMERCIAL BANKS", n=320, start="2024-01-01"):
    """Append `symbol` to Bronze `prices` + Silver `prices_adjusted`/
    `sectors`/`stock_metadata` on top of whatever `_write_prices_anchor`/
    `_write_silver` already wrote -- must run AFTER those."""
    from archive import silver_build

    rows = _recovery_symbol_rows(symbol=symbol, n=n, start=start)
    by_year: dict[str, list] = {}
    for r in rows:
        by_year.setdefault(r[1][:4], []).append(r)
    for year, rs in by_year.items():
        t = pa.table({k: [r[i] for r in rs] for i, k in enumerate(bronze_ingest.PRICES_COLUMNS)},
                     schema=bronze_ingest.PRICES_SCHEMA)
        fp = root / "prices_archive" / "bronze" / "prices" / f"year={year}" / "data_recovery.parquet"
        fp.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, fp, **bronze_ingest.PARQUET_OPTS)

        adj_rs = [(sym, ds, cl, vol, hi, lo, op, 0, 0, 0) for sym, ds, cl, vol, hi, lo, op in rs]
        t2 = pa.table({k: [r[i] for r in adj_rs] for i, k in enumerate(silver_build.PRICES_ADJ_COLUMNS)},
                      schema=silver_build.PRICES_ADJ_SCHEMA)
        fp2 = root / "prices_archive" / "silver" / "prices_adjusted" / f"year={year}" / "data_recovery.parquet"
        fp2.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t2, fp2, **bronze_ingest.PARQUET_OPTS)

    # sectors + stock_metadata are small single-file tables -- rewrite whole,
    # extended with the new symbol (same shape _write_silver itself writes).
    sct = pa.table({"symbol": [s for s, _ in _SYMS] + [symbol],
                    "sector": [x for _, x in _SYMS] + [sector]},
                   schema=pa.schema([("symbol", pa.string()), ("sector", pa.string())]))
    pq.write_table(sct, root / "prices_archive" / "silver" / "sectors" / "sectors.parquet",
                   **bronze_ingest.PARQUET_OPTS)

    syms = list(_SYMS) + [(symbol, sector)]
    n_syms = len(syms)
    mt = pa.table({"symbol": [s for s, _ in syms], "company_name": [s for s, _ in syms],
                  "sector": [x for _, x in syms], "listing_date": ["2024-01-01"] * n_syms,
                  "delisting_date": [None] * n_syms, "is_active": [1] * n_syms,
                  "in_kse100": [1] * n_syms, "notes": [None] * n_syms},
                 schema=pa.schema([
                     ("symbol", pa.string()), ("company_name", pa.string()),
                     ("sector", pa.string()), ("listing_date", pa.string()),
                     ("delisting_date", pa.string()), ("is_active", pa.int64()),
                     ("in_kse100", pa.int64()), ("notes", pa.string())]))
    pq.write_table(mt, root / "prices_archive" / "silver" / "stock_metadata" / "stock_metadata.parquet",
                   **bronze_ingest.PARQUET_OPTS)


def test_recovery_portfolio_setup_log_built_and_parity(env):
    """3.3e: `build_recovery_signals` / `build_portfolio_signals` port
    `signal_engine.py`'s recovery/portfolio screeners (extract-method +
    parameter-injection refactors -- `_scan_recovery_candidates` /
    `compute_portfolio_candidates` reused verbatim); `build_setup_log` ports
    `backfill_setup_log.py`'s daily hook (`_insert_setup_log_for_date` /
    `compute_forward_returns.main` reused verbatim). All three pass
    RECOMPUTE parity (same reused functions/queries, SQLite vs DuckDB).

    `trade_setups` is deliberately NOT ported -- see `build_setup_log`'s
    docstring (`processor.run_analysis()` hardcodes `support_setups = []`
    since 2026-07-23; the only automated writer of `trade_setups` is
    permanently dead code, so there is nothing live to port).
    """
    root, live, bars = env
    _write_recovery_symbol(root)

    scr = ["market_regime", "stock_signals", "sector_signals",
          "recovery_signals", "portfolio_signals", "setup_log"]
    r = gold_build.build(root / "psx_serving", window_days=730, run_parity=True, screeners=scr)
    for t in ("recovery_signals", "portfolio_signals", "setup_log"):
        assert t in r["rows"], r

    assert "trade_setups" not in gold_build.SCREENERS
    assert "trade_setups" not in gold_build.PARITY

    import duckdb
    c = duckdb.connect(str(root / "psx_serving" / "psx_serving.duckdb"), read_only=True)
    try:
        rs_rows = c.execute("SELECT as_of_date, symbol, list_type FROM recovery_signals").fetchall()
        ps_rows = c.execute("SELECT DISTINCT as_of_date FROM portfolio_signals").fetchall()
        sl_types = c.execute("SELECT DISTINCT setup_type FROM setup_log").fetchall()
    finally:
        c.close()

    # the injected decline+base fires at least one WATCHLIST/TRIGGERED row
    assert rs_rows, "expected at least one recovery_signals row from the injected decline+base"
    assert {row[2] for row in rs_rows} <= {"TRIGGERED", "WATCHLIST"}
    assert any(row[1] == "RCVSYM" for row in rs_rows)
    # "latest date only" scope (see build_recovery_signals's docstring) -- a
    # single as_of_date, not a per-trading-day backfill.
    assert len({row[0] for row in rs_rows}) == 1

    assert ps_rows, "expected portfolio_signals rows (320 bars >= MIN_HISTORY)"
    assert len(ps_rows) == 1, "latest-date-only scope, same as recovery_signals"

    assert sl_types, "expected at least one setup_log row"

    assert (root / "psx_serving" / "parquet" / "recovery_signals.parquet").exists()
    assert (root / "psx_serving" / "parquet" / "portfolio_signals.parquet").exists()
    assert (root / "psx_serving" / "parquet" / "setup_log.parquet").exists()

    parity = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())
    for t in ("recovery_signals", "portfolio_signals", "setup_log"):
        rep = parity[t]
        assert rep["status"] == "clean", (t, rep)
        assert rep["only_gold"] == [] and rep["only_recompute"] == [], (t, rep)
        assert all(v == 0 for v in rep["column_mismatch_totals"].values()), (t, rep["column_mismatch_totals"])
        assert rep["rows_compared"] > 0, (t, rep)


# --------------------------------------------- full-pipeline idempotency (3.3f)

def test_full_pipeline_idempotent_all_screeners(tmp_path, monkeypatch):
    """3.3f: "Idempotency test per transform (re-run -> identical output)" --
    closes that Phase 3 checklist item for every registered screener in ONE
    combined run, not just the two (`market_regime`/`stock_signals`) that had
    a dedicated hash-comparison test before this task. Also exercises "Gold:
    2-yr slice, run every registered screener, grade every sector" for real --
    every earlier 3.3x test built a SUBSET of `SCREENERS` (via `--only`), for
    speed or to isolate one port; this is the first test that runs
    `screeners=None` (the full registry, in its real dependency order) end to
    end, on the default 730-day window.

    Combines every special fixture requirement from the individual screener
    tests into one universe: `_jump_bars()` (boring_signals needs a genuine
    Donchian breakout), `_write_recovery_symbol()` (recovery_signals needs a
    >=30% decline + volume-shaped base), and `leaders_scan.MIN_PICK_SCORE`
    lowered (the tiny synthetic universe never reaches the real threshold) --
    so every one of the 8 tables actually gets non-trivial rows, not just an
    idempotent-because-empty pass.
    """
    import hashlib
    import leaders_scan as lsc

    root = tmp_path / "KIRAN_ARCHIVE"
    (root / "psx_serving").mkdir(parents=True)
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(gold_build, "ARCHIVE_ROOT", root)
    live = tmp_path / "psx_data.db"
    monkeypatch.setattr(gold_build, "LIVE_DB", live)
    monkeypatch.setattr(lsc, "MIN_PICK_SCORE", 1)

    bars = _jump_bars()
    _write_index(root, bars)
    _write_prices_anchor(root, bars)
    _write_silver(root, bars)
    # _write_recovery_symbol's own defaults (start="2024-01-01", n=320) match
    # _bars() -- must be overridden here to match _jump_bars()'s actual date
    # range (start="2025-01-01", n=450), or RCVSYM's history sits in a
    # calendar period none of the other 5 symbols ever trade in.
    _write_recovery_symbol(root, start="2025-01-01", n=450)

    tables = list(gold_build.SCREENERS) + gold_build.REFERENCE_TABLES

    def _hashes():
        return {
            t: hashlib.sha256((root / "psx_serving" / "parquet" / f"{t}.parquet").read_bytes()).hexdigest()
            for t in tables
        }

    r1 = gold_build.build(root / "psx_serving", window_days=730, run_parity=False, screeners=None)
    assert set(r1["screeners"]) == set(gold_build.SCREENERS)
    h1 = _hashes()

    r2 = gold_build.build(root / "psx_serving", window_days=730, run_parity=False, screeners=None)
    h2 = _hashes()

    assert h1 == h2, {t: (h1[t], h2[t]) for t in tables if h1[t] != h2[t]}
    # a genuinely non-trivial run, not idempotent-because-every-table-is-empty
    assert all(r2["rows"].get(t, 0) > 0 for t in tables), r2["rows"]


# ------------------------------------- consolidated signal-parity report (3.3f)

def test_consolidated_parity_report_covers_every_active_screener(env):
    """3.3f: `build(..., run_parity=True)` auto-writes a Markdown consolidated
    parity report (`GoldStore.parity_report_path`, `_gold_parity_report.md`)
    alongside `_gold_parity.json` -- closes Phase 3's "signal parity check ...
    differences explained" checklist item as its own reviewable artifact,
    without the owner needing to read raw JSON. Must cover every screener
    that actually ran (one row each) -- not silently drop a table whose
    parity function returned an unusual shape (`skipped`, or `leaders_scan`'s
    nested sub-report). `gold_build.write_consolidated_parity_report()` (the
    standalone regenerate-on-demand entry point) must reproduce the same text
    from the same `_gold_parity.json`.
    """
    root, live, bars = env
    scr = ["market_regime", "stock_signals", "sector_signals"]
    gold_build.build(root / "psx_serving", window_days=15, run_parity=True, screeners=scr)

    store = gold_build.GoldStore(root / "psx_serving")
    assert store.parity_report_path.exists()
    text = store.parity_report_path.read_text(encoding="utf-8")

    for t in scr:
        assert f"`{t}`" in text
    assert "clean" in text

    regenerated = gold_build.write_consolidated_parity_report(root / "psx_serving")
    assert regenerated == text
    assert "clean" in text
