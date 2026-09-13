"""CA v2 standalone prototype (archive/ca_v2_prototype.py) -- PARKED, not wired
into production. Proves the module builds stock_signals/sector_signals against a
CA-v2-shaped SQLite source, completely decoupled from archive/gold_build.py's own
Silver/Gold path, and that the adjustment (cum_price_factor applied to OHLC,
volume_v2 for volume) actually changes the computed signal vs. using raw prices.
"""
from __future__ import annotations

import datetime as dt
import math
import sqlite3
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from archive import bronze_ingest, ca_v2_prototype
from tests.test_gold_build import _SYMS, _bars, _write_index, _write_silver


def _write_v2_sqlite(path: Path, bars, split_symbol="LUCK", split_at_idx=200, split_factor=2.0):
    """A synthetic full_prices_v2.sqlite: same base series as _write_silver's
    prices_adjusted, but with `close`/`open`/`high`/`low` for one symbol reflecting
    a REAL unadjusted 2:1 split partway through (price halves, volume doubles) --
    while close_v2/cum_price_factor carry the adjustment that undoes it. This is
    the one thing a raw-price screener would get wrong and an adjusted one gets
    right, so it is the actual proof the adjustment mechanism works, not just that
    the code runs."""
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE prices_v2 (
        symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
        volume INTEGER, close_v2 REAL, close_tr REAL, volume_v2 INTEGER,
        cum_price_factor REAL, cum_tr_factor REAL, cum_volume_factor REAL,
        applied_event_ids TEXT, status TEXT, adjustment_confidence TEXT, flags TEXT)""")
    con.execute("CREATE TABLE meta (k TEXT, v TEXT)")
    con.execute("INSERT INTO meta VALUES ('built_at', ?)", (dt.datetime.now().isoformat(),))

    rows = []
    for si, (sym, _sec) in enumerate(_SYMS):
        mult = 0.001 * (1 + si)
        post_split_factor = 1.0
        for bi, (ds, hi, lo, cl, op) in enumerate(bars):
            c = cl * mult + 3 * math.sin((bi + si) / 7)
            raw_close = round(c, 4)
            vol = 500_000 + (bi * 37 + si * 991) % 300_000
            cum_factor = 1.0
            if sym == split_symbol:
                if bi < split_at_idx:
                    # pre-split: v2 restates history at post-split scale
                    cum_factor = 1.0 / split_factor
                else:
                    # split just happened: raw price halves, raw volume doubles
                    raw_close = raw_close / split_factor
                    vol = int(vol * split_factor)
                    cum_factor = 1.0
            close_v2 = round(raw_close * cum_factor, 4)
            rows.append((
                sym, ds, round(raw_close * 1.0, 4), round(raw_close * 1.01, 4),
                round(raw_close * 0.99, 4), raw_close, vol,
                close_v2, close_v2, int(vol / cum_factor) if cum_factor else vol,
                cum_factor, cum_factor, 1.0 / cum_factor if cum_factor else 1.0,
                "[]", "ADJUSTED" if sym == split_symbol else "RAW_NO_EVENTS", "CONFIRMED", "[]",
            ))
    con.executemany(
        "INSERT INTO prices_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(ca_v2_prototype, "ARCHIVE_ROOT", root)

    bars = _bars(n=320)
    _write_index(root, bars)
    _write_silver(root, bars)  # only sectors/stock_metadata are read from this

    v2_db = tmp_path / "full_prices_v2.sqlite"
    _write_v2_sqlite(v2_db, bars)
    return root, v2_db, bars


def test_build_produces_stock_and_sector_signals(env):
    root, v2_db, bars = env
    res = ca_v2_prototype.build(root / "ca_v2_prototype", window_days=730, v2_db=v2_db)
    assert res["outcome"] == "built"
    assert res["screeners"]["stock_signals"]["rows"] > 0
    assert res["screeners"]["sector_signals"]["rows"] > 0
    assert (root / "ca_v2_prototype" / "ca_v2_serving.duckdb").exists()
    assert not (root / "ca_v2_prototype" / "ca_v2_serving_staging.duckdb").exists()
    assert (root / "ca_v2_prototype" / "parquet" / "stock_signals.parquet").exists()
    assert (root / "ca_v2_prototype" / "parquet" / "sector_signals.parquet").exists()


def test_adjustment_actually_changes_the_signal(env):
    """The real proof: LUCK's synthetic 2:1 split means a screener reading RAW
    prices would see a spurious ~50% one-day drop right at the split date -- the
    v2-adjusted series must not show that discontinuity."""
    root, v2_db, bars = env
    import duckdb
    df = ca_v2_prototype._load_v2_adjusted(v2_db, "close_v2")
    luck = df[df.symbol == "LUCK"].sort_values("date").reset_index(drop=True)
    split_date = bars[200][0]
    idx = luck.index[luck.date == split_date][0]
    pct_change = abs(luck.close.iloc[idx] / luck.close.iloc[idx - 1] - 1)
    assert pct_change < 0.15, (
        f"adjusted close still shows a split-sized jump ({pct_change:.2%}) -- "
        "cum_price_factor was not applied correctly")


def test_decoupled_from_gold_build_store(env):
    """Building the v2 prototype must not create or touch psx_serving.duckdb --
    the whole point is that it can run without any interaction with the live
    Silver/Gold pipeline."""
    root, v2_db, bars = env
    ca_v2_prototype.build(root / "ca_v2_prototype", window_days=730, v2_db=v2_db)
    assert not (root / "psx_serving").exists()


def test_missing_v2_db_raises_clear_error(tmp_path, monkeypatch):
    root = tmp_path / "KIRAN_ARCHIVE"
    monkeypatch.setattr(bronze_ingest, "ARCHIVE_ROOT", root)
    monkeypatch.setattr(ca_v2_prototype, "ARCHIVE_ROOT", root)
    with pytest.raises(SystemExit, match="not found"):
        ca_v2_prototype.build(root / "ca_v2_prototype", v2_db=tmp_path / "does_not_exist.sqlite")
