"""Tests for backfill_setup_log.py's backfill fix (2026-08-12).

Background: `append_setup_log_today()` computed a single `target_date =
MAX(stock_signals.date)` and wrote only that day. Wrapped in its own
try/except in main.py's cmd_update() (by design), a transient failure on any
one day lost that day permanently -- the next successful run wrote whatever
the newest date was and moved on. `stock_signals.py`, which this reads from,
has always backfilled a date range, so the two silently drifted apart.

Confirmed in the local database before the fix, which is what makes this a
regression test rather than a hypothetical: `stock_signals` held all 147
trading dates of 2026 while `setup_log` stopped at 2026-07-31, with older
one-day holes at 2026-07-13, 07-20, 07-21 and 07-29 -- and every one of those
dates had data that would have produced ~20 RS_LEADER_MARKET rows plus
breakouts. Same defect class as the market_regime/sector_signals loss
(docs/KIRAN_CLEANUP_AUDIT.md §21, §22 A1/A2, audited under B5, fixed in §24).

Coverage here mirrors tests/test_regime_backfill.py:
  1. `_pending_setup_log_dates()` -- the pure, DB-free policy both the SQLite
     and Postgres paths share, so the two cannot drift apart again.
  2. `append_setup_log_today()` against a disposable temp SQLite database
     built from the real schema: multi-day gap coverage, idempotent re-runs,
     pre-gap rows left untouched, and the BREAKOUT transition-day rule still
     honoured on a backfilled date.

The Postgres path is not exercised -- it needs a live connection, which has
no place in an automated suite, and it now shares the same pure policy
function. This is the gap docs/DEPLOYMENT.md §5 names explicitly.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from backfill_setup_log import _pending_setup_log_dates  # noqa: E402

FIXTURE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "fixtures", "psx_fixture.db")

# Real trading-date shape: a Friday, then a gap, then the following week.
DATES = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]

SCHEMA_TABLES = ("setup_log", "stock_signals", "market_regime",
                 "stock_metadata", "prices")


# ── 1. the pure policy ────────────────────────────────────────────────────

def test_empty_signal_dates_yields_nothing():
    assert _pending_setup_log_dates([], None) == []
    assert _pending_setup_log_dates([], "2026-07-27") == []


def test_empty_setup_log_takes_newest_date_only():
    """An empty setup_log must NOT replay all history through this path.

    The historical backfill in the same module inserts BREAKOUT on every
    bos_flag=1 day; this path inserts transition days only. Replaying history
    here would write rows that disagree with the historical record.
    """
    assert _pending_setup_log_dates(DATES, None) == ["2026-07-31"]


def test_multi_day_gap_is_filled_oldest_first():
    """The whole point of the fix: 3 missed days are all picked up, in order."""
    assert _pending_setup_log_dates(DATES, "2026-07-28") == [
        "2026-07-29", "2026-07-30", "2026-07-31",
    ]


def test_up_to_date_yields_nothing():
    assert _pending_setup_log_dates(DATES, "2026-07-31") == []


def test_setup_log_ahead_of_signals_yields_nothing():
    """Defensive: a setup_date newer than any signal date must not go negative."""
    assert _pending_setup_log_dates(DATES, "2026-08-15") == []


def test_input_is_deduped_and_sorted():
    messy = ["2026-07-31", "2026-07-29", "2026-07-31", "2026-07-30"]
    assert _pending_setup_log_dates(messy, "2026-07-28") == [
        "2026-07-29", "2026-07-30", "2026-07-31",
    ]


# ── 2. end-to-end against a disposable SQLite database ────────────────────

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A temp DB carrying the REAL schema, wired in place of the live one.

    Both `backfill_setup_log` and `compute_forward_returns` bind DB_PATH at
    import time (`from config import DB_PATH`), so BOTH module attributes must
    be redirected -- patching config alone would leave step 2 of the function
    under test writing UPDATEs into the real psx_data.db.
    """
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


def _seed_signals(conn, dates, symbol="AAA", bos_by_date=None):
    """One symbol that qualifies for RS_LEADER_MARKET on every given date."""
    bos_by_date = bos_by_date or {}
    conn.executemany(
        """INSERT INTO stock_signals
               (symbol, date, rs_rank, sector_rs_rank, rank_change, rs_score_20,
                base_tightness, vol_contraction, pivot_distance_pct, bos_flag,
                avg_vol_10d)
           VALUES (?, ?, 1, 1, 0, 9.9, 5.0, 0.5, 1.0, ?, 900000)""",
        [(symbol, d, bos_by_date.get(d, 0)) for d in dates],
    )
    conn.commit()


def _logged_dates(conn, setup_type="RS_LEADER_MARKET"):
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT setup_date FROM setup_log WHERE setup_type=? ORDER BY setup_date",
        (setup_type,),
    )]


def test_multi_day_gap_is_backfilled_end_to_end(temp_db):
    """The regression: signals for 5 days, setup_log stops at day 2."""
    conn, _ = temp_db
    _seed_signals(conn, DATES)
    conn.execute(
        """INSERT INTO setup_log (symbol, setup_date, setup_type, outcome_label)
           VALUES ('AAA', ?, 'RS_LEADER_MARKET', 'BREAKEVEN')""",
        (DATES[1],),
    )
    conn.commit()

    from backfill_setup_log import append_setup_log_today
    append_setup_log_today()

    # every date after the last logged one, not just the newest
    assert _logged_dates(conn) == [DATES[1], DATES[2], DATES[3], DATES[4]]


