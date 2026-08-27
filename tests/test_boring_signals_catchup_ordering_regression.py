"""Regression test for the confirmed MACFL / 2026-08-19 catch-up ordering
failure in `boring_signals.py`.

Forensic background (read-only investigation, separate session, not this
file): a real, historical, production-data instance of a signal-suppression
defect was independently confirmed on Local SQLite by replaying the exact
`_breakout_fires()` formula against real `prices_adjusted` rows and
cross-checking the real `boring_signals` table:

    MACFL, lookback_n=20
    signal_date=2026-08-17, trigger_price=80.38, status now 'Stopped'
    resolution_date=2026-08-19 (HYBRID_TRAIL stop genuinely breached
        intraday: Low(2026-08-19)=79.58 <= the applicable trailing stop)
    Close(2026-08-19)=92.56 independently clears a fresh N=20 Donchian
        breakout level (~89.30) -- MACFL genuinely re-qualified for a new
        signal the SAME day its prior position resolved.
    No boring_signals row exists for MACFL / 2026-08-19. The fresh,
        legitimate signal was never recorded.

Root cause, confirmed by reading the real call sequence
(`_scan_boring_breakouts_sqlite()` / `_scan_boring_breakouts_pending_sqlite()`
/ `update_open_signal_statuses()`): each date's scan checks a fresh
`open_symbols` snapshot (boring_signals.py's DEDUP GATE, ~line 485) against
whatever `status` currently sits in the table -- but `update_open_signal_
statuses()` (the only thing that can flip a row from Pending to Stopped) is
never called between dates within a pending-date pass, only once at the very
end. So a symbol whose true state (per real price data, already fully
available in `prices_adjusted` by the time the pass runs) has already
resolved is still treated as "open" and blocked from firing a new,
independently-qualifying signal until the whole pass finishes.

This module proves that invariant two ways, using the REAL, unmodified
production functions (`scan_boring_breakouts`, `update_open_signal_
statuses`) against an isolated, synthetic, non-production SQLite database --
no monkeypatching of the scan/status logic itself, no reliance on real
Local/Cloud data, no network, no Postgres:

  1. test_defective_ordering_suppresses_the_resolved_and_requalified_signal
     -- calls the two real functions in the EXACT sequence production uses
     today (scan date 1, scan date 2, resolve statuses once at the end --
     the same shape `scan_boring_breakouts_pending()` + main.py's hook
     produce) and asserts the historical failure reproduces: the fresh
     signal on the resolution date is silently absent.

  2. test_corrected_ordering_would_have_permitted_the_legitimate_signal
     -- a test-level orchestration of the ordering the (not-yet-authorized)
     production fix would produce: resolve statuses BEFORE evaluating the
     next date, not after. Same real functions, same fixture, statuses
     resolved between the two scan calls instead of after both. Asserts the
     fresh signal IS recorded, proving the invariant is achievable without
     any change to `boring_signals.py` itself.

Neither test modifies boring_signals.py or any other production file.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import boring_signals as bs  # noqa: E402

_REAL_DB_PATH = os.path.abspath(os.path.join(_ROOT, "psx_data.db"))

SYMBOL = "MACFL"
SECTOR = "TECHNOLOGY"  # not in config.EXCLUDED_SECTORS

# 65 "quiet" trading days (enough for RS_60's 60-day-lookback requirement,
# see _rs60_and_liquidity_asof -- idx must be >= RS_WINDOW=60 as of the day
# BEFORE the evaluated date), then three days of interest:
#   entry_date -- the original signal fires (mirrors real 2026-08-17)
#   d1_date    -- the prior position's trailing stop is genuinely breached
#                 intraday AND a fresh, independent breakout genuinely
#                 qualifies the same day (mirrors real 2026-08-19)
#   d2_date    -- a second date the real catch-up pass also processed
#                 afterward (mirrors real 2026-08-20); quiet/no new event
#                 for this symbol, included only so the fixture genuinely
#                 exercises a two-date pending pass, not a single date.
_N_QUIET = 65
_START = date(2020, 1, 1)
_ALL_DATES = [(_START + timedelta(days=i)).isoformat() for i in range(_N_QUIET + 3)]
QUIET_DATES = _ALL_DATES[:_N_QUIET]
ENTRY_DATE = _ALL_DATES[_N_QUIET]
D1_DATE = _ALL_DATES[_N_QUIET + 1]
D2_DATE = _ALL_DATES[_N_QUIET + 2]


def _seed_prices(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE stock_metadata (symbol TEXT PRIMARY KEY, is_active INTEGER);
        CREATE TABLE sectors (symbol TEXT, sector TEXT);
        CREATE TABLE prices_adjusted (
            symbol TEXT, date TEXT, high REAL, low REAL, close REAL, volume REAL
        );
        CREATE TABLE index_prices (symbol TEXT, date TEXT, close REAL);
    """)
    conn.execute("INSERT INTO stock_metadata VALUES (?, 1)", (SYMBOL,))
    conn.execute("INSERT INTO sectors VALUES (?, ?)", (SYMBOL, SECTOR))

    rows = []
    for d in QUIET_DATES:
        # Flat quiet history: high just above close/low so the N=20/N=60
        # Donchian window has a known, boring prior high (50.0) that the
        # entry day clears.
        rows.append((SYMBOL, d, 50.0, 49.5, 50.0, 100_000))
    # entry_date: fires a real N=20 (and N=60) breakout -- prior 20/60-day
    # high is 50.0 (all quiet days); close 55.0 clears 50.0*1.01=50.5.
    rows.append((SYMBOL, ENTRY_DATE, 55.0, 53.0, 55.0, 100_000))
    # d1_date: Low=52.0 breaches the HYBRID_TRAIL stop that ratcheted up
    # from the entry day (see module docstring's math, verified against the
    # real _update_open_signal_statuses_sqlite() walk) -- a genuine
    # intraday stop-out. Close=93.0 the SAME day clears a fresh N=20 level
    # (prior 20-day high now 55.0 from entry_date; 55.0*1.01=55.55).
    rows.append((SYMBOL, D1_DATE, 93.0, 52.0, 93.0, 100_000))
    # d2_date: quiet continuation, no new breakout (prior high now 93.0;
    # close 93.0 does not clear 93.0*1.01). Present only to give the
    # pending-date pass a genuine second date.
    rows.append((SYMBOL, D2_DATE, 93.5, 92.0, 93.0, 100_000))

    conn.executemany(
        "INSERT INTO prices_adjusted (symbol, date, high, low, close, volume) VALUES (?,?,?,?,?,?)",
        rows,
    )

    # KSE-100: flat throughout. RS_60 ends up 0 (quiet days) / 10.0 (once
    # the stock has moved and the index hasn't) -- either way, non-None,
    # which is all _scan_boring_breakouts_sqlite() requires to keep the
    # symbol eligible; RS_60's actual value plays no role in whether the
    # Donchian breakout itself fires.
    kse_rows = [("KSE-100", d, 1000.0) for d in _ALL_DATES]
    conn.executemany("INSERT INTO index_prices VALUES (?,?,?)", kse_rows)

    conn.commit()


