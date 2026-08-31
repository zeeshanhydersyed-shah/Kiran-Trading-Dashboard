"""TR-01 Phase 1c -- rolling-trim coverage for `sector_signals`.

`database_pg.trim_old_rows_pg()` keeps the large Supabase tables to a rolling
2-year window (local SQLite is the permanent full-history archive -- audit
§38.1 / §40.14). It covered 5 tables; `sector_signals` -- the 4th-largest at
~15 MB, growing ~23 rows/session -- was omitted and left to grow unbounded
(audit §38.1, "the clearest gap").

`health_check.check_rolling_trim()` carries its OWN copy of the table list
(it is a standalone regression guard). These tests pin:
  * `sector_signals` is now trimmed;
  * `index_prices` is deliberately NOT (small table, kept at full history per
    §40.14 -- pinned so it is not "helpfully" added later);
  * the two hand-maintained lists (`_TRIM_TABLES` and health_check's) match,
    so they cannot drift.
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import database_pg  # noqa: E402
import health_check  # noqa: E402


class _RecCursor:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def fetchone(self):
        return (None,)          # MIN(...) -> None: no rows, check passes trivially

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _RecConn:
    def __init__(self):
        self.cur = _RecCursor()

    def cursor(self, **_kw):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _trim_table_set():
    return {t for t, _ in database_pg._TRIM_TABLES}


def test_sector_signals_is_trimmed():
    assert ("sector_signals", "date") in database_pg._TRIM_TABLES


def test_original_five_still_trimmed():
    for t in ("prices", "prices_adjusted", "stock_signals",
              "setup_log", "symbol_active_dates"):
        assert t in _trim_table_set()


def test_index_prices_is_deliberately_not_trimmed():
    # §40.14: small tables keep full history. Pinned so a future edit that
    # adds index_prices trips this test and has to justify itself.
    assert "index_prices" not in _trim_table_set()
    assert "market_regime" not in _trim_table_set()


def test_health_check_list_matches_trim_tables():
    conn = _RecConn()
    health_check.check_rolling_trim(conn)
    checked = {sql.split("FROM")[1].strip()
               for sql in conn.cur.sql if sql.strip().upper().startswith("SELECT MIN")}
    assert checked == _trim_table_set(), (
        f"health_check.check_rolling_trim() and database_pg._TRIM_TABLES "
        f"have drifted: {checked ^ _trim_table_set()}")


def test_trim_sql_deletes_two_year_window_per_table(monkeypatch):
    conn = _RecConn()
    monkeypatch.setattr(database_pg, "get_conn", lambda: conn)
    database_pg.trim_old_rows_pg()
    deletes = [s for s in conn.cur.sql if s.strip().upper().startswith("DELETE")]
    assert len(deletes) == len(database_pg._TRIM_TABLES)
    for (tbl, col), sql in zip(database_pg._TRIM_TABLES, deletes):
        assert f"DELETE FROM {tbl}" in sql
        assert f"{col} < CURRENT_DATE - INTERVAL '2 years'" in sql
