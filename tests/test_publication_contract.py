"""TR-08 Publication Contract -- current_publication: an append-only record of
every publication decision main.run_freshness_gate() makes.

v1 scope (owner-agreed, scratch TR08_PUBLICATION_CONTRACT_SPEC_DRAFT.md):
freshness + completeness + per-run MANDATORY_HOOKS completion only. Does not
change dashboard.py's existing `_pub_ok` serving-time behavior (TR-05,
already GREEN in production) -- this is a recording layer underneath it.

Fully isolated: an isolated on-disk SQLite DB per test (no live network, no
live DB, no fixture DB), same pattern as test_scrape_coverage.py /
test_deployment_identity.py. See docs/KIRAN_BORING_STATE_TRUST_REGISTER.md,
TR-08.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import data_health as dh  # noqa: E402
import main  # noqa: E402


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    db = str(tmp_path / "pub.db")
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", db)
    return db


def _seed_hook(db, hook_name, run_id, run_date="2026-09-02",
                execution_status=dh.EXECUTION_COMPLETED):
    con = sqlite3.connect(db)
    try:
        dh.ensure_ledger_sqlite(con)
        con.execute(
            """
            INSERT INTO pipeline_runs
                (hook_name, run_date, finished_at, status, run_id, execution_status)
            VALUES (?, ?, datetime('now'), ?, ?, ?)
            """,
            (hook_name, run_date, "ok" if execution_status == dh.EXECUTION_COMPLETED else "error",
             run_id, execution_status),
        )
        con.commit()
    finally:
        con.close()


def _seed_all_mandatory(db, run_id, skip=None, fail=None, run_date="2026-09-02"):
    skip = skip or set()
    fail = fail or set()
    for hook in dh.MANDATORY_HOOKS:
        if hook in skip:
            continue
        status = dh.EXECUTION_FAILED if hook in fail else dh.EXECUTION_COMPLETED
        _seed_hook(db, hook, run_id, run_date=run_date, execution_status=status)


def _seed_coherence_tables(db, dates: dict[str, str] | None = None,
                            default_date="2026-09-02"):
    """Create the four COHERENCE_TABLES with one row each. `dates` overrides
    the MAX(date) for named tables; anything unnamed gets `default_date`.
    Pass an empty string for a table to create it with no rows."""
    dates = dates or {}
    con = sqlite3.connect(db)
    try:
        for table, col in dh.COHERENCE_TABLES:
            con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({col} TEXT)")
            d = dates.get(table, default_date)
            if d:
                con.execute(f"INSERT INTO {table} ({col}) VALUES (?)", (d,))
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# mandatory_hooks_completed_for_run
# ---------------------------------------------------------------------------

def test_mandatory_hooks_completed_all_present(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1")
    assert dh.mandatory_hooks_completed_for_run("run-1") is True


def test_mandatory_hooks_completed_one_missing(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1", skip={"leaders_scan"})
    assert dh.mandatory_hooks_completed_for_run("run-1") is False


def test_mandatory_hooks_completed_one_failed(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1", fail={"boring_signals"})
    assert dh.mandatory_hooks_completed_for_run("run-1") is False


def test_mandatory_hooks_completed_no_run_id(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1")
    assert dh.mandatory_hooks_completed_for_run(None) is False


def test_mandatory_hooks_completed_wrong_run_id(sqlite_db):
    """A different run_id's complete hooks must not count for this one --
    the whole point is per-run atomicity, not "have these hooks ever run"."""
    _seed_all_mandatory(sqlite_db, "run-1")
    assert dh.mandatory_hooks_completed_for_run("run-2") is False


def test_mandatory_hooks_completed_never_raises_on_query_error(monkeypatch, tmp_path):
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", str(tmp_path / "nonexistent_dir" / "x.db"))
    assert dh.mandatory_hooks_completed_for_run("run-1") is False


# ---------------------------------------------------------------------------
# decide_and_record_publication
# ---------------------------------------------------------------------------

def test_promotes_when_everything_passes(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1")
    decision = dh.decide_and_record_publication(
        run_id="run-1", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
    )
    assert decision["promoted"] is True
    assert decision["withheld_reason"] is None
    row = dh.latest_promoted_publication()
    assert row is not None
    assert row["run_id"] == "run-1"
    assert row["code_version"] == "abc123"


def test_withholds_on_stale_freshness(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1")
    decision = dh.decide_and_record_publication(
        run_id="run-1", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_STALE, completeness_status=dh.COVERAGE_COMPLETE,
    )
    assert decision["promoted"] is False
    assert "freshness=STALE" in decision["withheld_reason"]
    assert dh.latest_promoted_publication() is None


def test_withholds_on_partial_completeness(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1")
    decision = dh.decide_and_record_publication(
        run_id="run-1", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_PARTIAL,
    )
    assert decision["promoted"] is False
    assert "completeness=PARTIAL" in decision["withheld_reason"]


def test_permissive_on_unknown_or_absent_completeness(sqlite_db):
    """UNKNOWN and None (no scrape_coverage row yet) must NOT block promotion
    -- matches boring_signals._completeness_ok()'s established TR-14 reading:
    a date with no coverage row yet is not retroactively treated as a
    failure. Only an explicit PARTIAL verdict withholds."""
    _seed_all_mandatory(sqlite_db, "run-1")
    for completeness in (dh.COVERAGE_UNKNOWN, None):
        decision = dh.decide_and_record_publication(
            run_id="run-1", code_version="abc123", source_as_of="2026-09-02",
            freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=completeness,
        )
        assert decision["promoted"] is True, f"completeness={completeness} should not block"


def test_withholds_on_incomplete_mandatory_hooks(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1", skip={"setup_log"})
    decision = dh.decide_and_record_publication(
        run_id="run-1", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
    )
    assert decision["promoted"] is False
    assert "mandatory_hooks_incomplete" in decision["withheld_reason"]


def test_multiple_reasons_all_named(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1", skip={"setup_log"})
    decision = dh.decide_and_record_publication(
        run_id="run-1", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_STALE, completeness_status=dh.COVERAGE_PARTIAL,
    )
    assert decision["promoted"] is False
    for fragment in ("freshness=STALE", "completeness=PARTIAL", "mandatory_hooks_incomplete"):
        assert fragment in decision["withheld_reason"]


def test_never_raises_on_write_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", str(tmp_path / "nonexistent_dir" / "x.db"))
    decision = dh.decide_and_record_publication(
        run_id="run-1", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
    )
    # The decision is still computed and returned even though the write failed.
    assert decision["promoted"] is False  # mandatory_hooks_completed_for_run also fails closed here


# ---------------------------------------------------------------------------
# The core TR-08 invariant: a withheld run must never overwrite the last
# genuinely promoted publication. This is the literal acceptance test named
# in the Trust Register row.
# ---------------------------------------------------------------------------

def test_withheld_run_does_not_overwrite_last_promoted(sqlite_db):
    """Forced mid-run-failure scenario: run-1 promotes cleanly, run-2 (a
    later run) fails a gate. latest_promoted_publication() must still return
    run-1 -- exactly TR-08's "dashboard must continue serving the previous
    verified publication" invariant, at the recording layer."""
    _seed_all_mandatory(sqlite_db, "run-1", run_date="2026-09-01")
    dh.decide_and_record_publication(
        run_id="run-1", code_version="aaa111", source_as_of="2026-09-01",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
    )

    _seed_all_mandatory(sqlite_db, "run-2", fail={"stock_signals"}, run_date="2026-09-02")
    dh.decide_and_record_publication(
        run_id="run-2", code_version="bbb222", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
    )

    promoted = dh.latest_promoted_publication()
    assert promoted["run_id"] == "run-1"
    assert promoted["code_version"] == "aaa111"

    attempt = dh.latest_publication_attempt()
    assert attempt["run_id"] == "run-2"
    assert attempt["promoted"] is False
    assert "mandatory_hooks_incomplete" in attempt["withheld_reason"]