@pytest.fixture
def isolated_boring_signals_db(tmp_path, monkeypatch):
    """Synthetic, isolated SQLite fixture -- never the real production DB.

    Follows this project's established isolation convention (see
    tests/test_tr05_freshness_gate.py's isolated_pipeline_db): DB_PATH is
    redirected via monkeypatch to a tmp_path file, and sqlite3.connect is
    additionally guarded so that even an unpatched/frozen reference to the
    real DB_PATH anywhere would be refused rather than silently succeed.
    boring_signals.py only ever calls sqlite3.connect(DB_PATH) using its
    own module-level DB_PATH binding, so patching bs.DB_PATH alone is
    sufficient -- the guard below is deliberate belt-and-suspenders, not
    a sign anything here is expected to reach the real path.
    """
    db_path = str(tmp_path / "isolated_boring_signals_test.db")

    conn = sqlite3.connect(db_path)
    _seed_prices(conn)
    bs.ensure_boring_signals_table(conn)
    conn.commit()
    conn.close()

    monkeypatch.setattr(bs, "DB_PATH", db_path)
    monkeypatch.setattr(bs, "_PG_URL", None)

    _real_connect = sqlite3.connect

    def _guarded_connect(db_arg, *args, **kwargs):
        try:
            resolved = os.path.abspath(str(db_arg))
        except Exception:
            resolved = None
        if resolved == _REAL_DB_PATH:
            raise RuntimeError(
                f"BLOCKED: attempted to open the real production database "
                f"({_REAL_DB_PATH!r}) during an isolated test -- refusing "
                f"the connection."
            )
        return _real_connect(db_arg, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _guarded_connect)

    return db_path


def _fetch_macfl_row(db_path, signal_date, lookback_n=20):
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute(
            "SELECT status, resolution_date, resolution_type, trigger_price "
            "FROM boring_signals WHERE symbol=? AND signal_date=? AND lookback_n=?",
            (SYMBOL, signal_date, lookback_n),
        )
        return cur.fetchone()
    finally:
        con.close()


