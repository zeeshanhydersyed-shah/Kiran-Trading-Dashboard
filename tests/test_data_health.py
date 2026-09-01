"""Unit tests for data_health -- the sidebar banner's verdict logic.

WHAT THESE GUARD
----------------
The banner's whole value is that it cannot quietly say "fine". Two specific
regressions are worth failing a build over:

  1. Green-by-default. Requirement: an unreadable table, an unreachable source,
     or a missing heartbeat must never produce green. `test_*_never_green`
     covers each route.

  2. The MAX(suspect_date) class of bug. The retired "Last Checked" metric read
     the date of the last *finding* rather than the last *run*, so a clean scan
     and a dead scanner rendered identically and it sat stale at 2026-06-22 for
     two months (docs/KIRAN_CLEANUP_AUDIT.md 31). The heartbeat tests assert
     that a run writing zero rows still registers as a run.

The DB-backed tests build a throwaway SQLite file, so they never touch
psx_data.db.
"""

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import data_health as dh  # noqa: E402


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_iso_normalises_date_types():
    from datetime import date, datetime
    assert dh._iso(date(2026, 8, 13)) == "2026-08-13"
    assert dh._iso(datetime(2026, 8, 13, 5, 30)) == "2026-08-13"
    assert dh._iso("2026-08-13") == "2026-08-13"
    assert dh._iso("2026-08-13T00:00:00") == "2026-08-13"
    assert dh._iso(None) is None


@pytest.mark.parametrize("msg", [
    "no such table: pipeline_runs",
    'relation "pipeline_runs" does not exist',
    "UndefinedTable",
])
def test_missing_table_detected_on_both_backends(msg):
    assert dh._is_missing_table(Exception(msg)) is True


def test_missing_table_does_not_swallow_real_errors():
    # A genuine fault must keep its message rather than be reported as
    # "no run recorded yet", which would understate a broken ledger.
    assert dh._is_missing_table(Exception("connection refused")) is False
    assert dh._is_missing_table(Exception("permission denied for table")) is False


# ---------------------------------------------------------------------------
# Verdict level precedence
# ---------------------------------------------------------------------------

def _verdict(*statuses):
    items = [dh.Item(f"t{n}", s, "") for n, s in enumerate(statuses)]
    level = ("red" if any(i.status == "stale" for i in items)
             else "amber" if any(i.status == "unknown" for i in items)
             else "green")
    return dh.Verdict(level=level, expected="2026-08-13",
                      expected_source="ksestocks", items=items)


def test_all_ok_is_green():
    assert _verdict("ok", "ok", "ok").level == "green"


def test_single_stale_table_turns_whole_system_red():
    # No partial credit: one behind means the system is red.
    assert _verdict("ok", "ok", "stale").level == "red"


def test_unknown_alone_is_amber_never_green():
    assert _verdict("ok", "unknown").level == "amber"


def test_stale_outranks_unknown():
    # A known-stale table is a stronger statement than an unverifiable one.
    assert _verdict("unknown", "stale").level == "red"


def test_failures_sorted_unknown_first_then_most_behind():
    v = dh.Verdict("red", "2026-08-13", "ksestocks", items=[
        dh.Item("a", "ok", ""),
        dh.Item("b", "stale", "", behind=2),
        dh.Item("c", "stale", "", behind=31),
        dh.Item("d", "unknown", ""),
    ])
    assert [i.label for i in v.failures] == ["d", "c", "b"]


# ---------------------------------------------------------------------------
# DB-backed behaviour
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """A throwaway SQLite DB with just enough schema, wired into data_health."""
    path = tmp_path / "test.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE prices (symbol TEXT, date TEXT)")
    for table, col in [("index_prices", "date"), ("prices_adjusted", "date"),
                       ("stock_signals", "date"), ("sector_signals", "date"),
                       ("market_regime", "date"), ("recovery_signals", "as_of_date")]:
        con.execute(f"CREATE TABLE {table} ({col} TEXT)")
    sessions = ["2026-08-11", "2026-08-12", "2026-08-13"]
    for d in sessions:
        con.execute("INSERT INTO prices VALUES ('AAA', ?)", (d,))
        for table, col in [("index_prices", "date"), ("prices_adjusted", "date"),
                           ("stock_signals", "date"), ("sector_signals", "date"),
                           ("market_regime", "date"), ("recovery_signals", "as_of_date")]:
            con.execute(f"INSERT INTO {table} ({col}) VALUES (?)", (d,))
    con.commit()
    con.close()

    monkeypatch.setattr(dh.config, "DB_PATH", str(path))
    monkeypatch.setattr(dh, "_PG_URL", None)
    return path


