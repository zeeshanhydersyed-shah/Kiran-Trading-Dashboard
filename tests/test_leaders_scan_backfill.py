"""Tests for leaders_scan.py's backfill fix and its Postgres boolean fix
(2026-08-12).

`append_leaders_scan()` carried the identical defect to setup_log's: it
computed `scan_date = MAX(stock_signals.date)` and wrote only that day, so any
day the hook missed was lost the moment a newer date was written. Measured
before the fix: local `leaders_scan` covered 28 of the trading dates since it
started on 2026-06-16, with holes at 06-25/26, 07-11/13, 07-18/21 and 07-29.

Production was worse and for a second reason: `leaders_scan` on Supabase was
frozen at 2026-06-30 because three queries on the Postgres path compared
`bos_flag` (BOOLEAN in Supabase, INTEGER in SQLite) against `0`/`1`, which
raises `operator does not exist: boolean = integer` and aborts the
transaction. See docs/KIRAN_CLEANUP_AUDIT.md §25.

The policy for "which dates still need writing" is *imported* from
backfill_setup_log rather than re-implemented, so the two hooks cannot drift
apart again -- test_shared_policy_is_actually_shared() pins that.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from decimal import Decimal

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import leaders_scan  # noqa: E402

FIXTURE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fixtures", "psx_fixture.db")

DATES = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]


@pytest.fixture
def mini_db(tmp_path, monkeypatch):
    """Temp DB with just the two tables _pending_scan_dates() reads."""
    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"schema source not found: {FIXTURE_DB}")
    db = str(tmp_path / "mini.db")
    src = sqlite3.connect(f"file:{FIXTURE_DB}?mode=ro", uri=True)
    dst = sqlite3.connect(db)
    for table in ("stock_signals", "leaders_scan"):
        dst.execute(src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,)).fetchone()[0])
    src.close()
    monkeypatch.setattr(leaders_scan, "_PG_URL", None)
    dst.executemany(
        "INSERT INTO stock_signals (symbol, date, avg_vol_10d) VALUES ('AAA', ?, 900000)",
        [(d,) for d in DATES])
    dst.commit()
    yield dst, db
    dst.close()


def _seed_scan(conn, date):
    conn.execute(
        "INSERT INTO leaders_scan (scan_date, setup_type, symbol) VALUES (?, 'BO', 'AAA')",
        (date,))
    conn.commit()


def test_gap_yields_every_missing_date(mini_db):
    conn, db = mini_db
    _seed_scan(conn, DATES[1])
    assert leaders_scan._pending_scan_dates(db) == DATES[2:]


def test_up_to_date_yields_nothing(mini_db):
    conn, db = mini_db
    _seed_scan(conn, DATES[-1])
    assert leaders_scan._pending_scan_dates(db) == []


def test_empty_table_takes_newest_only(mini_db):
    """Matches setup_log's rule -- an empty table is not a licence to replay
    every historical scan date through the daily path."""
    _conn, db = mini_db
    assert leaders_scan._pending_scan_dates(db) == [DATES[-1]]


def test_shared_policy_is_actually_shared():
    """The whole point of importing it: one definition, not two that drift."""
    import inspect
    from backfill_setup_log import _pending_setup_log_dates
    assert "_pending_setup_log_dates" in inspect.getsource(
        leaders_scan._pending_scan_dates)
    assert _pending_setup_log_dates(DATES, DATES[1]) == DATES[2:]


def test_explicit_scan_date_is_honoured(tmp_path):
    """append_leaders_scan(scan_date=...) must write THAT date, not the newest.

    Runs against a throwaway copy of the fixture database -- the real one is
    never touched.
    """
    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"fixture not found: {FIXTURE_DB}")
    db = str(tmp_path / "fix.db")
    shutil.copyfile(FIXTURE_DB, db)
    conn = sqlite3.connect(db)
    target = conn.execute(
        "SELECT DISTINCT date FROM stock_signals ORDER BY date DESC LIMIT 1 OFFSET 3"
    ).fetchone()[0]
    newest = conn.execute("SELECT MAX(date) FROM stock_signals").fetchone()[0]
    assert target != newest
    conn.execute("DELETE FROM leaders_scan")
    conn.commit()

    leaders_scan.append_leaders_scan(db, scan_date=target)

    written = [r[0] for r in conn.execute(
        "SELECT DISTINCT scan_date FROM leaders_scan")]
    conn.close()
    assert written == [target], f"expected only {target}, got {written}"


class _FakeCursor:
    """Stands in for a psycopg2 RealDictCursor -- .execute() is a no-op,
    .fetchall() replays canned rows shaped like what Postgres NUMERIC
    columns actually decode to (decimal.Decimal, not float)."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        pass

    def fetchall(self):
        return self._rows


def test_vol_rejection_flag_pg_handles_decimal_pivot_high():
    """Regression test: production leaders_scan was frozen on every pending
    date from 2026-07-01 onward with `unsupported operand type(s) for *:
    'decimal.Decimal' and 'float'`. Root cause: `pivot_high * 0.98` where
    pivot_high is a NUMERIC column -- psycopg2 hands back decimal.Decimal,
    and Decimal * float raises TypeError (Decimal * Decimal or Decimal *
    int does not). SQLite's twin (_vol_rejection_flag) never hit this
    because sqlite3 returns plain floats. See docs/KIRAN_CLEANUP_AUDIT.md
    and the GitHub Actions log for the 2026-08-18/19 runs, which show this
    exact message for all 34 pending dates.

    Confirmed against live production data (2026-08-20, read-only) that
    real stock_signals.pivot_high values are decimal.Decimal before this
    fix reproduced the identical TypeError, and that the fixed function
    runs clean against the same real row.
    """
    pivot_high = Decimal("13.650000")
    rows = [
        {
            "high": Decimal("13.00") + Decimal(i) / 100,
            "low": Decimal("12.50"),
            "open": Decimal("12.80"),
            "close": Decimal("12.90"),
            "volume": 100_000 + i * 1000,
        }
        for i in range(21)
    ]
    cur = _FakeCursor(rows)

    # Before the fix this raised TypeError inside the function; now it must
    # just return an int flag.
    result = leaders_scan._vol_rejection_flag_pg(cur, "AAA", "2026-08-19", pivot_high)
    assert result in (0, 1)
