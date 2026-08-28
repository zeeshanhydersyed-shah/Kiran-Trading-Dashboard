"""TR-13 / OI-6 -- the boring_signals scan-progress marker.

Trust Register §0a.1 / docs/KIRAN_CLEANUP_AUDIT.md §77. Proves the
`scan_boring_breakouts_pending()` rewrite closes the 15-trading-day
silent-loss window (§35.5): resume is now a pure set-difference against
`boring_signals_scanned` with NO lower bound, so an arbitrarily old
un-scanned trading date is still caught.

All tests run against an isolated, synthetic, non-production SQLite DB
(~60 flat-history symbols so RS_60 is computable and the completeness gate's
absolute floor is cleared) -- no real Local/Cloud data, no network, no
Postgres. The synthetic universe is deliberately quiet: 0 signals fire, so
these tests exercise the scan-progress mechanics (which dates get
scanned / marked / skipped), not signal generation (covered elsewhere).
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

N_SYMBOLS = 60           # > bs.MIN_UNIVERSE_ABS so the completeness gate's absolute floor passes
N_HISTORY = 80           # trading days of quiet history before the window of interest
SECTOR = "TECHNOLOGY"    # not in config.EXCLUDED_SECTORS


def _trading_days(start: date, n: int) -> list[str]:
    """n consecutive weekdays from `start` as ISO strings -- weekends skipped,
    so a gap in this list is 'not a trading day', exactly how `prices` behaves
    as the codebase's only trading calendar."""
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


ALL_TRADING_DAYS = _trading_days(date(2026, 1, 5), N_HISTORY + 40)
SYMBOLS = [f"SYM{i:02d}" for i in range(N_SYMBOLS)]