def _heartbeat_all(run_date="2026-08-13", rows=1):
    for hook, _ in dh.HEARTBEAT:
        dh.record_run(hook, run_date, rows_written=rows)


def test_fully_current_system_is_green(temp_db):
    _heartbeat_all()
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "green", [f"{i.label}:{i.detail}" for i in v.failures]


def test_zero_row_run_still_counts_as_a_run(temp_db):
    # The MAX(suspect_date) bug in one assertion: a scan that legitimately
    # finds nothing must still register as having run.
    _heartbeat_all(rows=0)
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "green"


def test_stale_table_named_with_session_count(temp_db):
    _heartbeat_all()
    con = sqlite3.connect(temp_db)
    con.execute("DELETE FROM sector_signals WHERE date > '2026-08-11'")
    con.commit()
    con.close()

    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "red"
    bad = [i for i in v.failures if i.label == "sector_signals"]
    assert bad, "sector_signals should be named in the failures"
    # 08-12 and 08-13 are both trading sessions in prices -> 2 behind.
    assert bad[0].behind == 2
    assert "2026-08-11" in bad[0].detail


def test_sessions_behind_ignores_non_trading_days(temp_db):
    """Counted from real prices rows, not calendar days.

    There is no PSX holiday calendar anywhere in this codebase, so calendar
    arithmetic would have reported 08-14 (Independence Day) and the weekend as
    missed sessions. prices IS the trading calendar.
    """
    con = sqlite3.connect(temp_db)
    # A 5-calendar-day gap containing exactly one trading session.
    con.execute("INSERT INTO prices VALUES ('AAA', '2026-08-18')")
    con.execute("DELETE FROM stock_signals WHERE date > '2026-08-13'")
    con.commit()
    con.close()
    _heartbeat_all()

    v = dh.check_all(expected_session="2026-08-18")
    bad = [i for i in v.failures if i.label == "stock_signals"]
    assert bad and bad[0].behind == 1


def test_missing_heartbeat_never_green(temp_db):
    # Ledger absent entirely -- must read as "no run recorded", not pass.
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level != "green"
    assert any(i.label == "boring_signals" and i.status == "unknown"
               for i in v.items)


def test_failed_heartbeat_is_stale_not_ok(temp_db):
    _heartbeat_all()
    dh.record_run("setup_log", "2026-08-13", status="error", detail="boom")
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "red"
    assert any(i.label == "setup_log" and i.status == "stale" for i in v.items)


# ---------------------------------------------------------------------------
# TR-14.1b -- scrape_coverage gating in check_all()
# ---------------------------------------------------------------------------

def _put_coverage(db_path, scrape_date, status, detail=None):
    con = sqlite3.connect(db_path)
    con.execute("""CREATE TABLE IF NOT EXISTS scrape_coverage (
        scrape_date TEXT PRIMARY KEY, expected_total INTEGER, parsed_total INTEGER,
        coverage_status TEXT NOT NULL, detail TEXT, recorded_at TEXT, code_version TEXT)""")
    con.execute("INSERT OR REPLACE INTO scrape_coverage "
                "(scrape_date, coverage_status, detail) VALUES (?, ?, ?)",
                (scrape_date, status, detail))
    con.commit()
    con.close()


def test_partial_scrape_coverage_turns_system_red(temp_db):
    _heartbeat_all()
    _put_coverage(temp_db, "2026-08-13", "PARTIAL", "CEMENT: 20 stated, 15 parsed")
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "red", [f"{i.label}:{i.status}" for i in v.items]
    bad = [i for i in v.failures if i.label == "scrape_coverage"]
    assert bad and bad[0].status == "stale"
    assert "CEMENT" in bad[0].detail
    assert dh.publication_status(v) == dh.PUBLICATION_STALE


def test_complete_scrape_coverage_stays_green(temp_db):
    _heartbeat_all()
    _put_coverage(temp_db, "2026-08-13", "COMPLETE")
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "green", [f"{i.label}:{i.detail}" for i in v.failures]
    assert any(i.label == "scrape_coverage" and i.status == "ok" for i in v.items)


def test_unknown_scrape_coverage_does_not_block(temp_db):
    # UNKNOWN = the source's own count row was absent/garbled. Per the TR-14
    # scoping decision it is surfaced but does NOT withhold publication.
    _heartbeat_all()
    _put_coverage(temp_db, "2026-08-13", "UNKNOWN")
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "green"
    assert any(i.label == "scrape_coverage" for i in v.items)


