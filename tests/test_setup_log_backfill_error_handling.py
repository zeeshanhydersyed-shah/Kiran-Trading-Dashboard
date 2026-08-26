"""Regression tests for the setup_log SQLite backfill's exception handling
fix (docs/KIRAN_CLEANUP_AUDIT.md §44).

Background: append_setup_log_today()'s per-date loop used a single broad
`except Exception -> log.warning` and CONTINUED to the next date on any
failure. Since `_pending_setup_log_dates()` computes pending dates from
MAX(setup_date), a failure on date D followed by a SUCCESS on date D+1 would
silently and permanently drop D: MAX(setup_date) advances past D+1, and
`d > last_logged` can never select D again. The Postgres path
(_append_setup_log_today_pg) was already fixed for this exact shape
(docs/KIRAN_CLEANUP_AUDIT.md §28) with a two-tier handler: a transient
error (sqlite3.OperationalError / psycopg2 equivalents) breaks the loop so
the next run resumes from the failed date; anything else is a real bug and
must raise, not be logged as a warning and treated as pipeline success. This
file proves the SQLite path now does the same.

Reuses the fixture/seeding helpers from test_setup_log_backfill.py.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from test_setup_log_backfill import (  # noqa: E402
    DATES, FIXTURE_DB, SCHEMA_TABLES, _seed_signals, _logged_dates,
)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"schema source not found: {FIXTURE_DB}")

    db = str(tmp_path / "test_psx.db")
    src = sqlite3.connect(f"file:{FIXTURE_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(db)
    for table in SCHEMA_TABLES:
        ddl = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        assert ddl, f"{table} missing from fixture schema"
        dst.execute(ddl[0])
    src.close()

    import backfill_setup_log
    import compute_forward_returns
    monkeypatch.setattr(backfill_setup_log, "DB_PATH", db)
    monkeypatch.setattr(backfill_setup_log, "_PG_URL", None)
    monkeypatch.setattr(compute_forward_returns, "DB_PATH", db)
    monkeypatch.setattr(compute_forward_returns, "_PG_URL", None)

    dst.execute("INSERT INTO stock_metadata (symbol, sector) VALUES ('AAA', 'CEMENT')")
    dst.executemany("INSERT INTO market_regime (date, regime) VALUES (?, 'TRENDING_UP')",
                    [(d,) for d in DATES])
    dst.commit()
    yield dst, db
    dst.close()


def _seed_and_prime(conn, primed_date):
    """5 days of signals, setup_log already caught up through `primed_date`."""
    _seed_signals(conn, DATES)
    conn.execute(
        """INSERT INTO setup_log (symbol, setup_date, setup_type, outcome_label)
           VALUES ('AAA', ?, 'RS_LEADER_MARKET', 'BREAKEVEN')""",
        (primed_date,),
    )
    conn.commit()


# ── 1. a real bug on a middle date must raise, not be swallowed ────────────

def test_unexpected_error_on_a_middle_date_raises(temp_db, monkeypatch):
    """DATES[1] is already logged, so pending = [2,3,4]. Force a non-transient
    error on DATES[2] (the middle of the three pending dates)."""
    conn, _ = temp_db
    _seed_and_prime(conn, DATES[1])

    import backfill_setup_log as bsl
    real_insert = bsl._insert_setup_log_for_date

    def _boom(cur, target_date):
        if target_date == DATES[2]:
            raise ValueError("simulated unexpected bug")
        return real_insert(cur, target_date)

    monkeypatch.setattr(bsl, "_insert_setup_log_for_date", _boom)

    with pytest.raises(ValueError, match="simulated unexpected bug"):
        bsl.append_setup_log_today()

    # DATES[3] (chronologically after the failure) must NOT have been
    # attempted -- proves the loop did not silently continue past the bug.
    logged = _logged_dates(conn)
    assert DATES[3] not in logged
    assert DATES[4] not in logged


def test_unexpected_error_does_not_advance_high_water_mark_past_the_gap(temp_db, monkeypatch):
    """The core regression: after the failure+raise, a second (successful)
    run must still be able to reach the date that failed -- it must not have
    been silently skipped forever."""
    conn, _ = temp_db
    _seed_and_prime(conn, DATES[1])

    import backfill_setup_log as bsl
    real_insert = bsl._insert_setup_log_for_date
    calls = []

    def _boom_once(cur, target_date):
        calls.append(target_date)
        if target_date == DATES[2] and calls.count(DATES[2]) == 1:
            raise ValueError("simulated transient-looking bug, first attempt only")
        return real_insert(cur, target_date)

    monkeypatch.setattr(bsl, "_insert_setup_log_for_date", _boom_once)

    with pytest.raises(ValueError):
        bsl.append_setup_log_today()

    # Second run: the same insert function now succeeds for DATES[2].
    bsl.append_setup_log_today()

    # All 3 originally-pending dates are now present -- DATES[2] was not
    # permanently lost despite failing on the first attempt.
    logged = _logged_dates(conn)
    assert DATES[2] in logged
    assert DATES[3] in logged
    assert DATES[4] in logged


# ── 2. a transient (sqlite3.OperationalError) failure breaks, doesn't raise ─

def test_transient_error_breaks_without_raising_and_stops_at_the_gap(temp_db, monkeypatch):
    conn, _ = temp_db
    _seed_and_prime(conn, DATES[1])

    import backfill_setup_log as bsl
    real_insert = bsl._insert_setup_log_for_date

    def _locked(cur, target_date):
        if target_date == DATES[2]:
            raise sqlite3.OperationalError("database is locked")
        return real_insert(cur, target_date)

    monkeypatch.setattr(bsl, "_insert_setup_log_for_date", _locked)

    # Must NOT raise -- a transient error is tolerated, not fatal.
    bsl.append_setup_log_today()

    logged = _logged_dates(conn)
    # DATES[2] failed transiently -- loop stopped there, so nothing after it
    # (DATES[3], DATES[4]) was attempted either.
    assert DATES[2] not in logged
    assert DATES[3] not in logged
    assert DATES[4] not in logged


def test_transient_error_leaves_the_date_recoverable_on_next_run(temp_db, monkeypatch):
    conn, _ = temp_db
    _seed_and_prime(conn, DATES[1])

    import backfill_setup_log as bsl
    real_insert = bsl._insert_setup_log_for_date
    attempt = {"n": 0}

    def _locked_once(cur, target_date):
        if target_date == DATES[2] and attempt["n"] == 0:
            attempt["n"] += 1
            raise sqlite3.OperationalError("database is locked")
        return real_insert(cur, target_date)

    monkeypatch.setattr(bsl, "_insert_setup_log_for_date", _locked_once)

    bsl.append_setup_log_today()          # stops at DATES[2]
    bsl.append_setup_log_today()          # resumes cleanly

    logged = _logged_dates(conn)
    assert logged == [DATES[1], DATES[2], DATES[3], DATES[4]]
