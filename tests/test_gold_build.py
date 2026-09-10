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


def _write_prices_anchor(root, max_date):
    """gold_build reads bronze/prices only for the window anchor (max date)."""
    t = pa.table({"symbol": ["HBL"], "date": [max_date], "close": [100.0],
                  "volume": [1], "high": [101.0], "low": [99.0], "open": [100.0]},
                 schema=bronze_ingest.PRICES_SCHEMA)
    fp = root / "prices_archive" / "bronze" / "prices" / f"year={max_date[:4]}" / "data.parquet"
    fp.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(t, fp, **bronze_ingest.PARQUET_OPTS)


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    (root / "psx_serving").mkdir(parents=True)
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(gold_build, "ARCHIVE_ROOT", root)

    bars = _bars()
    _write_index(root, bars)
    _write_prices_anchor(root, bars[-1][0])

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
    assert 'sqlite3.connect(f"file:{live_db}?mode=ro&immutable=1"' in text
    assert text.count("sqlite3.connect") == 1
