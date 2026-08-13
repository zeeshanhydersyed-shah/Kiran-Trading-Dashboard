"""The Postgres hook must leave a RESUMABLE gap when a date fails.

`_append_setup_log_today_pg()` walks `pending` in ascending order and commits
per date, and the next run recomputes `pending` from `MAX(setup_date)`. That
only self-heals if the committed dates stay a **contiguous prefix**. If the
loop skipped a failed date and carried on, `MAX` would advance past it and
`d > last_logged` could never reach it again -- the same permanent-loss shape
as §21/§24, reintroduced through the error path.

Both branches must therefore stop the loop:
  * unexpected errors re-raise (also making the run go red)
  * transient errors (OperationalError/InterfaceError) `break`

These tests drive the real function with a fake connection, so they need no
Postgres -- which matters, because CI has none (audit §23.5) and this is
exactly the class of bug that CI cannot otherwise see. See §28.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import backfill_setup_log as B  # noqa: E402

psycopg2 = pytest.importorskip("psycopg2")
pytest.importorskip("psycopg2.extras")
import psycopg2.errors  # noqa: E402
import psycopg2.extras  # noqa: E402

LOGGED_THROUGH = dt.date(2026, 6, 30)
SIGNAL_DATES = [dt.date(2026, 6, 30)] + [dt.date(2026, 7, d) for d in (1, 2, 3, 6, 7)]
PENDING = SIGNAL_DATES[1:]          # 07-01 .. 07-07
FAIL_ON = dt.date(2026, 7, 3)       # third pending date


class FakeCursor:
    """Answers only the handful of queries the hook actually issues."""

    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._last = None

    def execute(self, sql, params=None):
        self._last = None
        s = " ".join(sql.split())
        if "MAX(setup_date)" in s:
            self._last = [{"d": LOGGED_THROUGH}]
        elif "DISTINCT date" in s:
            self._last = [{"d": d} for d in SIGNAL_DATES]
        elif "MAX(date)" in s:
            self._last = [{"d": SIGNAL_DATES[-1]}]
        elif s.upper().startswith("SELECT"):          # one of the 4 setup queries
            self.conn.selected_for.append(params[0])
            self._last = [("AAA", params[0]) + ("x",) * 12]
        elif s.upper().startswith("UPDATE"):          # step 3 labelling
            self.rowcount = 0
        return None

    def fetchone(self):
        return self._last[0] if self._last else None

    def fetchall(self):
        return list(self._last or [])


class FakeConn:
    def __init__(self):
        self.committed, self.rolled_back, self.selected_for = [], [], []
        self._current = None

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def commit(self):
        # the date whose SELECTs ran most recently is the one being committed
        if self.selected_for:
            self.committed.append(self.selected_for[-1])

    def rollback(self):
        if self.selected_for:
            self.rolled_back.append(self.selected_for[-1])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def wired(monkeypatch):
    """Point the hook at a fake DB and a no-op forward-returns step."""
    import database_pg
    import compute_forward_returns

    conn = FakeConn()
    monkeypatch.setattr(database_pg, "get_conn", lambda *a, **k: conn)
    monkeypatch.setattr(compute_forward_returns, "main", lambda *a, **k: None)
    return conn


def _fail_execute_batch(exc_type, conn):
    """execute_batch that blows up only while FAIL_ON is being processed."""
    def _inner(cur, sql, rows, **kw):
        if conn.selected_for and conn.selected_for[-1] == FAIL_ON:
            raise exc_type("simulated: connection dropped mid-backfill")
        return None
    return _inner


@pytest.mark.parametrize("exc_type", [psycopg2.OperationalError,
                                      psycopg2.InterfaceError])
def test_transient_error_stops_the_loop_leaving_a_tail_gap(wired, monkeypatch, exc_type):
    """A transient failure on 07-03 must NOT let 07-06/07-07 be written."""
    conn = wired
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        _fail_execute_batch(exc_type, conn))

    B._append_setup_log_today_pg()

    assert conn.committed == PENDING[:2], (
        f"expected commits to stop before {FAIL_ON}; got {conn.committed}"
    )
    assert FAIL_ON in conn.rolled_back, "the failing date must be rolled back"
    assert not any(d > FAIL_ON for d in conn.committed), (
        "a date AFTER the failure was committed -- that pushes MAX(setup_date) "
        "past the gap and makes it permanently unreachable"
    )


@pytest.mark.parametrize("exc_type", [psycopg2.OperationalError,
                                      psycopg2.InterfaceError])
def test_next_run_pending_includes_the_skipped_date(wired, monkeypatch, exc_type):
    """The whole point: tomorrow's run must pick the failed date back up."""
    conn = wired
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        _fail_execute_batch(exc_type, conn))

    B._append_setup_log_today_pg()

    # what the next run would see: MAX(setup_date) = last committed date
    next_high_water = max(conn.committed)
    next_pending = B._pending_setup_log_dates(SIGNAL_DATES, next_high_water)

    assert FAIL_ON in next_pending, (
        f"{FAIL_ON} was skipped and is NOT in the next run's pending list "
        f"({next_pending}) -- it would be lost permanently"
    )
    assert next_pending == [d for d in SIGNAL_DATES if d > next_high_water]
    assert next_pending[0] == FAIL_ON, "resume must start exactly at the failed date"


def test_unexpected_error_also_stops_and_propagates(wired, monkeypatch):
    """Non-transient errors re-raise, so the run goes red AND the gap stays
    at the tail. This is the path a Supabase pooler ReadOnlySqlTransaction
    takes -- it subclasses InternalError, not OperationalError."""
    conn = wired
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        _fail_execute_batch(psycopg2.errors.ReadOnlySqlTransaction, conn))

    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        B._append_setup_log_today_pg()

    assert conn.committed == PENDING[:2]
    assert not any(d >= FAIL_ON for d in conn.committed)
