"""Tests for boring_signals.py's Postgres port (2026-08-21).

`boring_signals.py` was SQLite-only until this port (see CLAUDE.md's
now-closed "Known Gap" entry and the pre-registered port plan). Three
specific gotchas were already hit and fixed elsewhere in this codebase
during earlier Postgres ports (leaders_scan.py, signal_engine.py) and are
exactly the failure shapes worth pinning here rather than re-discovering
live against Supabase:

  1. NUMERIC columns (high/low/close in prices_adjusted) round-trip as
     decimal.Decimal via psycopg2 -- this module's numpy math needs plain
     floats. _load_price_history_pg() SQL-casts to DOUBLE PRECISION, but
     the regression test below feeds raw Decimal through the fake cursor
     anyway, so it also covers the case where that cast is ever dropped
     (np.array(..., dtype=float) coerces Decimal correctly either way).
  2. Boolean columns must be queried with IS TRUE/IS FALSE, and
     liquidity_pass/strategy_confirmed/executed are BOOLEAN in the new
     Postgres table vs INTEGER 0/1 in SQLite -- get_boring_signals() must
     still hand dashboard.py the same int 0/1 shape it always has.
  3. signal_date/executed_at/resolution_date are native DATE/TIMESTAMP in
     Postgres (psycopg2 hands back date/datetime objects or None), TEXT in
     SQLite -- get_boring_signals() must still hand dashboard.py plain
     strings (or None), not date objects or the literal string "None".
"""
from __future__ import annotations

import datetime
import os
import sys
from decimal import Decimal

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import boring_signals  # noqa: E402


class _FakeCursor:
    """Stands in for a psycopg2 RealDictCursor -- .execute() is a no-op,
    .fetchall() replays canned rows shaped like what Postgres actually
    decodes columns to (decimal.Decimal for NUMERIC, not float). Supports a
    queue of result sets so a function that issues more than one query
    (e.g. _eligible_universe_pg's universe query then its exclusion query)
    gets a different canned answer each call, in order."""

    def __init__(self, result_queue):
        self._queue = list(result_queue)
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchall(self):
        return self._queue.pop(0)

    def fetchone(self):
        rows = self._queue.pop(0)
        return rows[0] if rows else None


def test_load_price_history_pg_handles_decimal_ohlc():
    """Regression shape: prices_adjusted.high/low/close are NUMERIC in
    Postgres -- psycopg2 hands back decimal.Decimal. Feeding that straight
    through must still produce plain-float numpy arrays, since
    _rs60_and_liquidity_asof()/_breakout_fires() do float arithmetic
    (Decimal * float raises TypeError -- see leaders_scan._vol_rejection_flag_pg's
    PR #12 fix for the exact failure this avoids)."""
    rows = [
        {"symbol": "AAA", "date": "2026-08-17",
         "high": Decimal("13.65"), "low": Decimal("13.10"),
         "close": Decimal("13.40"), "volume": 250_000},
        {"symbol": "AAA", "date": "2026-08-18",
         "high": Decimal("13.90"), "low": Decimal("13.30"),
         "close": Decimal("13.80"), "volume": 300_000},
    ]
    cur = _FakeCursor([rows])

    by_symbol = boring_signals._load_price_history_pg(cur, {"AAA"})

    assert set(by_symbol.keys()) == {"AAA"}
    pf = by_symbol["AAA"]
    assert pf["high"].dtype == float
    assert pf["low"].dtype == float
    assert pf["close"].dtype == float
    assert pf["high"].tolist() == [13.65, 13.90]
    # Arithmetic that would raise TypeError on raw Decimal must just work.
    assert pf["close"][1] * 1.01 == 13.80 * 1.01


def test_load_price_history_pg_empty_symbols_short_circuits():
    """No query at all for an empty universe -- ANY(%s) with an empty list
    is valid SQL but pointless; also guards against ever regressing to
    ANY('{}') edge cases."""
    cur = _FakeCursor([])
    assert boring_signals._load_price_history_pg(cur, set()) == {}
    assert cur.queries == []


def test_eligible_universe_pg_excludes_configured_sectors():
    universe_rows = [{"symbol": "AAA"}, {"symbol": "BBB"}, {"symbol": "CCC"}]
    excluded_rows = [{"symbol": "BBB"}]
    cur = _FakeCursor([universe_rows, excluded_rows])

    result = boring_signals._eligible_universe_pg(cur)

    assert result == {"AAA", "CCC"}
    # First query must gate on is_active IS TRUE, not = 1 (gotcha #2).
    assert "IS TRUE" in cur.queries[0][0]