def test_rerun_is_idempotent(temp_db):
    conn, _ = temp_db
    _seed_signals(conn, DATES)
    conn.execute(
        """INSERT INTO setup_log (symbol, setup_date, setup_type, outcome_label)
           VALUES ('AAA', ?, 'RS_LEADER_MARKET', 'BREAKEVEN')""",
        (DATES[0],),
    )
    conn.commit()

    from backfill_setup_log import append_setup_log_today
    append_setup_log_today()
    after_first = conn.execute("SELECT COUNT(*) FROM setup_log").fetchone()[0]
    append_setup_log_today()
    after_second = conn.execute("SELECT COUNT(*) FROM setup_log").fetchone()[0]

    assert after_first == after_second, "re-run duplicated rows"


def test_pre_gap_rows_are_left_alone(temp_db):
    """A backfill must not rewrite rows that already exist."""
    conn, _ = temp_db
    _seed_signals(conn, DATES)
    conn.execute(
        """INSERT INTO setup_log (symbol, setup_date, setup_type, outcome_label,
                                  rs_score_20)
           VALUES ('AAA', ?, 'RS_LEADER_MARKET', 'WINNER', 1.23)""",
        (DATES[1],),
    )
    conn.commit()

    from backfill_setup_log import append_setup_log_today
    append_setup_log_today()

    label, score = conn.execute(
        "SELECT outcome_label, rs_score_20 FROM setup_log "
        "WHERE setup_date=? AND setup_type='RS_LEADER_MARKET'",
        (DATES[1],),
    ).fetchone()
    assert (label, score) == ("WINNER", 1.23)


def test_breakout_transition_rule_holds_on_a_backfilled_date(temp_db):
    """BREAKOUT is a transition-day signal: bos_flag 0 -> 1, not every 1-day.

    Checked on a date reached through the new backfill loop, since that is
    the path that did not exist before and could plausibly get the
    previous-day lookup wrong.
    """
    conn, _ = temp_db
    # flag turns on at DATES[3] and stays on at DATES[4]
    _seed_signals(conn, DATES, bos_by_date={DATES[3]: 1, DATES[4]: 1})
    conn.execute(
        """INSERT INTO setup_log (symbol, setup_date, setup_type, outcome_label)
           VALUES ('AAA', ?, 'RS_LEADER_MARKET', 'BREAKEVEN')""",
        (DATES[0],),
    )
    conn.commit()

    from backfill_setup_log import append_setup_log_today
    append_setup_log_today()

    # only the transition day, not the continuation day
    assert _logged_dates(conn, "BREAKOUT") == [DATES[3]]


# ── Postgres-path source guards ───────────────────────────────────────────────
# These are source-level, not behavioural: the Postgres path cannot be
# exercised without a live Postgres, and CI deliberately has none (audit
# §23.5). They pin the two mistakes that actually shipped and silently wrote
# ZERO rows to production for six weeks -- both invisible to every test here,
# because every test here runs on SQLite. See §25 and §27.

def _pg_source() -> str:
    """Source of the Postgres hook with comment lines stripped.

    Stripping matters: the fix is documented in comments that necessarily
    quote the very strings these guards search for (`tuple(r.values())`,
    `bos_flag = 1`), so an unfiltered source scan matches the explanation
    rather than the code. Caught by these tests failing on their first run.
    """
    import inspect
    import backfill_setup_log
    src = inspect.getsource(backfill_setup_log._append_setup_log_today_pg)
    return "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )


def _pg_queries_block() -> str:
    """Just the four SELECT statements, with SQL `--` comments stripped.

    Scoping matters. Run against the whole function these checks also match
    (a) the SQL comment explaining the bos_flag fix and (b) the labelling
    UPDATE's `outcome_label = 'BREAKEVEN'`, which is correct and has no
    business being aliased. Both showed up as false positives the first time
    these guards ran.
    """
    import re
    m = re.search(r"queries_pg = \[(.*?)\n            \]", _pg_source(), re.S)
    assert m, "could not locate queries_pg -- guard is stale, fix the guard"
    return "\n".join(
        line for line in m.group(1).splitlines() if not line.strip().startswith("--")
    )


def test_pg_insert_does_not_round_trip_rows_through_a_dict():
    """The bug: `tuple(r.values())` on a RealDictCursor.

    Both `'BREAKOUT'` and `'BREAKEVEN'` come back from Postgres named
    `?column?`. A dict collapses the duplicate key, so the row carried 13
    values against 14 %s placeholders and execute_batch raised
    `IndexError: tuple index out of range` for every row, every day -- caught
    by the per-date except, logged as a WARNING, pipeline reported success.
    """
    src = _pg_source()
    assert "tuple(r.values())" not in src, (
        "rows must not be rebuilt from a dict's values -- unnamed duplicate "
        "columns collapse and silently shorten the row"
    )
    assert "tup_cur.execute(select_sql" in src, "the SELECT must use the plain cursor"
    assert "execute_batch(tup_cur" in src, "the INSERT must use the plain cursor"


def test_pg_select_literals_are_aliased():
    """Defence in depth: even through a dict cursor, aliased literals cannot
    collide. Guards the same class if anyone reintroduces a dict round-trip."""
    import re
    unaliased = re.findall(
        r"'(BREAKOUT|PRE_BREAKOUT|RS_LEADER_\w+|BREAKEVEN)'(?!\s+AS\b)",
        _pg_queries_block(),
    )
    assert not unaliased, f"unaliased literal(s) in a Postgres SELECT: {unaliased}"


def test_pg_boolean_columns_are_not_compared_to_integers():
    """`bos_flag` is BOOLEAN in Supabase and INTEGER in SQLite; `= 1` raises
    `operator does not exist: boolean = integer` and aborts the transaction.
    That froze production setup_log at 2026-06-30 (§25)."""
    import re
    bad = re.findall(r"bos_flag\s*=\s*[01]\b", _pg_queries_block())
    assert not bad, f"boolean compared to an integer on the Postgres path: {bad}"