def test_defective_ordering_suppresses_the_resolved_and_requalified_signal(
    isolated_boring_signals_db,
):
    """Reproduces the historical MACFL failure using the REAL production
    call sequence: scan(D1) then scan(D2), with update_open_signal_
    statuses() called only once at the end -- exactly what
    scan_boring_breakouts_pending() + main.py's hook do today. This is the
    exact ordering that let the real 2026-08-19 signal go silently missing.
    """
    db_path = isolated_boring_signals_db

    inserted_entry = bs.scan_boring_breakouts(ENTRY_DATE)
    assert inserted_entry >= 1, "fixture is wrong -- the entry-day breakout must fire"
    entry_row = _fetch_macfl_row(db_path, ENTRY_DATE)
    assert entry_row is not None and entry_row[0] == "Pending"

    # Production ordering: both pending dates are scanned before ANY status
    # resolution happens (mirrors _scan_boring_breakouts_pending_sqlite()'s
    # per-date loop, which never calls update_open_signal_statuses()).
    bs.scan_boring_breakouts(D1_DATE)
    bs.scan_boring_breakouts(D2_DATE)

    # THE DEFECT: no fresh signal was recorded for D1_DATE, even though
    # MACFL genuinely re-qualified that day.
    suppressed_row = _fetch_macfl_row(db_path, D1_DATE)
    assert suppressed_row is None, (
        "expected the historical suppression to reproduce (no boring_signals "
        "row for MACFL/D1_DATE) -- if this fails, the defect this test "
        "protects against may already be fixed, or the fixture no longer "
        "reproduces it; do not weaken this assertion without re-verifying "
        "against the real MACFL/2026-08-19 facts in the module docstring."
    )

    # Only NOW does status resolution run -- proving the suppression wasn't
    # because MACFL never actually resolved; ground truth (via the real,
    # unmodified update_open_signal_statuses()) confirms it resolved
    # exactly on D1_DATE, the same date its fresh signal was silently lost.
    bs.update_open_signal_statuses()
    resolved_entry_row = _fetch_macfl_row(db_path, ENTRY_DATE)
    assert resolved_entry_row[0] == "Stopped"
    assert resolved_entry_row[1] == D1_DATE
    assert resolved_entry_row[2] == "STOP"


def test_corrected_ordering_would_have_permitted_the_legitimate_signal(
    isolated_boring_signals_db,
):
    """Test-level orchestration of the (not-yet-authorized) production fix:
    resolve statuses BEFORE evaluating the next pending date, rather than
    after the whole pass. Same real functions, same fixture, only the call
    order changes -- proving the invariant is achievable with zero change
    to boring_signals.py's own code.
    """
    db_path = isolated_boring_signals_db

    inserted_entry = bs.scan_boring_breakouts(ENTRY_DATE)
    assert inserted_entry >= 1, "fixture is wrong -- the entry-day breakout must fire"

    # Corrected ordering: resolve open positions using the full price
    # history already available (D1_DATE's low is already in
    # prices_adjusted, exactly as it would be in production -- prices are
    # scraped well before boring_signals runs) BEFORE D1_DATE's dedup check
    # runs, instead of after.
    bs.update_open_signal_statuses()
    resolved_entry_row = _fetch_macfl_row(db_path, ENTRY_DATE)
    assert resolved_entry_row[0] == "Stopped", (
        "fixture/ordering assumption broken -- the entry-day position must "
        "already be resolved before D1_DATE's scan runs for this test to "
        "demonstrate anything"
    )

    bs.scan_boring_breakouts(D1_DATE)

    permitted_row = _fetch_macfl_row(db_path, D1_DATE)
    assert permitted_row is not None, (
        "under corrected ordering, MACFL's independently-qualifying "
        "D1_DATE breakout must be recorded -- its prior position was "
        "already resolved before this date's dedup check ran"
    )
    assert permitted_row[0] == "Pending"
    assert permitted_row[3] == pytest.approx(93.0)


def test_isolated_db_is_not_the_real_production_database(isolated_boring_signals_db):
    """Direct proof the fixture never points at the real DB, independent of
    whether either test above happens to exercise that path."""
    assert os.path.abspath(isolated_boring_signals_db) != _REAL_DB_PATH


def test_guard_blocks_a_direct_real_path_connection_attempt(isolated_boring_signals_db):
    """Proves the sqlite3.connect guard itself is live, the same
    belt-and-suspenders check this project's other isolated fixtures use."""
    with pytest.raises(RuntimeError, match="BLOCKED"):
        sqlite3.connect(_REAL_DB_PATH)
