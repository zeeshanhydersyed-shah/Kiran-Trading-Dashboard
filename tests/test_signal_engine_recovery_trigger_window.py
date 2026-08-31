"""Trust Register TR-01 Phase 1a -- recovery_signals trigger-scan window.

`signal_engine.run_recovery_signals()` writes a single snapshot keyed to the
latest price date. The trigger scan used to look only at the last 5 trading
sessions (a hard-coded `all_dates[-5:]`), so any recovery-base trigger that
fired while the pipeline was not running for more than 5 sessions was silently
and permanently dropped -- the same class of defect as boring_signals' old
15-day window (audit ledger §89).

The fix widens that window to cover any gap since `recovery_signals` was last
written, capped at 30 sessions. These tests pin:

  * `_recovery_trigger_window()` -- the pure sizing function (min 5, widen to
    the gap, cap at 30, clamp to the available history, None-safe).
  * `_last_recovery_as_of()` -- the read-only MAX(as_of_date) probe: reads the
    real value, returns None on a missing table, never raises.
  * end to end: a trigger that fired 8 sessions ago is CAUGHT when the table is
    10 sessions stale, and is NOT caught on a normal run (window back to 5) --
    proving the widening is driven by the gap, not always-on.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys

import numpy as np
import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import database  # noqa: E402
import signal_engine  # noqa: E402

FIXTURE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fixtures", "psx_fixture.db")


# ---------------------------------------------------------------------------
# _recovery_trigger_window -- pure function
# ---------------------------------------------------------------------------

@pytest.fixture
def dates_28():
    # 28 consecutive business days
    return pd.bdate_range("2026-06-01", periods=28).to_numpy()


def test_window_none_is_minimum(dates_28):
    win, n = signal_engine._recovery_trigger_window(dates_28, None)
    assert n == 5
    assert win == set(dates_28[-5:])


def test_window_current_table_stays_minimum(dates_28):
    # last recorded == the newest session: 0 behind -> min window
    last = pd.Timestamp(dates_28[-1]).strftime("%Y-%m-%d")
    _, n = signal_engine._recovery_trigger_window(dates_28, last)
    assert n == 5


def test_window_widens_to_the_gap(dates_28):
    # last recorded == 10 sessions before the newest -> 10 sessions behind
    last = pd.Timestamp(dates_28[-11]).strftime("%Y-%m-%d")
    win, n = signal_engine._recovery_trigger_window(dates_28, last)
    assert n == 10
    assert win == set(dates_28[-10:])


def test_window_is_capped(dates_28):
    # a very old last-recorded date would imply 27 behind; cap is 30 but the
    # available history is only 28, so it clamps to len(all_dates)
    _, n = signal_engine._recovery_trigger_window(dates_28, "2020-01-01")
    assert n == 28


def test_window_cap_binds_when_history_is_long():
    long_dates = pd.bdate_range("2026-01-01", periods=120).to_numpy()
    _, n = signal_engine._recovery_trigger_window(long_dates, "2026-01-02")
    assert n == signal_engine._RECOVERY_TRIGGER_WINDOW_CAP == 30


def test_window_clamped_to_short_history():
    three = pd.bdate_range("2026-06-01", periods=3).to_numpy()
    _, n = signal_engine._recovery_trigger_window(three, None)
    assert n == 3


# ---------------------------------------------------------------------------
# _last_recovery_as_of -- read-only probe
# ---------------------------------------------------------------------------

def _recovery_schema() -> str:
    src = sqlite3.connect(f"file:{FIXTURE_DB}?mode=ro", uri=True)
    try:
        return src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='recovery_signals'").fetchone()[0]
    finally:
        src.close()


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"schema source not found: {FIXTURE_DB}")
    db = str(tmp_path / "rec.db")
    con = sqlite3.connect(db)
    con.execute(_recovery_schema())
    con.commit()
    con.close()
    monkeypatch.setattr(signal_engine, "_PG_URL", None)
    monkeypatch.setattr(signal_engine, "DB_PATH", db)
    return db


def _seed_as_of(db, as_of_date, symbol="AAA", list_type="WATCHLIST"):
    con = sqlite3.connect(db)
    con.execute(
        "INSERT INTO recovery_signals (as_of_date, symbol, list_type) "
        "VALUES (?, ?, ?)", (as_of_date, symbol, list_type))
    con.commit()
    con.close()


def test_last_recovery_as_of_reads_max(temp_db):
    _seed_as_of(temp_db, "2026-08-10")
    _seed_as_of(temp_db, "2026-08-25")
    _seed_as_of(temp_db, "2026-08-18")
    assert signal_engine._last_recovery_as_of() == "2026-08-25"


def test_last_recovery_as_of_none_when_empty(temp_db):
    assert signal_engine._last_recovery_as_of() is None


def test_last_recovery_as_of_never_raises(tmp_path, monkeypatch):
    # point at a DB file with no recovery_signals table at all
    db = str(tmp_path / "bare.db")
    sqlite3.connect(db).close()
    monkeypatch.setattr(signal_engine, "_PG_URL", None)
    monkeypatch.setattr(signal_engine, "DB_PATH", db)
    assert signal_engine._last_recovery_as_of() is None


# ---------------------------------------------------------------------------
# end to end -- a gap-era trigger is caught, a normal run does not reach back
# ---------------------------------------------------------------------------

def _synthetic_recovery_frame():
    """One symbol with a hand-built recovery-base trigger at index 67 -- 8
    sessions before the latest date (index 74). Every one of the screener's
    ~9 gates is passed by a wide margin on purpose: this test asserts the
    *scan window*, not the gate thresholds, and must not be fragile to a
    pandas/numpy version difference between the dev box and CI.

    Returns (rows, dates) where rows is the list-of-dicts shape
    database.get_sector_price_data_300d_active() yields.
    """
    n = 75
    d = pd.bdate_range("2026-04-01", periods=n)
    close = np.empty(n)
    vol = np.full(n, 1_000_000.0)

    # 0-14   pre-base plateau at 100  (pre_high)
    close[0:15] = 100.0
    # 15-45  deep decline plateau at 30  -> a hard cliff into the base so
    #        _base_scan() stops unambiguously at index 46 (drop >> 20%)
    close[15:46] = 30.0
    # 46-66  the base: a tight 52/54 oscillation (range ~4%, well under 20%)
    base = np.where(np.arange(46, 67) % 2 == 0, 52.0, 54.0)
    close[46:67] = base
    # base volume: baseline == median(vol[46:56]) == 1.0M; three 2x surges
    # inside the base (Gate 9 needs >=2 bars > 1.5x); the last 5 base bars
    # collapse to 0.15x (Gate 8 needs mean < 0.5 and >=3 bars < 0.6)
    for i in (48, 50, 52):
        vol[i] = 2_000_000.0
    vol[62:67] = 150_000.0
    # 67  the trigger: closes far above the base high, on ~9x volume,
    #     near the top of a wide day range
    close[67] = 80.0
    vol[67] = 10_000_000.0
    # 68-74  drift up after the trigger (keeps avg_vol_20d comfortably > 800k)
    close[68:75] = 82.0
    vol[68:75] = 2_000_000.0

    high = close + 2.0
    low = close - 2.0
    high[67], low[67] = 82.0, 78.0     # range 4; (80-78)/4 = 0.5 >= 0.40

    rows = [
        {
            "symbol": "RECOV", "sector": "CEMENT",
            "date": d[i].strftime("%Y-%m-%d"),
            "open": float(close[i]), "high": float(high[i]),
            "low": float(low[i]), "close": float(close[i]),
            "volume": float(vol[i]),
        }
        for i in range(n)
    ]
    return rows, [ts.strftime("%Y-%m-%d") for ts in d]


@pytest.fixture
def screener_env(temp_db, monkeypatch):
    rows, dates = _synthetic_recovery_frame()
    monkeypatch.setattr(database, "get_sector_price_data_300d_active",
                        lambda: rows)
    monkeypatch.setattr(database, "get_index_prices",
                        lambda _sym: [{"date": r["date"], "close": 1000.0 + i}
                                      for i, r in enumerate(rows[-30:])])
    return temp_db, dates


def _rows_for(db, as_of_date, symbol="RECOV"):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM recovery_signals WHERE as_of_date = ? AND symbol = ?",
            (as_of_date, symbol)).fetchall()]
    finally:
        con.close()


def test_synthetic_trigger_fires_when_window_reaches_it(screener_env):
    db, dates = screener_env
    latest = dates[-1]
    # table 10 sessions stale -> window widens to 10 -> the day-67 trigger
    # (8 sessions before latest) is inside the scan window
    _seed_as_of(db, dates[-11])

    res = signal_engine.run_recovery_signals()
    assert res["status"] == "ok"
    assert res["as_of_date"] == latest

    hits = _rows_for(db, latest)
    triggered = [r for r in hits if r["list_type"] == "TRIGGERED"]
    assert len(triggered) == 1, f"expected the gap-era trigger to be caught: {hits}"
    row = triggered[0]
    assert row["triggered_date"] == dates[67]
    assert row["fresh"] == 0            # caught late, not a same-day trigger


def test_normal_run_does_not_reach_back_past_five_sessions(screener_env):
    db, dates = screener_env
    latest = dates[-1]
    # table is current -> window stays at the 5-session minimum -> the day-67
    # trigger is outside it and is NOT (re-)recorded on this snapshot
    _seed_as_of(db, dates[-2])

    res = signal_engine.run_recovery_signals()
    assert res["status"] == "ok"
    triggered = [r for r in _rows_for(db, latest) if r["list_type"] == "TRIGGERED"]
    assert triggered == []


def test_idempotent_no_duplicate_rows(screener_env):
    db, dates = screener_env
    _seed_as_of(db, dates[-11])

    signal_engine.run_recovery_signals()
    signal_engine.run_recovery_signals()

    con = sqlite3.connect(db)
    try:
        dupes = con.execute(
            "SELECT as_of_date, symbol, list_type, COUNT(*) c "
            "FROM recovery_signals GROUP BY as_of_date, symbol, list_type "
            "HAVING c > 1").fetchall()
    finally:
        con.close()
    assert dupes == []


def test_window_size_is_logged(screener_env, caplog):
    db, dates = screener_env
    _seed_as_of(db, dates[-11])
    with caplog.at_level(logging.INFO, logger="signal_engine"):
        signal_engine.run_recovery_signals()
    assert any("trigger scan window = 10 session(s)" in m for m in caplog.messages)
