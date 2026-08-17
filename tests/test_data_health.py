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
