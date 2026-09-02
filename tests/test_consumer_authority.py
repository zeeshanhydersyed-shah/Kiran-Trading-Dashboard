"""TR-01/TR-12 consumer-authority alert (ledger §109) -- Option A of the
two-option plan agreed with the owner: alert immediately if a local Windows
process ends up with a live Postgres URL and is about to write production
data, don't block (Option B -- Postgres role separation -- is a deferred
structural follow-up).

Fully isolated: no live network, no live/fixture database touched by the
detection-logic tests; the alert-mechanics tests use an isolated on-disk
SQLite DB and a stubbed urllib call. See
docs/KIRAN_BORING_STATE_TRUST_REGISTER.md, TR-01/TR-12.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import platform  # noqa: E402 -- patched directly; data_health imports it locally
                  # per-call, and a local `import platform` just retrieves the
                  # same cached sys.modules singleton this patches too.

import data_health as dh  # noqa: E402
import main  # noqa: E402

_REAL_DB_PATH = os.path.abspath(os.path.join(_ROOT, "psx_data.db"))
_FIXTURE_DB = os.path.join(_ROOT, "tests", "fixtures", "psx_fixture.db")


# ---------------------------------------------------------------------------
# is_local_windows_pg_write_risk() -- pure detection logic
# ---------------------------------------------------------------------------

def test_true_when_windows_and_pg_url_set(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    assert dh.is_local_windows_pg_write_risk("postgresql://fake") is True


def test_false_when_no_pg_url(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    assert dh.is_local_windows_pg_write_risk(None) is False
    assert dh.is_local_windows_pg_write_risk("") is False


def test_false_when_linux_even_with_pg_url(monkeypatch):
    """The shape of a real GitHub Actions run: Postgres URL set, but never
    Windows -- must never fire."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert dh.is_local_windows_pg_write_risk("postgresql://fake") is False


def test_never_raises_on_platform_detection_failure(monkeypatch):
    def _boom():
        raise RuntimeError("simulated platform.system() failure")
    monkeypatch.setattr(platform, "system", _boom)
    # Fails open (not a risk) -- this is an alert mechanism, not a gate; a
    # detection failure must not itself become a spurious alarm.
    assert dh.is_local_windows_pg_write_risk("postgresql://fake") is False


# ---------------------------------------------------------------------------
# alert_consumer_authority_violation() -- the actual alert mechanics
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    db = str(tmp_path / "consumer_authority.db")
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", db)
    return db


def test_alert_writes_heartbeat_and_pushes_ntfy(sqlite_db, monkeypatch):
    pushed = {}

    class _FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _fake_urlopen(req, timeout=10):
        pushed["url"] = req.full_url
        pushed["data"] = req.data
        pushed["headers"] = dict(req.header_items())
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    dh.alert_consumer_authority_violation("run-1", "abc123", "test detail")

    # Heartbeat landed
    con = sqlite3.connect(sqlite_db)
    row = con.execute(
        "SELECT hook_name, status, execution_status, run_id, code_version, detail "
        "FROM pipeline_runs WHERE hook_name = 'consumer_authority_violation'"
    ).fetchone()
    con.close()
    assert row is not None
    assert row[1] == "error"
    assert row[2] == dh.EXECUTION_FAILED
    assert row[3] == "run-1"
    assert row[4] == "abc123"
    assert "test detail" in row[5]

    # ntfy push attempted with the right topic/priority
    assert "kiran-psx-alerts-7g3k9qx2mp" in pushed["url"]
    assert pushed["headers"].get("Priority") == "urgent"
    assert b"test detail" in pushed["data"]