def test_latest_promoted_publication_none_when_never_promoted(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-1", skip={"setup_log"})
    dh.decide_and_record_publication(
        run_id="run-1", code_version="aaa111", source_as_of="2026-09-01",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
    )
    assert dh.latest_promoted_publication() is None
    attempt = dh.latest_publication_attempt()
    assert attempt is not None
    assert attempt["promoted"] is False


def test_latest_promoted_publication_none_when_table_absent(sqlite_db):
    assert dh.latest_promoted_publication() is None
    assert dh.latest_publication_attempt() is None


# ---------------------------------------------------------------------------
# Integration: main.run_freshness_gate() actually wires the decision through,
# reusing the same verdict it already computed (not a second live check).
# ---------------------------------------------------------------------------

def test_freshness_gate_records_promotion_on_green(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-x")
    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-09-02",
        check_all_fn=lambda expected_session, source_error: dh.Verdict(
            level="green", expected="2026-09-02", expected_source="ksestocks", items=[]),
        run_id="run-x", code_version="ccc333",
    )
    assert ok is True
    promoted = dh.latest_promoted_publication()
    assert promoted is not None
    assert promoted["run_id"] == "run-x"
    assert promoted["code_version"] == "ccc333"


def test_freshness_gate_records_withheld_on_red(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-y")
    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-09-02",
        check_all_fn=lambda expected_session, source_error: dh.Verdict(
            level="red", expected="2026-09-02", expected_source="ksestocks",
            items=[dh.Item("prices", "stale", "3 sessions behind", behind=3)]),
        run_id="run-y", code_version="ddd444",
    )
    assert ok is False
    assert dh.latest_promoted_publication() is None
    attempt = dh.latest_publication_attempt()
    assert attempt["run_id"] == "run-y"
    assert attempt["promoted"] is False
    assert "freshness=STALE" in attempt["withheld_reason"]


def test_freshness_gate_without_run_id_never_writes(sqlite_db):
    """Every pre-existing caller of run_freshness_gate() (health_check.py's
    own tests, TR-05's own suite) never passes run_id -- confirm the new
    recording path is a true no-op in that case, not just untested."""
    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-09-02",
        check_all_fn=lambda expected_session, source_error: dh.Verdict(
            level="green", expected="2026-09-02", expected_source="ksestocks", items=[]),
    )
    assert ok is True
    assert dh.latest_promoted_publication() is None
    assert dh.latest_publication_attempt() is None


