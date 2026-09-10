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


def _write_prices_anchor(root, max_date):
    """gold_build reads bronze/prices only for the window anchor (max date)."""
    t = pa.table({"symbol": ["HBL"], "date": [max_date], "close": [100.0],
                  "volume": [1], "high": [101.0], "low": [99.0], "open": [100.0]},
                 schema=bronze_ingest.PRICES_SCHEMA)
    fp = root / "prices_archive" / "bronze" / "prices" / f"year={max_date[:4]}" / "data.parquet"
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
    _write_prices_anchor(root, bars[-1][0])
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
    res = gold_build.build(root / "psx_serving", window_days=730, run_parity=False)
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
    gold_build.build(root / "psx_serving", window_days=90, run_parity=False)
    rows = _gold_regime(root)
    anchor = dt.date.fromisoformat(bars[-1][0])
    assert all(dt.date.fromisoformat(d) >= anchor - dt.timedelta(days=90) for d, _, _ in rows)
    # regime_days still chained from full history -> boundary count > 1 possible
    assert rows[0][2] >= 1


def test_idempotent(env):
    root, live, bars = env
    import hashlib
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False)
    h1 = hashlib.sha256((root / "psx_serving" / "parquet" / "market_regime.parquet").read_bytes()).hexdigest()
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False)
    h2 = hashlib.sha256((root / "psx_serving" / "parquet" / "market_regime.parquet").read_bytes()).hexdigest()
    assert h1 == h2


def test_parity_clean_when_live_is_a_gapless_subset(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False)
    gold = _gold_regime(root)
    # seed a live market_regime with the same rows minus the last 3 (a trailing
    # gap, not an interior one) -> Gold is a clean superset
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE market_regime (date TEXT PRIMARY KEY, regime TEXT, "
                "regime_days INT, ema_20 REAL, atr_pct REAL)")
    con.executemany("INSERT INTO market_regime VALUES (?,?,?,?,?)",
                    [(d, r, dd, None, None) for d, r, dd in gold[:-3]])
    con.commit(); con.close()

    res = gold_build.build(root / "psx_serving", window_days=730, run_parity=True)
    rep = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())
    assert rep["market_regime"]["status"] == "clean"
    assert rep["market_regime"]["only_live"] == []
    assert rep["market_regime"]["pre_gap_residual"] == []


def test_interior_disagreement_is_residual(env):
    root, live, bars = env
    gold_build.build(root / "psx_serving", window_days=730, run_parity=False)
    gold = _gold_regime(root)
    con = sqlite3.connect(live)
    con.execute("CREATE TABLE market_regime (date TEXT PRIMARY KEY, regime TEXT, "
                "regime_days INT, ema_20 REAL, atr_pct REAL)")
    # same dates, but flip one interior regime label -> genuine pre-gap residual
    rows = [(d, ("RANGING" if i == 50 else r), dd, None, None)
            for i, (d, r, dd) in enumerate(gold)]
    con.executemany("INSERT INTO market_regime VALUES (?,?,?,?,?)", rows)
    con.commit(); con.close()

    gold_build.build(root / "psx_serving", window_days=730, run_parity=True)
    rep = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())
    assert rep["market_regime"]["status"] == "residual"
    assert rep["market_regime"]["pre_gap_residual"] == [gold[50][0]]


def test_never_writes_psx_data_db(env):
    root, live, bars = env
    before = live.read_bytes() if live.exists() else None
    gold_build.build(root / "psx_serving", window_days=730, run_parity=True)
    assert (live.read_bytes() if live.exists() else None) == before
    text = open(gold_build.__file__).read()
    # every sqlite3.connect in the module is the read-only parity reference
    n = text.count("sqlite3.connect")
    assert n >= 1
    assert text.count('sqlite3.connect(f"file:{live_db}?mode=ro&immutable=1"') == n


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
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False)
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
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False)
    h1 = hashlib.sha256((root / "psx_serving" / "parquet" / "stock_signals.parquet").read_bytes()).hexdigest()
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False)
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
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False)
    _seed_live_ss_from_gold(root, live)
    gold_build.build(root / "psx_serving", window_days=200, run_parity=True)
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
    gold_build.build(root / "psx_serving", window_days=200, run_parity=False)

    def _bump_one_score(rows, cols):
        si, ci = cols.index("symbol"), cols.index("rs_score_20")
        target = rows[0][si]
        for r in rows:
            if r[si] == target and r[ci] is not None:
                r[ci] = r[ci] + 5.0        # shared symbol, now disagrees with Gold

    _seed_live_ss_from_gold(root, live, mutate=_bump_one_score)
    gold_build.build(root / "psx_serving", window_days=200, run_parity=True)
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
    _write_prices_anchor(root, bars[-1][0])
    _write_silver(root, bars, extra_syms=[("ZEXC", excl_sector)])

    gold_build.build(root / "psx_serving", window_days=200, run_parity=False)
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
    gold_build.build(root / "psx_serving", window_days=200, run_parity=True)
    ss = json.loads((root / "psx_serving" / "_gold_parity.json").read_text())["stock_signals"]
    assert ss["status"] == "clean", ss
    assert ss["only_live_genuine_total"] == 0
    assert ss["live_excluded_sector_ranked"]["total"] >= 1