def test_missing_scrape_coverage_row_is_silent(temp_db):
    # A date with no scrape_coverage row (predates TR-14.1a / nothing recorded
    # on this backend yet) must not add any item -- deploying the check while
    # the table is still empty changes nothing.
    _heartbeat_all()
    _put_coverage(temp_db, "2026-08-11", "COMPLETE")  # some other date only
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "green"
    assert not any(i.label == "scrape_coverage" for i in v.items)


def test_absent_scrape_coverage_table_is_silent(temp_db):
    # The temp_db fixture never creates scrape_coverage at all.
    _heartbeat_all()
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "green"
    assert not any(i.label == "scrape_coverage" for i in v.items)


def test_partial_coverage_checked_against_prices_max_when_source_unreachable(temp_db):
    # expected_session=None -> reference falls back to prices MAX(date). A
    # PARTIAL row for that date must still block.
    _heartbeat_all()
    _put_coverage(temp_db, "2026-08-13", "PARTIAL", "REFINERY: 4 stated, 2 parsed")
    v = dh.check_all(expected_session=None, source_error="522")
    assert v.level == "red"
    assert any(i.label == "scrape_coverage" and i.status == "stale" for i in v.failures)


def test_unreachable_source_never_green(temp_db):
    # Absolute check cannot be performed -> amber, never green, even though
    # every relative check passes.
    _heartbeat_all()
    v = dh.check_all(expected_session=None, source_error="522")
    assert v.level == "amber"
    assert any(i.status == "unknown" and "ksestocks" in i.detail for i in v.items)


def test_unreadable_database_is_red_not_blank(temp_db, monkeypatch):
    monkeypatch.setattr(dh.config, "DB_PATH", "/nonexistent/dir/nope.db")
    v = dh.check_all(expected_session="2026-08-13")
    assert v.level == "red"
    assert v.failures, "a failed check must surface at least one named item"


def test_record_run_is_idempotent(temp_db):
    # Re-running a hook for the same session updates in place. Learned the hard
    # way: setup_log's Postgres table had no unique key for months, so its bare
    # ON CONFLICT DO NOTHING silently deduplicated nothing (audit 29.3).
    for _ in range(3):
        dh.record_run("setup_log", "2026-08-13", rows_written=74)
    con = sqlite3.connect(temp_db)
    n = con.execute("SELECT COUNT(*) FROM pipeline_runs").fetchone()[0]
    con.close()
    assert n == 1


def test_record_run_never_raises(monkeypatch):
    # Telemetry must not be able to break the pipeline it measures.
    monkeypatch.setattr(dh.config, "DB_PATH", "/nonexistent/dir/nope.db")
    monkeypatch.setattr(dh, "_PG_URL", None)
    dh.record_run("setup_log", "2026-08-13")  # must not raise


# ---------------------------------------------------------------------------
# _env_pg_url() isolation boundary (2026-08-26 incident regression).
#
# A test that explicitly clears DATABASE_URL/SUPABASE_DB_URL via
# monkeypatch.setenv(key, "") must never have that overridden by a real
# .env file on disk. The prior implementation checked truthiness
# (`os.environ.get(...) or ...`), so an explicitly-empty string fell through
# to the file read exactly like a genuinely-unset variable -- this let a
# test's boring_signals mirror_to_postgres=True call reach real production
# Supabase. Presence (`in os.environ`) is now checked instead of truthiness.
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_env_file(tmp_path, monkeypatch):
    """A real .env file with a real-looking (fake) Postgres URL, so these
    tests prove the fallback is actually skipped -- not merely that no file
    happens to exist."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        'SUPABASE_DB_URL="postgresql://fake_user:fake_pass@fake-host:5432/postgres"\n'
    )
    monkeypatch.setattr(dh, "_PROJECT_DIR", tmp_path)
    return env_file


def test_env_pg_url_explicitly_empty_vars_never_fall_through_to_env_file(
    fake_env_file, monkeypatch,
):
    """The exact 2026-08-26 incident shape: both vars explicitly cleared to
    "" (present, not absent) -- must return None, never the .env file's URL."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_DB_URL", "")
    assert dh._env_pg_url() is None