def test_freshness_gate_gate_computation_failure_records_cannot_verify(sqlite_db):
    def _boom(expected_session, source_error):
        raise RuntimeError("simulated check_all() failure")

    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-09-02",
        check_all_fn=_boom,
        run_id="run-z", code_version="eee555",
    )
    assert ok is False
    assert dh.latest_promoted_publication() is None
    attempt = dh.latest_publication_attempt()
    assert attempt["run_id"] == "run-z"
    assert attempt["promoted"] is False
    assert attempt["freshness_status"] == dh.PUBLICATION_CANNOT_VERIFY


# ---------------------------------------------------------------------------
# SHADOWMODE_SPEC_DRAFT.md §5.1 -- the `coherence` field: do every
# every-session MANDATORY table carry data through the same session date?
# Recorded on current_publication; does NOT gate the promote/withhold rule.
# ---------------------------------------------------------------------------

def test_coherence_all_tables_at_expected(sqlite_db):
    _seed_coherence_tables(sqlite_db, default_date="2026-09-02")
    status, detail = dh.mandatory_tables_coherence("2026-09-02")
    assert status == dh.COHERENCE_COHERENT
    assert detail is None


def test_coherence_one_table_behind_is_incoherent_and_named(sqlite_db):
    _seed_coherence_tables(
        sqlite_db, default_date="2026-09-02",
        dates={"prices_adjusted": "2026-08-25"},   # the §36.2 failure shape
    )
    status, detail = dh.mandatory_tables_coherence("2026-09-02")
    assert status == dh.COHERENCE_INCOHERENT
    assert "prices_adjusted=2026-08-25" in detail
    assert "stock_signals" not in detail  # the ones that agree are not named