def test_normalize_boring_signals_rows_decimal_bool_and_date():
    """The full row shape a real Postgres SELECT * FROM boring_signals
    would hand back: Decimal price columns, Python bool flag columns,
    datetime.date for signal_date, None for an unresolved resolution_date.
    Output must match what the SQLite path's pd.read_sql_query() has always
    produced -- plain float, plain int 0/1, plain str/None -- since
    dashboard.py's rendering code is written against that shape and has no
    backend-specific branch of its own."""
    rows = [{
        "id": 1,
        "symbol": "AAA",
        "signal_date": datetime.date(2026, 8, 17),
        "lookback_n": 20,
        "breakout_level": Decimal("13.50"),
        "trigger_price": Decimal("13.80"),
        "target_price": Decimal("15.18"),
        "stop_price": Decimal("12.97"),
        "rs_60": Decimal("4.25"),
        "rs_60_decile": 9,
        "avg_vol_10d": Decimal("312500.00"),
        "liquidity_pass": True,
        "strategy_confirmed": True,
        "status": "Pending",
        "executed": False,
        "executed_at": None,
        "executed_price": None,
        "resolution_date": None,
        "resolution_type": None,
        "days_open": 3,
        "current_stop": Decimal("12.97"),
        "created_at": datetime.datetime(2026, 8, 17, 16, 30, 0),
    }]

    df = boring_signals._normalize_boring_signals_rows(rows)

    assert df["breakout_level"].dtype == float
    assert df.loc[0, "trigger_price"] == 13.80
    # np.int64, not Python bool/int -- matches what the SQLite path's own
    # pd.read_sql_query() produces for an INTEGER column, which is the
    # parity bar here, not "plain Python int".
    assert df["liquidity_pass"].dtype.kind == "i"
    assert df.loc[0, "liquidity_pass"] == 1
    assert df.loc[0, "strategy_confirmed"] == 1
    assert df.loc[0, "executed"] == 0
    assert df.loc[0, "signal_date"] == "2026-08-17"
    # An unresolved trade's resolution_date must stay a real None, not the
    # literal string "None" that a naive .astype(str) would produce.
    assert df.loc[0, "resolution_date"] is None


def test_normalize_boring_signals_rows_empty_is_empty_frame():
    df = boring_signals._normalize_boring_signals_rows([])
    assert df.empty


def test_scan_boring_breakouts_dispatches_to_pg_when_url_set(monkeypatch):
    """Public API must route to the Postgres implementation whenever
    _PG_URL is set -- the one thing every _pg twin's correctness depends on
    upstream of its own logic."""
    called = {}
    monkeypatch.setattr(boring_signals, "_PG_URL", "postgres://fake")
    monkeypatch.setattr(boring_signals, "_scan_boring_breakouts_pg",
                         lambda date=None: called.setdefault("pg", date) or 0)
    boring_signals.scan_boring_breakouts("2026-08-17")
    assert called == {"pg": "2026-08-17"}


def test_scan_boring_breakouts_dispatches_to_sqlite_when_no_url(monkeypatch):
    called = {}
    monkeypatch.setattr(boring_signals, "_PG_URL", None)
    monkeypatch.setattr(boring_signals, "_scan_boring_breakouts_sqlite",
                         lambda date=None: called.setdefault("sqlite", date) or 0)
    boring_signals.scan_boring_breakouts("2026-08-17")
    assert called == {"sqlite": "2026-08-17"}


def test_get_boring_signals_dispatches_on_pg_url(monkeypatch):
    monkeypatch.setattr(boring_signals, "_PG_URL", "postgres://fake")
    monkeypatch.setattr(boring_signals, "_get_boring_signals_pg",
                         lambda status=None: "pg-result")
    assert boring_signals.get_boring_signals("Pending") == "pg-result"


def test_mark_executed_dispatches_on_pg_url(monkeypatch):
    called = {}
    monkeypatch.setattr(boring_signals, "_PG_URL", "postgres://fake")
    monkeypatch.setattr(boring_signals, "_mark_executed_pg",
                         lambda signal_id, executed_price=None: called.setdefault("pg", (signal_id, executed_price)))
    boring_signals.mark_executed(42, 13.5)
    assert called == {"pg": (42, 13.5)}
