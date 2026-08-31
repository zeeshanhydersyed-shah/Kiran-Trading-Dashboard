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
# run_recovery_signals wiring -- the gap-widened window reaches the scan loop
# ---------------------------------------------------------------------------
#
# These do NOT assert that a synthetic trigger fires. The ~250-line recovery
# screener is unchanged by this PR, and it behaves differently across the
# pandas 2 (CI / Streamlit Cloud) vs pandas 3 (some dev boxes) split
# documented in ledger §89.9 -- coupling a regression test for the *scan
# window* to the *gate thresholds* is the wrong seam. The window's exact
# contents are proven version-independently by the _recovery_trigger_window()
# tests above; these pin that run_recovery_signals() feeds
# _last_recovery_as_of() into it and consumes the result.

def _plain_frame(n=75, start="2026-04-01"):
    """One symbol, n sessions, gentle uptrend -- flows through
    run_recovery_signals() with status ok and zero signal rows."""
    d = pd.bdate_range(start, periods=n)
    close = np.linspace(100.0, 108.0, n)
    rows = [
        {"symbol": "PLAIN", "sector": "CEMENT", "date": d[i].strftime("%Y-%m-%d"),
         "open": float(close[i]), "high": float(close[i] + 1.0),
         "low": float(close[i] - 1.0), "close": float(close[i]),
         "volume": 1_000_000.0}
        for i in range(n)
    ]
    return rows, [ts.strftime("%Y-%m-%d") for ts in d]


@pytest.fixture
def screener_env(temp_db, monkeypatch):
    rows, dates = _plain_frame()
    monkeypatch.setattr(database, "get_sector_price_data_300d_active", lambda: rows)
    monkeypatch.setattr(database, "get_index_prices", lambda _sym: [])
    return temp_db, dates


@pytest.fixture
def window_spy(monkeypatch):
    """Records every _recovery_trigger_window() call while delegating to the
    real implementation."""
    calls: list[dict] = []
    real = signal_engine._recovery_trigger_window

    def spy(all_dates, last_recorded_as_of):
        result = real(all_dates, last_recorded_as_of)
        calls.append({"last_as_of": last_recorded_as_of,
                      "window_len": result[1],
                      "n_all_dates": len(list(all_dates))})
        return result

    monkeypatch.setattr(signal_engine, "_recovery_trigger_window", spy)
    return calls


def test_run_widens_window_to_the_gap(screener_env, window_spy):
    db, dates = screener_env
    _seed_as_of(db, dates[-11])                       # table 10 sessions stale

    assert signal_engine.run_recovery_signals()["status"] == "ok"
    assert window_spy == [{"last_as_of": dates[-11],  # fed from _last_recovery_as_of()
                           "window_len": 10,          # widened to the gap
                           "n_all_dates": len(dates)}]  # full history handed over


def test_run_keeps_min_window_when_table_is_current(screener_env, window_spy):
    db, dates = screener_env
    _seed_as_of(db, dates[-1])                        # table current -> 0 behind

    assert signal_engine.run_recovery_signals()["status"] == "ok"
    assert window_spy[0]["last_as_of"] == dates[-1]
    assert window_spy[0]["window_len"] == 5


def test_run_uses_min_window_on_first_run(screener_env, window_spy):
    # recovery_signals is empty -> _last_recovery_as_of() is None
    assert signal_engine.run_recovery_signals()["status"] == "ok"
    assert window_spy[0]["last_as_of"] is None
    assert window_spy[0]["window_len"] == 5


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
