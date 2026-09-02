"""TR-01 shadow-mode Component B -- local_archive_sync.py (SHADOWMODE_SPEC_DRAFT.md
§6 / ledger §111).

Fully isolated: the "Postgres" source is a real SQLite DB wrapped in a
compact psycopg2-emulating shim (same idea as
test_boring_signals_backend_parity.py's _PgLikeCursor -- translate the small,
fixed set of PG-isms this one script emits: `%s` placeholders, `= %s` on a
boolean column). No live Supabase, no network. The archive is its own
separate SQLite file. psx_data.db is never referenced.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import local_archive_sync as las  # noqa: E402


# ---------------------------------------------------------------------------
# SQLite-as-Postgres shim
# ---------------------------------------------------------------------------
class _PgCur:
    def __init__(self, sqlite_cur):
        self._c = sqlite_cur

    def execute(self, sql, params=()):
        self._c.execute(sql.replace("%s", "?"), params)
        return self

    @property
    def description(self):
        return self._c.description

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def close(self):
        self._c.close()


class _PgConn:
    def __init__(self, path):
        self._conn = sqlite3.connect(path)

    def cursor(self):
        return _PgCur(self._conn.cursor())

    def set_session(self, **kw):  # psycopg2 API, no-op here
        pass

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# a minimal "Postgres" with the tables local_archive_sync pulls
# ---------------------------------------------------------------------------
_PG_TABLES = {
    "prices": "symbol TEXT, date TEXT, close REAL",
    "index_prices": "symbol TEXT, date TEXT, close REAL",
    "prices_adjusted": "symbol TEXT, date TEXT, close REAL",
    "stock_signals": "symbol TEXT, date TEXT, bos_flag INTEGER",
    "sector_signals": "sector TEXT, date TEXT, rs_rank INTEGER",
    "market_regime": "date TEXT, regime TEXT",
    "recovery_signals": "symbol TEXT, as_of_date TEXT, status TEXT",
    "portfolio_signals": "symbol TEXT, as_of_date TEXT, weight REAL",
    "boring_signals": "symbol TEXT, signal_date TEXT, strategy_confirmed INTEGER, status TEXT",
    "boring_signals_scanned": "scan_date TEXT, status TEXT",
    "setup_log": "symbol TEXT, setup_date TEXT, setup_type TEXT, outcome_label TEXT",
    "leaders_scan": "symbol TEXT, scan_date TEXT, score REAL",
    "leaders_top_picks": "symbol TEXT, scan_date TEXT, outcome_label TEXT",
    "scrape_coverage": "scrape_date TEXT, coverage_status TEXT",
    "current_publication": (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, promoted_at TEXT, "
        "source_as_of TEXT, promoted INTEGER, coherence TEXT"
    ),
}


@pytest.fixture
def pg_path(tmp_path):
    p = str(tmp_path / "fake_pg.db")
    con = sqlite3.connect(p)
    for name, cols in _PG_TABLES.items():
        con.execute(f"CREATE TABLE {name} ({cols})")
    con.commit()
    con.close()
    return p


@pytest.fixture
def archive_path(tmp_path):
    return str(tmp_path / "psx_archive.db")


def _seed_session(pg_path, session, *, promoted=True, coherence="COHERENT",
                  run_id=None, promoted_at=None, rows_per_table=2):
    run_id = run_id or f"run-{session}"
    promoted_at = promoted_at or (session + "T20:00:00Z")
    con = sqlite3.connect(pg_path)
    try:
        con.execute(
            "INSERT INTO current_publication (run_id, promoted_at, source_as_of, promoted, coherence) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, promoted_at, session, 1 if promoted else 0, coherence),
        )
        for i in range(rows_per_table):
            con.execute("INSERT INTO prices VALUES (?, ?, ?)", (f"SYM{i}", session, 100.0 + i))
            con.execute("INSERT INTO index_prices VALUES (?, ?, ?)", ("KSE100", session, 50000.0))
            con.execute("INSERT INTO prices_adjusted VALUES (?, ?, ?)", (f"SYM{i}", session, 100.0 + i))
            con.execute("INSERT INTO stock_signals VALUES (?, ?, ?)", (f"SYM{i}", session, i % 2))
            con.execute("INSERT INTO sector_signals VALUES (?, ?, ?)", (f"SEC{i}", session, i + 1))
            con.execute("INSERT INTO setup_log VALUES (?, ?, ?, ?)", (f"SYM{i}", session, "BREAKOUT", "BREAKEVEN"))
            con.execute("INSERT INTO leaders_scan VALUES (?, ?, ?)", (f"SYM{i}", session, 0.5))
        con.execute("INSERT INTO market_regime VALUES (?, ?)", (session, "TRENDING_UP"))
        con.execute("INSERT INTO boring_signals_scanned VALUES (?, ?)", (session, "complete"))
        con.execute("INSERT INTO scrape_coverage VALUES (?, ?)", (session, "COMPLETE"))
        con.execute("INSERT INTO boring_signals VALUES (?, ?, ?, ?)", ("PRL", session, 1, "Pending"))
        con.commit()
    finally:
        con.close()


def _run(pg_path, archive_path, window_days=90, now=None):
    conn = _PgConn(pg_path)
    try:
        return las.sync_archive(pg_conn=conn, archive_path=archive_path,
                                window_days=window_days, now=now)
    finally:
        conn.close()


def _arc_rows(archive_path, table, session=None, datecol=None):
    con = sqlite3.connect(archive_path)
    try:
        if session is None:
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {datecol} = ?", (session,)
        ).fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_only_promoted_coherent_sessions_are_pulled(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01")
    _seed_session(pg_path, "2026-09-02")
    _seed_session(pg_path, "2026-09-03", promoted=False)          # withheld
    _seed_session(pg_path, "2026-09-04", coherence="INCOHERENT")  # incoherent

    summary = _run(pg_path, archive_path)

    assert set(summary["synced"]) == {"2026-09-01", "2026-09-02"}
    assert _arc_rows(archive_path, "prices", "2026-09-03", "date") == 0
    assert _arc_rows(archive_path, "prices", "2026-09-04", "date") == 0
    assert _arc_rows(archive_path, "prices", "2026-09-02", "date") == 2
    assert _arc_rows(archive_path, "boring_signals", "2026-09-01", "signal_date") == 1


def test_rerun_with_no_new_data_is_a_clean_noop(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01")
    _seed_session(pg_path, "2026-09-02")
    _run(pg_path, archive_path)
    before = {t: _arc_rows(archive_path, t) for t, _ in las.ARCHIVE_TABLES}

    summary2 = _run(pg_path, archive_path)
    after = {t: _arc_rows(archive_path, t) for t, _ in las.ARCHIVE_TABLES}

    assert before == after
    assert summary2["status"] == las.STATUS_OK
    st = las.archive_status(archive_path)
    assert st["last_session_synced"] == "2026-09-02"
    assert st["is_behind"] is False


def test_catches_up_a_multi_session_gap_in_one_pass(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01")
    _run(pg_path, archive_path)
    for d in ("2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"):
        _seed_session(pg_path, d)

    summary = _run(pg_path, archive_path)

    assert set(summary["synced"]) == {"2026-09-01", "2026-09-02", "2026-09-03",
                                      "2026-09-04", "2026-09-05"}
    for d in ("2026-09-02", "2026-09-05"):
        assert _arc_rows(archive_path, "prices", d, "date") == 2


class _DropOnePricesRowCur(_PgCur):
    """Makes `SELECT * FROM prices WHERE ...` return one fewer row than
    `SELECT COUNT(*) ...` reports -- a source that silently hands back an
    incomplete result set, which the post-pull row-count check must catch."""
    def __init__(self, sqlite_cur):
        super().__init__(sqlite_cur)
        self._drop = False

    def execute(self, sql, params=()):
        self._drop = sql.strip().upper().startswith("SELECT *") and "FROM PRICES" in sql.upper()
        return super().execute(sql, params)

    def fetchall(self):
        rows = super().fetchall()
        return rows[:-1] if self._drop and len(rows) > 1 else rows


def test_row_count_mismatch_marks_session_partial(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01")

    conn = _PgConn(pg_path)
    conn.cursor = lambda: _DropOnePricesRowCur(conn._conn.cursor())
    try:
        summary = las.sync_archive(pg_conn=conn, archive_path=archive_path, window_days=90)
    finally:
        conn.close()

    assert "2026-09-01" in summary["partial"]
    assert summary["status"] == las.STATUS_PARTIAL
    con = sqlite3.connect(archive_path)
    row = con.execute(
        "SELECT status, detail FROM archive_sync_state WHERE session_date = ?",
        ("2026-09-01",)).fetchone()
    con.close()
    assert row[0] == las.STATUS_PARTIAL
    assert "prices" in row[1]


def test_never_touches_psx_data_db(pg_path, archive_path, monkeypatch, tmp_path):
    sentinel = tmp_path / "psx_data_SENTINEL.db"
    monkeypatch.setattr(las.config, "DB_PATH", str(sentinel))
    _seed_session(pg_path, "2026-09-01")
    _run(pg_path, archive_path)
    assert not sentinel.exists()


def test_refuses_to_use_psx_data_db_as_archive(pg_path, monkeypatch, tmp_path):
    db = str(tmp_path / "psx_data.db")
    monkeypatch.setattr(las.config, "DB_PATH", db)
    with pytest.raises(RuntimeError, match="refusing"):
        _run(pg_path, db)


def test_post_hoc_mutation_is_re_pulled_within_window(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01")
    _run(pg_path, archive_path)
    assert _pg_boring_status(archive_path, "2026-09-01") == "Pending"

    con = sqlite3.connect(pg_path)
    con.execute("UPDATE boring_signals SET status = 'Target' WHERE signal_date = '2026-09-01'")
    con.commit()
    con.close()

    _run(pg_path, archive_path)
    assert _pg_boring_status(archive_path, "2026-09-01") == "Target"


def _pg_boring_status(archive_path, session):
    con = sqlite3.connect(archive_path)
    try:
        return con.execute(
            "SELECT status FROM boring_signals WHERE signal_date = ?", (session,)
        ).fetchone()[0]
    finally:
        con.close()


def test_sessions_outside_the_window_are_skipped(pg_path, archive_path):
    _seed_session(pg_path, "2026-01-01")   # far in the past
    _seed_session(pg_path, "2026-09-01")
    _seed_session(pg_path, "2026-09-02")

    summary = _run(pg_path, archive_path, window_days=30)

    assert summary["skipped_out_of_window"] == 1
    assert "2026-01-01" not in summary["synced"]
    assert _arc_rows(archive_path, "prices", "2026-01-01", "date") == 0


def test_later_withheld_rerun_does_not_unpromote_a_session(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01", run_id="run-a", promoted_at="2026-09-01T14:00:00Z")
    # a later slot the same day fails freshness -> a withheld row, later timestamp
    con = sqlite3.connect(pg_path)
    con.execute(
        "INSERT INTO current_publication (run_id, promoted_at, source_as_of, promoted, coherence) "
        "VALUES (?, ?, ?, ?, ?)",
        ("run-b", "2026-09-01T20:00:00Z", "2026-09-01", 0, "COHERENT"),
    )
    con.commit()
    con.close()

    summary = _run(pg_path, archive_path)
    assert "2026-09-01" in summary["synced"]  # the promoted row still wins


def test_status_reports_behind_when_a_session_failed(pg_path, archive_path, monkeypatch):
    _seed_session(pg_path, "2026-09-01")
    _seed_session(pg_path, "2026-09-02")

    real = las._pull_session

    def fail_second(*args, **kw):
        session = args[2]
        if session == "2026-09-02":
            raise RuntimeError("boom")
        return real(*args, **kw)

    monkeypatch.setattr(las, "_pull_session", fail_second)
    summary = _run(pg_path, archive_path)

    assert summary["errored"] == ["2026-09-02"]
    st = las.archive_status(archive_path)
    assert st["last_session_synced"] == "2026-09-01"
    assert st["pg_latest_promoted_session"] == "2026-09-02"
    assert st["is_behind"] is True


def test_no_eligible_sessions_yet_is_ok_not_error(pg_path, archive_path):
    summary = _run(pg_path, archive_path)
    assert summary["status"] == las.STATUS_OK
    assert summary["eligible_sessions"] == 0
    st = las.archive_status(archive_path)
    assert st["last_run_status"] == las.STATUS_OK


def test_current_publication_is_mirrored(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01")
    _seed_session(pg_path, "2026-09-02", promoted=False)
    _run(pg_path, archive_path)
    con = sqlite3.connect(archive_path)
    try:
        n = con.execute("SELECT COUNT(*) FROM current_publication").fetchone()[0]
        promoted = con.execute(
            "SELECT COUNT(*) FROM current_publication WHERE promoted = 1").fetchone()[0]
    finally:
        con.close()
    assert n == 2 and promoted == 1


def test_idempotent_content_across_runs(pg_path, archive_path):
    _seed_session(pg_path, "2026-09-01")
    _seed_session(pg_path, "2026-09-02")
    _run(pg_path, archive_path)
    snap1 = _dump(archive_path)
    _run(pg_path, archive_path)
    _run(pg_path, archive_path)
    snap2 = _dump(archive_path)
    assert snap1 == snap2


def _dump(archive_path):
    con = sqlite3.connect(archive_path)
    try:
        out = {}
        for t, _ in las.ARCHIVE_TABLES:
            out[t] = sorted(map(str, con.execute(f"SELECT * FROM {t}").fetchall()))
        return out
    finally:
        con.close()