def _seed(conn: sqlite3.Connection, dates: list[str], symbols: list[str] | None = None) -> None:
    """(Re)seed prices_adjusted for `dates` across `symbols` (default: all).
    Flat quiet prices -> no breakout ever fires. KSE-100 flat too."""
    symbols = symbols or SYMBOLS
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stock_metadata (symbol TEXT PRIMARY KEY, is_active INTEGER);
        CREATE TABLE IF NOT EXISTS sectors (symbol TEXT, sector TEXT);
        CREATE TABLE IF NOT EXISTS prices_adjusted (
            symbol TEXT, date TEXT, high REAL, low REAL, close REAL, volume REAL
        );
        CREATE TABLE IF NOT EXISTS index_prices (symbol TEXT, date TEXT, close REAL);
    """)
    for s in symbols:
        conn.execute("INSERT OR IGNORE INTO stock_metadata VALUES (?, 1)", (s,))
        conn.execute("INSERT OR IGNORE INTO sectors VALUES (?, ?)", (s, SECTOR))
    rows = [(s, d, 50.0, 49.5, 50.0, 300_000) for s in symbols for d in dates]
    conn.executemany(
        "INSERT INTO prices_adjusted (symbol, date, high, low, close, volume) VALUES (?,?,?,?,?,?)",
        rows,
    )
    for d in dates:
        conn.execute("INSERT OR IGNORE INTO index_prices VALUES ('KSE-100', ?, 1000.0)", (d,))
    conn.commit()


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "isolated_scan_marker.db")
    conn = sqlite3.connect(path)
    bs.ensure_boring_signals_table(conn)   # also ensures boring_signals_scanned
    conn.close()

    monkeypatch.setattr(bs, "DB_PATH", path)
    monkeypatch.setattr(bs, "_PG_URL", None)
    # The real floor is the 2026-07-10 go-live; the synthetic history below
    # starts earlier, so drop the floor for the test's own date range.
    monkeypatch.setattr(bs, "BORING_SIGNALS_FLOOR_DATE", "2000-01-01")

    _real_connect = sqlite3.connect

    def _guarded(db_arg, *a, **kw):
        try:
            resolved = os.path.abspath(str(db_arg))
        except Exception:
            resolved = None
        if resolved == _REAL_DB_PATH:
            raise RuntimeError(f"BLOCKED: refused a connection to the real DB {_REAL_DB_PATH!r}")
        return _real_connect(db_arg, *a, **kw)

    monkeypatch.setattr(sqlite3, "connect", _guarded)
    return path


def _scanned(path: str) -> dict[str, int]:
    con = sqlite3.connect(path)
    try:
        return {r[0]: r[1] for r in con.execute(
            "SELECT scan_date, complete FROM boring_signals_scanned").fetchall()}
    finally:
        con.close()


# ---------------------------------------------------------------------------
# #1 -- the headline TR-13 acceptance test: a > 15-trading-day gap
# ---------------------------------------------------------------------------

def test_gap_longer_than_old_window_is_still_fully_scanned(db):
    """A gap far longer than the deleted 15-trading-day window: every
    un-scanned in-history date must still be scanned. This is the exact
    silent-loss branch the old code had -- it must be gone."""
    history = ALL_TRADING_DAYS[:N_HISTORY]
    _seed(sqlite3.connect(db), history)

    # First run: cover the first chunk, marking it done.
    covered = history[:N_HISTORY - 30]
    for d in covered:
        bs._mark_scanned(d, N_SYMBOLS, N_SYMBOLS, complete=True)

    gap = history[N_HISTORY - 30:]        # 30 trading days -- 2x the old cap
    assert len(gap) > bs.LONG_GAP_ALERT_DAYS

    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)

    assert eligible == len(gap) == processed
    marks = _scanned(db)
    for d in gap:
        assert d in marks, f"{d} was silently dropped -- the 15-day silent-loss window is back"
    assert all(v == 1 for d, v in marks.items() if d in gap)  # full universe -> complete


# ---------------------------------------------------------------------------
# #2 -- holidays / weekends
# ---------------------------------------------------------------------------

def test_non_trading_days_are_never_pending_or_marked(db):
    history = ALL_TRADING_DAYS[:20]
    _seed(sqlite3.connect(db), history)

    bs.scan_boring_breakouts_pending()

    marks = _scanned(db)
    assert set(marks) == set(history)          # exactly the trading days, nothing else
    # a weekend date between two trading days was never a candidate
    gap_day = (date.fromisoformat(history[4]) + timedelta(days=1))
    while gap_day.weekday() < 5:
        gap_day += timedelta(days=1)
    assert gap_day.isoformat() not in marks


# ---------------------------------------------------------------------------
# #3 -- delayed source release: dates arrive out of order
# ---------------------------------------------------------------------------

def test_late_arriving_date_is_scanned_even_though_newer_dates_are_done(db):
    """Fri's data is published Mon: it lands in prices_adjusted *after* dates
    that are already scanned. A set-difference marker still catches it; a
    naive MAX(signal_date) high-water mark would not."""
    history = ALL_TRADING_DAYS[:20]
    late = history[10]                    # the "Friday" that shows up late
    early = [d for d in history if d != late]

    conn = sqlite3.connect(db)
    _seed(conn, early)                    # everything except `late`
    conn.close()

    bs.scan_boring_breakouts_pending()
    marks1 = _scanned(db)
    assert late not in marks1
    assert marks1[history[15]] == 1       # a date *after* `late` is already done

    # `late` finally arrives.
    conn = sqlite3.connect(db)
    _seed(conn, [late])
    conn.close()

    bs.scan_boring_breakouts_pending()
    marks2 = _scanned(db)
    assert late in marks2, "a date that arrived out of order was never scanned"


# ---------------------------------------------------------------------------
# #4 -- partial-scrape day: scanned, marked incomplete, re-scanned later
# ---------------------------------------------------------------------------

def test_partial_day_is_marked_incomplete_then_rescanned_when_full(db):
    history = ALL_TRADING_DAYS[:40]
    partial_day = history[-1]
    full_days = history[:-1]

    conn = sqlite3.connect(db)
    _seed(conn, full_days)
    _seed(conn, [partial_day], symbols=SYMBOLS[:5])   # only 5 of 60 symbols priced
    conn.close()

    bs.scan_boring_breakouts_pending()
    marks = _scanned(db)
    assert marks[partial_day] == 0, "a thin/partial day must be marked incomplete"
    assert marks[full_days[-1]] == 1

    # it stays pending because complete=0 is excluded from `already_done`
    conn = sqlite3.connect(db)
    _seed(conn, [partial_day], symbols=SYMBOLS[5:])   # the rest of the universe lands
    conn.close()

    bs.scan_boring_breakouts_pending()
    assert _scanned(db)[partial_day] == 1, "a re-scan with full data must flip it to complete"


# ---------------------------------------------------------------------------
# #5 -- invalidate_scanned_from()
# ---------------------------------------------------------------------------

def test_invalidate_scanned_from_reopens_dates_without_touching_signals(db):
    history = ALL_TRADING_DAYS[:30]
    _seed(sqlite3.connect(db), history)
    bs.scan_boring_breakouts_pending()

    # a hand-planted signal row -- must survive the invalidation untouched
    con = sqlite3.connect(db)
    con.execute(
        """INSERT INTO boring_signals
           (symbol, signal_date, lookback_n, trigger_price, target_price, stop_price,
            rs_60, rs_60_decile, avg_vol_10d, liquidity_pass, strategy_confirmed)
           VALUES ('SYM01', ?, 20, 10.0, 11.0, 9.4, 1.0, 9, 300000, 1, 1)""",
        (history[20],),
    )
    con.commit()
    con.close()

    cutoff = history[15]
    n = bs.invalidate_scanned_from(cutoff)
    assert n == len([d for d in history if d >= cutoff])

    marks = _scanned(db)
    assert all(d < cutoff for d in marks), "markers on/after the cutoff must be gone"

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM boring_signals").fetchone()[0] == 1
    finally:
        con.close()

    # next run re-scans exactly the invalidated window
    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)
    assert eligible == len([d for d in history if d >= cutoff])


# ---------------------------------------------------------------------------
# #6 -- idempotency
# ---------------------------------------------------------------------------

def test_second_run_with_no_new_data_is_a_noop(db):
    history = ALL_TRADING_DAYS[:40]
    _seed(sqlite3.connect(db), history)

    bs.scan_boring_breakouts_pending()
    marks_after_first = _scanned(db)
    assert all(v == 1 for v in marks_after_first.values())

    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)
    assert (total, eligible, processed) == (0, 0, 0)
    assert _scanned(db) == marks_after_first


# ---------------------------------------------------------------------------
# #8 -- SQLite / Postgres parity of the resume computation
# ---------------------------------------------------------------------------

def test_pending_dates_helper_is_the_shared_set_difference(monkeypatch):
    """Both backends call _pending_dates() -- the one place the resume set is
    computed -- so they cannot drift. No *upper* bound on age within the
    feature's lifetime: a very old un-done in-window date is still returned."""
    monkeypatch.setattr(bs, "BORING_SIGNALS_FLOOR_DATE", "2000-01-01")
    all_dates = ALL_TRADING_DAYS[:50]
    done = set(all_dates[:20]) | {all_dates[40]}   # a contiguous block + one later date
    pending = bs._pending_dates(all_dates, done)

    assert pending == [d for d in all_dates if d not in done]
    assert all_dates[0] not in pending
    assert all_dates[19] not in pending
    assert all_dates[20] in pending
    assert all_dates[40] not in pending
    assert all_dates[41] in pending
    # order preserved, oldest first
    assert pending == sorted(pending)