def test_coherence_table_absent_is_unknown_not_false_coherent(sqlite_db):
    # Only two of the four tables exist -- the rest are unreadable.
    _seed_coherence_tables(sqlite_db, dates={"stock_signals": "", "sector_signals": ""})
    con = sqlite3.connect(sqlite_db)
    con.execute("DROP TABLE stock_signals")
    con.execute("DROP TABLE sector_signals")
    con.commit()
    con.close()
    status, detail = dh.mandatory_tables_coherence("2026-09-02")
    assert status == dh.COHERENCE_UNKNOWN
    assert "stock_signals" in detail and "sector_signals" in detail


def test_coherence_no_expected_session_is_unknown(sqlite_db):
    _seed_coherence_tables(sqlite_db)
    status, detail = dh.mandatory_tables_coherence(None)
    assert status == dh.COHERENCE_UNKNOWN


def test_coherence_never_raises_on_query_error(monkeypatch, tmp_path):
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", str(tmp_path / "nonexistent_dir" / "x.db"))
    status, _ = dh.mandatory_tables_coherence("2026-09-02")
    assert status == dh.COHERENCE_UNKNOWN


def test_decision_round_trips_coherence(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-c")
    _seed_coherence_tables(sqlite_db)
    dh.decide_and_record_publication(
        run_id="run-c", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
        coherence_status=dh.COHERENCE_COHERENT,
    )
    assert dh.latest_promoted_publication()["coherence"] == dh.COHERENCE_COHERENT
    assert dh.latest_publication_attempt()["coherence"] == dh.COHERENCE_COHERENT


def test_incoherent_state_is_recorded_but_still_promoted(sqlite_db):
    """v1 scope: coherence is recorded, not gated. An INCOHERENT run whose
    freshness + completeness + mandatory hooks all pass is still promoted --
    the shadow-mode consumer (local_archive_sync, PR 2) is what filters on
    `coherence != INCOHERENT`, not the promotion rule."""
    _seed_all_mandatory(sqlite_db, "run-i")
    decision = dh.decide_and_record_publication(
        run_id="run-i", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
        coherence_status=dh.COHERENCE_INCOHERENT,
    )
    assert decision["promoted"] is True
    assert decision["withheld_reason"] is None
    assert decision["coherence"] == dh.COHERENCE_INCOHERENT
    assert dh.latest_promoted_publication()["coherence"] == dh.COHERENCE_INCOHERENT


def test_decision_without_coherence_kwarg_stores_null(sqlite_db):
    """Every pre-existing caller omits coherence_status -- must stay valid."""
    _seed_all_mandatory(sqlite_db, "run-n")
    dh.decide_and_record_publication(
        run_id="run-n", code_version="abc123", source_as_of="2026-09-02",
        freshness_status=dh.PUBLICATION_VERIFIED, completeness_status=dh.COVERAGE_COMPLETE,
    )
    assert dh.latest_promoted_publication()["coherence"] is None


def test_ensure_current_publication_sqlite_adds_column_to_existing_table(sqlite_db):
    """The live table predates this column (SQLite since PR #60). Simulate
    that: create it WITHOUT coherence, then ensure_* must add it, idempotently."""
    con = sqlite3.connect(sqlite_db)
    con.execute("""
        CREATE TABLE current_publication (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, promoted_at TEXT,
            code_version TEXT, source_as_of TEXT, freshness_status TEXT,
            completeness_status TEXT, mandatory_hooks_completed INTEGER,
            promoted INTEGER NOT NULL, withheld_reason TEXT)
    """)
    con.commit()
    dh.ensure_current_publication_sqlite(con)
    dh.ensure_current_publication_sqlite(con)  # idempotent -- must not raise
    cols = {row[1] for row in con.execute("PRAGMA table_info(current_publication)")}
    assert "coherence" in cols
    con.close()


def test_freshness_gate_records_coherence_status(sqlite_db):
    _seed_all_mandatory(sqlite_db, "run-g")
    _seed_coherence_tables(sqlite_db, default_date="2026-09-02")
    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-09-02",
        check_all_fn=lambda expected_session, source_error: dh.Verdict(
            level="green", expected="2026-09-02", expected_source="ksestocks", items=[]),
        run_id="run-g", code_version="ccc333",
    )
    assert ok is True
    assert dh.latest_promoted_publication()["coherence"] == dh.COHERENCE_COHERENT


