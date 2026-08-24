"""Regression tests for the second TR-06 independent-review blocker
(2026-08-24): dashboard.py's `_dh_load_summary()` (SQLite) and
dashboard_pg.py's `get_dh_summary_pg()` (Postgres) each independently
hardcoded `WHERE hook_name = 'corporate_action'` -- a retired name main.py
stopped writing entirely once TR-06 split it into `corporate_action_append`
and `corporate_action_suspects_scan`. This was missed by the first blocker
fix (which only updated data_health.py's HEARTBEAT list) because these two
dashboard functions are separate, direct consumers of `pipeline_runs`, never
routed through `check_all()` at all.

Fix: both queries now read `hook_name = 'corporate_action_suspects_scan'`
-- the correct successor, per the pre-existing comment directly above each
query ("a scan that ran cleanly and found nothing... Last Checked"), which
was always about the SUSPECTS SCAN specifically, never the unrelated
prices_adjusted append.

SQLite: `_dh_load_summary()` is a closure nested inside dashboard.py's
`elif cur == PAGES[14]:` page-render block -- not an importable module
attribute. It can only be genuinely exercised through Streamlit's own
`AppTest` harness (this project's existing convention, tests/test_app_boot.py),
which runs the real script and the real nested closure. This is slower
(~1 minute per run, including a live fetch of the source date) than a unit
test, so exactly one AppTest-based test is used here -- it is the single
strongest proof available that the real reader logic recognizes the active
name, and it doubles as the "critical regression test": the isolated test
database this test builds (copied from tests/fixtures/psx_fixture.db, see
below) carries a stale row under the retired 'corporate_action' name
(2026-08-21), so if the old hardcoded string were ever restored in
dashboard.py, this test would see that stale date leak through instead of
the fresh date it writes, and fail.

PRODUCTION-SAFETY INCIDENT NOTE (2026-08-24): an earlier version of this
test reused test_app_boot.py's "_database" fixture verbatim -- "use the
real local psx_data.db if one is present, otherwise stage the fixture".
That convention is safe for test_app_boot.py itself, which only ever READS
the database while rendering pages. It is NOT safe for a test that also
calls record_run() to set up its scenario: on a developer machine where a
real psx_data.db exists (as it does here), that fixture handed back the
real production database path, and record_run() wrote a real
pipeline_runs row into it. This was caught and the row removed under
explicit user authorization (see docs/KIRAN_CLEANUP_AUDIT.md). The fix
below never touches config.DB_PATH's default value at all: it builds a
throwaway copy of the fixture at a fresh tempfile.mkdtemp() location (never
under the repo tree, so it can never coincide with the real psx_data.db
path or leave a stray file behind) and points config.DB_PATH at that copy
only, with an explicit assertion that refuses to proceed if the resolved
path ever equals the real database -- belt-and-suspenders, since the whole
point of this fixture is that path can never be reached in the first place.
The key distinction to preserve in any future test like this: a read-only
test may reuse the real database opportunistically; a test with ANY write
path must never be handed anything but an isolated, disposable database,
regardless of what convention a sibling read-only test uses.

Postgres: `get_dh_summary_pg()` has no comparable AppTest path (Postgres
requires DATABASE_URL/SUPABASE_DB_URL, which this project's test session
forces empty everywhere -- tests must never reach production Postgres, see
test_app_boot.py's _no_production_db fixture). No practical Postgres
integration-test mechanism exists in this repository for dashboard
functions specifically. The strongest deterministic alternative available,
following this repo's own established convention (tests/test_boring_signals_pg.py's
_FakeCursor), is used instead: the real get_dh_summary_pg() function is
called against a fake cursor that records every query string issued,
letting the test assert on the actual SQL text the function sends, not on
a copy-pasted duplicate of it.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import data_health  # noqa: E402


# ---------------------------------------------------------------------------
# SQLite path -- real AppTest render of the actual "Data Health" page
# ---------------------------------------------------------------------------

DASHBOARD = os.path.join(_ROOT, "dashboard.py")
REAL_DB_PATH = os.path.abspath(os.path.join(_ROOT, "psx_data.db"))
FIXTURE_DB = os.path.join(_ROOT, "tests", "fixtures", "psx_fixture.db")


@pytest.fixture
def isolated_dashboard_db(tmp_path, monkeypatch):
    """Builds a throwaway copy of the fixture DB under pytest's own tmp_path
    (never under the repo tree) and points config.DB_PATH at it -- this is
    the ONLY database any code this test triggers can reach, by construction:
    config.DB_PATH is a plain module attribute (not env-var-driven, see
    config.py), read fresh by both record_run() and dashboard.py's own
    `from config import DB_PATH as _dh_db` on every script execution, so
    monkeypatching it here redirects both the write and the read path.
    Confirmed empirically (not assumed) that Streamlit's AppTest executes
    dashboard.py in-process, so this redirection reaches it.

    monkeypatch.setattr guarantees restoration even if the test fails --
    unlike the incident version of this fixture, which mutated
    data_health.config.DB_PATH via a bare assignment with no cleanup at all.
    """
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_DB_URL", "")

    if not os.path.exists(FIXTURE_DB):
        pytest.skip(f"no fixture at {FIXTURE_DB}")

    temp_db = str(tmp_path / "isolated_dashboard_test.db")
    shutil.copyfile(FIXTURE_DB, temp_db)

    # Belt-and-suspenders: this path can never legitimately equal the real
    # database (tmp_path is pytest's own per-test temp directory, never this
    # repo), but refuse outright rather than silently proceed if it ever did.
    assert os.path.abspath(temp_db) != REAL_DB_PATH, (
        "isolated test database resolved to the real production path -- refusing "
        "to proceed rather than risk repeating the 2026-08-24 incident"
    )

    import config
    monkeypatch.setattr(config, "DB_PATH", temp_db)
    monkeypatch.setattr(data_health, "_PG_URL", None)

    yield temp_db


def test_data_health_page_last_checked_reflects_active_suspects_scan_heartbeat(
    isolated_dashboard_db,
):
    """Critical regression test: writes a fresh corporate_action_suspects_scan
    heartbeat via the real record_run() path (targeting only the isolated
    test database), then renders the real "Data Health" page through
    Streamlit's AppTest and reads the actual "Last Checked" metric it
    produces. The fixture DB independently already carries a stale row
    under the retired 'corporate_action' name (2026-08-21) -- if the
    hardcoded query in dashboard.py ever regressed back to that name, this
    test would see that stale date leak through instead of the fresh one
    written below, and fail."""
    data_health.record_run(
        "corporate_action_suspects_scan", "2026-08-24", status="ok", rows_written=2,
    )

    # Prove the write landed in the isolated DB, not anywhere else, before
    # ever touching Streamlit -- an independent check, not just trusting
    # record_run()'s own return (it has none; it never raises by design).
    con = sqlite3.connect(isolated_dashboard_db)
    written = con.execute(
        "SELECT run_date, status FROM pipeline_runs "
        "WHERE hook_name = 'corporate_action_suspects_scan'"
    ).fetchall()
    con.close()
    assert written == [("2026-08-24", "ok")]

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(DASHBOARD, default_timeout=300)
    at.session_state["page"] = "🏥 Data Health"
    at.run()

    assert not at.exception, (
        "Data Health page raised an uncaught exception: "
        f"{[str(e.value) for e in at.exception]}"
    )

    last_checked = next(
        (m.value for m in at.metric if "Last Checked" in m.label), None
    )
    assert last_checked is not None, "no 'Last Checked' metric was rendered at all"
    assert last_checked == "2026-08-24", (
        f"expected the fresh corporate_action_suspects_scan heartbeat's date, "
        f"got {last_checked!r} -- this is exactly the regression shape: a stale "
        f"or 'never run' value means the page is still reading the retired "
        f"'corporate_action' name"
    )


# ---------------------------------------------------------------------------
# Postgres path -- real get_dh_summary_pg() against a fake cursor
# ---------------------------------------------------------------------------

class _FakeCursor:
    """Same convention as tests/test_boring_signals_pg.py's _FakeCursor --
    .execute() is a no-op that records the call, .fetchone() replays one
    canned result per call, in order."""

    def __init__(self, result_queue):
        self._queue = list(result_queue)
        self.queries: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return self._queue.pop(0) if self._queue else None


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def rollback(self):
        pass

    def commit(self):
        pass


def _fake_get_conn(cur):
    import contextlib

    @contextlib.contextmanager
    def _cm():
        yield _FakeConn(cur)

    return _cm()


def test_get_dh_summary_pg_queries_active_suspects_scan_name(monkeypatch):
    """Regression test for the Postgres twin: the real get_dh_summary_pg()
    must issue its pipeline_runs query against 'corporate_action_suspects_scan',
    never the retired 'corporate_action'. Exercises the actual function and
    its actual SQL text, not a duplicate string."""
    import dashboard_pg

    cur = _FakeCursor([(0,), (0,), ("2026-08-24", "ok")])
    monkeypatch.setattr(dashboard_pg, "get_conn", lambda: _fake_get_conn(cur))

    pending, confirmed, last_checked = dashboard_pg.get_dh_summary_pg()

    pipeline_runs_queries = [q for q, _ in cur.queries if "pipeline_runs" in q]
    assert len(pipeline_runs_queries) == 1
    query_text = pipeline_runs_queries[0]
    assert "corporate_action_suspects_scan" in query_text
    assert "'corporate_action'" not in query_text, (
        "get_dh_summary_pg() must not query the retired hook_name — this is "
        "exactly what would fail if the old string were restored"
    )
    assert last_checked == "2026-08-24"


def test_get_dh_summary_pg_reports_never_run_when_absent(monkeypatch):
    """Negative case: no matching row at all -> 'never run', not a stale or
    fabricated date."""
    import dashboard_pg

    cur = _FakeCursor([(0,), (0,), None])
    monkeypatch.setattr(dashboard_pg, "get_conn", lambda: _fake_get_conn(cur))

    _, _, last_checked = dashboard_pg.get_dh_summary_pg()
    assert last_checked == "never run"


def test_get_dh_summary_pg_reports_failed_run(monkeypatch):
    """A recorded row with status != 'ok' must show as failed, not silently
    read as healthy."""
    import dashboard_pg

    cur = _FakeCursor([(0,), (0,), ("2026-08-24", "error")])
    monkeypatch.setattr(dashboard_pg, "get_conn", lambda: _fake_get_conn(cur))

    _, _, last_checked = dashboard_pg.get_dh_summary_pg()
    assert last_checked == "2026-08-24 (failed)"