def test_pending_dates_never_returns_anything_before_the_go_live_floor():
    """prices_adjusted goes back to 2005; this table's go-live is 2026-07-10
    and the pending scan must never reach earlier -- otherwise the first run
    tries to scan ~19 years of history the table was never meant to hold."""
    dates = ["2005-01-03", "2018-06-01", "2026-07-09",
             bs.BORING_SIGNALS_FLOOR_DATE, "2026-07-13", "2026-08-25"]
    pending = bs._pending_dates(dates, already_done=set())
    assert pending == [bs.BORING_SIGNALS_FLOOR_DATE, "2026-07-13", "2026-08-25"]


# ---------------------------------------------------------------------------
# #9 -- first run on an empty marker table
# ---------------------------------------------------------------------------

def test_first_ever_run_scans_all_history_exactly_once(db):
    history = ALL_TRADING_DAYS[:35]
    _seed(sqlite3.connect(db), history)

    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)
    assert eligible == len(history) == processed
    assert set(_scanned(db)) == set(history)

    # a repeat run does nothing
    total2, eligible2, _ = bs.scan_boring_breakouts_pending(return_coverage=True)
    assert (total2, eligible2) == (0, 0)


def test_completeness_gate_absolute_and_relative_floors():
    # absolute floor
    assert bs._completeness_ok(bs.MIN_UNIVERSE_ABS, []) is True
    assert bs._completeness_ok(bs.MIN_UNIVERSE_ABS - 1, []) is False
    # relative floor only applies once COVERAGE_MEDIAN_WINDOW prior complete scans exist
    short_history = [500] * (bs.COVERAGE_MEDIAN_WINDOW - 1)
    assert bs._completeness_ok(100, short_history) is True          # skipped -> only absolute
    full_history = [500] * bs.COVERAGE_MEDIAN_WINDOW
    assert bs._completeness_ok(500, full_history) is True
    assert bs._completeness_ok(int(0.5 * 500), full_history) is False  # < 85% of median
    assert bs._completeness_ok(int(0.90 * 500), full_history) is True


