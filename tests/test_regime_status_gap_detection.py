"""
Tests for the has_gap detection added to _get_regime_status() /
get_regime_status_pg() (2026-08-12).

Background: even after regime.py's backfill fix (see
test_regime_backfill.py) stops NEW gaps from forming, a gap could already
exist from before the fix was deployed, or from any future edge case. The
sidebar/header "days since regime change" widget used to trust a plain
row-count between the detected transition and the latest market_regime
row -- which is silently wrong whenever a row is missing, in either
direction, not just understated. This was proven for real: backfilling a
genuine gap on 2026-08-07 found a one-day VOLATILE dip hiding inside what
had looked like an unbroken TRENDING_UP streak (see
docs/KIRAN_CLEANUP_AUDIT.md). has_gap cross-references index_prices (the
authoritative trading calendar) to detect when market_regime's row count
doesn't match the real number of trading dates in the window, so the UI
can flag the uncertainty instead of silently displaying a number that
might be wrong.

Exercises dashboard.py's _get_regime_status() (SQLite path) directly,
clearing its st.cache_data cache between calls -- it takes no arguments,
so every call would otherwise share one cache entry across tests. The PG
sibling (get_regime_status_pg() in dashboard_pg.py) runs the identical
query shape against Postgres instead of SQLite and isn't covered here for
the same reason the rest of this project's PG paths aren't: no live
Postgres connection belongs in an automated test suite.
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard  # noqa: E402


def _seed_db(path: str, market_regime_rows: list[tuple], index_prices_dates: list[str]):
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE market_regime (
            date TEXT PRIMARY KEY, regime TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE index_prices (
            symbol TEXT NOT NULL, date TEXT NOT NULL, close REAL,
            PRIMARY KEY (symbol, date)
        )
    """)
    for d, regime in market_regime_rows:
        conn.execute("INSERT INTO market_regime (date, regime) VALUES (?, ?)", (d, regime))
    for d in index_prices_dates:
        conn.execute(
            "INSERT INTO index_prices (symbol, date, close) VALUES ('KSE-100', ?, 100)", (d,)
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_psx_data.db")
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setattr(dashboard, "_PG_URL", None)
    dashboard._get_regime_status.clear()  # each test gets a fresh cache
    yield db_path
    dashboard._get_regime_status.clear()


def test_no_gap_when_market_regime_is_complete(temp_db):
    dates = ["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    regimes = ["VOLATILE", "VOLATILE", "TRENDING_UP", "TRENDING_UP", "TRENDING_UP", "TRENDING_UP"]
    _seed_db(temp_db, list(zip(dates, regimes)), dates)

    regime_now, latest_date, days_since, has_gap = dashboard._get_regime_status()

    assert regime_now == "TRENDING_UP"
    assert latest_date == "2026-08-11"
    assert days_since == 3  # 08-07, 08-10, 08-11 are the 3 rows after the 08-06 transition
    assert has_gap is False


def test_gap_detected_when_market_regime_row_is_missing(temp_db):
    # Mirrors the real 2026-08-07 incident: index_prices has every trading
    # date, but market_regime is missing 08-07 and 08-10 -- only 08-06 and
    # 08-11 exist, sitting adjacent in the row array.
    trading_dates = ["2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    market_regime_rows = [
        ("2026-08-04", "VOLATILE"),
        ("2026-08-05", "VOLATILE"),
        ("2026-08-06", "TRENDING_UP"),
        ("2026-08-11", "TRENDING_UP"),  # 08-07 and 08-10 rows missing
    ]
    _seed_db(temp_db, market_regime_rows, trading_dates)

    regime_now, latest_date, days_since, has_gap = dashboard._get_regime_status()

    assert regime_now == "TRENDING_UP"
    assert days_since == 1, "row-count still reports 1 -- the number itself isn't fixed, just flagged"
    assert has_gap is True, "3 real trading dates exist after the transition but only 1 row does"


def test_no_gap_when_streak_is_a_single_day(temp_db):
    """A regime that changed on the very latest date has no window to
    check for gaps in -- must not be flagged as has_gap=True.
    """
    dates = ["2026-08-10", "2026-08-11"]
    regimes = ["VOLATILE", "TRENDING_UP"]
    _seed_db(temp_db, list(zip(dates, regimes)), dates)

    regime_now, latest_date, days_since, has_gap = dashboard._get_regime_status()

    assert days_since == 0
    assert has_gap is False


def test_gap_before_any_transition_is_not_flagged(temp_db):
    """A gap sitting entirely BEFORE the current streak (already-settled
    history, not the live streak's own window) must not raise a false
    alarm -- only gaps inside the current streak's own window matter for
    trusting days_since.
    """
    trading_dates = ["2026-07-20", "2026-07-21", "2026-07-22", "2026-08-06", "2026-08-07"]
    market_regime_rows = [
        ("2026-07-20", "VOLATILE"),
        # 2026-07-21 missing from market_regime -- old, already-settled gap
        ("2026-07-22", "VOLATILE"),
        ("2026-08-06", "TRENDING_UP"),
        ("2026-08-07", "TRENDING_UP"),
    ]
    _seed_db(temp_db, market_regime_rows, trading_dates)

    regime_now, latest_date, days_since, has_gap = dashboard._get_regime_status()

    assert days_since == 1
    assert has_gap is False, "the gap is outside the current streak's window and shouldn't be flagged"
