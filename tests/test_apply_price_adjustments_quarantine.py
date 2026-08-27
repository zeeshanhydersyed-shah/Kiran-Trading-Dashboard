"""Regression test for the prices_adjusted quarantine guard (2026-08-21).

Background: docs/KIRAN_CLEANUP_AUDIT.md §41-42. prices_adjusted carries three
columns -- hit_circuit_up, hit_circuit_down, thin_trading_flag -- with real
historical data (218,111 non-zero rows, 2005-2026) whose producer code was
never found anywhere in this repository's git history (273 revisions, all
branches). Classification: B -- semantics strongly inferred, producer
unconfirmed. Disposition: PRESERVE / QUARANTINE, not reconstruct.

Empirically confirmed (§42.6, disposable-DB test) that build_adjusted_prices()'s
rebuild (DROP TABLE + CREATE TABLE AS SELECT * FROM prices) silently destroys
these columns and their data -- no error, no warning. This test proves the
fix: snapshot_quarantined_columns()/restore_quarantined_columns() carry
existing values across the rebuild unchanged. It does NOT test or assert any
semantic meaning for the columns -- only that a rebuild is now a no-op for
data that already existed.
"""
from __future__ import annotations

import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from apply_price_adjustments import (  # noqa: E402
    QUARANTINED_COLUMNS,
    build_adjusted_prices,
    snapshot_quarantined_columns,
    restore_quarantined_columns,
)


def _fresh_con():
    con = sqlite3.connect(":memory:")
    con.execute(
        "CREATE TABLE prices (symbol TEXT, date TEXT, close REAL, volume INT, "
        "high REAL, low REAL, open REAL)"
    )
    return con


def _seed_prices(con, rows):
    con.executemany(
        "INSERT INTO prices VALUES (?,?,?,?,?,?,?)", rows
    )
    con.commit()


# ── 1. rebuild with no pre-existing prices_adjusted: no columns invented ────

def test_first_ever_rebuild_does_not_invent_quarantined_columns():
    con = _fresh_con()
    _seed_prices(con, [("TEST", "2026-01-01", 100, 1000, 105, 95, 100)])

    build_adjusted_prices(con, events=[])

    cols = {r[1] for r in con.execute("PRAGMA table_info(prices_adjusted)")}
    assert not cols & set(QUARANTINED_COLUMNS), (
        "a rebuild with no prior prices_adjusted must not invent quarantined "
        "columns from nothing"
    )


# ── 2. rebuild with pre-existing quarantined data: values survive exactly ──

def test_rebuild_preserves_quarantined_values_exactly():
    con = _fresh_con()
    _seed_prices(con, [
        ("AAA", "2026-01-01", 100, 1000, 105, 95, 100),
        ("BBB", "2026-01-01", 50, 2000, 52, 48, 50),
    ])
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL, "
        "hit_circuit_up INTEGER NOT NULL DEFAULT 0, "
        "hit_circuit_down INTEGER NOT NULL DEFAULT 0, "
        "thin_trading_flag INTEGER NOT NULL DEFAULT 0)"
    )
    con.execute(
        "INSERT INTO prices_adjusted VALUES "
        "('AAA','2026-01-01',100,1000,105,95,100,1,0,0),"
        "('BBB','2026-01-01',50,2000,52,48,50,0,1,1)"
    )
    con.commit()

    build_adjusted_prices(con, events=[])

    cols = {r[1] for r in con.execute("PRAGMA table_info(prices_adjusted)")}
    assert set(QUARANTINED_COLUMNS) <= cols, "quarantined columns must survive the rebuild"

    rows = dict(
        (r[0], r[1:]) for r in con.execute(
            "SELECT symbol, hit_circuit_up, hit_circuit_down, thin_trading_flag "
            "FROM prices_adjusted ORDER BY symbol"
        )
    )
    assert rows["AAA"] == (1, 0, 0)
    assert rows["BBB"] == (0, 1, 1)


# ── 3. a symbol/date only in `prices` (not previously in prices_adjusted) ──
#    gets the column's own default, not a fabricated value

def test_new_date_with_no_prior_snapshot_gets_default_not_invented_value():
    con = _fresh_con()
    _seed_prices(con, [
        ("AAA", "2026-01-01", 100, 1000, 105, 95, 100),   # existing, flagged
        ("AAA", "2026-01-02", 101, 1100, 106, 96, 101),   # brand new date
    ])
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL, "
        "hit_circuit_up INTEGER NOT NULL DEFAULT 0, "
        "hit_circuit_down INTEGER NOT NULL DEFAULT 0, "
        "thin_trading_flag INTEGER NOT NULL DEFAULT 0)"
    )
    con.execute(
        "INSERT INTO prices_adjusted VALUES "
        "('AAA','2026-01-01',100,1000,105,95,100,1,0,0)"
    )
    con.commit()

    build_adjusted_prices(con, events=[])

    row = con.execute(
        "SELECT hit_circuit_up, hit_circuit_down, thin_trading_flag "
        "FROM prices_adjusted WHERE date='2026-01-02'"
    ).fetchone()
    assert row == (0, 0, 0), "a date with no prior snapshot must fall back to the column default, never an invented value"


# ── 4. idempotency: two rebuilds in a row produce the same result ──────────

def test_rebuild_is_idempotent_for_quarantined_columns():
    con = _fresh_con()
    _seed_prices(con, [("AAA", "2026-01-01", 100, 1000, 105, 95, 100)])
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL, "
        "hit_circuit_up INTEGER NOT NULL DEFAULT 0, "
        "hit_circuit_down INTEGER NOT NULL DEFAULT 0, "
        "thin_trading_flag INTEGER NOT NULL DEFAULT 0)"
    )
    con.execute(
        "INSERT INTO prices_adjusted VALUES "
        "('AAA','2026-01-01',100,1000,105,95,100,1,1,0)"
    )
    con.commit()

    build_adjusted_prices(con, events=[])
    build_adjusted_prices(con, events=[])  # run again

    row = con.execute(
        "SELECT hit_circuit_up, hit_circuit_down, thin_trading_flag "
        "FROM prices_adjusted WHERE symbol='AAA' AND date='2026-01-01'"
    ).fetchone()
    assert row == (1, 1, 0)


# ── 5. snapshot/restore helpers directly, in isolation ─────────────────────

def test_snapshot_returns_empty_when_no_prices_adjusted_table():
    con = _fresh_con()
    present, rows = snapshot_quarantined_columns(con)
    assert present == []
    assert rows == []


def test_snapshot_returns_empty_when_columns_absent():
    con = _fresh_con()
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL)"
    )
    present, rows = snapshot_quarantined_columns(con)
    assert present == []
    assert rows == []


def test_restore_is_noop_when_nothing_to_restore():
    con = _fresh_con()
    con.execute(
        "CREATE TABLE prices_adjusted (symbol TEXT, date TEXT, close REAL, "
        "volume INT, high REAL, low REAL, open REAL)"
    )
    n = restore_quarantined_columns(con, [], [])
    assert n == 0
    cols = {r[1] for r in con.execute("PRAGMA table_info(prices_adjusted)")}
    assert not cols & set(QUARANTINED_COLUMNS)