def test_isolated_db_is_not_the_real_production_database(db):
    assert os.path.abspath(db) != _REAL_DB_PATH


# ---------------------------------------------------------------------------
# bulk-backfill guard + seed_scanned_window (the un-empty-table transition)
# ---------------------------------------------------------------------------

def _plant_covered_history(conn, dates, n_signals=40):
    """Put boring_signals rows on the earlier dates (mostly Stopped, like a
    real pre-marker table) with NO marker rows -- the dangerous shape."""
    for i in range(n_signals):
        d = dates[i % max(1, len(dates) // 2)]
        conn.execute(
            """INSERT INTO boring_signals
               (symbol, signal_date, lookback_n, trigger_price, target_price, stop_price,
                rs_60, rs_60_decile, avg_vol_10d, liquidity_pass, strategy_confirmed, status)
               VALUES (?, ?, 20, 10.0, 11.0, 9.4, 1.0, 9, 300000, 1, 1, 'Stopped')""",
            (f"OLD{i:02d}", d),
        )
    conn.commit()


def test_guard_refuses_large_backfill_over_populated_table_with_no_markers(db):
    history = ALL_TRADING_DAYS[:40]
    conn = sqlite3.connect(db)
    _seed(conn, history)
    _plant_covered_history(conn, history[:20], n_signals=40)   # 40 signals, 0 markers
    conn.close()

    with pytest.raises(RuntimeError, match="refusing to auto-backfill"):
        bs.scan_boring_breakouts_pending()

    # nothing was scanned / marked
    assert _scanned(db) == {}


def test_guard_allows_clean_wipe_replay_empty_signals_table(db):
    """The §71 method: boring_signals empty -> a large first run is a clean
    build, not a corrupting replay. Must be allowed."""
    history = ALL_TRADING_DAYS[:40]
    _seed(sqlite3.connect(db), history)   # 0 boring_signals rows, 0 markers

    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)
    assert eligible == len(history) == processed        # not blocked


def test_guard_allows_long_outage_on_established_marker_table(db):
    history = ALL_TRADING_DAYS[:60]
    conn = sqlite3.connect(db)
    _seed(conn, history)
    _plant_covered_history(conn, history[:20], n_signals=40)
    conn.close()
    # 40 markers already exist (an established table) ...
    for d in history[:40]:
        bs._mark_scanned(d, N_SYMBOLS, N_SYMBOLS, complete=True)
    # ... now a 20-date outage gap
    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)
    assert eligible == 20 == processed                  # allowed through