# ---------------------------------------------------------------------------
# The five formerly-HELD cmd_update() hooks now thread run_id into their
# pipeline_runs heartbeat (ledger §113). Without it,
# mandatory_hooks_completed_for_run() can never match them to the freshness
# gate's run_id, so decide_and_record_publication() withholds EVERY
# authoritative publication -- exactly what the first real cloud
# current_publication row (2026-09-02, withheld_reason=
# "mandatory_hooks_incomplete") turned out to be. Asserted against main.py's
# AST rather than a full cmd_update() run so the guard is deterministic and
# has no scrape/DB dependency.
# ---------------------------------------------------------------------------

_HELD_HOOKS = {
    "regime", "sector_signals", "stock_signals",
    "recovery_signals", "portfolio_signals",
}


def _record_hook_calls_by_hook_name(source: str):
    import ast

    calls: dict[str, list[ast.Call]] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "_record_hook"):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        calls.setdefault(node.args[0].value, []).append(node)
    return calls


def test_held_hooks_thread_run_id_into_every_record_hook_call():
    main_py = os.path.join(_ROOT, "main.py")
    with open(main_py, encoding="utf-8") as fh:
        calls = _record_hook_calls_by_hook_name(fh.read())

    for hook in _HELD_HOOKS:
        hook_calls = calls.get(hook, [])
        assert hook_calls, f"no _record_hook('{hook}', ...) call found in main.py"
        for call in hook_calls:
            kwargs = {kw.arg for kw in call.keywords}
            assert "run_id" in kwargs, (
                f"_record_hook('{hook}', ...) at main.py line {call.lineno} "
                f"is missing run_id= -- mandatory_hooks_completed_for_run() "
                f"cannot match it and the publication will withhold (ledger §113)"
            )


def test_held_hook_success_calls_report_completed_execution_status():
    """The success-path call for each HELD hook must land execution_status
    COMPLETED -- either passed explicitly or derived by record_run() from
    status='ok' (test_tr06_coverage_fields covers the derivation). A call
    that passes status='error' unconditionally would silently never count."""
    main_py = os.path.join(_ROOT, "main.py")
    with open(main_py, encoding="utf-8") as fh:
        calls = _record_hook_calls_by_hook_name(fh.read())

    import ast

    for hook in _HELD_HOOKS:
        saw_completed_path = False
        for call in calls.get(hook, []):
            status_kw = next((kw for kw in call.keywords if kw.arg == "status"), None)
            exec_kw = next((kw for kw in call.keywords if kw.arg == "execution_status"), None)
            # A bare call (no status=) or status="ok" derives COMPLETED.
            if status_kw is None:
                saw_completed_path = True
            elif isinstance(status_kw.value, ast.Constant) and status_kw.value.value == "ok":
                saw_completed_path = True
            elif exec_kw is not None and isinstance(exec_kw.value, ast.IfExp):
                saw_completed_path = True  # status computed per sub-signal
        assert saw_completed_path, (
            f"no COMPLETED-path _record_hook('{hook}', ...) call in main.py"
        )
