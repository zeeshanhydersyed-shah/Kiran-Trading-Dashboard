"""OI-9 / TR-11 -- standing deployment-identity mechanism (KIRAN_CLEANUP_AUDIT.md 88).

Three components, all covered here with isolated units -- no real DB, no
network, no AppTest, no touching the real repository or psx_data.db:

  A. serving_revision.resolve_code_version() precedence + pipeline_runs.code_version
     round-tripping through data_health.record_run() / _record_pg().
  B. serving_revision.describe_drift() (the pure comparison the Data Health
     panel renders) + data_health.latest_pipeline_code_version().
  C. main._working_tree_state() dirty/clean/unknown detection + _record_hook()
     defaulting code_version to the run's resolved value.

Note: GITHUB_SHA is set on the GitHub Actions runner these tests also run on,
so every "unset" scenario explicitly deletes it via monkeypatch.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import serving_revision as sr  # noqa: E402
import data_health as dh  # noqa: E402

VALID_SHA = "09cdfdb5be148f7da58cee20b8ee16049b36148a"
OTHER_SHA = "ffdccf9edf70692714f91b72b79e8302874c8c07"


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Component A -- resolve_code_version() precedence
# ---------------------------------------------------------------------------

def test_resolve_prefers_github_sha_when_valid(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_SHA", VALID_SHA.upper())  # upper -> normalised
    # a real .git that would resolve to something else, to prove GITHUB_SHA wins
    _write(os.path.join(str(tmp_path), ".git", "HEAD"), OTHER_SHA + "\n")
    assert sr.resolve_code_version(repo_dir=str(tmp_path)) == VALID_SHA


def test_resolve_falls_through_to_git_head_when_github_sha_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    _write(os.path.join(str(tmp_path), ".git", "HEAD"), "ref: refs/heads/main\n")
    _write(os.path.join(str(tmp_path), ".git", "refs", "heads", "main"), VALID_SHA + "\n")
    assert sr.resolve_code_version(repo_dir=str(tmp_path)) == VALID_SHA


def test_resolve_returns_none_when_nothing_available(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    # tmp_path has no .git
    assert sr.resolve_code_version(repo_dir=str(tmp_path)) is None


def test_resolve_ignores_junk_github_sha_and_falls_through(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_SHA", "not-a-real-sha")
    _write(os.path.join(str(tmp_path), ".git", "HEAD"), VALID_SHA + "\n")
    # must NOT return the junk; must resolve via .git instead
    assert sr.resolve_code_version(repo_dir=str(tmp_path)) == VALID_SHA


def test_resolve_junk_github_sha_and_no_git_is_none(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_SHA", "deadbeef")
    assert sr.resolve_code_version(repo_dir=str(tmp_path)) is None


# ---------------------------------------------------------------------------
# Component A -- code_version round-trips through record_run (SQLite)
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.db"
    monkeypatch.setattr(dh.config, "DB_PATH", str(path))
    monkeypatch.setattr(dh, "_PG_URL", None)
    return str(path)


def test_record_run_persists_code_version_sqlite(sqlite_ledger):
    dh.record_run("boring_signals", "2026-08-31", rows_written=3, code_version=VALID_SHA)
    con = sqlite3.connect(sqlite_ledger)
    row = con.execute(
        "SELECT code_version FROM pipeline_runs WHERE hook_name = 'boring_signals'"
    ).fetchone()
    con.close()
    assert row[0] == VALID_SHA


def test_record_run_without_code_version_is_null_and_does_not_raise(sqlite_ledger):
    dh.record_run("setup_log", "2026-08-31", rows_written=1)  # no code_version kwarg
    con = sqlite3.connect(sqlite_ledger)
    row = con.execute(
        "SELECT code_version FROM pipeline_runs WHERE hook_name = 'setup_log'"
    ).fetchone()
    con.close()
    assert row[0] is None


def test_record_run_updates_code_version_on_conflict(sqlite_ledger):
    dh.record_run("leaders_scan", "2026-08-31", code_version=OTHER_SHA)
    dh.record_run("leaders_scan", "2026-08-31", code_version=VALID_SHA)  # same (hook, date)
    con = sqlite3.connect(sqlite_ledger)
    rows = con.execute(
        "SELECT code_version FROM pipeline_runs WHERE hook_name = 'leaders_scan'"
    ).fetchall()
    con.close()
    assert rows == [(VALID_SHA,)]


# ---------------------------------------------------------------------------
# Component A -- code_version reaches the Postgres INSERT (faked psycopg2)
# ---------------------------------------------------------------------------

class _CapturingCursor:
    def __init__(self):
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        if "INSERT INTO pipeline_runs" in sql:
            self.sql = sql
            self.params = params


class _CapturingConn:
    def __init__(self):
        self.cur = _CapturingCursor()
        self.committed = False

    def cursor(self):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def test_record_pg_includes_code_version_in_insert(monkeypatch):
    import database_pg
    monkeypatch.setattr(database_pg, "_parse_pg_url", lambda url: {})
    import psycopg2
    conn = _CapturingConn()
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: conn)
    monkeypatch.setattr(dh, "ensure_ledger_pg", lambda cur: None)

    from datetime import datetime, timezone
    dh._record_pg(
        "postgresql://fake/db", "boring_signals", "2026-08-31",
        datetime.now(timezone.utc), "ok", 3, None,
        code_version=VALID_SHA,
    )
    assert "code_version" in conn.cur.sql
    assert VALID_SHA in conn.cur.params
    assert conn.committed is True


# ---------------------------------------------------------------------------
# Component B -- describe_drift() (pure)
# ---------------------------------------------------------------------------

def test_describe_drift_match():
    level, msg = sr.describe_drift(VALID_SHA, VALID_SHA)
    assert level == "match"
    assert VALID_SHA[:7] in msg


def test_describe_drift_reports_both_shas_on_drift():
    level, msg = sr.describe_drift(VALID_SHA, OTHER_SHA)
    assert level == "drift"
    assert VALID_SHA[:7] in msg and OTHER_SHA[:7] in msg
    assert "reboot" in msg.lower()


def test_describe_drift_unknown_when_serving_missing():
    for missing in (None, ""):
        level, msg = sr.describe_drift(missing, VALID_SHA)
        assert level == "unknown"


def test_describe_drift_pending_when_pipeline_has_no_version():
    for missing in (None, ""):
        level, msg = sr.describe_drift(VALID_SHA, missing)
        assert level == "pending"


# ---------------------------------------------------------------------------
# Component B -- latest_pipeline_code_version()
# ---------------------------------------------------------------------------

def test_latest_pipeline_code_version_returns_most_recent_ok_run(sqlite_ledger):
    dh.record_run("setup_log", "2026-08-30", status="ok", code_version=OTHER_SHA)
    dh.record_run("boring_signals", "2026-08-31", status="ok", code_version=VALID_SHA)
    assert dh.latest_pipeline_code_version() == VALID_SHA


def test_latest_pipeline_code_version_ignores_failed_runs(sqlite_ledger):
    dh.record_run("setup_log", "2026-08-30", status="ok", code_version=OTHER_SHA)
    # a later FAILED run must not shadow the last good one
    dh.record_run("boring_signals", "2026-08-31", status="error", code_version=VALID_SHA)
    assert dh.latest_pipeline_code_version() == OTHER_SHA


def test_latest_pipeline_code_version_none_when_no_column(tmp_path, monkeypatch):
    # a pre-migration / CI-fixture pipeline_runs with no code_version column
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE pipeline_runs (hook_name TEXT, run_date TEXT, "
        "finished_at TEXT, status TEXT)"
    )
    con.execute(
        "INSERT INTO pipeline_runs VALUES ('setup_log', '2026-08-31', "
        "'2026-08-31T00:00:00', 'ok')"
    )
    con.commit()
    con.close()
    monkeypatch.setattr(dh.config, "DB_PATH", str(path))
    monkeypatch.setattr(dh, "_PG_URL", None)
    assert dh.latest_pipeline_code_version() is None  # no crash


def test_latest_pipeline_code_version_none_when_no_rows(sqlite_ledger):
    dh.record_run("setup_log", "2026-08-31", status="ok")  # code_version NULL
    assert dh.latest_pipeline_code_version() is None


# ---------------------------------------------------------------------------
# Component C -- main._working_tree_state() + _record_hook default
# ---------------------------------------------------------------------------

import main as m  # noqa: E402


class _FakeCompleted:
    def __init__(self, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout


def test_working_tree_state_flags_dirty_python(monkeypatch):
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeCompleted(0, " M boring_signals.py\n M data_health.py\n"),
    )
    state, files = m._working_tree_state()
    assert state == "dirty"
    assert "boring_signals.py" in files and "data_health.py" in files


def test_working_tree_state_ignores_data_and_test_files(monkeypatch):
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _FakeCompleted(0, " M breadth_data.csv\n M tests/test_x.py\n"),
    )
    assert m._working_tree_state() == ("clean", [])


def test_working_tree_state_clean(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(0, ""))
    assert m._working_tree_state() == ("clean", [])


def test_working_tree_state_unknown_on_git_failure(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompleted(128, ""))
    assert m._working_tree_state() == ("unknown", [])


def test_working_tree_state_unknown_when_git_missing(monkeypatch):
    import subprocess

    def _boom(*a, **k):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", _boom)
    assert m._working_tree_state() == ("unknown", [])


def test_record_hook_defaults_code_version_to_run_value(sqlite_ledger, monkeypatch):
    m._set_run_code_version(VALID_SHA)
    try:
        m._record_hook("regime", "2026-08-31")  # no code_version passed
    finally:
        m._set_run_code_version(None)
    con = sqlite3.connect(sqlite_ledger)
    row = con.execute(
        "SELECT code_version FROM pipeline_runs WHERE hook_name = 'regime'"
    ).fetchone()
    con.close()
    assert row[0] == VALID_SHA


def test_record_hook_explicit_code_version_wins(sqlite_ledger):
    m._set_run_code_version(OTHER_SHA)
    try:
        m._record_hook("deployment_identity", "2026-08-31", code_version=VALID_SHA)
    finally:
        m._set_run_code_version(None)
    con = sqlite3.connect(sqlite_ledger)
    row = con.execute(
        "SELECT code_version FROM pipeline_runs WHERE hook_name = 'deployment_identity'"
    ).fetchone()
    con.close()
    assert row[0] == VALID_SHA
