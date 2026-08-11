"""
Tests for regime.py's backfill fix (2026-08-12).

Background: before this fix, the regime hook only ever computed and wrote
the single most-recent trading date. Since it's wrapped in its own
try/except in main.py's cmd_update() (by design -- one bad day shouldn't
kill the rest of the daily pipeline), a transient failure on any one day
meant that day's row in market_regime was permanently lost: the next
successful run just wrote whatever the new latest date was and moved on.
This happened for real on 2026-08-07 (see docs/KIRAN_CLEANUP_AUDIT.md) --
market_regime jumped straight from 2026-08-06 to 2026-08-10 even though
index_prices had 2026-08-07 the whole time.

These tests cover the fix at two levels:
  1. _pending_regime_rows() -- the pure, DB-free generator both the PG and
     SQLite paths share. This is where the actual backfill/chaining logic
     lives, so it gets the most direct coverage.
  2. _append_latest_regime_sqlite() (via the public append_latest_regime())
     against a disposable temp SQLite DB -- proves the DB wiring around the
     pure function is correct: full gap coverage, correct regime_days
     chaining across a multi-day gap, and idempotent re-runs.

The PG path (_append_latest_regime_pg) is not exercised here -- it requires
a live Postgres connection, which has no place in an automated test suite,
and it shares the exact same _pending_regime_rows() logic already covered
above. It should get one manual, read-verified dry run against a disposable
copy before ever touching production, per this project's standing
production-write discipline (never exercised automatically here).
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import regime  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

def _synthetic_kse100_df(n_days: int, start="2020-01-01", seed=0) -> pd.DataFrame:
    """A smooth, steadily-rising synthetic KSE-100 series -- long enough to
    clear the 199-row INSUFFICIENT_DATA warmup and land cleanly in
    TRENDING_UP once past it (rising EMA stack, positive 20d return).
    """
    rng = np.random.default_rng(seed)
    dates = [
        (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(n_days)
    ]
    # steady uptrend + small noise, strictly positive
    base = 40000 + np.cumsum(rng.normal(loc=25, scale=15, size=n_days))
    close = np.round(base, 2)
    high = np.round(close * 1.003, 2)
    low = np.round(close * 0.997, 2)
    return pd.DataFrame({"date": dates, "high": high, "low": low, "close": close})


def _seed_sqlite_regime_db(path: str, kse_df: pd.DataFrame, written_through_idx: int | None):
    """Creates index_prices + market_regime and pre-populates market_regime
    up to (and including) written_through_idx by directly replaying
    regime.py's own pure logic -- i.e. simulating "every prior day's hook
    run succeeded individually", the state a real gap starts from.
    written_through_idx=None means market_regime starts completely empty.
    """
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE index_prices (
            symbol TEXT NOT NULL, date TEXT NOT NULL,
            high REAL, low REAL, close REAL NOT NULL,
            PRIMARY KEY (symbol, date)
        )
    """)
    conn.execute("""
        CREATE TABLE market_regime (
            date TEXT PRIMARY KEY, close REAL, ema_20 REAL, ema_50 REAL, ema_200 REAL,
            atr_20 REAL, atr_pct REAL, return_20d REAL,
            regime TEXT NOT NULL, regime_days INTEGER, notes TEXT
        )
    """)
    for _, r in kse_df.iterrows():
        conn.execute(
            "INSERT INTO index_prices (symbol, date, high, low, close) VALUES ('KSE-100', ?, ?, ?, ?)",
            (r["date"], r["high"], r["low"], r["close"]),
        )
    conn.commit()

    if written_through_idx is not None:
        df = kse_df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = regime._compute_indicators(df)
        total = len(df)
        prev_regime, prev_days = None, 0
        for date_str, row, rgm, rgm_days in regime._pending_regime_rows(
            df.iloc[: written_through_idx + 1], total, None, prev_regime, prev_days
        ):
            conn.execute(
                """INSERT OR REPLACE INTO market_regime
                   (date, close, ema_20, ema_50, ema_200, atr_20, atr_pct, return_20d, regime, regime_days, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    date_str, float(row["close"]), float(row["ema_20"]), float(row["ema_50"]), float(row["ema_200"]),
                    float(row["atr_20"]) if pd.notna(row["atr_20"]) else None,
                    float(row["atr_pct"]) if pd.notna(row["atr_pct"]) else None,
                    float(row["return_20d"]) if pd.notna(row["return_20d"]) else None,
                    rgm, rgm_days,
                ),
            )
        conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────
# 1. Pure function -- _pending_regime_rows
# ─────────────────────────────────────────────────────────────────────────

def test_pending_regime_rows_backfills_full_gap():
    n = 220
    kse_df = _synthetic_kse100_df(n)
    df = kse_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = regime._compute_indicators(df)
    total = len(df)

    # simulate: last successful write was 5 trading days before the latest
    last_written_date = df.iloc[-6]["date"].strftime("%Y-%m-%d")

    pending = list(regime._pending_regime_rows(df, total, last_written_date, "TRENDING_UP", 40))
    pending_dates = [d for d, *_ in pending]

    expected_dates = [
        d.strftime("%Y-%m-%d") for d in df["date"].iloc[-5:]
    ]
    assert pending_dates == expected_dates, "must yield exactly the 5 missing trading dates, in order"


def test_pending_regime_rows_chains_regime_days_across_gap():
    n = 220
    kse_df = _synthetic_kse100_df(n)
    df = kse_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = regime._compute_indicators(df)
    total = len(df)

    last_written_date = df.iloc[-4]["date"].strftime("%Y-%m-%d")
    pending = list(regime._pending_regime_rows(df, total, last_written_date, "TRENDING_UP", 10))

    assert len(pending) == 3
    days = [d for *_, d in pending]
    # each subsequent day in an unbroken same-regime streak increments by 1,
    # continuing from the pre-gap count (10) -- not restarting at 1
    assert days == [11, 12, 13], (
        "regime_days must continue the pre-gap streak across every "
        "backfilled date, not just get the count right for the final one"
    )


def test_pending_regime_rows_resets_on_regime_change():
    n = 220
    kse_df = _synthetic_kse100_df(n)
    df = kse_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = regime._compute_indicators(df)
    total = len(df)

    last_written_date = df.iloc[-2]["date"].strftime("%Y-%m-%d")
    pending = list(regime._pending_regime_rows(df, total, last_written_date, "VOLATILE", 7))
    # synthetic series classifies TRENDING_UP once warmed up -- different
    # from the simulated previous regime, so the streak must restart at 1
    assert pending[0][2] != "VOLATILE" or pending[0][3] == 1
    if pending[0][2] != "VOLATILE":
        assert pending[0][3] == 1


def test_pending_regime_rows_empty_when_already_current():
    n = 220
    kse_df = _synthetic_kse100_df(n)
    df = kse_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = regime._compute_indicators(df)
    total = len(df)

    last_written_date = df.iloc[-1]["date"].strftime("%Y-%m-%d")
    pending = list(regime._pending_regime_rows(df, total, last_written_date, "TRENDING_UP", 5))
    assert pending == []


# ─────────────────────────────────────────────────────────────────────────
# 2. SQLite integration -- append_latest_regime() end to end
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Points regime.py at a disposable temp SQLite file for the duration
    of the test -- never the real local psx_data.db, never production.
    """
    db_path = str(tmp_path / "test_psx_data.db")
    monkeypatch.setattr(regime, "DB", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setattr(regime, "_PG_URL", None)
    return db_path


def test_sqlite_backfill_fills_multi_day_gap(temp_db):
    n = 220
    kse_df = _synthetic_kse100_df(n)
    # pre-populate through 3 days before the latest -- simulating the hook
    # having failed silently for the last 3 trading days
    _seed_sqlite_regime_db(temp_db, kse_df, written_through_idx=n - 4)

    regime.append_latest_regime()

    conn = sqlite3.connect(temp_db)
    rows = conn.execute("SELECT date FROM market_regime ORDER BY date").fetchall()
    conn.close()
    got_dates = [r[0] for r in rows]
    expected_dates = list(kse_df["date"])
    assert got_dates == expected_dates, "every trading date must now have a market_regime row, no gap"


def test_sqlite_backfill_regime_days_chain_correctly(temp_db):
    n = 220
    kse_df = _synthetic_kse100_df(n)
    _seed_sqlite_regime_db(temp_db, kse_df, written_through_idx=n - 4)

    regime.append_latest_regime()

    conn = sqlite3.connect(temp_db)
    rows = conn.execute(
        "SELECT date, regime, regime_days FROM market_regime ORDER BY date"
    ).fetchall()
    conn.close()

    # every date in an unbroken same-regime streak must increment by
    # exactly 1 over the previous date's regime_days -- checked across the
    # whole table, not just the backfilled tail, so this also proves the
    # backfilled dates chain correctly onto the pre-existing history.
    for i in range(1, len(rows)):
        prev_regime, prev_days = rows[i - 1][1], rows[i - 1][2]
        cur_regime, cur_days = rows[i][1], rows[i][2]
        if cur_regime == prev_regime:
            assert cur_days == prev_days + 1, f"streak break at {rows[i][0]}"
        else:
            assert cur_days == 1, f"regime change at {rows[i][0]} must reset regime_days to 1"


def test_sqlite_backfill_is_idempotent(temp_db):
    n = 220
    kse_df = _synthetic_kse100_df(n)
    _seed_sqlite_regime_db(temp_db, kse_df, written_through_idx=n - 4)

    regime.append_latest_regime()

    conn = sqlite3.connect(temp_db)
    before = conn.execute(
        "SELECT date, close, ema_20, ema_50, ema_200, regime, regime_days FROM market_regime ORDER BY date"
    ).fetchall()
    conn.close()

    regime.append_latest_regime()  # re-run with nothing new to backfill

    conn = sqlite3.connect(temp_db)
    after = conn.execute(
        "SELECT date, close, ema_20, ema_50, ema_200, regime, regime_days FROM market_regime ORDER BY date"
    ).fetchall()
    conn.close()

    assert before == after, "a re-run with no new data must not change any existing row"


def test_sqlite_backfill_does_not_touch_dates_before_the_gap(temp_db):
    n = 220
    kse_df = _synthetic_kse100_df(n)
    _seed_sqlite_regime_db(temp_db, kse_df, written_through_idx=n - 4)

    conn = sqlite3.connect(temp_db)
    pre_existing = dict(
        conn.execute(
            "SELECT date, regime_days FROM market_regime WHERE date <= (SELECT MIN(date) FROM ("
            "SELECT date FROM market_regime ORDER BY date DESC LIMIT 4))"
        ).fetchall()
    )
    conn.close()

    regime.append_latest_regime()

    conn = sqlite3.connect(temp_db)
    after = dict(conn.execute("SELECT date, regime_days FROM market_regime").fetchall())
    conn.close()

    for d, days in pre_existing.items():
        assert after[d] == days, f"pre-gap row {d} must be unchanged"


def test_sqlite_normal_single_new_date_still_works(temp_db):
    """Sanity check: the no-gap, single-new-date case (the old behaviour's
    only supported case) must still work exactly as before.
    """
    n = 220
    kse_df = _synthetic_kse100_df(n)
    _seed_sqlite_regime_db(temp_db, kse_df, written_through_idx=n - 2)  # only the latest date missing

    regime.append_latest_regime()

    conn = sqlite3.connect(temp_db)
    rows = conn.execute("SELECT date FROM market_regime ORDER BY date").fetchall()
    conn.close()
    assert [r[0] for r in rows] == list(kse_df["date"])
