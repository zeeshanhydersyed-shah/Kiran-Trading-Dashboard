"""Regression tests for TR-06 Tier 2 coverage instrumentation
(docs/KIRAN_BORING_STATE_TRUST_REGISTER.md, TR-06 -- design-lock record,
2026-08-24).

Covers, per module:

  data_health.py    -- pipeline_runs schema widened additively; record_run()
                        persists the new fields; execution_status is derived
                        from status for callers that don't pass it explicitly
                        (the still-HELD main.py hooks never will).
  boring_signals.py -- scan_boring_breakouts_pending()'s default return
                        contract is unchanged (bare int); return_coverage=True
                        exposes (total, dates_eligible, dates_processed),
                        including the partial-completion case a transient
                        per-date break can reach without raising.
  leaders_scan.py   -- run_all()'s previously-silent per-date exception
                        swallowing (bare print(), nothing propagated) now
                        returns dates_eligible/dates_processed/failed_dates
                        instead of None, while still continuing to process
                        remaining dates after a per-date failure.
  backfill_setup_log.py -- append_setup_log_today() returns a dict carrying
                        eligible_count/completed_all_pending_dates alongside
                        the existing inserted-row count.

  check_all() integration (independent-review blocker fix, 2026-08-24) --
                        HEARTBEAT previously still queried the retired
                        hook_name='corporate_action', which main.py's split
                        into corporate_action_append/corporate_action_
                        suspects_scan stopped writing entirely -- the health
                        check would have permanently read "no run ever
                        recorded" post-deployment despite both new heartbeats
                        succeeding. These tests exercise the real record_run()
                        write path followed by the real check_all() read path
                        (not mocks of either), which is exactly the
                        integration gap the independent review identified as
                        what let the original defect through undetected.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import data_health  # noqa: E402
import boring_signals as bs  # noqa: E402
import leaders_scan  # noqa: E402


# ---------------------------------------------------------------------------
# data_health.record_run() -- new fields
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_pipeline_runs_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_psx.db")
    monkeypatch.setattr(data_health.config, "DB_PATH", db)
    monkeypatch.setattr(data_health, "_PG_URL", None)
    return db


def _fetch_row(db, hook_name, run_date):
    con = sqlite3.connect(db)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(pipeline_runs)").fetchall()]
        row = con.execute(
            "SELECT * FROM pipeline_runs WHERE hook_name = ? AND run_date = ?",
            (hook_name, run_date),
        ).fetchone()
        return dict(zip(cols, row)) if row else None
    finally:
        con.close()


def test_record_run_persists_new_coverage_fields(temp_pipeline_runs_db):
    data_health.record_run(
        "some_hook", "2026-08-24", status="ok", rows_written=5,
        run_id="abc-123", execution_status="COMPLETED",
        coverage_status="EXPECTED", eligible_count=10, processed_count=10,
    )
    row = _fetch_row(temp_pipeline_runs_db, "some_hook", "2026-08-24")
    assert row["run_id"] == "abc-123"
    assert row["execution_status"] == "COMPLETED"
    assert row["coverage_status"] == "EXPECTED"
    assert row["eligible_count"] == 10
    assert row["processed_count"] == 10
    # Pre-existing fields untouched by the widening.
    assert row["status"] == "ok"
    assert row["rows_written"] == 5


def test_record_run_derives_execution_status_when_not_passed(temp_pipeline_runs_db):
    """The still-HELD main.py hooks (regime/sector_signals/stock_signals/
    recovery_signals/portfolio_signals) call _record_hook() without any of
    the new kwargs -- execution_status must still land as a sensible value
    once main.py's HELD diff is eventually deployed, with zero call-site
    changes required of it."""
    data_health.record_run("held_style_hook", "2026-08-24", status="ok")
    row = _fetch_row(temp_pipeline_runs_db, "held_style_hook", "2026-08-24")
    assert row["execution_status"] == "COMPLETED"
    assert row["coverage_status"] is None
    assert row["run_id"] is None

    data_health.record_run("held_style_hook", "2026-08-25", status="error")
    row = _fetch_row(temp_pipeline_runs_db, "held_style_hook", "2026-08-25")
    assert row["execution_status"] == "FAILED"


def test_ensure_ledger_sqlite_migrates_a_pre_existing_table(tmp_path, monkeypatch):
    """A production pipeline_runs table created before this change (only the
    original 7 columns) must gain the new columns idempotently, not error or
    require manual migration."""
    db = str(tmp_path / "old_schema.db")
    con = sqlite3.connect(db)
    con.execute("""
        CREATE TABLE pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hook_name TEXT NOT NULL,
            run_date TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            status TEXT NOT NULL,
            rows_written INTEGER,
            detail TEXT,
            UNIQUE(hook_name, run_date)
        )
    """)
    con.execute(
        "INSERT INTO pipeline_runs (hook_name, run_date, finished_at, status) "
        "VALUES ('old_row', '2026-08-01', '2026-08-01T00:00:00', 'ok')"
    )
    con.commit()
    con.close()

    monkeypatch.setattr(data_health.config, "DB_PATH", db)
    monkeypatch.setattr(data_health, "_PG_URL", None)

    # Old, pre-existing row must survive the migration untouched.
    data_health.record_run("new_row", "2026-08-24", status="ok", run_id="xyz")

    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(pipeline_runs)").fetchall()}
    assert {"run_id", "execution_status", "coverage_status",
            "eligible_count", "processed_count"} <= cols
    old = con.execute(
        "SELECT status FROM pipeline_runs WHERE hook_name='old_row'"
    ).fetchone()
    assert old[0] == "ok"
    con.close()


# ---------------------------------------------------------------------------
# boring_signals.scan_boring_breakouts_pending -- coverage return
# ---------------------------------------------------------------------------

DATES = ["2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"]


@pytest.fixture
def temp_boring_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_psx.db")
    con = sqlite3.connect(db)
    bs.ensure_boring_signals_table(con)
    con.close()
    monkeypatch.setattr(bs, "DB_PATH", db)
    monkeypatch.setattr(bs, "_PG_URL", None)
    monkeypatch.setattr(bs, "_eligible_universe", lambda conn: {"AAA"})
    monkeypatch.setattr(bs, "_load_price_history", lambda conn, universe: {"AAA": {"dates": DATES}})
    return db


def test_default_return_is_unchanged_bare_int(temp_boring_db, monkeypatch):
    """Backward compatibility: every pre-existing caller (main.py before
    this change, other tests) must keep getting a bare int."""
    monkeypatch.setattr(bs, "scan_boring_breakouts", lambda d: 0)
    total = bs.scan_boring_breakouts_pending()
    assert total == 0
    assert isinstance(total, int)


def test_return_coverage_reports_full_completion(temp_boring_db, monkeypatch):
    monkeypatch.setattr(bs, "scan_boring_breakouts", lambda d: 1 if d == DATES[-1] else 0)
    total, eligible, processed = bs.scan_boring_breakouts_pending(
        return_coverage=True
    )
    assert total == 1
    assert eligible == len(DATES)
    assert processed == len(DATES)


def test_return_coverage_reports_partial_completion_on_transient_break(temp_boring_db, monkeypatch):
    """The exact scenario TR-06 Tier 2 exists to catch: a transient error
    breaks the loop, the function returns normally (no exception), but fewer
    dates were processed than were eligible -- previously invisible to any
    caller."""
    def _locked(scan_date):
        if scan_date == DATES[2]:
            raise sqlite3.OperationalError("database is locked")
        return 0

    monkeypatch.setattr(bs, "scan_boring_breakouts", _locked)
    total, eligible, processed = bs.scan_boring_breakouts_pending(
        return_coverage=True
    )
    assert eligible == len(DATES)
    assert processed == 2  # DATES[0], DATES[1] completed before the break
    assert processed < eligible


def test_return_coverage_empty_universe_reports_zero_zero_zero(tmp_path, monkeypatch):
    db = str(tmp_path / "empty.db")
    con = sqlite3.connect(db)
    bs.ensure_boring_signals_table(con)
    con.close()
    monkeypatch.setattr(bs, "DB_PATH", db)
    monkeypatch.setattr(bs, "_PG_URL", None)
    monkeypatch.setattr(bs, "_eligible_universe", lambda conn: set())
    monkeypatch.setattr(bs, "_load_price_history", lambda conn, universe: {})

    total, eligible, processed = bs.scan_boring_breakouts_pending(return_coverage=True)
    assert (total, eligible, processed) == (0, 0, 0)


# ---------------------------------------------------------------------------
# leaders_scan.run_all() -- failure propagation fix
# ---------------------------------------------------------------------------

@pytest.fixture
def leaders_stub(monkeypatch):
    monkeypatch.setattr(leaders_scan, "_pending_scan_dates", lambda db_path=None: list(DATES))
    # save_top_picks() gained a scan_date param (§29.9 / TR-01 Phase 1b) -- run_all()
    # now calls it once per caught-up date, so the stub must accept it.
    monkeypatch.setattr(leaders_scan, "save_top_picks",
                        lambda db_path=None, scan_date=None: None)
    monkeypatch.setattr(leaders_scan, "fill_leaders_forward_returns", lambda db_path=None: None)


def test_run_all_clean_run_reports_full_coverage(leaders_stub, monkeypatch):
    calls = []
    monkeypatch.setattr(
        leaders_scan, "append_leaders_scan",
        lambda db_path=None, scan_date=None: calls.append(scan_date),
    )
    result = leaders_scan.run_all()
    assert calls == DATES
    assert result == {"dates_eligible": 5, "dates_processed": 5, "failed_dates": []}


def test_run_all_per_date_failure_is_no_longer_silently_swallowed(leaders_stub, monkeypatch):
    """Regression test for the exact defect this implementation fixes: a
    per-date failure used to be caught and print()'d with nothing returned
    (implicitly None) -- a caller had no way to know anything failed. Also
    confirms the existing "continue processing other dates" behaviour is
    preserved, not replaced with a hard stop."""
    calls = []

    def _flaky(db_path=None, scan_date=None):
        calls.append(scan_date)
        if scan_date == DATES[2]:
            raise ValueError("simulated per-date failure")

    monkeypatch.setattr(leaders_scan, "append_leaders_scan", _flaky)
    result = leaders_scan.run_all()

    # Processing continued past the failed date -- unchanged behaviour.
    assert calls == DATES
    assert result["dates_eligible"] == 5
    assert result["dates_processed"] == 4
    assert result["failed_dates"] == [DATES[2]]


def test_run_all_still_calls_whole_table_steps_even_with_failures(monkeypatch):
    monkeypatch.setattr(leaders_scan, "_pending_scan_dates", lambda db_path=None: list(DATES))
    top_picks_called = []
    forward_returns_called = []
    monkeypatch.setattr(leaders_scan, "save_top_picks",
                         lambda db_path=None, scan_date=None: top_picks_called.append(True))
    monkeypatch.setattr(leaders_scan, "fill_leaders_forward_returns",
                         lambda db_path=None: forward_returns_called.append(True))

    def _always_fails(db_path=None, scan_date=None):
        raise ValueError("boom")

    monkeypatch.setattr(leaders_scan, "append_leaders_scan", _always_fails)
    result = leaders_scan.run_all()

    assert result["dates_processed"] == 0
    assert len(result["failed_dates"]) == 5
    # Preserved exactly as before: whole-table steps still run unconditionally.
    assert top_picks_called == [True]
    assert forward_returns_called == [True]


# ---------------------------------------------------------------------------
# backfill_setup_log.append_setup_log_today() -- dict return
# ---------------------------------------------------------------------------

def test_append_setup_log_today_returns_dict_with_no_data(tmp_path, monkeypatch):
    import backfill_setup_log as bsl

    db = str(tmp_path / "empty_setup_log.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE setup_log (setup_date TEXT)")
    con.execute("CREATE TABLE stock_signals (date TEXT, symbol TEXT)")
    con.commit()
    con.close()

    monkeypatch.setattr(bsl, "DB_PATH", db)
    monkeypatch.setattr(bsl, "_PG_URL", None)

    result = bsl.append_setup_log_today()
    assert result == {
        "inserted": 0, "eligible_count": None, "target_date": None,
        "completed_all_pending_dates": True,
    }


# ---------------------------------------------------------------------------
# check_all() integration -- independent-review blocker regression test
# ---------------------------------------------------------------------------
# Uses the real record_run() write path and the real check_all() read path
# together, against a temp SQLite file -- not mocks of either. A minimal
# `prices` table is created (empty) so check_all()'s absolute freshness check
# degrades gracefully to "unknown" rather than raising; that item is not
# under test here and is ignored by these assertions.

@pytest.fixture
def temp_health_db(tmp_path, monkeypatch):
    db = str(tmp_path / "test_psx.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE prices (date TEXT)")
    con.close()
    monkeypatch.setattr(data_health.config, "DB_PATH", db)
    monkeypatch.setattr(data_health, "_PG_URL", None)
    return db


def _item(verdict, label):
    return next((i for i in verdict.items if i.label == label), None)


def test_check_all_recognizes_corporate_action_append_heartbeat(temp_health_db):
    data_health.record_run(
        "corporate_action_append", "2026-08-24", status="ok", rows_written=5,
        execution_status="COMPLETED", coverage_status="EXPECTED",
        eligible_count=5, processed_count=5,
    )
    verdict = data_health.check_all(expected_session=None)

    item = _item(verdict, "prices_adjusted append")
    assert item is not None, "HEARTBEAT list has no entry for corporate_action_append"
    assert item.status == "ok", (
        f"expected 'ok' for a successful corporate_action_append heartbeat, "
        f"got {item.status!r} ({item.detail!r}) -- this is exactly the "
        f"independent-review defect: check_all() querying a retired hook_name"
    )


# ---------------------------------------------------------------------------
# TR-06 Tier 2 completion (ledger §115): check_all() reads the coverage
# assertion, not just run_date/status; the 3 non-critical chain steps get a
# heartbeat but never feed the verdict.
# ---------------------------------------------------------------------------

def test_check_all_flags_insufficient_coverage_as_stale(temp_health_db):
    """leaders_scan ran (status ok) but its own coverage report says it
    skipped some eligible dates -- processed < eligible. That is the "ran but
    under-produced" state TR-06 requires be distinguishable from a clean run;
    check_all() must return it as stale (blocking), not ok."""
    data_health.record_run(
        "leaders_scan", "2026-09-02", status="ok",
        execution_status="COMPLETED", coverage_status="INSUFFICIENT",
        eligible_count=5, processed_count=3, detail="failed_dates=['2026-08-30']",
    )
    verdict = data_health.check_all(expected_session=None)
    item = _item(verdict, "leaders_scan")
    assert item is not None
    assert item.status == "stale", (
        f"INSUFFICIENT coverage with processed<eligible must block, got "
        f"{item.status!r} ({item.detail!r})"
    )
    assert "INSUFFICIENT" in item.detail


def test_check_all_large_catchup_is_visible_but_not_blocking(temp_health_db):
    """boring_signals scanned a big backlog in one run -- coverage_status is
    INSUFFICIENT (abnormally large) but every eligible session WAS processed
    (processed == eligible). The data is complete; surface a note, do not
    withhold the signal."""
    data_health.record_run(
        "boring_signals", "2026-09-02", status="ok",
        execution_status="COMPLETED", coverage_status="INSUFFICIENT",
        eligible_count=22, processed_count=22,
        detail="long scan gap: 22 trading dates were pending in one run",
    )
    verdict = data_health.check_all(expected_session=None)
    item = _item(verdict, "boring_signals")
    assert item is not None
    assert item.status == "ok", (
        f"a complete (processed==eligible) large catch-up must not block, got "
        f"{item.status!r} ({item.detail!r})"
    )
    assert "catch-up" in item.detail


def test_check_all_expected_coverage_is_ok(temp_health_db):
    data_health.record_run(
        "setup_log", "2026-09-02", status="ok",
        execution_status="COMPLETED", coverage_status="EXPECTED",
        eligible_count=1, processed_count=1,
    )
    verdict = data_health.check_all(expected_session=None)
    item = _item(verdict, "setup_log")
    assert item is not None and item.status == "ok"


def test_check_all_null_coverage_is_ok(temp_health_db):
    """portfolio_signals (and every held-style hook) reports no coverage pair
    -- coverage_status NULL. That is a legitimate non-answer, not a fault."""
    data_health.record_run(
        "portfolio_signals", "2026-09-02", status="ok", execution_status="COMPLETED",
    )
    verdict = data_health.check_all(expected_session=None)
    item = _item(verdict, "portfolio_signals")
    assert item is not None and item.status == "ok"


def test_check_all_degrades_when_coverage_columns_absent(tmp_path, monkeypatch):
    """The committed CI fixture's pipeline_runs has only the base 7 columns.
    check_all() must still evaluate heartbeats on run_date/status and never
    raise -- exactly the defensive contract latest_pipeline_code_version()
    already follows."""
    db = str(tmp_path / "old_schema.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE prices (date TEXT)")
    con.execute(
        "CREATE TABLE pipeline_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "hook_name TEXT, run_date TEXT, finished_at TEXT, status TEXT, "
        "rows_written INTEGER, detail TEXT)"
    )
    con.execute(
        "INSERT INTO pipeline_runs (hook_name, run_date, finished_at, status) "
        "VALUES ('setup_log', '2026-09-02', '2026-09-02T00:00:00', 'ok')"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(data_health.config, "DB_PATH", db)
    monkeypatch.setattr(data_health, "_PG_URL", None)

    verdict = data_health.check_all(expected_session=None)  # must not raise
    item = _item(verdict, "setup_log")
    assert item is not None and item.status == "ok"


# -- non_mandatory_hook_health() -------------------------------------------

def test_non_mandatory_hook_health_reports_latest_per_hook(temp_pipeline_runs_db):
    data_health.record_run("agent_daily", "2026-09-01", status="ok",
                           execution_status="COMPLETED")
    data_health.record_run("agent_daily", "2026-09-02", status="error",
                           execution_status="FAILED", detail="exit 1: anthropic not installed")
    data_health.record_run("rolling_trim", "2026-09-02", status="ok",
                           execution_status="COMPLETED", detail="sector_signals=120")
    rows = data_health.non_mandatory_hook_health()
    by_hook = {r["hook"]: r for r in rows}
    assert by_hook["agent_daily"]["last_run"] == "2026-09-02"
    assert by_hook["agent_daily"]["execution_status"] == "FAILED"
    assert "anthropic" in by_hook["agent_daily"]["detail"]
    assert by_hook["rolling_trim"]["execution_status"] == "COMPLETED"
    # market_breadth_oscillator never ran -> omitted, not a fake row
    assert "market_breadth_oscillator" not in by_hook


def test_non_mandatory_hook_health_never_raises_on_missing_table(tmp_path, monkeypatch):
    monkeypatch.setattr(data_health.config, "DB_PATH", str(tmp_path / "empty.db"))
    monkeypatch.setattr(data_health, "_PG_URL", None)
    assert data_health.non_mandatory_hook_health() == []


def test_non_mandatory_hooks_never_reach_check_all_verdict(temp_health_db):
    """A failed agent_daily / breadth / trim heartbeat must NOT produce a
    check_all() item -- §39.2 classes them degraded-OK; a failed Agent run
    cannot be allowed to make Kiran say NOT VERIFIED."""
    data_health.record_run("agent_daily", "2026-09-02", status="error",
                           execution_status="FAILED", detail="boom")
    data_health.record_run("market_breadth_oscillator", "2026-09-02", status="error",
                           execution_status="FAILED")
    data_health.record_run("rolling_trim", "2026-09-02", status="error",
                           execution_status="FAILED")
    verdict = data_health.check_all(expected_session=None)
    labels = {i.label for i in verdict.items}
    assert "agent daily" not in labels
    assert "breadth oscillator" not in labels
    assert "rolling trim" not in labels


# -- main.py wires the 3 non-critical steps -------------------------------

def test_main_instruments_the_three_non_critical_steps():
    import ast as _ast
    src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
    hooks_recorded = {
        node.args[0].value
        for node in _ast.walk(_ast.parse(src))
        if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
        and node.func.id == "_record_hook" and node.args
        and isinstance(node.args[0], _ast.Constant)
    }
    for h in ("agent_daily", "market_breadth_oscillator", "rolling_trim"):
        assert h in hooks_recorded, f"main.py cmd_update() does not _record_hook({h!r})"


def test_check_all_recognizes_corporate_action_suspects_scan_heartbeat(temp_health_db):
    data_health.record_run(
        "corporate_action_suspects_scan", "2026-08-24", status="ok", rows_written=0,
        execution_status="COMPLETED", coverage_status="NOT_APPLICABLE",
    )
    verdict = data_health.check_all(expected_session=None)

    item = _item(verdict, "corporate_action scan")
    assert item is not None, "HEARTBEAT list has no entry for corporate_action_suspects_scan"
    assert item.status == "ok"


def test_check_all_no_longer_queries_the_retired_corporate_action_name(temp_health_db):
    """The exact regression: writing under the OLD, retired name must not be
    what makes the new labels read 'ok' -- confirms the fix targets the
    hook_name main.py actually writes, not a coincidentally-matching label.
    HEARTBEAT always produces an Item per entry (never omits one), so a
    write under the wrong name must leave both new items at 'unknown', not
    absent."""
    data_health.record_run("corporate_action", "2026-08-24", status="ok", rows_written=0)
    verdict = data_health.check_all(expected_session=None)

    assert _item(verdict, "prices_adjusted append").status == "unknown"
    assert _item(verdict, "corporate_action scan").status == "unknown"


def test_check_all_reports_unknown_before_either_heartbeat_runs(temp_health_db):
    """Negative case: with no corporate_action_* row at all, both new items
    must read 'unknown' / 'no run ever recorded' -- proving this test suite
    would fail against the pre-fix HEARTBEAT list (which had zero entries
    matching either new name) rather than passing vacuously."""
    verdict = data_health.check_all(expected_session=None)

    for label in ("prices_adjusted append", "corporate_action scan"):
        item = _item(verdict, label)
        assert item is not None
        assert item.status == "unknown"
        assert "no run ever recorded" in item.detail or "no run recorded yet" in item.detail


def test_check_all_liveness_does_not_upgrade_suspects_scan_coverage_to_expected(temp_health_db):
    """TR-06's own semantic distinction (execution/liveness vs. coverage)
    must survive contact with check_all(): a hook reading 'ok' for liveness
    here says nothing about coverage_status, and must not be read as if it
    had. coverage_status is asserted directly against the stored row, since
    check_all() itself doesn't read that column at all (by design, per the
    TR-06 Tier 2 design-lock record -- coverage truth lives in pipeline_runs,
    not squeezed into check_all()'s freshness/liveness model)."""
    data_health.record_run(
        "corporate_action_suspects_scan", "2026-08-24", status="ok", rows_written=0,
        execution_status="COMPLETED", coverage_status="NOT_APPLICABLE",
    )
    verdict = data_health.check_all(expected_session=None)
    assert _item(verdict, "corporate_action scan").status == "ok"

    con = sqlite3.connect(temp_health_db)
    row = con.execute(
        "SELECT coverage_status FROM pipeline_runs WHERE hook_name = ?",
        ("corporate_action_suspects_scan",),
    ).fetchone()
    con.close()
    assert row[0] == "NOT_APPLICABLE", (
        "check_all() reporting liveness as 'ok' must never coincide with "
        "coverage_status silently becoming EXPECTED"
    )
