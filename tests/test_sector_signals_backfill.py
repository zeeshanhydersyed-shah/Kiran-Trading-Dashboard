"""
Tests for sector_signals.py's backfill fix (2026-08-12).

Same root problem as regime.py (see tests/test_regime_backfill.py's module
docstring): the daily hook used to compute and write sector_signals for
only the single latest available date. Because it's wrapped in its own
try/except in main.py's cmd_update() (by design), a transient failure on
one day permanently lost that day -- confirmed on production for
2026-08-07 (docs/KIRAN_CLEANUP_AUDIT.md): sector_signals has no row for
that date even though prices_adjusted does.

These tests build a small, fully synthetic SQLite universe (2 sectors, 2
symbols each) and drive the real SQLite code path
(_compute_and_write_sector_signals_for_date_sqlite /
append_latest_sector_signals) end to end -- no mocking of the actual
computation, only synthetic input data. They focus on what the fix
changed -- backfill completeness, cross-date chaining (rs_rank_prev,
sector_rs_new_high history), and idempotency -- not on re-deriving the RS/
breadth/composite-score math itself, which is pre-existing and unchanged.

The PG path is not exercised here (needs a live Postgres connection, out
of place in an automated suite) -- it shares the same per-date computation
body as the SQLite path (both were split out of the same original
single-date function), so this coverage transfers structurally. As with
regime.py, the PG path should get one manual, read-verified dry run
against a disposable copy before ever touching production.
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sector_signals  # noqa: E402


SECTORS = {
    "TECH":   ["TSYM1", "TSYM2"],
    "CEMENT": ["CSYM1", "CSYM2"],
}
ALL_SYMBOLS = [s for syms in SECTORS.values() for s in syms]

SCHEMA = """
CREATE TABLE prices_adjusted (
    symbol TEXT NOT NULL, date TEXT NOT NULL,
    close REAL, volume INTEGER,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE stock_metadata (
    symbol TEXT PRIMARY KEY, sector TEXT, is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE stock_market_cap (
    symbol TEXT PRIMARY KEY, market_cap_m REAL
);
CREATE TABLE active_stocks_on_date (
    trading_date TEXT, symbol TEXT
);
CREATE TABLE index_prices (
    symbol TEXT NOT NULL, date TEXT NOT NULL, high REAL, low REAL, close REAL NOT NULL,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE market_regime (
    date TEXT PRIMARY KEY, regime TEXT
);
CREATE TABLE sector_signals (
    date TEXT NOT NULL, sector TEXT NOT NULL,
    rs_score_20 REAL, rs_score_50 REAL, rs_rank INTEGER, rs_rank_prev INTEGER,
    breadth_score REAL, adv_dec_ratio REAL, vol_ratio REAL, rs_inflection INTEGER,
    regime TEXT, composite_score REAL,
    sector_ema50 REAL, sector_above_ema INTEGER, sector_ema_slope REAL,
    sector_stage TEXT, sector_pivot_dist_pct REAL, sector_rs_new_high INTEGER,
    PRIMARY KEY (date, sector)
);
"""


def _build_synthetic_db(path: str, n_days: int, seed: int = 0) -> list[str]:
    """Creates the full schema and seeds prices_adjusted/index_prices/
    stock_metadata/stock_market_cap for n_days of synthetic trading.
    sector_signals is left EMPTY -- callers seed it as needed per test.
    Returns the ordered list of trading date strings.
    active_stocks_on_date is deliberately left empty to exercise the real
    documented fallback (full stock_metadata universe) -- a state this
    project's own CLAUDE.md already notes can happen in production.
    Returns the list of trading dates.
    """
    rng = np.random.default_rng(seed)
    dates = [
        (datetime(2024, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(n_days)
    ]

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    for sym in ALL_SYMBOLS:
        conn.execute(
            "INSERT INTO stock_metadata (symbol, sector, is_active) VALUES (?, ?, 1)",
            (sym, "TECH" if sym in SECTORS["TECH"] else "CEMENT"),
        )
        conn.execute(
            "INSERT INTO stock_market_cap (symbol, market_cap_m) VALUES (?, ?)",
            (sym, float(rng.uniform(500, 5000))),
        )

    # TECH trends up faster than CEMENT so RS ranking is meaningful/stable
    for sym in ALL_SYMBOLS:
        drift = 35 if sym in SECTORS["TECH"] else 8
        base = 100 + np.cumsum(rng.normal(loc=drift, scale=6, size=n_days))
        close = np.round(np.clip(base, 10, None), 2)
        volume = rng.integers(200_000, 800_000, size=n_days)
        for d, c, v in zip(dates, close, volume):
            conn.execute(
                "INSERT INTO prices_adjusted (symbol, date, close, volume) VALUES (?, ?, ?, ?)",
                (sym, d, float(c), int(v)),
            )

    kse_base = 40000 + np.cumsum(rng.normal(loc=20, scale=10, size=n_days))
    for d, c in zip(dates, kse_base):
        conn.execute(
            "INSERT INTO index_prices (symbol, date, high, low, close) VALUES "
            "('KSE-100', ?, ?, ?, ?)",
            (d, float(c) * 1.003, float(c) * 0.997, float(c)),
        )
        conn.execute("INSERT INTO market_regime (date, regime) VALUES (?, 'TRENDING_UP')", (d,))

    conn.commit()
    conn.close()
    return dates


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_psx_data.db")
    monkeypatch.setattr(sector_signals, "DB", db_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setattr(sector_signals, "_PG_URL", None)
    return db_path


def _written_dates(db_path: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT DISTINCT date FROM sector_signals ORDER BY date").fetchall()
    conn.close()
    return [r[0] for r in rows]


def test_backfill_fills_multi_day_gap(temp_db):
    n_days = 75
    dates = _build_synthetic_db(temp_db, n_days)

    # Simulate: sector_signals was correctly populated up through 4 days
    # before the latest, then the hook silently failed for the rest.
    conn = sqlite3.connect(temp_db)
    for d in dates[: n_days - 4]:
        sector_signals._compute_and_write_sector_signals_for_date_sqlite(conn, d)
    conn.close()

    assert _written_dates(temp_db) == dates[: n_days - 4]

    sector_signals.append_latest_sector_signals()

    got = _written_dates(temp_db)
    assert got == dates, "every trading date must have sector_signals rows after backfill, no gap"


def test_backfill_chains_rs_rank_prev_across_the_gap(temp_db):
    n_days = 75
    dates = _build_synthetic_db(temp_db, n_days)

    conn = sqlite3.connect(temp_db)
    for d in dates[: n_days - 4]:
        sector_signals._compute_and_write_sector_signals_for_date_sqlite(conn, d)
    conn.close()

    sector_signals.append_latest_sector_signals()

    conn = sqlite3.connect(temp_db)
    rows_by_date = {}
    for d in dates[-5:]:  # the last pre-gap date + the 4 backfilled ones
        rows_by_date[d] = dict(
            conn.execute(
                "SELECT sector, rs_rank FROM sector_signals WHERE date = ?", (d,)
            ).fetchall()
        )
    conn.close()

    ordered = dates[-5:]
    for i in range(1, len(ordered)):
        prev_date, cur_date = ordered[i - 1], ordered[i]
        conn = sqlite3.connect(temp_db)
        cur_prev_ranks = dict(
            conn.execute(
                "SELECT sector, rs_rank_prev FROM sector_signals WHERE date = ?", (cur_date,)
            ).fetchall()
        )
        conn.close()
        for sector in SECTORS:
            assert cur_prev_ranks[sector] == rows_by_date[prev_date][sector], (
                f"{cur_date}'s rs_rank_prev for {sector} must equal {prev_date}'s "
                f"freshly-backfilled rs_rank, proving the loop chains sequentially "
                f"rather than each date reading stale prev-gap data"
            )


def test_backfill_is_idempotent(temp_db):
    n_days = 75
    dates = _build_synthetic_db(temp_db, n_days)

    conn = sqlite3.connect(temp_db)
    for d in dates[: n_days - 3]:
        sector_signals._compute_and_write_sector_signals_for_date_sqlite(conn, d)
    conn.close()

    sector_signals.append_latest_sector_signals()

    conn = sqlite3.connect(temp_db)
    before = conn.execute(
        "SELECT date, sector, rs_score_20, rs_rank, rs_rank_prev, composite_score "
        "FROM sector_signals ORDER BY date, sector"
    ).fetchall()
    conn.close()

    sector_signals.append_latest_sector_signals()  # nothing left to backfill

    conn = sqlite3.connect(temp_db)
    after = conn.execute(
        "SELECT date, sector, rs_score_20, rs_rank, rs_rank_prev, composite_score "
        "FROM sector_signals ORDER BY date, sector"
    ).fetchall()
    conn.close()

    assert before == after, "a re-run with nothing new to backfill must not change any existing row"


def test_backfill_does_not_touch_dates_before_the_gap(temp_db):
    n_days = 75
    dates = _build_synthetic_db(temp_db, n_days)

    conn = sqlite3.connect(temp_db)
    for d in dates[: n_days - 4]:
        sector_signals._compute_and_write_sector_signals_for_date_sqlite(conn, d)
    conn.close()

    conn = sqlite3.connect(temp_db)
    pre_existing = conn.execute(
        "SELECT date, sector, rs_score_20, rs_rank, composite_score "
        "FROM sector_signals WHERE date < ? ORDER BY date, sector",
        (dates[n_days - 4],),
    ).fetchall()
    conn.close()

    sector_signals.append_latest_sector_signals()

    conn = sqlite3.connect(temp_db)
    after = conn.execute(
        "SELECT date, sector, rs_score_20, rs_rank, composite_score "
        "FROM sector_signals WHERE date < ? ORDER BY date, sector",
        (dates[n_days - 4],),
    ).fetchall()
    conn.close()

    assert pre_existing == after, "rows written before the gap must be completely untouched"


def test_normal_single_new_date_still_works(temp_db):
    """Sanity check: the no-gap, single-new-date case still works exactly
    as the old single-date-only version did.
    """
    n_days = 75
    dates = _build_synthetic_db(temp_db, n_days)

    conn = sqlite3.connect(temp_db)
    for d in dates[:-1]:  # everything except the latest date
        sector_signals._compute_and_write_sector_signals_for_date_sqlite(conn, d)
    conn.close()

    sector_signals.append_latest_sector_signals()

    assert _written_dates(temp_db) == dates


def test_backfill_from_completely_empty_table(temp_db):
    """The other edge the old code silently mishandled less obviously:
    a totally empty sector_signals (e.g. a fresh DB) must backfill every
    available trading date, not just the latest one.
    """
    n_days = 75
    dates = _build_synthetic_db(temp_db, n_days)

    sector_signals.append_latest_sector_signals()

    assert _written_dates(temp_db) == dates