def test_alert_never_raises_when_db_write_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(dh, "_PG_URL", None)
    monkeypatch.setattr(dh.config, "DB_PATH", str(tmp_path / "nonexistent_dir" / "x.db"))
    monkeypatch.setattr("urllib.request.urlopen",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network")))
    # Must not raise despite both the DB write and the network call failing.
    dh.alert_consumer_authority_violation("run-1", "abc123", "test detail")


def test_alert_never_raises_when_ntfy_fails(sqlite_db, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                         lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network")))
    # DB write still succeeds even though the network push fails.
    dh.alert_consumer_authority_violation("run-1", "abc123", "test detail")
    con = sqlite3.connect(sqlite_db)
    count = con.execute(
        "SELECT COUNT(*) FROM pipeline_runs WHERE hook_name = 'consumer_authority_violation'"
    ).fetchone()[0]
    con.close()
    assert count == 1


# ---------------------------------------------------------------------------
# Integration: main.cmd_update() actually fires the alert at the right
# moment, and does not fire in the normal (non-Windows or SQLite-mode) case.
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_pipeline_db(tmp_path, monkeypatch):
    """Trimmed version of test_tr05_freshness_gate.py's fixture of the same
    name -- same isolation guarantees (never touches the real SQLite file or
    a real Postgres connection), scoped to just what this file's integration
    test needs."""
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("SUPABASE_DB_URL", "")

    if not os.path.exists(_FIXTURE_DB):
        pytest.skip(f"no fixture at {_FIXTURE_DB}")

    temp_db = str(tmp_path / "isolated_pipeline_test.db")
    shutil.copyfile(_FIXTURE_DB, temp_db)
    assert os.path.abspath(temp_db) != _REAL_DB_PATH

    import config
    import database
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
            raise RuntimeError("BLOCKED: attempted to open the real production database "
                                "during an isolated test.")
        return _real_connect(db_arg, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", _guarded_connect)

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("BLOCKED: attempted a real PostgreSQL connection during an isolated test.")))

    yield temp_db


def test_cmd_update_fires_alert_on_windows_with_pg_url(
    isolated_pipeline_db, monkeypatch,
):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-for-this-test-only")

    calls = []
    monkeypatch.setattr(dh, "alert_consumer_authority_violation",
                         lambda run_id, code_version, detail: calls.append((run_id, detail)))

    # Route cmd_update() through the shortest real path (the "already up to
    # date" branch, same technique test_tr05_freshness_gate.py uses) --
    # this study's check runs before that branch, so it's still exercised.
    monkeypatch.setattr(main, "dates_since", lambda latest_date: [])
    monkeypatch.setattr(main, "run_analysis", lambda: None)
    monkeypatch.setattr(main, "run_freshness_gate", lambda **kw: True)

    main.cmd_update()

    assert len(calls) == 1
    assert "Windows" in calls[0][1] or "run_id" in calls[0][1]


def test_cmd_update_does_not_fire_in_normal_sqlite_mode(
    isolated_pipeline_db, monkeypatch,
):
    """The overwhelmingly common real case: local run, no Postgres URL at
    all. Must be a true no-op, not just untested."""
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    # isolated_pipeline_db already clears DATABASE_URL/SUPABASE_DB_URL.

    calls = []
    monkeypatch.setattr(dh, "alert_consumer_authority_violation",
                         lambda *a, **k: calls.append(1))

    monkeypatch.setattr(main, "dates_since", lambda latest_date: [])
    monkeypatch.setattr(main, "run_analysis", lambda: None)
    monkeypatch.setattr(main, "run_freshness_gate", lambda **kw: True)

    main.cmd_update()

    assert calls == []


def test_cmd_update_does_not_fire_on_linux_even_with_pg_url(
    isolated_pipeline_db, monkeypatch,
):
    """The shape of a real GitHub Actions run -- must never fire."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake-for-this-test-only")

    calls = []
    monkeypatch.setattr(dh, "alert_consumer_authority_violation",
                         lambda *a, **k: calls.append(1))

    monkeypatch.setattr(main, "dates_since", lambda latest_date: [])
    monkeypatch.setattr(main, "run_analysis", lambda: None)
    monkeypatch.setattr(main, "run_freshness_gate", lambda **kw: True)

    main.cmd_update()

    assert calls == []