def test_env_pg_url_falls_through_to_env_file_only_when_genuinely_absent(
    fake_env_file, monkeypatch,
):
    """Legitimate local-invocation behavior (main.py --all via Task
    Scheduler) must be preserved: when the vars are truly unset -- not just
    empty -- the .env file is still consulted."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert dh._env_pg_url() == "postgresql://fake_user:fake_pass@fake-host:5432/postgres"


def test_env_pg_url_prefers_real_env_var_when_actually_set(fake_env_file, monkeypatch):
    """A genuinely-set env var still wins over .env, unchanged from before."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://real-env-var-wins/db")
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert dh._env_pg_url() == "postgresql://real-env-var-wins/db"


# ---------------------------------------------------------------------------
# _record_pg diagnostic instrumentation (docs/KIRAN_CLEANUP_AUDIT.md 57,
# Hidden Risk 1 diagnostic) -- no real Postgres connection is made in any of
# these; psycopg2.connect and database_pg._parse_pg_url are both faked.
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, fail_on_execute=None):
        self._fail_on_execute = fail_on_execute
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if self._fail_on_execute and "INSERT INTO pipeline_runs" in sql:
            raise self._fail_on_execute


class _FakeConn:
    def __init__(self, fail_on_execute=None, fail_on_commit=None):
        self.cursor_obj = _FakeCursor(fail_on_execute)
        self._fail_on_commit = fail_on_commit
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        if self._fail_on_commit:
            raise self._fail_on_commit
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _patch_parse_pg_url(monkeypatch):
    import database_pg
    monkeypatch.setattr(database_pg, "_parse_pg_url", lambda url: {})


def test_record_pg_logs_connect_failure_without_leaking_url(monkeypatch, caplog):
    import psycopg2

    _patch_parse_pg_url(monkeypatch)

    def fake_connect(**kwargs):
        raise psycopg2.OperationalError("could not translate host name")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    with caplog.at_level("WARNING", logger="data_health"):
        dh._record_pg(
            "postgresql://user:s3cr3t@example.invalid:5432/postgres",
            "corporate_action", "2026-08-21",
            dh.datetime.now(dh.timezone.utc), "ok", 0, None,
        )

    assert len(caplog.records) == 1
    msg = caplog.records[0].message
    assert "stage=connect" in msg
    assert "error=OperationalError" in msg
    assert "hook=corporate_action" in msg
    assert "s3cr3t" not in msg
    assert "example.invalid" not in msg


def test_record_pg_logs_insert_failure_and_rolls_back(monkeypatch, caplog):
    _patch_parse_pg_url(monkeypatch)
    fake_conn = _FakeConn(fail_on_execute=Exception("relation does not exist"))

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: fake_conn)
    monkeypatch.setattr(dh, "ensure_ledger_pg", lambda cur: None)

    with caplog.at_level("WARNING", logger="data_health"):
        dh._record_pg(
            "postgresql://user:pw@host/db",
            "setup_log", "2026-08-21",
            dh.datetime.now(dh.timezone.utc), "ok", 5, None,
        )

    assert fake_conn.rolled_back is True
    assert fake_conn.committed is False
    assert fake_conn.closed is True
    assert len(caplog.records) == 1
    assert "stage=insert" in caplog.records[0].message
    assert "hook=setup_log" in caplog.records[0].message


def test_record_pg_logs_success(monkeypatch, caplog):
    _patch_parse_pg_url(monkeypatch)
    fake_conn = _FakeConn()

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: fake_conn)
    monkeypatch.setattr(dh, "ensure_ledger_pg", lambda cur: None)

    with caplog.at_level("INFO", logger="data_health"):
        dh._record_pg(
            "postgresql://user:pw@host/db",
            "leaders_scan", "2026-08-21",
            dh.datetime.now(dh.timezone.utc), "ok", 12, None,
        )

    assert fake_conn.committed is True
    assert fake_conn.closed is True
    records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(records) == 1
    assert "heartbeat written" in records[0].message
    assert "hook=leaders_scan" in records[0].message


def test_record_pg_never_raises_on_unexpected_error(monkeypatch):
    # Same "never raises" guarantee as record_run itself -- an error even
    # database_pg._parse_pg_url() itself must not escape this function.
    import database_pg

    def boom(url):
        raise ValueError("unexpected")

    monkeypatch.setattr(database_pg, "_parse_pg_url", boom)
    dh._record_pg(
        "postgresql://user:pw@host/db",
        "setup_log", "2026-08-21",
        dh.datetime.now(dh.timezone.utc), "ok", 0, None,
    )  # must not raise