def test_seed_scanned_window_marks_complete_without_scanning(db, monkeypatch):
    monkeypatch.setattr(bs, "BORING_SIGNALS_FLOOR_DATE", ALL_TRADING_DAYS[5])
    history = ALL_TRADING_DAYS[:40]
    conn = sqlite3.connect(db)
    _seed(conn, history)
    _plant_covered_history(conn, history[5:25], n_signals=30)
    conn.close()
    sig_before = sqlite3.connect(db).execute("SELECT COUNT(*) FROM boring_signals").fetchone()[0]

    through = history[30]
    n = bs.seed_scanned_window(through)

    marks = _scanned(db)
    assert set(marks) == {d for d in history if ALL_TRADING_DAYS[5] <= d <= through}
    assert all(v == 1 for v in marks.values())
    assert n == len(marks)
    # zero scanning happened -> boring_signals unchanged
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM boring_signals").fetchone()[0] == sig_before

    # and now the pending scan only does the genuine tail, no guard trip
    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)
    tail = [d for d in history if d > through]
    assert eligible == len(tail) == processed


# ---------------------------------------------------------------------------
# as_of_date -- the true-chronological-replay guarantee (§0a.1.7)
# ---------------------------------------------------------------------------

def test_walk_end_index_caps_the_forward_walk():
    dates = ["2026-07-10", "2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16"]
    assert bs._walk_end_index(dates, None) == 5
    assert bs._walk_end_index(dates, "2026-07-14") == 3      # includes 07-14
    assert bs._walk_end_index(dates, "2026-07-11") == 1      # between 07-10 and 07-13
    assert bs._walk_end_index(dates, "2026-06-01") == 0      # before all


def test_as_of_date_does_not_resolve_a_position_that_stops_out_later(db, monkeypatch):
    """A catch-up scanning 07-13 must NOT see a position as resolved just
    because it stopped out on 07-20 -- otherwise the dedup gate wrongly
    frees the symbol and a backdated signal fires. This is the exact bug
    the first real run surfaced."""
    monkeypatch.setattr(bs, "BORING_SIGNALS_FLOOR_DATE", "2000-01-01")
    history = ALL_TRADING_DAYS[:90]

    conn = sqlite3.connect(db)
    _seed(conn, history)
    # BREAKER: flat until an entry-day pop, then a hard drop 5 sessions later.
    # Entry well past RS_60's 60-row lookback so the symbol is eligible.
    conn.execute("INSERT OR IGNORE INTO stock_metadata VALUES ('BREAKER', 1)")
    conn.execute("INSERT OR IGNORE INTO sectors VALUES ('BREAKER', ?)", (SECTOR,))
    entry_i = 75
    rows = []
    for i, d in enumerate(history):
        if i < entry_i:
            rows.append(("BREAKER", d, 50.0, 49.5, 50.0, 300_000))
        elif i == entry_i:
            rows.append(("BREAKER", d, 60.0, 58.0, 60.0, 300_000))   # breakout close
        elif i < entry_i + 5:
            # gently rising lows so the trailing stop never catches up here
            rows.append(("BREAKER", d, 61.0, 58.0 + 0.2 * (i - entry_i), 60.0, 300_000))
        else:
            rows.append(("BREAKER", d, 61.0, 40.0, 41.0, 300_000))   # hard stop-out
    conn.executemany(
        "INSERT INTO prices_adjusted (symbol,date,high,low,close,volume) VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    # Scan only through entry_i+2 -- well before the stop-out.
    for d in history[: entry_i + 3]:
        bs.scan_boring_breakouts(d)              # builds the BREAKER position
    open_before = sqlite3.connect(db).execute(
        "SELECT status FROM boring_signals WHERE symbol='BREAKER'").fetchall()
    assert open_before and all(s[0] == "Pending" for s in open_before)

    # Resolve as of a date BEFORE the stop-out: must stay Pending.
    bs.update_open_signal_statuses(as_of_date=history[entry_i + 2])
    still = sqlite3.connect(db).execute(
        "SELECT DISTINCT status FROM boring_signals WHERE symbol='BREAKER'").fetchall()
    assert still == [("Pending",)], f"position resolved using future data: {still}"

    # Resolve with no cap: now it stops out.
    bs.update_open_signal_statuses()
    resolved = sqlite3.connect(db).execute(
        "SELECT DISTINCT status FROM boring_signals WHERE symbol='BREAKER'").fetchall()
    assert resolved == [("Stopped",)]
