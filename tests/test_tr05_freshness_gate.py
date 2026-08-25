"""TR-05 Blocker 1 -- local execution-time freshness gate (main.run_freshness_gate).

Fully isolated: both dependencies (the live-source-date fetch and the
check_all() verdict) are injected, so these tests touch no network and no
database, live or fixture. See docs/KIRAN_BORING_STATE_TRUST_REGISTER.md,
TR-05.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from data_health import Item, Verdict
import main


def _verdict(level: str, expected: str = "2026-08-24", items=None) -> Verdict:
    return Verdict(level=level, expected=expected, expected_source="ksestocks",
                   items=items or [])


def test_green_verdict_passes():
    """Fresh SQLite state -> gate passes."""
    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-08-24",
        check_all_fn=lambda expected_session, source_error: _verdict("green"),
    )
    assert ok is True


def test_red_verdict_fails():
    """Stale SQLite state -> gate fails."""
    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-08-24",
        check_all_fn=lambda expected_session, source_error: _verdict(
            "red", items=[Item("prices", "stale", "2026-08-20, 3 sessions behind", behind=3)]
        ),
    )
    assert ok is False


def test_amber_verdict_fails():
    """Cannot-verify (amber) state -> gate fails, not treated as success."""
    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: None,
        check_all_fn=lambda expected_session, source_error: _verdict(
            "amber", expected=None,
            items=[Item("prices", "unknown", "cannot reach ksestocks to confirm")],
        ),
    )
    assert ok is False


def test_check_all_raising_fails_closed():
    """The verdict computation itself failing must be treated as failure, not success."""
    def _boom(expected_session, source_error):
        raise RuntimeError("simulated check_all() failure")

    ok = main.run_freshness_gate(
        fetch_expected_session=lambda: "2026-08-24",
        check_all_fn=_boom,
    )
    assert ok is False


def test_source_date_fetch_raising_fails_closed():
    """The live-source-date fetch failing must also be treated as failure, not success."""
    def _boom():
        raise RuntimeError("simulated ksestocks fetch failure")

    ok = main.run_freshness_gate(
        fetch_expected_session=_boom,
        check_all_fn=lambda expected_session, source_error: _verdict("green"),
    )
    assert ok is False


def test_cmd_update_dispatch_reports_failure_via_exit_code(monkeypatch):
    """main()'s --update/--all dispatch must not report success after a gate failure.

    This is the property TR-05 Blocker 1 actually requires: the local
    execution chain (`python main.py --all`, invoked by run_update.bat) must
    not exit 0 when the terminal freshness gate fails.
    """
    monkeypatch.setattr(main, "cmd_update", lambda: False)
    monkeypatch.setattr(main, "cmd_report", lambda: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--all"])

    with pytest.raises(SystemExit) as exc_info:
        main.main()
    assert exc_info.value.code == 1


def test_cmd_update_dispatch_preserves_success_exit(monkeypatch):
    """A passing gate (True) must not trigger sys.exit -- existing successful-run
    behavior (process exits 0) is preserved."""
    monkeypatch.setattr(main, "cmd_update", lambda: True)
    monkeypatch.setattr(main, "cmd_report", lambda: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--all"])

    main.main()  # must not raise SystemExit


def test_cmd_update_dispatch_preserves_bootstrap_none(monkeypatch):
    """The pre-existing cmd_init()-redirect bootstrap path (cmd_update() -> None)
    is not a freshness-gate outcome and must not be treated as a failure."""
    monkeypatch.setattr(main, "cmd_update", lambda: None)
    monkeypatch.setattr(main, "cmd_report", lambda: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--all"])

    main.main()  # must not raise SystemExit


# ---------------------------------------------------------------------------
# Real cmd_update() exit-path wiring -- both meaningful exits.
#
# These call the REAL main.cmd_update(), not a stand-in, to prove the actual
# control-flow wiring (not just run_freshness_gate() in isolation, already
# covered above). Production-database safety mirrors this program's own
# established, incident-hardened convention (tests/test_tr06_dashboard_
# corporate_action_regression.py, following the 2026-08-24 incident where a
# write-capable test inherited a read-only-safe fixture convention and wrote
# a real row into production): an isolated throwaway copy of the fixture DB
# under pytest's own tmp_path, config.DB_PATH/database.DB_PATH/main.DB_PATH
# all redirected to it, plus an active sqlite3.connect guard that raises
# immediately if anything -- however it got there, including a hook whose own
# module has some other frozen DB_PATH binding this fixture didn't
# individually patch -- ever tries to open the real production path. A hook
# blocked by the guard is caught by that hook's own pre-existing
# try/except-and-warn wrapping (the same tolerance every hook already has for
# a real transient failure), so this remains safe even though not every one
# of cmd_update()'s ~12 hooks is individually mocked -- what's being proven
# here is that execution reaches the real run_freshness_gate() call and
# propagates its result, not that every hook succeeds.
# ---------------------------------------------------------------------------

import shutil
import sqlite3

import config
import database

_REAL_DB_PATH = os.path.abspath(os.path.join(_ROOT, "psx_data.db"))
_FIXTURE_DB = os.path.join(_ROOT, "tests", "fixtures", "psx_fixture.db")


@pytest.fixture
def isolated_pipeline_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_DB_URL", "")

    if not os.path.exists(_FIXTURE_DB):
        pytest.skip(f"no fixture at {_FIXTURE_DB}")

    temp_db = str(tmp_path / "isolated_pipeline_test.db")
    shutil.copyfile(_FIXTURE_DB, temp_db)

    assert os.path.abspath(temp_db) != _REAL_DB_PATH, (
        "isolated test database resolved to the real production path -- refusing "
        "to proceed rather than risk repeating the 2026-08-24 incident"
    )

    monkeypatch.setattr(config, "DB_PATH", temp_db)
    monkeypatch.setattr(database, "DB_PATH", temp_db)
    monkeypatch.setattr(main, "DB_PATH", temp_db)

    _real_connect = sqlite3.connect

    def _guarded_connect(db_arg, *args, **kwargs):
        try:
            resolved = os.path.abspath(str(db_arg))
        except Exception:
            resolved = None
        if resolved == _REAL_DB_PATH:
            raise RuntimeError(
                f"BLOCKED: attempted to open the real production database "
                f"({_REAL_DB_PATH!r}) during an isolated test -- isolation "
                f"guard tripped, refusing the connection rather than risk "
                f"repeating the 2026-08-24 incident."
            )
        return _real_connect(db_arg, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _guarded_connect)

    yield temp_db


@pytest.fixture
def _no_network_or_subprocess(monkeypatch):
    """Blocks the two real-world-reaching call classes cmd_update() can make
    (a scrape network call, and two subprocess.run spawns -- the Agent daily
    hook and the market breadth oscillator script, the latter of which writes
    real files into the repo root if actually run) -- independent of, and in
    addition to, the DB isolation guard above."""
    import subprocess as _subprocess_module

    monkeypatch.setattr(main, "build_session", lambda: object())
    monkeypatch.setattr(main, "scrape_date_range", lambda *a, **k: ([], [], []))

    class _FakeCompletedProcess:
        returncode = 0
        stdout = b""
        stderr = b""

    monkeypatch.setattr(_subprocess_module, "run",
                         lambda *a, **k: _FakeCompletedProcess())

    try:
        import page_flows
        monkeypatch.setattr(page_flows, "scrape_flows_today",
                             lambda: {"rows_saved": 0, "failed": 0})
    except ImportError:
        pass


def test_not_new_dates_branch_invokes_gate(
    isolated_pipeline_db, _no_network_or_subprocess, monkeypatch,
):
    """The 'already up to date' branch (main.py's `if not new_dates:`) must
    reach run_freshness_gate() before returning -- this is the specific
    defect this correction pass fixes: it previously returned bare `None`
    without ever calling the gate."""
    monkeypatch.setattr(main, "dates_since", lambda latest_date: [])

    calls = []
    monkeypatch.setattr(main, "run_freshness_gate",
                         lambda: (calls.append(1), True)[1])

    result = main.cmd_update()

    assert calls == [1], "run_freshness_gate() was not invoked on the not-new-dates path"
    assert result is True


def test_not_new_dates_branch_propagates_gate_failure(
    isolated_pipeline_db, _no_network_or_subprocess, monkeypatch,
):
    """A failing gate on this path must make cmd_update() itself return False,
    and main()'s dispatch must consequently exit non-zero."""
    monkeypatch.setattr(main, "dates_since", lambda latest_date: [])
    monkeypatch.setattr(main, "run_freshness_gate", lambda: False)

    result = main.cmd_update()
    assert result is False

    monkeypatch.setattr(main, "cmd_update", lambda: result)
    monkeypatch.setattr(main, "cmd_report", lambda: None)
    monkeypatch.setattr(sys, "argv", ["main.py", "--all"])
    with pytest.raises(SystemExit) as exc_info:
        main.main()
    assert exc_info.value.code == 1


def test_tail_path_invokes_gate(
    isolated_pipeline_db, _no_network_or_subprocess, monkeypatch,
):
    """The ordinary tail path (new dates present, all ~12 hooks run) must
    still reach the real run_freshness_gate() call at the end of
    cmd_update() -- the pre-existing, already-correct path, re-verified here
    end-to-end through the real function rather than only through main()'s
    dispatch logic (which the earlier tests in this file cover in isolation)."""
    import datetime as _dt
    monkeypatch.setattr(main, "dates_since", lambda latest_date: [_dt.date(2026, 8, 24)])

    calls = []
    monkeypatch.setattr(main, "run_freshness_gate",
                         lambda: (calls.append(1), True)[1])

    result = main.cmd_update()

    assert calls == [1], "run_freshness_gate() was not invoked on the tail path"
    assert result is True
